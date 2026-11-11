"""Zapis plików markdown archiwum — nigdy nie nadpisuj identycznej treści.

`doc/llm-archive` leży w drzewie synchronizowanym przez Syncthing, a każdy
daemon (Mac, rog, kontener `apps`) renderuje markdown od nowa przy każdym
ingestcie. Do 2026-11 zapis był bezwarunkowy (`Path.write_text`), więc plik
kilkumeгабайтовy był przepisywany co ~2 minuty mimo identycznej treści: zmiana
mtime i rozmiaru wystarczała, żeby Syncthing przesyłał cały plik na wszystkie
maszyny, a Obsidian przeładowywał notatkę.

Ten moduł zapisuje wyłącznie wtedy, gdy treść faktycznie się różni, i robi to
atomowo (zapis do pliku tymczasowego + `os.replace`), żeby Syncthing nigdy nie
zobaczył pliku zapisanego w połowie.
"""

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger("llm-archive.markdown-store")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str | None:
    """Hash pliku na dysku albo `None`, gdy plik nie istnieje / nie da się go przeczytać."""
    try:
        return _sha256(path.read_bytes())
    except OSError:
        return None


def file_matches(path: Path, content: str) -> bool:
    """Czy plik istnieje i ma dokładnie taką treść."""
    return file_sha256(path) == _sha256(content.encode("utf-8"))


def write_if_changed(path: Path, content: str) -> bool:
    """Zapisuje `content` do `path` tylko gdy różni się od tego, co już leży na dysku.

    Zwraca `True`, gdy plik został (atomowo) zapisany, `False` gdy treść była
    identyczna — wtedy mtime zostaje nietknięty i Syncthing nie ma czego słać.
    """
    if file_matches(path, content):
        logger.debug(f"Markdown unchanged, skipping write: {path}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
    logger.info(f"Wrote markdown: {path}")
    return True


def remove_if_unchanged(path: Path, expected_sha256: str | None) -> bool:
    """Usuwa osierocony plik, ale tylko jeśli jego treść to dokładnie ta, którą sami zapisaliśmy.

    Zabezpieczenie przed skasowaniem pliku, który ktoś (np. Obsidian, ręczna
    edycja) zdążył zmienić: wtedy zostawiamy go i logujemy ostrzeżenie.
    """
    if not path.is_file():
        return False
    actual = file_sha256(path)
    if expected_sha256 and actual == expected_sha256:
        path.unlink()
        logger.info(f"Removed superseded markdown: {path}")
        return True
    logger.warning(
        f"Not removing {path}: content differs from what the server wrote "
        f"(expected {str(expected_sha256)[:12]}, found {str(actual)[:12]}) — leaving it for manual review"
    )
    return False
