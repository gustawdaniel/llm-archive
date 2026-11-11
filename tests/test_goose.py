import pytest
from pathlib import Path
from src.normalizers import GooseNormalizer


def test_goose_normalizer_real():
    goose_db = Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"
    if not goose_db.is_file():
        pytest.skip("Goose sessions.db not found")

    norm = GooseNormalizer()
    conv = norm.parse(goose_db, {"session_id": "20261108_1"})
    assert conv.platform == "goose"
    assert conv.external_id == "20261108_1"
    assert conv.title == "DigitalOcean cost analysis"
    assert len(conv.messages) > 0
    assert conv.model == "deepseek-flash"
    assert "shell" in conv.tools_used

    # Test token summary
    tok_sum = conv.raw_metadata.get("token_summary")
    assert tok_sum is not None
    assert tok_sum.get("input_tokens", 0) > 0

    # Verify no raw turn-context remains in message contents
    for m in conv.messages:
        assert "<turn-context>" not in m.content

    # Test re-parse from serialized NormalizedMessage list (HTTP ingest pathway)
    payload = [m.model_dump(mode="json") for m in conv.messages]
    rehydrated = norm.parse(
        payload,
        {
            "session_id": conv.external_id,
            "title": conv.title,
            "project_path": conv.project_path,
            "device": "mac",
            "model": conv.model,
        },
    )
    assert rehydrated.platform == "goose"
    assert rehydrated.external_id == conv.external_id
    assert len(rehydrated.messages) == len(conv.messages)
