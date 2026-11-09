import pytest
from pathlib import Path
from src.normalizers import ZedNormalizer, HermesNormalizer


def test_zed_normalizer_real():
    zed_db = Path.home() / ".local" / "share" / "zed" / "threads" / "threads.db"
    if not zed_db.is_file():
        pytest.skip("Zed threads.db not found")

    norm = ZedNormalizer()
    conv = norm.parse(zed_db)
    assert conv.platform == "zed"
    assert conv.external_id
    assert conv.title
    assert len(conv.messages) > 0
    assert bool(conv.model)
    cum_tok = conv.raw_metadata.get("cumulative_token_usage")
    assert cum_tok is not None
    assert cum_tok.get("input_tokens", 0) > 0


def test_hermes_normalizer_real():
    hermes_db = Path.home() / ".hermes" / "state.db"
    if not hermes_db.is_file():
        pytest.skip("Hermes state.db not found")

    norm = HermesNormalizer()
    conv = norm.parse(hermes_db)
    assert conv.platform == "hermes"
    assert conv.external_id
    assert conv.title
    assert len(conv.messages) > 0
    assert "gpt-4o" in conv.model or conv.model
    assert conv.raw_metadata.get("input_tokens", 0) > 0
