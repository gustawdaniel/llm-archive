#!/usr/bin/env python3
"""Porządkuje ścieżki w `llm_documents` po AutoTitlerze — bez ruszania zdrowych wpisów.

Trzy klasy błędów, które zostawił po sobie AutoTitler (oraz stary `naming.py`):

1. **Wpis wskazuje na nieistniejący plik.** AutoTitler zmienił tytuł i przeniósł
   notatkę pod nowy slug, a plik pod starym zniknął (albo został przeniesiony
   przy sprzątaniu osieroconych kopii). Markdown jest w bazie
   (`content_markdown`), więc odtwarzamy go pod ścieżką kanoniczną.
2. **Dwie rozmowy dzielą jedną ścieżkę.** `conversation_rel_path()` bierze
   `external_id[:8]`, a to nie jest unikalne (`aider_2026-09-26_…` zawsze daje
   `aider_20`, a id ChatGPT potrafią dzielić pierwsze 8 znaków). Druga rozmowa
   nadpisywała notatkę pierwszej. Przegrany dostaje sufiks z hasha pełnego
   `external_id` — deterministyczny, więc każda maszyna wyliczy ten sam.
3. **Slug w nazwie pliku nie zgadza się z tytułem w bazie.** Tytuł zmienił się
   bez przemianowania (np. gdy wygenerowany tytuł był identyczny z tekstem
   transkryptu) — plik nosi nieaktualną nazwę. Przenosimy plik i poprawiamy
   `title:`/H1 w treści.

Czego skrypt NIE robi: nie zmienia nazw wpisów, które są spójne — więc nie
wywołuje masowego przemianowania archiwum i nie budzi Syncthinga.

Tag urządzenia (`-apps`, `-mac`, `-rog`) jest zachowywany z dotychczasowej
ścieżki: mówi, która maszyna napisała notatkę, a nie kim jesteśmy teraz.

Domyślnie dry-run. Uruchamiać w kontenerze `apps`, jako użytkownik `brain`
(inaczej pliki w /var/lib/brain/doc wyjdą root-owned):

    set -a && . /etc/brain/llm-archive.env && set +a
    .venv/bin/python scripts/fix_document_paths.py          # podgląd
    .venv/bin/python scripts/fix_document_paths.py --apply
"""

import argparse
import asyncio
import hashlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.markdown_store import file_matches, remove_if_unchanged, write_if_changed  # noqa: E402
from src.naming import collision_suffix  # noqa: E402

DEV_RE = re.compile(r"-(?P<dev>[a-z0-9][a-z0-9\-]*)\.md$")


