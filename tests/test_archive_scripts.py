"""Testy skryptów porządkowych archiwum (`scripts/find_orphans.py`, `fix_document_paths.py`).

Powstały po incydencie z AutoTitlerem (2026-11): retitle przenosił plik pod nowy
slug, a kolejny ingest tworzył kopię pod starym. Testy pilnują dwóch rzeczy,
które wtedy zawiodły — rozpoznawania „czyj to plik” oraz tego, że sufiks
kolizyjny i blok `Related` nie gubią się po drodze.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import find_orphans  # noqa: E402
import fix_document_paths  # noqa: E402


def test_slugify_keeps_polish_diacritics():
    assert fix_document_paths.slugify("Porządki w ClickUp") == "porządki-w-clickup"
    assert find_orphans.slugify("Porządki w ClickUp") == "porządki-w-clickup"


def test_slugify_strips_punctuation_and_caps_length():
    assert fix_document_paths.slugify("Co? (test) — #1!") == "co-test-1"
    assert len(fix_document_paths.slugify("a" * 200)) == 60
    assert fix_document_paths.slugify("???") == "conversation"


def test_collision_suffix_is_stable_and_short():
    first = fix_document_paths.collision_suffix("aider_2026-09-26_010041")
    second = fix_document_paths.collision_suffix("aider_2026-09-26_010041")
    other = fix_document_paths.collision_suffix("aider_2026-09-26_005943")
    assert first == second
    assert first != other
    assert len(first) == 4
    # ten sam algorytm po obu stronach (sprzątanie i wykrywanie sierot)
    assert first == find_orphans.collision_suffix("aider_2026-09-26_010041")


def test_build_path_variants():
    build = fix_document_paths.build_path
    assert build("chatgpt", "2026-03-20", "temat", "abcd1234", None, None) == "chatgpt/2026-03-20_temat_abcd1234.md"
    assert build("chatgpt", "2026-03-20", "temat", "abcd1234", "apps", None) == "chatgpt/2026-03-20_temat_abcd1234-apps.md"
    assert (
        build("chatgpt", "2026-03-20", "temat", "abcd1234", "apps", "3f9a")
        == "chatgpt/2026-03-20_temat_abcd1234-3f9a-apps.md"
    )


def _index(*conversations):
    """Buduje indeks tak, jak robi to `load_conversations` (bez bazy)."""
    index = {}
    for platform, date_str, external_id, title in conversations:
        key = (platform, date_str, external_id[:8])
        index.setdefault(key, []).append(
            {
                "slug": find_orphans.slugify(title),
                "untitled": not title.strip(),
                "suffix": find_orphans.collision_suffix(external_id),
            }
        )
    return index


def test_file_matching_current_title_is_kept():
    index = _index(("chatgpt", "2026-03-20", "abcd1234ef", "Porządki w ClickUp"))
    assert find_orphans.classify("chatgpt/2026-03-20_porządki-w-clickup_abcd1234.md", index)[0] == "ok"
    assert find_orphans.classify("chatgpt/2026-03-20_porządki-w-clickup_abcd1234-mac.md", index)[0] == "ok"


def test_file_with_stale_slug_is_orphan():
    index = _index(("chatgpt", "2026-03-20", "abcd1234ef", "Porządki w ClickUp"))
    kind, detail = find_orphans.classify("chatgpt/2026-03-20_stary-tytul_abcd1234.md", index)
    assert kind == "orphan"
    assert detail["slugs_in_db"] == ["porządki-w-clickup"]


def test_two_conversations_sharing_id_prefix_are_not_confused():
    """Regresja: osiem znaków id nie jest unikalne — oba slugi są poprawne."""
    index = _index(
        ("chatgpt", "2024-09-21", "66eea7b9-4da8", "Porównanie rehypePlugins z remarkPlugin"),
        ("chatgpt", "2024-09-21", "66eea7b9-6578", "Porównanie rehypePlugins z regex"),
    )
    assert find_orphans.classify("chatgpt/2024-09-21_porównanie-rehypeplugins-z-remarkplugin_66eea7b9-apps.md", index)[0] == "ok"
    assert find_orphans.classify("chatgpt/2024-09-21_porównanie-rehypeplugins-z-regex_66eea7b9.md", index)[0] == "ok"


def test_collision_suffixed_file_is_recognised_only_with_right_suffix():
    external_id = "66eea7b9-6578-800f-bcb0-6d40c6ad94fb"
    index = _index(("chatgpt", "2024-09-21", external_id, "Porównanie rehypePlugins z remarkPlugin"))
    suffix = find_orphans.collision_suffix(external_id)
    good = f"chatgpt/2024-09-21_porównanie-rehypeplugins-z-remarkplugin_66eea7b9-{suffix}-apps.md"
    bad = "chatgpt/2024-09-21_porównanie-rehypeplugins-z-remarkplugin_66eea7b9-dead-apps.md"
    assert find_orphans.classify(good, index)[0] == "ok"
    assert find_orphans.classify(bad, index)[0] == "orphan"


def test_untitled_and_unparseable_files():
    index = _index(("chatgpt", "2026-03-20", "abcd1234ef", "  "))
    assert find_orphans.classify("chatgpt/2026-03-20_cokolwiek_abcd1234.md", index)[0] == "untitled"
    assert find_orphans.classify("_topics/clickup.md", index)[0] == "unknown"


def test_detects_file_whose_date_no_longer_matches():
    index = _index(("claude_code", "2026-10-14", "e2c24a8a-aa", "Długi tytuł"))
    kind, detail = find_orphans.classify("claude_code/2026-10-15_długi-tytuł_e2c24a8a-mac.md", index)
    assert kind == "stale_date"
    assert detail["canonical"] == ["claude_code/2026-10-14_długi-tytuł_e2c24a8a"]


def test_retitle_markdown_updates_frontmatter_and_h1_only():
    source = '---\ntitle: "Stary"\nplatform: chatgpt\n---\n\n# Stary\n\nTreść\n\n# Nie ruszaj\n'
    out = fix_document_paths.retitle_markdown(source, "Nowy tytuł")
    assert 'title: "Nowy tytuł"' in out
    assert out.count("# Nowy tytuł") == 1
    assert "# Nie ruszaj" in out


def test_related_block_survives_rename():
    block = "<!-- BEGIN RELATED (auto-generated) -->\n## Related\n- [[a]]\n<!-- END RELATED -->"
    old = f"---\ntitle: Stary\n---\n\n# Stary\n\nTreść\n\n{block}\n"
    new = '---\ntitle: "Nowy"\n---\n\n# Nowy\n\nTreść\n'
    merged = fix_document_paths.with_related(new, old)
    assert block in merged
    assert merged.count("<!-- BEGIN RELATED") == 1
    # gdy nowa treść już ma blok, nie duplikujemy
    assert fix_document_paths.with_related(merged, old).count("<!-- BEGIN RELATED") == 1


@pytest.mark.parametrize("body", ["", "---\ntitle: x\n---\n# x\n"])
def test_with_related_handles_files_without_block(body):
    assert fix_document_paths.with_related("nowa treść\n", body) == "nowa treść\n"
