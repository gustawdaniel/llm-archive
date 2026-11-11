"""Nazwy plików markdown w archiwum konwersacji (`doc/llm-archive`).

Katalog leży w drzewie synchronizowanym przez Syncthing i pisze do niego każde
urządzenie, na którym działa daemon archiwum (Mac, rog, kontener `apps`). Do
2026-11 nazwa pliku to było `<data>_<slug>_<short-id>.md`, więc dwie maszyny
mogły wygenerować ten sam plik o różnej treści — stąd setki plików
`*.sync-conflict-*`. Krótkie id dostaje teraz tag urządzenia, więc każda maszyna
pisze własne pliki i Syncthing nie ma czego rozstrzygać.

Drugi problem tego schematu: `external_id[:8]` **nie jest unikalne** — aider ma
syntetyczne id zaczynające się zawsze od `aider_20`, a identyfikatory ChatGPT
potrafią dzielić pierwsze 8 znaków. Dwie różne rozmowy dostawały wtedy tę samą
nazwę i jedna nadpisywała notatkę drugiej. `avoid_collision()` sprawdza, do kogo
należy istniejący plik (po `id:` z frontmattera) i w razie konfliktu dokłada
deterministyczny sufiks z hasha pełnego id — ten sam na każdej maszynie.

Tag bierzemy z `BRAIN_DEVICE` (jeśli ustawione), inaczej z pierwszego członu
hostname. Wystarczy, że będzie różny między maszynami — nie musi być ładny.
"""

import hashlib
import os
import platform
import re
from pathlib import Path

ENV_VAR = "BRAIN_DEVICE"

FRONTMATTER_ID_RE = re.compile(r"^id:\s*(?P<id>.+)$", re.MULTILINE)


def device_tag() -> str:
    """Stabilny, bezpieczny dla systemu plików tag tej maszyny."""
    raw = os.environ.get(ENV_VAR) or platform.node() or "unknown"
    tag = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")[:12]
    return tag or "unknown"


def conversation_rel_path(platform_name: str, date_str: str, slug: str, short_id: str) -> str:
    """Ścieżka względna w `doc/llm-archive`, unikalna per urządzenie."""
    return f"{platform_name}/{date_str}_{slug}_{short_id}-{device_tag()}.md"


def conversation_id(platform_name: str, external_id: str) -> str:
    """Identyfikator rozmowy w frontmatterze (`id:`) — po nim poznajemy właściciela pliku."""
    return f"{platform_name}_{external_id}"


def collision_suffix(external_id: str) -> str:
    """4 znaki hasha `external_id` — deterministyczne, więc zgodne między maszynami.

    Hashujemy sam `external_id` (platforma jest już w ścieżce), żeby sufiks był
    identyczny w kodzie piszącym pliki i w skryptach porządkowych.
    """
    return hashlib.sha1(external_id.encode("utf-8")).hexdigest()[:4]


def file_owner_id(path: Path) -> str | None:
    """`id:` z frontmattera pliku albo `None`, gdy plik nie istnieje / nie ma frontmattera."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(1024)
    except OSError:
        return None
    match = FRONTMATTER_ID_RE.search(head)
    return match.group("id").strip().strip("\"'") if match else None


def avoid_collision(rel_path: str, external_id: str, root: Path | None = None) -> str:
    """Zwraca `rel_path`, a jeśli plik pod tą nazwą należy do INNEJ rozmowy — wariant z sufiksem.

    Bez tego dwie rozmowy o wspólnym prefiksie `external_id[:8]` pisały do jednego
    pliku i jedna nadpisywała drugą (notatka „znikała", choć zostawała w bazie).
    Gdy plik nie istnieje albo nie da się ustalić właściciela (np. ręcznie dodana
    notatka), zachowujemy dotychczasową nazwę — nie chcemy masowo przemianowywać
    archiwum.
    """
    if root is None:
        from .config import settings  # import lokalny: unikamy cyklu przy starcie modułu

        root = settings.MARKDOWN_EXPORT_DIR
    if not root:
        return rel_path

    platform_name = rel_path.split("/", 1)[0]
    full_id = conversation_id(platform_name, external_id)
    target = Path(root) / rel_path
    owner = file_owner_id(target)
    if owner is None or owner == full_id:
        return rel_path

    suffix = collision_suffix(external_id)
    ending = f"-{device_tag()}.md"
    if rel_path.endswith(ending):
        return f"{rel_path[: -len(ending)]}-{suffix}{ending}"
    return f"{rel_path[:-3]}-{suffix}.md" if rel_path.endswith(".md") else f"{rel_path}-{suffix}"
