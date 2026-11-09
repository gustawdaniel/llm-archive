import io
import logging
import os
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("importer.extractor")

ARCHIVE_EXTENSIONS = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar")


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:3.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def find_archive_files(base_dir: Path, recursive: bool = True) -> List[Path]:
    """Find all archive files (.zip, .tar.gz, etc.) in base_dir."""
    if not base_dir.is_dir():
        return []
    candidates = base_dir.rglob("*") if recursive else base_dir.glob("*")
    archives = [
        p for p in candidates
        if p.is_file() and any(p.name.lower().endswith(ext) for ext in ARCHIVE_EXTENSIONS)
    ]
    return sorted(archives, key=lambda p: str(p).lower())


def is_safe_path(target_dir: Path, path: Path) -> bool:
    """Ensure extracted file path does not escape destination directory (Path traversal mitigation)."""
    try:
        resolved_target = target_dir.resolve()
        resolved_path = path.resolve()
        return str(resolved_path).startswith(str(resolved_target))
    except Exception:
        return False


def extract_archive(
    archive_path: Path,
    dest_dir: Path,
    overwrite: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Extract a zip or tar archive safely into dest_dir."""
    archive_path = archive_path.resolve()
    dest_dir = dest_dir.resolve()

    if zipfile.is_zipfile(archive_path):
        return _extract_zip(archive_path, dest_dir, overwrite, verbose, dry_run)
    elif tarfile.is_tarfile(archive_path):
        return _extract_tar(archive_path, dest_dir, overwrite, verbose, dry_run)
    else:
        raise ValueError(f"Unsupported archive format: {archive_path.name}")


def _extract_zip(
    archive_path: Path,
    dest_dir: Path,
    overwrite: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> Tuple[int, int]:
    if dry_run:
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = zf.infolist()
            total_bytes = sum(m.file_size for m in members if not m.is_dir())
            total_files = sum(1 for m in members if not m.is_dir())
            return total_files, total_bytes

    dest_dir.mkdir(parents=True, exist_ok=True)
    files_extracted = 0
    bytes_extracted = 0

    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            target_path = dest_dir / member.filename
            if not is_safe_path(dest_dir, target_path):
                logger.warning(f"Skipping unsafe path in archive {archive_path.name}: {member.filename}")
                continue

            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() and not overwrite:
                continue

            with zf.open(member) as source, open(target_path, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)

            files_extracted += 1
            bytes_extracted += member.file_size

    return files_extracted, bytes_extracted


def _extract_tar(
    archive_path: Path,
    dest_dir: Path,
    overwrite: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> Tuple[int, int]:
    if dry_run:
        with tarfile.open(archive_path, "r:*") as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            total_bytes = sum(m.size for m in members)
            return len(members), total_bytes

    dest_dir.mkdir(parents=True, exist_ok=True)
    files_extracted = 0
    bytes_extracted = 0

    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            target_path = dest_dir / member.name
            if not is_safe_path(dest_dir, target_path):
                logger.warning(f"Skipping unsafe path in archive {archive_path.name}: {member.name}")
                continue

            if member.isdir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() and not overwrite:
                continue

            if member.isfile():
                f = tf.extractfile(member)
                if f:
                    with open(target_path, "wb") as target:
                        while chunk := f.read(1024 * 1024):
                            target.write(chunk)
                    files_extracted += 1
                    bytes_extracted += member.size

    return files_extracted, bytes_extracted


class ArchiveExtractor:
    """Helper to discover and extract archives inside takeout directories."""

    @staticmethod
    def extract_directory_archives(
        base_dir: Path,
        subfolder: bool = False,
        keep: bool = True,
        nested: bool = True,
        dry_run: bool = False,
    ) -> dict:
        base_dir = base_dir.resolve()
        processed = set()
        total_archives = 0
        total_files = 0
        total_bytes = 0

        while True:
            archive_files = [p for p in find_archive_files(base_dir) if p not in processed]
            if not archive_files:
                break

            for archive_path in archive_files:
                processed.add(archive_path)
                total_archives += 1
                dest_dir = (archive_path.parent / archive_path.stem) if subfolder else archive_path.parent

                try:
                    f_cnt, b_cnt = extract_archive(
                        archive_path=archive_path,
                        dest_dir=dest_dir,
                        dry_run=dry_run,
                    )
                    total_files += f_cnt
                    total_bytes += b_cnt

                    if not keep and not dry_run:
                        archive_path.unlink()
                except Exception as e:
                    logger.error(f"Error extracting archive {archive_path}: {e}")

            if not nested:
                break

        return {
            "archives_processed": total_archives,
            "files_extracted": total_files,
            "total_bytes": total_bytes,
        }
