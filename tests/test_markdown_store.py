"""Testy zapisu markdownu: identyczna treść nie może dotykać pliku na dysku."""

import os

from src.markdown_store import file_matches, remove_if_unchanged, write_if_changed


def test_writes_when_file_missing(tmp_path):
    target = tmp_path / "antigravity" / "note.md"
    assert write_if_changed(target, "# Notatka\n") is True
    assert target.read_text(encoding="utf-8") == "# Notatka\n"


def test_skips_identical_content_and_keeps_mtime(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("# Notatka\n", encoding="utf-8")
    before = target.stat()

    assert write_if_changed(target, "# Notatka\n") is False

    after = target.stat()
    assert after.st_mtime == before.st_mtime
    assert after.st_ino == before.st_ino


def test_rewrites_when_content_differs(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("# Stara\n", encoding="utf-8")

    assert write_if_changed(target, "# Nowa\n") is True
    assert target.read_text(encoding="utf-8") == "# Nowa\n"


def test_no_leftover_tmp_file(tmp_path):
    target = tmp_path / "note.md"
    write_if_changed(target, "# A\n")
    write_if_changed(target, "# B\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["note.md"]


def test_file_matches(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("treść", encoding="utf-8")
    assert file_matches(target, "treść") is True
    assert file_matches(target, "inna") is False
    assert file_matches(tmp_path / "brak.md", "treść") is False


def test_remove_if_unchanged_deletes_own_file(tmp_path):
    target = tmp_path / "old.md"
    write_if_changed(target, "treść")
    import hashlib

    digest = hashlib.sha256("treść".encode("utf-8")).hexdigest()
    assert remove_if_unchanged(target, digest) is True
    assert not target.exists()


def test_remove_if_unchanged_spares_edited_file(tmp_path):
    """Ręczna edycja w Obsidianie nie może zostać skasowana przez porządki."""
    target = tmp_path / "old.md"
    target.write_text("treść zmieniona ręcznie", encoding="utf-8")
    assert remove_if_unchanged(target, "0" * 64) is False
    assert target.exists()
