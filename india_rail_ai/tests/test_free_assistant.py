"""The free assistants: offline pattern matching and a mocked local Ollama server."""

from __future__ import annotations

import io
import json

import pytest

from india_rail import free_assistant
from india_rail.free_assistant import OfflineAssistant, OllamaAssistant, make_assistant
from india_rail.services import Services


@pytest.fixture()
def services(db_path, tmp_path):
    return Services(db_path=db_path, model_path=tmp_path / "missing.joblib")


def test_offline_plan_question(services):
    answer = OfflineAssistant(services).ask("54001 is 3 min late at AAA, what should we hold?")
    assert answer.startswith("PROPOSAL for controller review")
    assert "54001" in answer and "Rajdhani" not in answer


def test_offline_resolves_station_names(services):
    answer = OfflineAssistant(services).ask("trains from Station AAA to Station CCC")
    assert "54001" in answer and "12001" in answer
    assert "Fastest: 12001" in answer


def test_offline_schedule_and_help(services):
    assistant = OfflineAssistant(services)
    assert "AAA" in assistant.ask("schedule of 19001")
    assert "without any paid service" in assistant.ask("what is the weather")


def test_auto_falls_back_to_offline_without_ollama(services, monkeypatch):
    monkeypatch.setattr(OllamaAssistant, "available", staticmethod(lambda *a, **k: False))
    assert make_assistant(services, "auto").name == "offline"


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_ollama_tool_loop(services, monkeypatch):
    sent = []

    def fake_urlopen(request, timeout=0):
        body = json.loads(request.data)
        sent.append(body)
        if len(sent) == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "trains_between", "arguments": {"origin": "AAA", "destination": "CCC"}}}
                ],
            }
        else:
            message = {"role": "assistant", "content": "Three trains run AAA to CCC."}
        return _Response(json.dumps({"message": message}).encode())

    monkeypatch.setattr(free_assistant.urllib.request, "urlopen", fake_urlopen)
    answer = OllamaAssistant(services, url="http://ollama.test").ask("AAA to CCC?")
    assert answer == "Three trains run AAA to CCC."
    assert {t["function"]["name"] for t in sent[0]["tools"]} >= {"plan_disruption", "trains_between"}
    tool_message = sent[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "12001" in tool_message["content"]


def test_unknown_tool_and_bad_arguments_become_errors(services):
    tools = OfflineAssistant(services).tools
    assert "Unknown tool" in tools.call("drop_tables", {})
    assert "Missing arguments" in tools.call("plan_disruption", {"train_number": "54001"})
