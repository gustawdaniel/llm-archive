import sqlite3
import pytest
from datetime import datetime, timezone
from src.normalizers.antigravity import AntigravityNormalizer


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _fv(f, n):
    return _varint((f << 3) | 0) + _varint(n)


def _fs(f, data):
    return _varint((f << 3) | 2) + _varint(len(data)) + data


def test_recover_session_usage_from_db(tmp_path, monkeypatch):
    """Historical sessions keep real usage in the per-session db at
    step_payload field 5.9 {2:input, 3:output, 5:cache_read}."""
    db = tmp_path / "sess.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE steps (idx INTEGER PRIMARY KEY, step_payload BLOB)")
    # two model steps with usage
    for idx, (i, o, c) in enumerate([(1000, 50, 0), (1200, 30, 950)]):
        usage = _fv(2, i) + _fv(3, o) + _fv(5, c)   # 5.9 inner
        payload = _fs(5, _fs(9, usage))              # field 5 -> field 9 -> usage
        conn.execute("INSERT INTO steps VALUES (?, ?)", (idx, payload))
    conn.commit()
    conn.close()

    norm = AntigravityNormalizer()
    monkeypatch.setattr(norm, "_find_session_db", lambda cid: db)
    assert norm._recover_session_usage("sess-x") == (2200, 80, 950)


def test_antigravity_normalizer_basic():
    normalizer = AntigravityNormalizer()
    sample_lines = [
        {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-05-27T18:48:28Z",
            "content": "<USER_REQUEST>\nJak skonfigurować Caddy jako reverse proxy?\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime: 2026-05-27\n</ADDITIONAL_METADATA>"
        },
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-05-27T18:48:30Z",
            "content": "Pokażę konfigurację Caddyfile.",
            "tool_calls": [
                {
                    "name": "view_file",
                    "args": {"AbsolutePath": "/etc/caddy/Caddyfile"}
                }
            ]
        }
    ]

    conv = normalizer.parse(sample_lines, metadata={"conversation_id": "test-conv-123"})

    assert conv.platform == "antigravity"
    assert conv.external_id == "test-conv-123"
    assert conv.title == "Jak skonfigurować Caddy jako reverse proxy?"
    assert len(conv.messages) == 2

    user_msg = conv.messages[0]
    assert user_msg.role == "user"
    assert "ADDITIONAL_METADATA" not in user_msg.content
    assert user_msg.content == "Jak skonfigurować Caddy jako reverse proxy?"

    asst_msg = conv.messages[1]
    assert asst_msg.role == "assistant"
    assert len(asst_msg.tool_calls) == 1
    assert asst_msg.tool_calls[0].name == "view_file"
    assert asst_msg.tool_calls[0].input["AbsolutePath"] == "/etc/caddy/Caddyfile"
    assert conv.tools_used == ["view_file"]


def test_antigravity_uses_real_token_usage():
    """When the transcript carries real per-call usage, sum it across the turn
    instead of char-count estimating."""
    normalizer = AntigravityNormalizer()
    lines = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
         "status": "DONE", "created_at": "2026-10-24T20:00:00Z",
         "content": "<USER_REQUEST>\nping\n</USER_REQUEST>"},
        # Two model calls in one turn (agent loop) -> usage must be summed.
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE",
         "status": "DONE", "created_at": "2026-10-24T20:00:01Z",
         "content": "", "input_tokens": 1000, "output_tokens": 10, "cache_read_tokens": 500},
        {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE",
         "status": "DONE", "created_at": "2026-10-24T20:00:02Z",
         "content": "pong", "input_tokens": 1200, "output_tokens": 5, "cache_read_tokens": 800},
    ]
    conv = normalizer.parse(lines, metadata={"conversation_id": "real-usage"})
    asst = [m for m in conv.messages if m.role == "assistant"]
    assert len(asst) == 1
    u = asst[0].token_usage
    assert u["input_tokens"] == 2200
    assert u["output_tokens"] == 15
    assert u["cache_read_tokens"] == 1300
    assert u["total_tokens"] == 2200 + 15 + 1300
    assert not u.get("is_estimated")


def test_antigravity_estimates_when_no_usage():
    """Older transcripts with no usage fields still fall back to an estimate."""
    normalizer = AntigravityNormalizer()
    lines = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
         "status": "DONE", "created_at": "2026-10-24T20:00:00Z",
         "content": "<USER_REQUEST>\nping\n</USER_REQUEST>"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE",
         "status": "DONE", "created_at": "2026-10-24T20:00:01Z",
         "content": "pong " * 20},
    ]
    conv = normalizer.parse(lines, metadata={"conversation_id": "est-usage"})
    asst = [m for m in conv.messages if m.role == "assistant"]
    assert len(asst) == 1
    u = asst[0].token_usage
    assert u.get("is_estimated")
    assert u["total_tokens"] > 0
    assert "input_tokens" not in u


def test_daemon_antigravity_parser(tmp_path):
    import json
    from daemon.parsers.antigravity import AntigravityParser

    parser = AntigravityParser()
    brain_dir = tmp_path / "brain" / "conv-456" / ".system_generated" / "logs"
    brain_dir.mkdir(parents=True)
    transcript_file = brain_dir / "transcript.jsonl"

    lines = [
        {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-05-27T18:48:28Z",
            "content": "<USER_REQUEST>\nTest query for Antigravity\n</USER_REQUEST>"
        },
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-05-27T18:48:30Z",
            "content": "Test response from model"
        }
    ]

    with open(transcript_file, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    # Test scanning
    transcripts = parser.scan_transcripts(tmp_path)
    assert len(transcripts) == 1
    assert transcripts[0] == transcript_file

    # Test parsing file
    conv = parser.parse_file(transcript_file, metadata={"conversation_id": "conv-456"})
    assert conv.external_id == "conv-456"
    assert conv.platform == "antigravity"
    assert len(conv.messages) == 2
    assert conv.messages[0].content == "Test query for Antigravity"

