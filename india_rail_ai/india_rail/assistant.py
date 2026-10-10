"""Optional Claude-powered assistant (paid Anthropic API; never used by default).

The free assistants in `free_assistant.py` are the default. This one is only
used when explicitly selected with provider "claude", and each question is
billed to the caller's own Anthropic account.

It answers by calling the same read-only tools as the other assistants. It can
propose a re-plan but cannot apply one: no tool writes to any system.
"""

from __future__ import annotations

from typing import Any

import anthropic
from anthropic import beta_tool

from india_rail.services import Services
from india_rail.tools import SYSTEM_PROMPT, RailTools, clip

MODEL = "claude-opus-5-5"


def build_tools(services: Services) -> list:
    """Wrap the shared tools; the decorator derives each schema from the docstring."""

    tools = RailTools(services)

    @beta_tool
    def search_trains(query: str) -> str:
        """Find trains by number or (partial) name.

        Args:
            query: Train number such as "12951" or part of a name such as "Rajdhani".
        """
        return clip(tools.search_trains(query))

    @beta_tool
    def search_stations(query: str) -> str:
        """Find stations by code or (partial) name.

        Args:
            query: Station code such as "NDLS" or part of a name such as "Howrah".
        """
        return clip(tools.search_stations(query))

    @beta_tool
    def train_schedule(train_number: str) -> str:
        """Return a train's timetable: origin, destination and every booked halt.

        Args:
            train_number: Five-digit train number.
        """
        return clip(tools.train_schedule(train_number))

    @beta_tool
    def trains_between(origin: str, destination: str) -> str:
        """List direct trains from one station to another, ordered by departure time.

        Args:
            origin: Origin station code.
            destination: Destination station code.
        """
        return clip(tools.trains_between(origin, destination))

    @beta_tool
    def station_board(station_code: str) -> str:
        """List trains calling at a station, ordered by time of day.

        Args:
            station_code: Station code.
        """
        return clip(tools.station_board(station_code))

    @beta_tool
    def busiest_sections(zone: str = "", limit: int = 15) -> str:
        """Rank track sections by scheduled trains per day.

        Args:
            zone: Optional railway zone code such as "CR" or "NR" to restrict by train zone.
            limit: Number of sections to return (max 50).
        """
        return clip(tools.busiest_sections(zone, limit))

    @beta_tool
    def fastest_path(origin: str, destination: str) -> str:
        """Quickest station sequence across the network by median scheduled run time.

        Args:
            origin: Origin station code.
            destination: Destination station code.
        """
        return clip(tools.fastest_path(origin, destination))

    @beta_tool
    def timetable_slack(train_number: str) -> str:
        """Compare a train's scheduled run times with the model's prediction to find padding and tight sections.

        Args:
            train_number: Five-digit train number.
        """
        return clip(tools.timetable_slack(train_number))

    @beta_tool
    def plan_disruption(train_number: str, station_code: str, delay_min: int, headway_min: int = 6) -> str:
        """Propose holds that keep headway after a train is delayed. Returns a proposal only.

        Args:
            train_number: The delayed train.
            station_code: Station where the train's departure is delayed.
            delay_min: Delay in minutes (1-720).
            headway_min: Minimum separation between trains entering a section, in minutes.
        """
        return clip(tools.plan_disruption(train_number, station_code, delay_min, headway_min))

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
    name = "claude"

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
