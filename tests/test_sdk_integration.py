"""Drive the real anthropic SDK against a mock HTTP transport.

The FakeClient tests check our logic; this one checks the contract with the SDK:
the request it actually puts on the wire, and that its typed response objects
work with the analyzer loop. No network, no API key.
"""

import json

import anthropic
import httpx2

from agent.analyzer import Analyzer
from agent.collector import ErrorGroup
from tests.conftest import finding_json


def api_message(content, stop_reason):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 150, "cache_read_input_tokens": 800,
                  "cache_creation_input_tokens": 0},
    }


def test_real_sdk_round_trip(settings, audit):
    replies = [
        api_message(
            [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "demo_app/main.py"}},
            ],
            "tool_use",
        ),
        api_message([{"type": "text", "text": finding_json()}], "end_turn"),
    ]
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request, json.loads(request.content)))
        return httpx2.Response(200, json=replies[len(seen) - 1])

    client = anthropic.Anthropic(api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    group = ErrorGroup("fp1", "exception", "ZeroDivisionError in stats")
    group.add({"msg": "boom"})

    finding = Analyzer(settings, audit, client).investigate(group)

    assert finding is not None and finding.severity == "high"
    first_req, body = seen[0]
    assert first_req.url.path == "/v1/messages"
    assert "server-side-fallback-2026-07-01" in first_req.headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert all(t["strict"] for t in body["tools"])
    assert "tool_choice" not in body  # forced tool choice is rejected on this model

    # Turn 2 echoes the assistant turn (thinking block included) and returns the tool result.
    _, body2 = seen[1]
    assistant, tool_turn = body2["messages"][1], body2["messages"][2]
    assert [b["type"] for b in assistant["content"]] == ["thinking", "tool_use"]
    assert tool_turn["content"][0]["tool_use_id"] == "toolu_1"
    assert "len(orders)" in tool_turn["content"][0]["content"]


def _client_returning(status: int, body: dict) -> anthropic.Anthropic:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(status, json=body))
    return anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=httpx2.Client(transport=transport))


def _write_error_log(settings):
    entry = {"level": "ERROR", "msg": "x",
             "exception": {"type": "KeyError", "frames": [{"file": "demo_app/main.py", "line": 1, "func": "f"}]}}
    settings.log_file.write_text(json.dumps(entry) + "\n")


def test_invalid_api_key_aborts_with_exit_code_2(settings, capsys):
    from agent.main import run

    _write_error_log(settings)
    err = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    assert run(settings, client=_client_returning(401, err)) == 2
    assert "AuthenticationError" in capsys.readouterr().err


def test_bad_request_skips_group_but_finishes_run(settings):
    from agent.main import run

    _write_error_log(settings)
    err = {"type": "error", "error": {"type": "invalid_request_error", "message": "nope"}}
    assert run(settings, client=_client_returning(400, err)) == 0
    assert next(settings.reports_dir.glob("*/report.md")).exists()
    assert '"api_error"' in settings.audit_file.read_text()
