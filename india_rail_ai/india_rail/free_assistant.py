"""Free assistants: no API keys, no paid services, nothing leaves your machine.

* OfflineAssistant understands the common question types with plain pattern
  matching and calls the shared tools directly. It needs nothing installed.
* OllamaAssistant uses a free open-source model running locally under Ollama
  (https://ollama.com) with full natural-language tool calling.

`make_assistant("auto")` uses Ollama when it is running and falls back to the
offline assistant otherwise. The paid Claude assistant is only used when it is
asked for by name.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from india_rail.services import Services
from india_rail.tools import SYSTEM_PROMPT, RailTools, json_schema_tools

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def _http_url(url: str) -> str:
    """Only http(s) endpoints: an OLLAMA_URL of file:// or another scheme must never be opened."""

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Ollama URL must be http(s), got {url.split(':', 1)[0]}:")
    return url.rstrip("/")


OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
MAX_TOOL_ROUNDS = 8

TRAIN_RE = re.compile(r"\b(\d{5})\b")
DELAY_RE = re.compile(r"\b(\d{1,3})\s*(?:min|mins|minutes|minute|m)\b", re.IGNORECASE)
PLACE_STOP = r"(?=\s+(?:by|is|and|running|late|delayed|station|what|which|who|how|today)\b|[,.?!]|$)"
AT_RE = re.compile(r"\bat\s+([A-Za-z][A-Za-z .()-]*?)" + PLACE_STOP, re.IGNORECASE)
BETWEEN_RE = re.compile(
    r"\b(?:from|between)\s+([A-Za-z][A-Za-z .()-]*?)\s+(?:to|and)\s+([A-Za-z][A-Za-z .()-]*?)" + PLACE_STOP,
    re.IGNORECASE,
)
ZONE_RE = re.compile(r"\b(CR|ER|ECR|ECoR|NR|NCR|NER|NFR|NWR|SR|SCR|SER|SECR|SWR|WR|WCR|KR)\b")

HELP = """I can answer these without any paid service:
  - "12002 is 30 min late at NDLS"            -> proposed holds for the controller
  - "trains from New Delhi to Howrah"         -> direct trains, by departure time
  - "fastest route from NDLS to HWH"          -> quickest path through the network
  - "schedule of 12951"                       -> booked halts
  - "trains at BCT" / "station board for Pune"
  - "busiest sections" (optionally with a zone, e.g. "busiest sections WR")
  - "slack in 12951"                          -> padded and tight sections vs the model
  - "find Rajdhani" / "station code for Lucknow"
For free-form questions, install Ollama (https://ollama.com), run `ollama pull qwen2.5:7b`,
and ask again: the local AI assistant is used automatically."""


