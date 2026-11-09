from src.normalizers.mirror import MirrorNormalizer


# --- tiny protobuf encoder (mirrors the wire format MirrorNormalizer reads) ---
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wt: int) -> bytes:
    return _varint((field << 3) | wt)


def fv(field: int, n: int) -> bytes:
    return _tag(field, 0) + _varint(n)


def fs(field: int, data) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _tag(field, 2) + _varint(len(data)) + data


TS = fs(3, fv(1, 1792879950))  # timestamp {1: unix_seconds}


def user_entry(seq, text):
    inner = fs(2, fs(1, text))           # 4.2 { 1: text }
    return fv(1, seq) + fs(2, f"u{seq}") + TS + fs(4, inner)


def assistant_entry(seq, content, reasoning, call_id, tool, args_json,
                    prompt_total, out_tok, cache_read):
    fn = fs(1, tool) + fs(2, args_json)                       # 4.3.2.3 {name,args}
    toolcall = fs(1, call_id) + fs(2, "function") + fs(3, fn)  # 4.3.2
    asst = fs(1, content) + fs(2, toolcall) + fs(3, reasoning) # 4.3
    usage = fv(1, prompt_total) + fv(2, out_tok) + fv(3, cache_read)  # 4.5
    entry = fs(3, asst) + fs(5, usage) + fv(7, 1)
    model = fs(1, "Beam-1.0-501B-A23B") + fs(2, "reflection")
    return fv(1, seq) + fs(2, f"a{seq}") + TS + fs(4, entry) + fs(8, model)


def tool_result_entry(seq, call_id, output, tool):
    res = fs(1, call_id) + fs(2, output) + fs(3, tool)  # 4.4 { call_id, output, tool }
    entry = fs(4, res)                                   # entry wrapper: field 4
    return fv(1, seq) + fs(2, f"t{seq}") + TS + fs(4, entry)


def status_entry(seq, call_id):
    # field 13 lifecycle marker, no field 4 -> must be skipped
    return fv(1, seq) + fs(2, f"s{seq}") + TS + fs(13, fs(1, call_id) + fs(2, "bash") + fv(3, 1))


def test_mirror_real_usage_and_structure():
    payloads = [
        user_entry(1, "ping\nsecond line"),
        assistant_entry(2, "pong done", "thinking about it", "call-1", "bash",
                        '{"command": "ls"}', prompt_total=9743, out_tok=63, cache_read=8448),
        status_entry(3, "call-1"),
        tool_result_entry(4, "call-1", "file_a\nfile_b", "bash"),
    ]
    conv = MirrorNormalizer()._build("sess-abc", "/home/u/proj", payloads, {})

    assert conv.platform == "mirror"
    assert conv.external_id == "sess-abc"
    assert conv.project_path == "/home/u/proj"
    assert conv.model == "Beam-1.0-501B-A23B"
    assert conv.raw_metadata.get("provider") == "reflection"
    assert conv.title == "ping"  # first line of first user message

    assert [m.role for m in conv.messages] == ["user", "assistant"]  # status skipped, result folded

    a = conv.messages[1]
    assert a.content == "pong done"
    assert a.reasoning_content == "thinking about it"
    assert len(a.tool_calls) == 1
    assert a.tool_calls[0].name == "bash"
    assert a.tool_calls[0].input == {"command": "ls"}
    assert a.tool_calls[0].output == "file_a\nfile_b"  # tool result correlated by call id

    u = a.token_usage
    assert u["input_tokens"] == 9743 - 8448  # non-cached prompt only
    assert u["output_tokens"] == 63
    assert u["cache_read_tokens"] == 8448
    assert u["total_tokens"] == (9743 - 8448) + 63 + 8448


def test_mirror_revalidation_list_path():
    """Server re-ingest path: already-normalized messages are passed straight through."""
    payload = [{
        "step_index": 0, "role": "user", "content": "hi",
        "created_at": "2026-10-24T20:00:00Z", "token_usage": {},
    }]
    conv = MirrorNormalizer().parse(payload, {"session_id": "s1", "project_path": "/p"})
    assert conv.platform == "mirror"
    assert conv.external_id == "s1"
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hi"
