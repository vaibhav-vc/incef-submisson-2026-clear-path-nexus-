"""Read-only tools shared by every assistant (offline, local Ollama, Claude).

Each tool returns plain data. None of them changes anything: the disruption
planner returns a proposal for a human controller.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from india_rail.services import Services

MAX_TOOL_RESULT_CHARS = 20_000

SYSTEM_PROMPT = """You assist Indian Railways planners and section controllers.

You answer questions about trains, stations, schedules and network load, and you
prepare disruption re-plans, using only the tools provided. The data is an open
community timetable snapshot (about 2016, CC0, DataMeet) with no running-days
information, so say so whenever an answer depends on current or day-specific
service. Run-time predictions come from a gradient-boosted model of planned
(timetabled) run times, not observed delays.

When you prepare a re-plan, present it as a proposal for the controller to
accept or reject: list the holds, the projected delays, the conflicts left
unresolved and the assumptions the planner reported. Never describe a plan as
issued, applied or sent to trains or signalling; you have no such capability.
If a station or train name is ambiguous, look it up before answering. Keep
answers concise and use station codes alongside names."""


def clip(payload: Any) -> str:
    text = json.dumps(payload, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + '..."(truncated)"'
    return text


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _integer(description: str) -> dict[str, str]:
    return {"type": "integer", "description": description}


# name -> (description, properties, required)
TOOL_SPECS: dict[str, tuple[str, dict[str, Any], list[str]]] = {
    "search_trains": (
        "Find trains by number or (partial) name.",
        {"query": _string('Train number such as "12951" or part of a name such as "Rajdhani".')},
        ["query"],
    ),
    "search_stations": (
        "Find stations by code or (partial) name.",
        {"query": _string('Station code such as "NDLS" or part of a name such as "Howrah".')},
        ["query"],
    ),
    "train_schedule": (
        "Return a train's timetable: origin, destination and every booked halt.",
        {"train_number": _string("Five-digit train number.")},
        ["train_number"],
    ),
    "trains_between": (
        "List direct trains from one station to another, ordered by departure time.",
        {"origin": _string("Origin station code."), "destination": _string("Destination station code.")},
        ["origin", "destination"],
    ),
    "station_board": (
        "List trains calling at a station, ordered by time of day.",
        {"station_code": _string("Station code.")},
        ["station_code"],
    ),
    "busiest_sections": (
        "Rank track sections by scheduled trains per day.",
        {
            "zone": _string('Optional railway zone code such as "CR" or "NR"; empty for all.'),
            "limit": _integer("Number of sections to return (max 50)."),
        },
        [],
    ),
    "fastest_path": (
        "Quickest station sequence across the network by median scheduled run time.",
        {"origin": _string("Origin station code."), "destination": _string("Destination station code.")},
        ["origin", "destination"],
    ),
    "timetable_slack": (
        "Compare a train's scheduled run times with the model's prediction to find padding and tight sections.",
        {"train_number": _string("Five-digit train number.")},
        ["train_number"],
    ),
    "plan_disruption": (
        "Propose holds that keep separation after a train is delayed. Returns a proposal only.",
        {
            "train_number": _string("The delayed train."),
            "station_code": _string("Station where the train's departure is delayed."),
            "delay_min": _integer("Delay in minutes (1-720)."),
            "headway_min": _integer("Minimum separation between trains entering a section, minutes (default 6)."),
        },
        ["train_number", "station_code", "delay_min"],
    ),
}


class RailTools:
    def __init__(self, services: Services):
        self.services = services
        self.net = services.network

    def search_trains(self, query: str) -> Any:
        return self.net.search_trains(query)

    def search_stations(self, query: str) -> Any:
        return self.net.search_stations(query)

    def train_schedule(self, train_number: str) -> Any:
        info = self.net.train(train_number)
        if info is None:
            return {"error": f"Unknown train {train_number}"}
        stops = self.net.schedule(train_number)
        halts = [s for i, s in enumerate(stops) if s["dwell_min"] > 0 or i in (0, len(stops) - 1)]
        return {"train": info, "timed_points": len(stops), "halts": halts}

    def trains_between(self, origin: str, destination: str) -> Any:
        return self.net.trains_between(origin, destination)

    def station_board(self, station_code: str) -> Any:
        return self.net.station_board(station_code)

    def busiest_sections(self, zone: str = "", limit: int = 15) -> Any:
        return self.net.busiest_sections(limit=max(1, min(int(limit), 50)), zone=zone or None)

    def fastest_path(self, origin: str, destination: str) -> Any:
        return self.net.fastest_path(origin, destination) or {"error": "No path in the timetable network"}

    def timetable_slack(self, train_number: str) -> Any:
        return self.services.timetable_slack(train_number)

    def plan_disruption(self, train_number: str, station_code: str, delay_min: int, headway_min: int = 6) -> Any:
        delay_min, headway_min = int(delay_min), int(headway_min)
        if not 1 <= delay_min <= 720 or not 2 <= headway_min <= 30:
            return {"error": "delay_min must be 1-720 and headway_min 2-30"}
        try:
            return self.services.plan(train_number, station_code, delay_min, headway_min)
        except (KeyError, ValueError) as exc:
            return {"error": str(exc)}

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool by name with model-supplied arguments; errors become data."""

        if name not in TOOL_SPECS:
            return clip({"error": f"Unknown tool {name}"})
        _description, properties, required = TOOL_SPECS[name]
        missing = [key for key in required if key not in arguments]
        if missing:
            return clip({"error": f"Missing arguments: {', '.join(missing)}"})
        kwargs = {key: value for key, value in arguments.items() if key in properties}
        method: Callable[..., Any] = getattr(self, name)
        try:
            return clip(method(**kwargs))
        except (TypeError, ValueError) as exc:
            return clip({"error": str(exc)})


def json_schema_tools() -> list[dict[str, Any]]:
    """Tool definitions in the function-calling format used by Ollama."""

    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }
        for name, (description, properties, required) in TOOL_SPECS.items()
    ]
