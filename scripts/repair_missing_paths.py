#!/usr/bin/env python3
"""Naprawia wpisy `llm_documents.relative_path`, które wskazują na nieistniejący plik.

Po porządkach (usuwanie kopii po AutoTitlerze) część wpisów w bazie wskazuje na
pliki, których już nie ma — bo leżały pod nieaktualnym slugiem. Markdown jest
nadal w bazie (`content_markdown`), więc odtwarzamy go pod ścieżką kanoniczną:
slug z `llm_conversations.title`, tag tego urządzenia (naming.device_tag).

Domyślnie dry-run; `--apply` zapisuje plik i aktualizuje bazę.
Uruchamiać w środowisku API (kontener apps, DATABASE_URL z /etc/brain/llm-archive.env).
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.markdown_store import file_matches, write_if_changed  # noqa: E402
from src.naming import conversation_rel_path  # noqa: E402


def slugify(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", (title or "").lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")[:60] or "conversation"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = wszystkie")
    args = ap.parse_args()

    root = Path(os.getenv("MARKDOWN_EXPORT_DIR", "/var/lib/brain/doc/llm-archive"))
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("BŁĄD: brak DATABASE_URL", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("""
            SELECT d.id AS doc_id, d.relative_path, d.content_markdown,
                   c.platform, c.external_id, c.started_at, c.title
            FROM llm_documents d
            JOIN llm_conversations c ON c.id = d.conversation_id
            ORDER BY c.started_at;
        """)

        broken = []
        for r in rows:
            rel = r["relative_path"]
            if not rel or not r["content_markdown"]:
                continue
            if not (root / rel).is_file():
                broken.append(r)

        if args.limit:
            broken = broken[: args.limit]

        print(f"wpisów w bazie: {len(rows)}, wskazują na brakujący plik: {len(broken)}")

        fixed = 0
        for r in broken:
            new_rel = conversation_rel_path(
                r["platform"],
                r["started_at"].strftime("%Y-%m-%d"),
                slugify(r["title"]),
                r["external_id"][:8],
            )
            target = root / new_rel
            print(f"  {r['relative_path']}  →  {new_rel}")
            if not args.apply:
                continue
            write_if_changed(target, r["content_markdown"])
            await conn.execute(
                "UPDATE llm_documents SET relative_path = $1, updated_at = NOW() WHERE id = $2;",
                new_rel,
                r["doc_id"],
            )
            fixed += 1

        if args.apply:
            print(f"naprawiono: {fixed}")
        else:
            print("To był dry-run. Powtórz z --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
