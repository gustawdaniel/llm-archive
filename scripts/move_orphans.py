#!/usr/bin/env python3
"""Przenosi osierocone kopie notatek poza drzewo Syncthing (na podstawie find_orphans.py).

Domyślnie dry-run: pokazuje, co by przeniósł. `--apply` wykonuje przenoszenie do
`<backup-dir>/<platforma>/<nazwa>` zachowując strukturę katalogów, żeby dało się
je odtworzyć jednym `cp -a`. Pliki zmodyfikowane w ciągu ostatnich `--skip-newer-min`
minut są pomijane (trwa w nich zapis żywej sesji) — lepiej je dogonić przy
następnym przebiegu niż usuwać spod piszącego procesu.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orphans", required=True, help="JSON z find_orphans.py")
    ap.add_argument("--archive", default=str(Path.home() / "pro/brain/doc/llm-archive"))
    ap.add_argument("--backup-dir", default=str(Path.home() / "backups/llm-archive-orphans-20261109"))
    ap.add_argument("--skip-newer-min", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    archive = Path(args.archive)
    backup = Path(args.backup_dir)
    data = json.load(open(args.orphans))

    cutoff = time.time() - args.skip_newer_min * 60
    moved = skipped_recent = missing = 0
    moved_bytes = 0

    for item in data["orphans"] + data.get("stale_date", []):
        src = archive / item["path"]
        if not src.is_file():
            missing += 1
            continue
        if src.stat().st_mtime > cutoff:
            skipped_recent += 1
            print(f"  pomijam (świeży zapis): {item['path']}")
            continue
        dst = backup / item["path"]
        moved += 1
        moved_bytes += src.stat().st_size
        if args.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    verb = "przeniesiono" if args.apply else "do przeniesienia"
    print(
        f"\n{verb}: {moved} plików ({moved_bytes / 1e6:.1f} MB) → {backup}\n"
        f"pominięte (świeży zapis < {args.skip_newer_min} min): {skipped_recent}, "
        f"brak na dysku: {missing}"
    )
    if not args.apply:
        print("To był dry-run. Powtórz z --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
