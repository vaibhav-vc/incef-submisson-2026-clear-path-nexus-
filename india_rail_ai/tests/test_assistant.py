"""Exercise the assistant's tool loop against a mocked Messages API."""

from __future__ import annotations

import json

import anthropic
import httpx2 as httpx

from india_rail.assistant import MODEL, RailAssistant
from india_rail.services import Services


def _message(content, stop_reason):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_tool_loop_runs_real_tools(db_path, tmp_path):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=_message(
                    [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "trains_between",
                            "input": {"origin": "AAA", "destination": "CCC"},
                        }
                    ],
                    "tool_use",
                ),
            )
        return httpx.Response(200, json=_message([{"type": "text", "text": "Three direct trains."}], "end_turn"))

    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    services = Services(db_path=db_path, model_path=tmp_path / "missing.joblib")
    assistant = RailAssistant(services, client=client)

    assert assistant.ask("Which trains run AAA to CCC?") == "Three direct trains."
    assert requests[0]["model"] == MODEL
    assert {t["name"] for t in requests[0]["tools"]} >= {"plan_disruption", "trains_between"}
    tool_result = requests[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    content = tool_result["content"]
    text = content if isinstance(content, str) else "".join(part["text"] for part in content)
    assert "12001" in text
    # The transcript keeps the tool call and its result for later turns.
    assert [m["role"] for m in assistant.messages] == ["user", "assistant", "user", "assistant"]


def test_plan_tool_validates_bounds(db_path, tmp_path):
    services = Services(db_path=db_path, model_path=tmp_path / "missing.joblib")
    from india_rail.assistant import build_tools

    plan = {t.name: t for t in build_tools(services)}["plan_disruption"]
    assert "error" in json.loads(plan.call({"train_number": "54001", "station_code": "AAA", "delay_min": 0}))
    result = json.loads(plan.call({"train_number": "54001", "station_code": "AAA", "delay_min": 3}))
    assert result["status"] == "PROPOSED_FOR_CONTROLLER_REVIEW"
