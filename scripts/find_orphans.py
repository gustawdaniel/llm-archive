#!/usr/bin/env python3
"""Znajduje notatki w `doc/llm-archive`, które nie odpowiadają żadnej rozmowie w bazie.

Tło: do 2026-11 AutoTitler zmieniał tytuł rozmowy i przenosił plik pod nowy slug,
ale kolejny ingest renderował markdown z surowego tytułu transkryptu i tworzył
PLIK POD STARĄ NAZWĄ. W efekcie jedna rozmowa miała na dysku kilka kopii pod
różnymi slugami (np. `…_14824_…`, `…_dokumentacja-i-wdrożenie_…`), każda z inną
(starszą) treścią.

Reguła dopasowania jest **per rozmowa**, nie per rodzina: plik jest nasz, gdy
istnieje rozmowa o tej samej platformie, dacie `started_at` i pierwszym
8-znakowym fragmencie `external_id` oraz slug równy `slugify(title)`. Dlatego
dwie różne rozmowy o wspólnym prefiksie id (np. `aider_2026-09-26_…`, albo id
ChatGPT dzielące pierwsze 8 znaków) nie są już mylone — a plik z sufiksem
kolizyjnym (`…_abcd1234-3f9a-apps.md`) też jest rozpoznawany.

Kategorie wyniku:
  • `orphans`   — plik pasuje do rozmowy po (platforma, data, prefiks id), ale
                  slug jest nieaktualny → pozostałość po AutoTitlerze, do sprzątnięcia.
  • `unknown`   — nie pasuje do żadnej rozmowy (np. `_topics/`, fixture'y testowe).
                  Tego NIE ruszamy: to nie nasze pliki.
  • `families_without_canonical_title` — rozmowa bez tytułu, więc nie da się
                  rozstrzygnąć, która nazwa jest aktualna.

Skrypt NIC nie rusza: wypisuje JSON. Przenoszenie robi `move_orphans.py`.

Użycie (w kontenerze, tam gdzie jest DATABASE_URL):
    python scripts/find_orphans.py                    # JSON na stdout
    python scripts/find_orphans.py --pretty           # + podsumowanie na stderr
"""

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

ARCHIVE_SUFFIX_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<slug>.*)_(?P<sid>[^_]+?)(?:-(?P<suffix>[0-9a-f]{4}))?(?:-(?P<dev>[a-z0-9\-]+))?\.md$"
)


def slugify(title: str) -> str:
    """Ten sam slug, którego używa AutoTitler (`auto_titler.slugify_title`)."""
    clean = re.sub(r"[^\w\s-]", "", (title or "").lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")[:60] or "conversation"


def collision_suffix(external_id: str) -> str:
    """Ten sam sufiks, którym `fix_document_paths.py` rozbija kolizje 8-znakowych prefiksów."""
    import hashlib

    return hashlib.sha1(external_id.encode("utf-8")).hexdigest()[:4]


async def load_conversations(dsn: str) -> dict[tuple[str, str, str], list[dict]]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT platform, external_id, started_at, title FROM llm_conversations"
        )
    finally:
        await conn.close()

    index: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["platform"], row["started_at"].strftime("%Y-%m-%d"), row["external_id"][:8])
        index[key].append(
            {
                "slug": slugify(row["title"]),
                "untitled": not (row["title"] or "").strip(),
                "suffix": collision_suffix(row["external_id"]),
            }
        )
    return index


def classify(rel_path: str, index: dict[tuple[str, str, str], list[dict]]) -> tuple[str, dict | None]:
    platform = rel_path.split("/", 1)[0]
    match = ARCHIVE_SUFFIX_RE.match(rel_path.split("/", 1)[-1])
    if not match:
        return "unknown", None

    key = (platform, match.group("date"), match.group("sid"))
    candidates = index.get(key)
    if not candidates:
        # spróbuj dopasować po samym prefiksie id (data mogła się zmienić przy retitle)
        for other_key, other in index.items():
            if other_key[0] == platform and other_key[2] == match.group("sid"):
                return "stale_date", {
                    "path": rel_path,
                    "why": "data w nazwie ≠ data startu rozmowy",
                    "canonical": [f"{platform}/{other_key[1]}_{c['slug']}_{match.group('sid')}" for c in other],
                }
        return "unknown", None

    slug = match.group("slug")
    suffix = match.group("suffix")
    for cand in candidates:
        if cand["untitled"]:
            return "untitled", {"path": rel_path, "why": "rozmowa bez tytułu — nie da się ustalić slugu"}
        if cand["slug"] != slug:
            continue
        if suffix and suffix != cand["suffix"]:
            continue
        return "ok", None
    return "orphan", {"path": rel_path, "slugs_in_db": sorted({c["slug"] for c in candidates})}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", default=os.getenv("MARKDOWN_EXPORT_DIR", "/var/lib/brain/doc/llm-archive"))
    parser.add_argument("--pretty", action="store_true", help="podsumowanie na stderr")
    parser.add_argument("--all", action="store_true", help="pokaż też pliki nierozpoznane (unknown)")
    args = parser.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("BŁĄD: brak DATABASE_URL", file=sys.stderr)
        return 2

    root = Path(args.archive_dir)
    index = await load_conversations(dsn)

    buckets: dict[str, list] = defaultdict(list)
    sizes = {"orphan": 0, "stale_date": 0}
    disk = [str(p.relative_to(root)) for p in sorted(root.rglob("*.md"))]
    unknown = 0
    disk_set = set(disk)
    for rel in disk:
        kind, detail = classify(rel, index)
        if kind == "stale_date":
            # przenosimy tylko wtedy, gdy kanoniczna wersja naprawdę istnieje —
            # inaczej zostawiamy plik, bo mógłby być jedyną kopią notatki
            prefix = detail.get("canonical") or []
            if not any(
                any(d.startswith(cand + "-") or d == cand + ".md" for d in disk_set) for cand in prefix
            ):
                kind = "unknown"
        if kind in ("orphan", "stale_date"):
            sizes[kind] += (root / rel).stat().st_size
            buckets[kind].append(detail)
        elif kind == "unknown":
            unknown += 1
            if args.all:
                buckets["unknown"].append({"path": rel})
        elif args.all:
            buckets[kind].append({"path": rel})

    report = {
        "archive_dir": str(root),
        "files": sum(1 for _ in root.rglob("*.md")),
        "conversations": sum(len(v) for v in index.values()),
        "orphans": buckets["orphan"],
        "stale_date": buckets["stale_date"],
        "untitled": buckets["untitled"],
        "unknown_count": unknown,
        "unknown_sample": buckets["unknown"][:20],
    }
    print(json.dumps(report, ensure_ascii=False, indent=1 if args.pretty else None))

    if args.pretty:
        mb = lambda n: f"{n / 1024 / 1024:.1f} MB"  # noqa: E731
        print(
            f"{len(buckets['orphan'])} osieroconych ({mb(sizes['orphan'])}), "
            f"{len(buckets['stale_date'])} ze zmienioną datą ({mb(sizes['stale_date'])}), "
            f"{len(buckets['untitled'])} bez tytułu, {unknown} nierozpoznanych "
            f"z {report['files']} plików",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