def slugify(title: str) -> str:
    """Ten sam slug, którego używa AutoTitler i `MarkdownGenerator`."""
    clean = re.sub(r"[^\w\s-]", "", (title or "").lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")[:60] or "conversation"


def device_tag_of(rel_path: str) -> str | None:
    match = DEV_RE.search(rel_path or "")
    return match.group("dev") if match else None


def build_path(platform: str, date_str: str, slug: str, short_id: str, dev: str | None, suffix: str | None) -> str:
    tail = f"{short_id}-{suffix}" if suffix else short_id
    if dev:
        tail = f"{tail}-{dev}"
    return f"{platform}/{date_str}_{slug}_{tail}.md"


def retitle_markdown(markdown: str, title: str) -> str:
    """Podmienia `title:` w frontmatterze i pierwszy H1 (jak `apply_new_title`)."""
    updated = re.sub(r"^title:.*(?:\n\s+.*)*", f'title: "{title}"', markdown, count=1, flags=re.MULTILINE)
    return re.sub(r"^# .*$", f"# {title}", updated, count=1, flags=re.MULTILINE)


def related_block(markdown: str) -> str | None:
    """Wyciąga blok `<!-- BEGIN RELATED … -->…<!-- END RELATED -->` z pliku na dysku.

    Blok powstaje w `brain-llm topics export-links` i żyje WYŁĄCZNIE na dysku —
    nie ma go w `llm_documents.content_markdown`. Zapis z bazy (przemianowanie,
    odtworzenie brakującego pliku) musi go przenieść, inaczej graf Obsidiana
    traci krawędzie do czasu ponownego `export-links`.
    """
    begin = markdown.find("<!-- BEGIN RELATED")
    if begin < 0:
        return None
    end = markdown.find("<!-- END RELATED -->", begin)
    if end < 0:
        return None
    return markdown[begin : end + len("<!-- END RELATED -->")]


def with_related(markdown: str, old_markdown: str | None) -> str:
    """Dokłada blok `Related` ze starego pliku, jeśli nowa treść go nie ma."""
    if "<!-- BEGIN RELATED" in markdown or not old_markdown:
        return markdown
    block = related_block(old_markdown)
    if not block:
        return markdown
    return markdown.rstrip() + "\n\n" + block + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="zapisz zmiany (domyślnie dry-run)")
    args = parser.parse_args()

    dsn = os.getenv("DATABASE_URL")
    root = Path(os.getenv("MARKDOWN_EXPORT_DIR", "/var/lib/brain/doc/llm-archive"))
    if not dsn:
        print("BŁĄD: brak DATABASE_URL", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT d.id AS doc_id, d.relative_path, d.content_markdown, d.hash_sha256,
                   c.platform, c.external_id, c.started_at, c.title
            FROM llm_documents d
            JOIN llm_conversations c ON c.id = d.conversation_id
            ORDER BY c.started_at, d.updated_at;
            """
        )

        # --- krok 1: ścieżka kanoniczna dla każdego wpisu (tag urządzenia z nazwy) ---
        planned = []
        by_target: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            dev = device_tag_of(row["relative_path"] or "")
            item = {
                "row": row,
                "old_rel": row["relative_path"] or "",
                "dev": dev,
                "target": build_path(
                    row["platform"],
                    row["started_at"].strftime("%Y-%m-%d"),
                    slugify(row["title"]),
                    row["external_id"][:8],
                    dev,
                    None,
                ),
                "collision": False,
            }
            planned.append(item)
            by_target[item["target"]].append(item)

        # --- krok 2: rozbij kolizje — przegrany dostaje sufiks z hasha pełnego id ---
        for group in by_target.values():
            if len(group) < 2:
                continue

            def keeps(item: dict) -> tuple[int, int]:
                row = item["row"]
                on_disk = file_matches(root / item["old_rel"], row["content_markdown"] or "")
                return (1 if on_disk else 0, row["doc_id"].int)

            winner = max(group, key=keeps)
            for item in group:
                if item is winner:
                    continue
                row = item["row"]
                item["collision"] = True
                item["target"] = build_path(
                    row["platform"],
                    row["started_at"].strftime("%Y-%m-%d"),
                    slugify(row["title"]),
                    row["external_id"][:8],
                    item["dev"],
                    collision_suffix(row["external_id"]),
                )

        # --- krok 3: wykonaj tylko to, co naprawdę jest zepsute ---
        owners = defaultdict(int)
        for item in planned:
            owners[item["target"]] += 1

        to_fix = []
        for item in planned:
            old_rel = item["old_rel"]
            exists = bool(old_rel) and (root / old_rel).is_file()
            if exists and old_rel == item["target"]:
                continue
            to_fix.append(item)

        changed = 0
        for item in to_fix:
            row, old_rel, target = item["row"], item["old_rel"], item["target"]
            content = row["content_markdown"] or ""
            target_path = root / target
            exists = bool(old_rel) and (root / old_rel).is_file()

            if owners[target] > 1:
                print(f"  POMIJAM {old_rel} — {owners[target]} wpisów celuje w {target}", file=sys.stderr)
                continue
            # nie nadpisujemy cudzej notatki, jeśli plik pod celem ma inną treść
            if target_path.is_file() and not file_matches(target_path, content) and old_rel != target:
                print(f"  POMIJAM {old_rel} — {target} istnieje z inną treścią", file=sys.stderr)
                continue

            reason = "brak pliku" if not exists else ("kolizja" if item["collision"] else "nieaktualna nazwa")
            # przy samej zmianie nazwy dopasuj też tytuł w treści
            if exists and old_rel != target and slugify(row["title"]) not in Path(old_rel).name:
                content = retitle_markdown(content, row["title"])

            # blok `Related` żyje tylko na dysku — przenosimy go, ale do bazy
            # zapisujemy treść bez niego (inaczej hash w bazie nie zgadzałby się
            # z tym, co renderuje API, i każdy ingest kasowałby blok)
            disk_content = content
            if exists and old_rel != target:
                old_text = (root / old_rel).read_text(encoding="utf-8", errors="replace")
                disk_content = with_related(content, old_text)

            print(f"  {old_rel or '(brak)'}\n    → {target}   [{reason}]")
            if not args.apply:
                continue

            write_if_changed(target_path, disk_content)
            await conn.execute(
                "UPDATE llm_documents SET relative_path = $1, content_markdown = $2, "
                "hash_sha256 = $3, updated_at = NOW() WHERE id = $4;",
                target,
                content,
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
                row["doc_id"],
            )
            # stary plik usuwamy tylko gdy żaden inny wpis go nie używa i gdy jego
            # treść nadal odpowiada temu wpisowi (czyli nikt go nie edytował ręcznie)
            if exists and old_rel != target and owners.get(old_rel, 0) == 0:
                remove_if_unchanged(root / old_rel, row["hash_sha256"])
            changed += 1

        print(f"wpisów w bazie: {len(rows)}, do naprawy: {len(to_fix)}")
        print(f"naprawiono: {changed}" if args.apply else "To był dry-run. Powtórz z --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
