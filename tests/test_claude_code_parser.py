import pytest
from pathlib import Path
from src.normalizers.claude_code import ClaudeCodeNormalizer


def test_claude_code_normalizer():
    normalizer = ClaudeCodeNormalizer()
    sample_lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Zbuduj kontener docker dla SvelteKit"},
            "timestamp": 1771091491658
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Sprawdzę package.json."},
                    {"type": "tool_use", "id": "tool_1", "name": "run_command", "input": {"command": "cat package.json"}}
                ]
            },
            "timestamp": 1771091495000
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_1", "content": '{"name": "homepage"}'}
                ]
            },
            "timestamp": 1771091496000
        }
    ]

    conv = normalizer.parse(sample_lines, metadata={"session_id": "sess-abc", "project_path": "/home/user/project"})

    assert conv.platform == "claude_code"
    assert conv.external_id == "sess-abc"
    assert conv.title == "Zbuduj kontener docker dla SvelteKit"
    assert conv.project_path == "/home/user/project"

    # User message + Assistant message (tool_result attached to tool_use)
    assert len(conv.messages) == 2
    asst_msg = conv.messages[1]
    assert len(asst_msg.tool_calls) == 1
    assert asst_msg.tool_calls[0].output == '{"name": "homepage"}'


def test_daemon_claude_code_parser():
    from daemon.parsers.claude_code import ClaudeCodeParser
    import tempfile

    parser = ClaudeCodeParser()
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "session-123.jsonl"
        fpath.write_text(
            '{"type":"user","message":{"role":"user","content":"Test question"}}\n'
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Test answer"}]}}\n',
            encoding="utf-8"
        )
        conv = parser.parse_file(fpath)
        assert conv.platform == "claude_code"
        assert conv.external_id == "session-123"
        assert len(conv.messages) == 2


def test_claude_code_chunk_merge_and_token_summary():
    normalizer = ClaudeCodeNormalizer()
    sample_lines = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Analyze code"},
            "timestamp": 1771091490000
        },
        # Chunk 1: thinking only (should not become empty message)
        {
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "Let me search files", "signature": "sig1"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 100,
                    "cache_read_input_tokens": 500,
                    "cache_creation_input_tokens": 200,
                    "output_tokens_details": {"thinking_tokens": 50}
                }
            },
            "timestamp": 1771091491000
        },
        # Chunk 2: tool use with same msg_id (should be merged into msg_001)
        {
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 120,
                    "cache_read_input_tokens": 500,
                    "cache_creation_input_tokens": 200,
                    "output_tokens_details": {"thinking_tokens": 50}
                }
            },
            "timestamp": 1771091492000
        },
        # Tool result
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file.txt"}]
            },
            "timestamp": 1771091493000
        },
        # Final answer
        {
            "type": "assistant",
            "message": {
                "id": "msg_002",
                "role": "assistant",
                "content": [{"type": "text", "text": "Found file.txt"}],
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 600,
                    "cache_creation_input_tokens": 50
                }
            },
            "timestamp": 1771091494000
        }
    ]

    conv = normalizer.parse(sample_lines, metadata={"session_id": "sess-chunk"})
    assert conv is not None
    # Exactly 3 messages: user, assistant (merged thinking+tool), assistant (text)
    assert len(conv.messages) == 3

    msg1 = conv.messages[1]
    assert msg1.role == "assistant"
    assert msg1.external_id == "msg_001"
    assert msg1.reasoning_content == "Let me search files"
    assert len(msg1.tool_calls) == 1
    assert msg1.tool_calls[0].name == "Bash"
    assert msg1.tool_calls[0].output == "file.txt"
    assert msg1.token_usage["output_tokens"] == 120

    msg2 = conv.messages[2]
    assert msg2.role == "assistant"
    assert msg2.content == "Found file.txt"

    token_sum = conv.raw_metadata.get("token_summary")
    assert token_sum is not None
    assert token_sum["input_tokens"] == 15
    assert token_sum["output_tokens"] == 160
    assert token_sum["cache_read_tokens"] == 1100
    assert token_sum["cache_write_tokens"] == 250
    assert token_sum["total_tokens"] == 15 + 160 + 1100 + 250


