import json
from pathlib import Path

import pytest

from src.normalizers import CodexNormalizer


def _line(kind, payload, ts="2026-10-03T22:44:27.000Z"):
    return json.dumps({"timestamp": ts, "type": kind, "payload": payload})


@pytest.fixture
def rollout(tmp_path: Path) -> Path:
    lines = [
        _line("session_meta", {"id": "01a103f0-sess", "timestamp": "2026-10-03T22:44:25.844Z", "cwd": "/home/ubuntu/task",
                               "cli_version": "0.160.0"}),
        _line("turn_context", {"model": "gpt-6.1-sol", "cwd": "/home/ubuntu/task"}),
        _line("response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<skills>"}]}),
        _line("response_item", {"type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": "<environment_context>\n</environment_context>"}],
                                "internal_chat_message_metadata_passthrough": {"content_item_kinds": ["environments.environment_context"]}}),
        _line("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Sum the numbers"}],
                                "internal_chat_message_metadata_passthrough": {"content_item_kinds": ["user.text"]}}),
        _line("response_item", {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Plan: read input"}]}),
        _line("response_item", {"type": "custom_tool_call", "call_id": "c1", "name": "exec", "input": "cat problem.md"}),
        _line("response_item", {"type": "custom_tool_call_output", "call_id": "c1",
                                "output": [{"type": "input_text", "text": "# Sum"}]}),
        _line("token_usage_record", {"usage": {"input_tokens": 100, "cached_input_tokens": 0, "cache_write_input_tokens": 90,
                                               "output_tokens": 10, "reasoning_output_tokens": 4, "total_tokens": 110}}),
        _line("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}),
        _line("token_usage_record", {"usage": {"input_tokens": 120, "cached_input_tokens": 90, "cache_write_input_tokens": 20,
                                               "output_tokens": 5, "reasoning_output_tokens": 0, "total_tokens": 125}}),
        _line("event_msg", {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 220, "cached_input_tokens": 90, "cache_write_input_tokens": 110,
            "output_tokens": 15, "reasoning_output_tokens": 4, "total_tokens": 235}}}),
    ]
    f = tmp_path / "rollout-2026-10-03T22-44-25-01a103f0-sess.jsonl"
    f.write_text("\n".join(lines) + "\n")
    return f


def test_codex_rollout(rollout: Path):
    conv = CodexNormalizer().parse(rollout)
    assert conv.platform == "codex"
    assert conv.external_id == "01a103f0-sess"
    assert conv.model == "gpt-6.1-sol"
    assert conv.project_path == "/home/ubuntu/task"
    assert conv.title == "Sum the numbers"
    assert [m.role for m in conv.messages] == ["user", "assistant"]  # developer + injected context dropped

    asst = conv.messages[1]
    assert asst.content == "Done."
    assert asst.reasoning_content == "Plan: read input"
    assert asst.tool_calls[0].name == "exec"
    assert asst.tool_calls[0].input == {"input": "cat problem.md"}
    assert asst.tool_calls[0].output == "# Sum"
    assert asst.token_usage["input_tokens"] == 220
    assert asst.token_usage["cache_read_tokens"] == 90

    ts = conv.raw_metadata["token_summary"]
    assert ts == {"input_tokens": 220, "cache_read_tokens": 90, "cache_write_tokens": 110,
                  "output_tokens": 15, "thinking_tokens": 4, "total_tokens": 235}


def test_codex_prenormalized_roundtrip(rollout: Path):
    conv = CodexNormalizer().parse(rollout)
    payload = [m.model_dump(mode="json") for m in conv.messages]
    again = CodexNormalizer().parse(payload, {"session_id": conv.external_id, "model": conv.model, "title": conv.title})
    assert again.model == "gpt-6.1-sol"
    assert len(again.messages) == len(conv.messages)


def test_codex_real_sessions():
    files = sorted((Path.home() / ".codex" / "sessions").glob("*/*/*/rollout-*.jsonl"))
    if not files:
        pytest.skip("no local Codex sessions")
    for f in files:
        conv = CodexNormalizer().parse(f)
        assert conv.messages, f
