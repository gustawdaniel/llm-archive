import pytest
from pathlib import Path
from src.normalizers import OpenCodeNormalizer, AiderNormalizer, OMPNormalizer


def test_opencode_normalizer_real():
    db_path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
    if not db_path.is_file():
        pytest.skip("opencode.db not found")

    norm = OpenCodeNormalizer()
    conv = norm.parse(db_path)
    assert conv.platform == "opencode"
    assert conv.external_id.startswith("ses_")
    assert conv.title
    assert len(conv.messages) > 0
    assert bool(conv.model)
    token_sum = conv.raw_metadata.get("token_summary")
    assert token_sum is not None
    assert token_sum.get("input_tokens", 0) > 0


def test_aider_normalizer_real():
    history_file = Path.home() / "exp" / "llm-agents" / "aider" / ".aider.chat.history.md"
    if not history_file.is_file():
        history_file = Path.home() / ".aider.chat.history.md"
    if not history_file.is_file():
        pytest.skip("Aider chat history file not found")

    norm = AiderNormalizer()
    conv = norm.parse(history_file)
    assert conv.platform == "aider"
    assert conv.title
    assert len(conv.messages) > 0
    assert "deepseek" in conv.model
    token_sum = conv.raw_metadata.get("token_summary")
    assert token_sum is not None


def test_omp_normalizer_real():
    omp_sessions = list((Path.home() / ".omp" / "agent" / "sessions").glob("*/*.jsonl"))
    if not omp_sessions:
        pytest.skip("OMP sessions not found")

    norm = OMPNormalizer()
    conv = norm.parse(omp_sessions[0])
    assert conv.platform == "omp"
    assert conv.title
    assert len(conv.messages) > 0
    assert "deepseek" in conv.model
    token_sum = conv.raw_metadata.get("token_summary")
    assert token_sum is not None
    assert token_sum.get("total_tokens", 0) > 0
