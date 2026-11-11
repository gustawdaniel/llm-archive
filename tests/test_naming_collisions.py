"""Testy ochrony przed kolizją nazw plików (wspólny prefiks `external_id[:8]`)."""

from pathlib import Path

from src.naming import avoid_collision, collision_suffix, conversation_id, file_owner_id


def _write(tmp_path: Path, rel: str, owner: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\nid: {owner}\nplatform: chatgpt\n---\n\n# Notatka\n', encoding="utf-8")
    return path


def test_file_owner_id_reads_frontmatter(tmp_path):
    path = _write(tmp_path, "chatgpt/2026-01-01_temat_abcd1234-mac.md", "chatgpt_abcd1234-full")
    assert file_owner_id(path) == "chatgpt_abcd1234-full"


def test_file_owner_id_is_none_for_missing_file(tmp_path):
    assert file_owner_id(tmp_path / "nie-ma.md") is None


def test_no_collision_when_path_is_free(tmp_path):
    rel = "chatgpt/2026-01-01_temat_abcd1234-mac.md"
    assert avoid_collision(rel, "abcd1234-full", root=tmp_path) == rel


def test_same_conversation_keeps_its_path(tmp_path):
    rel = "chatgpt/2026-01-01_temat_abcd1234-mac.md"
    _write(tmp_path, rel, conversation_id("chatgpt", "abcd1234-full"))
    assert avoid_collision(rel, "abcd1234-full", root=tmp_path) == rel


def test_other_conversation_gets_deterministic_suffix(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_DEVICE", "mac")
    rel = "chatgpt/2026-01-01_temat_abcd1234-mac.md"
    _write(tmp_path, rel, conversation_id("chatgpt", "abcd1234-ONE"))

    resolved = avoid_collision(rel, "abcd1234-TWO", root=tmp_path)
    suffix = collision_suffix("abcd1234-TWO")
    assert resolved == f"chatgpt/2026-01-01_temat_abcd1234-{suffix}-mac.md"
    # deterministyczne: ten sam wynik przy każdym uruchomieniu i na każdej maszynie
    assert avoid_collision(rel, "abcd1234-TWO", root=tmp_path) == resolved


def test_no_device_tag_in_name(tmp_path):
    rel = "chatgpt/2026-01-01_temat_abcd1234.md"
    _write(tmp_path, rel, conversation_id("chatgpt", "abcd1234-ONE"))
    resolved = avoid_collision(rel, "abcd1234-TWO", root=tmp_path)
    assert resolved == f"chatgpt/2026-01-01_temat_abcd1234-{collision_suffix('abcd1234-TWO')}.md"


def test_foreign_note_without_frontmatter_is_left_alone(tmp_path):
    rel = "chatgpt/2026-01-01_recznie-pisana_abcd1234-mac.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Moja własna notatka\n", encoding="utf-8")
    assert avoid_collision(rel, "abcd1234-TWO", root=tmp_path) == rel


def test_generated_markdown_avoids_overwriting_another_conversation(tmp_path, monkeypatch):
    """Regresja: ingest drugiej rozmowy o tym samym prefiksie id nie nadpisuje pierwszej."""
    from datetime import datetime, timezone

    from src.models import NormalizedConversation
    from src.normalizers.markdown_generator import MarkdownGenerator

    monkeypatch.setenv("BRAIN_DEVICE", "mac")
    monkeypatch.setattr(
        "src.naming.device_tag", lambda: "mac", raising=False
    )
    monkeypatch.setenv("MARKDOWN_EXPORT_DIR", str(tmp_path))
    from src.config import settings

    monkeypatch.setattr(settings, "MARKDOWN_EXPORT_DIR", tmp_path)

    started = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    first = NormalizedConversation(
        platform="chatgpt",
        external_id="abcd1234-ONE",
        title="Ten sam tytuł",
        started_at=started,
        updated_at=started,
        messages=[],
    )
    second = NormalizedConversation(
        platform="chatgpt",
        external_id="abcd1234-TWO",
        title="Ten sam tytuł",
        started_at=started,
        updated_at=started,
        messages=[],
    )

    _, first_rel = MarkdownGenerator.generate(first)
    (tmp_path / first_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / first_rel).write_text(
        f'---\nid: {conversation_id("chatgpt", "abcd1234-ONE")}\n---\n\n# pierwsza\n', encoding="utf-8"
    )

    _, second_rel = MarkdownGenerator.generate(second)
    assert second_rel != first_rel
    assert collision_suffix("abcd1234-TWO") in second_rel