class OfflineAssistant:
    """Pattern-matching assistant over the shared tools. Free and fully offline."""

    name = "offline"

    def __init__(self, services: Services):
        self.tools = RailTools(services)

    # ---- helpers -----------------------------------------------------------
    def _station(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if not text:
            return None
        exact = self.tools.net.station(text) if len(text) <= 5 else None
        if exact:
            return exact
        matches = self.tools.search_stations(text)
        return matches[0] if matches else None

    @staticmethod
    def _label(station: dict[str, Any]) -> str:
        return f"{station['name']} ({station['code']})"

    # ---- intents -----------------------------------------------------------
    def ask(self, question: str) -> str:
        q = question.strip()
        lower = q.lower()
        trains = TRAIN_RE.findall(q)
        delay = DELAY_RE.search(q)

        if trains and delay and any(w in lower for w in ("late", "delay", "held", "behind", " at ")):
            return self._plan(trains[0], q, int(delay.group(1)))
        if trains and any(w in lower for w in ("slack", "padding", "padded", "tight", "recover")):
            return self._slack(trains[0])
        between = BETWEEN_RE.search(q)
        if between:
            fastest = any(w in lower for w in ("fastest", "quickest", "route", "path"))
            return self._between(between.group(1), between.group(2), fastest)
        if any(w in lower for w in ("busiest", "busy", "congested", "crowded")):
            zone = ZONE_RE.search(q)
            return self._busiest(zone.group(1) if zone else "")
        if any(w in lower for w in ("board", "trains at", "calling at", "stop at", "stopping at")):
            at = AT_RE.search(q) or re.search(r"\bfor\s+([A-Za-z][A-Za-z .()-]*?)" + PLACE_STOP, q, re.IGNORECASE)
            if at:
                return self._board(at.group(1))
        if any(w in lower for w in ("station code", "code for", "which station", "find station")):
            name = re.split(r"station code|code for|find station|which station is", q, flags=re.I)[-1]
            name = re.sub(r"^\s*(for|of)\b", "", name, flags=re.I)
            return self._search_stations(name.strip(" ?."))
        if trains:
            return self._schedule(trains[0])
        if lower.startswith(("find", "search")):
            return self._search_trains(re.sub(r"^(find|search)( for)?( train)?", "", q, flags=re.I).strip(" ?."))
        return HELP

    def _plan(self, train: str, question: str, delay: int) -> str:
        tl = self.tools.net.schedule(train)
        if not tl:
            return f"I couldn't find train {train} in the timetable."
        at = AT_RE.search(question)
        station = None
        if at:
            station = self._station(at.group(1))
        else:
            codes = {s["station_code"] for s in tl}
            words = re.findall(r"\b[A-Z]{2,5}\b", question)
            station = next((self.tools.net.station(w) for w in words if w in codes), None)
        if station is None:
            return f"Where is {train} delayed? Say e.g. '{train} is {delay} min late at {tl[0]['station_code']}'."
        calls_at = {s["station_code"] for s in tl}
        if station["code"] not in calls_at:
            # A name search can pick a different station in the same city; prefer one this train calls at.
            candidates = self.tools.search_stations(at.group(1) if at else station["name"])
            calling = [s for s in candidates if s["code"] in calls_at]
            if not calling:
                return f"Train {train} does not call at {self._label(station)}."
            station = calling[0]
        plan = self.tools.plan_disruption(train, station["code"], delay)
        if "error" in plan:
            return plan["error"]
        lines = [
            f"PROPOSAL for controller review — {train} running {delay} min late at {self._label(station)}",
            f"Conflicts found: {plan['conflicts_detected']}. Trains affected: {len(plan['train_impacts'])}. "
            f"Total delay at destinations: {plan['total_delay_at_destinations_min']} min.",
        ]
        if plan["hold_summary"]:
            lines.append("Holds proposed:")
            for item in plan["hold_summary"][:10]:
                first = next(a for a in plan["actions"] if a["train_number"] == item["train_number"])
                lines.append(
                    f"  - {item['train_number']}: {item['total_hold_min']} min over {item['holds']} hold(s); "
                    f"first at {first['station_code']} — {first['reason']}"
                )
        else:
            lines.append("No holds needed: the delay does not squeeze any other train below its planned separation.")
        late = [i for i in plan["train_impacts"] if i["projected_delay_at_destination_min"] >= 1]
        if late:
            lines.append("Projected delay at destination:")
            lines += [
                f"  - {i['train_number']} ({i['train_type'] or '?'}) to {i['destination']}: "
                f"{i['projected_delay_at_destination_min']} min"
                for i in sorted(late, key=lambda x: -x["projected_delay_at_destination_min"])[:10]
            ]
        if plan["unresolved"]:
            lines.append(f"Unresolved items: {len(plan['unresolved'])} (cascade limit); review manually.")
        lines.append("Assumptions: " + " ".join(plan["assumptions"]))
        return "\n".join(lines)

    def _slack(self, train: str) -> str:
        result = self.tools.timetable_slack(train)
        if "error" in result:
            return result["error"]
        lines = [
            f"Train {train}: scheduled running {result['scheduled_running_min']} min, "
            f"model expects {result['predicted_running_p50_min']} min; "
            f"about {result['recoverable_min_vs_p10']} min is recoverable at fast-but-typical running.",
            "Most padded sections:",
        ]
        lines += [
            f"  - {s['section']} (dep {s['departs']}): scheduled {s['scheduled_min']}, typical {s['predicted_p50_min']}"
            for s in result["most_padded_sections"]
        ]
        lines.append("Tightest sections:")
        lines += [
            f"  - {s['section']} (dep {s['departs']}): scheduled {s['scheduled_min']}, typical {s['predicted_p50_min']}"
            for s in result["tightest_sections"]
        ]
        return "\n".join(lines)

    def _between(self, origin_text: str, destination_text: str, fastest: bool) -> str:
        origin, destination = self._station(origin_text), self._station(destination_text)
        if origin is None or destination is None:
            missing = origin_text if origin is None else destination_text
            return f"I couldn't find a station matching '{missing}'. Try its code, e.g. NDLS."
        if fastest:
            path = self.tools.fastest_path(origin["code"], destination["code"])
            if "error" in path:
                return path["error"]
            hours, minutes = divmod(int(path["running_minutes"]), 60)
            via = path["stations"]
            return (
                f"Fastest network path {self._label(origin)} -> {self._label(destination)}: "
                f"about {hours} h {minutes} min of running over {path['hops']} sections "
                f"(via {', '.join(via[1:-1][:: max(1, len(via) // 8)][:8])}). "
                "This is a path, not a single train; connection waits are not included."
            )
        rows = self.tools.trains_between(origin["code"], destination["code"])
        if not rows:
            return f"No direct train from {self._label(origin)} to {self._label(destination)} in this timetable."
        lines = [f"Direct trains {self._label(origin)} -> {self._label(destination)} (2016 timetable, all days):"]
        for r in rows[:15]:
            hours, minutes = divmod(r["travel_min"], 60)
            lines.append(
                f"  - {r['number']} {r['name']} ({r['type'] or '?'}): "
                f"dep {r['departs']}, arr {r['arrives']}, {hours}h{minutes:02d}"
            )
        best = min(rows, key=lambda r: r["travel_min"])
        lines.append(f"Fastest: {best['number']} {best['name']}.")
        return "\n".join(lines)

    def _busiest(self, zone: str) -> str:
        rows = self.tools.busiest_sections(zone=zone, limit=10)
        title = f"Busiest sections{' for ' + zone + ' trains' if zone else ''} (scheduled trains per day, both ways):"
        return "\n".join(
            [title] + [f"  - {r['station_a']}-{r['station_b']}: {r['trains_per_day']} trains/day" for r in rows]
        )

    def _board(self, text: str) -> str:
        station = self._station(text)
        if station is None:
            return f"I couldn't find a station matching '{text}'."
        rows = self.tools.station_board(station["code"])
        lines = [f"Trains at {self._label(station)} by time of day (first {len(rows)}):"]
        lines += [f"  - {r['departure'][:5]} {r['number']} {r['name']} ({r['type'] or '?'})" for r in rows]
        return "\n".join(lines)

    def _schedule(self, train: str) -> str:
        result = self.tools.train_schedule(train)
        if "error" in result:
            return result["error"]
        info = result["train"]
        lines = [f"{train} {info['name']} ({info['type']}), {info['from_code']} -> {info['to_code']}:"]
        lines += [
            f"  - {h['station_code']} {h['station_name']}: arr {h['arrival']}, dep {h['departure']}"
            for h in result["halts"]
        ]
        return "\n".join(lines)

    def _search_trains(self, text: str) -> str:
        rows = self.tools.search_trains(text)
        if not rows:
            return f"No train matches '{text}'."
        return "\n".join(
            f"  - {r['number']} {r['name']} ({r['type']}): {r['from_code']} -> {r['to_code']}" for r in rows
        )

    def _search_stations(self, text: str) -> str:
        rows = self.tools.search_stations(text)
        if not rows:
            return f"No station matches '{text}'."
        return "\n".join(
            f"  - {r['code']}: {r['name']}"
            + (f" ({r['state']})" if r.get("state") else "")
            + f", {r['train_calls']} train calls"
            for r in rows
        )


class OllamaAssistant:
    """Natural-language assistant on a free local model served by Ollama."""

    name = "ollama"

    def __init__(self, services: Services, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL, timeout: float = 300):
        self.tools = RailTools(services)
        self.model = model
        self.url = _http_url(url)
        self.timeout = timeout
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    @staticmethod
    def available(url: str = OLLAMA_URL, timeout: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(f"{_http_url(url)}/api/tags", timeout=timeout) as response:  # nosec B310
                return response.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _chat(self) -> dict[str, Any]:
        body = json.dumps(
            {"model": self.model, "messages": self.messages, "tools": json_schema_tools(), "stream": False}
        ).encode()
        request = urllib.request.Request(
            f"{self.url}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310 - http(s) checked
            return json.load(response)

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(MAX_TOOL_ROUNDS):
            message = self._chat().get("message", {})
            self.messages.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                return (message.get("content") or "").strip()
            for call in calls:
                function = call.get("function", {})
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                result = self.tools.call(function.get("name", ""), arguments)
                self.messages.append({"role": "tool", "content": result, "tool_name": function.get("name", "")})
        return "Stopped after too many tool calls; try a more specific question."


def make_assistant(services: Services, provider: str = "auto") -> Any:
    """Pick an assistant. "auto" is always free: Ollama if running, else offline."""

    provider = provider.lower()
    if provider == "auto":
        provider = "ollama" if OllamaAssistant.available() else "offline"
    if provider == "offline":
        return OfflineAssistant(services)
    if provider == "ollama":
        return OllamaAssistant(services)
    if provider == "claude":
        from india_rail.assistant import RailAssistant  # paid API, opt-in only

        return RailAssistant(services)
    raise ValueError(f"Unknown assistant provider {provider!r}; use auto, offline, ollama or claude")
