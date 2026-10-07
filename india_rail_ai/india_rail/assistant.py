"""Claude-powered assistant for timetable questions and disruption planning.

The assistant answers in natural language by calling the same read-only tools
the API exposes. It can propose a re-plan but cannot apply one: there is no tool
that writes to any operational system.

Requires the `anthropic` package and an Anthropic API credential
(ANTHROPIC_API_KEY or an `ant auth login` profile).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from anthropic import beta_tool

from india_rail.services import Services

MODEL = "claude-opus-5-5"
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


def _clip(payload: Any) -> str:
    text = json.dumps(payload, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + '..."(truncated)"'
    return text


def build_tools(services: Services) -> list:
    net = services.network

    @beta_tool
    def search_trains(query: str) -> str:
        """Find trains by number or (partial) name.

        Args:
            query: Train number such as "12951" or part of a name such as "Rajdhani".
        """
        return _clip(net.search_trains(query))

    @beta_tool
    def search_stations(query: str) -> str:
        """Find stations by code or (partial) name.

        Args:
            query: Station code such as "NDLS" or part of a name such as "Howrah".
        """
        return _clip(net.search_stations(query))

    @beta_tool
    def train_schedule(train_number: str) -> str:
        """Return a train's timetable: origin, destination and every booked halt.

        Args:
            train_number: Five-digit train number.
        """
        info = net.train(train_number)
        if info is None:
            return _clip({"error": f"Unknown train {train_number}"})
        stops = net.schedule(train_number)
        halts = [s for i, s in enumerate(stops) if s["dwell_min"] > 0 or i in (0, len(stops) - 1)]
        return _clip({"train": info, "timed_points": len(stops), "halts": halts})

    @beta_tool
    def trains_between(origin: str, destination: str) -> str:
        """List direct trains from one station to another, ordered by departure time.

        Args:
            origin: Origin station code.
            destination: Destination station code.
        """
        return _clip(net.trains_between(origin, destination))

    @beta_tool
    def station_board(station_code: str) -> str:
        """List trains calling at a station, ordered by time of day.

        Args:
            station_code: Station code.
        """
        return _clip(net.station_board(station_code))

    @beta_tool
    def busiest_sections(zone: str = "", limit: int = 15) -> str:
        """Rank track sections by scheduled trains per day.

        Args:
            zone: Optional railway zone code such as "CR" or "NR" to restrict by train zone.
            limit: Number of sections to return (max 50).
        """
        return _clip(net.busiest_sections(limit=max(1, min(limit, 50)), zone=zone or None))

    @beta_tool
    def fastest_path(origin: str, destination: str) -> str:
        """Quickest station sequence across the network by median scheduled run time.

        Args:
            origin: Origin station code.
            destination: Destination station code.
        """
        return _clip(net.fastest_path(origin, destination) or {"error": "No path in the timetable network"})

    @beta_tool
    def timetable_slack(train_number: str) -> str:
        """Compare a train's scheduled run times with the model's prediction to find padding and tight sections.

        Args:
            train_number: Five-digit train number.
        """
        return _clip(services.timetable_slack(train_number))

    @beta_tool
    def plan_disruption(train_number: str, station_code: str, delay_min: int, headway_min: int = 6) -> str:
        """Propose holds that keep headway after a train is delayed. Returns a proposal only.

        Args:
            train_number: The delayed train.
            station_code: Station where the train's departure is delayed.
            delay_min: Delay in minutes (1-720).
            headway_min: Minimum separation between trains entering a section, in minutes.
        """
        if not 1 <= delay_min <= 720 or not 2 <= headway_min <= 30:
            return _clip({"error": "delay_min must be 1-720 and headway_min 2-30"})
        try:
            return _clip(services.plan(train_number, station_code, delay_min, headway_min))
        except (KeyError, ValueError) as exc:
            return _clip({"error": str(exc)})

    return [
        search_trains,
        search_stations,
        train_schedule,
        trains_between,
        station_board,
        busiest_sections,
        fastest_path,
        timetable_slack,
        plan_disruption,
    ]


class RailAssistant:
    def __init__(self, services: Services, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.tools = build_tools(services)
        self.messages: list[dict[str, Any]] = []

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        runner = self.client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        final = None
        for message in runner:
            final = message
            # Keep the full transcript (tool calls included) so later turns stay valid.
            self.messages.append({"role": "assistant", "content": message.content})
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                self.messages.append(tool_response)
        if final is None:
            return "No response."
        if final.stop_reason == "refusal":
            return "The request was declined by the model's safeguards."
        return "".join(block.text for block in final.content if block.type == "text").strip()
