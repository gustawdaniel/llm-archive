import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID
import httpx

from ..config import settings
from ..database import Database
from ..naming import avoid_collision, conversation_rel_path
from ..markdown_store import write_if_changed

logger = logging.getLogger("llm-archive.auto_titler")

SYSTEM_PROMPT = """Jesteś precyzyjnym asystentem nadającym profesjonalne, zwięzłe tytuły konwersacjom programistycznym w języku polskim.
Na podstawie podanego kontekstu i wypowiedzi użytkownika z różnych etapów rozmowy zaproponuj JEDEN krótki, rzeczowy tytuł (od 3 do 8 słów).
Zasady:
- Tytuł musi podsumowywać główny temat całej konwersacji. Jeśli w rozmowie poruszono kilka wyraźnych, niezależnych tematów, połącz je w zwięzły sposób (np. "Antigravity JSON, konfiguracja PostgreSQL i WhatsApp").
- Ignoruj wulgaryzmy, zwroty potoczne ("zobacz", "ej", "kurwa") i komendy systemowe ("pnpm ...", "make ...").
- Zwróć WYŁĄCZNIE sam tytuł w jednej linijce, bez cudzysłowów, bez markdownu i bez komentarzy."""


def sample_user_messages(msgs: List[str], max_samples: int = 12, max_chars_per_msg: int = 600) -> List[str]:
    """
    Selects representative user messages spanning beginning, middle, and end of conversation.
    Limits individual message size to prevent overflowing context.
    """
    total = len(msgs)
    if total <= max_samples:
        selected_indices = list(range(total))
    else:
        head = [0, 1, 2]
        tail = [total - 3, total - 2, total - 1]
        middle_count = max_samples - len(head) - len(tail)
        step = (total - 6) / (middle_count + 1)
        mid = [int(3 + step * (i + 1)) for i in range(middle_count)]
        selected_indices = sorted(list(set(head + mid + tail)))

    samples = []
    for idx in selected_indices:
        txt = msgs[idx].strip()
        if len(txt) > max_chars_per_msg:
            txt = txt[:max_chars_per_msg] + "... [przycięto]"
        if txt:
            samples.append(f"[Krok {idx+1}/{total}]: {txt}")
    return samples


def slugify_title(title: str) -> str:
    """Creates a URL/filesystem safe slug from a title using dashes."""
    clean = re.sub(r"[^\w\s-]", "", title.lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")[:60] or "conversation"


class AutoTitler:
    def __init__(self, db: Database, model: Optional[str] = None):
        self.db = db
        self.model = model or settings.TITLER_MODEL
        
        # Build list of candidate Ollama endpoints
        raw_candidates: List[str] = []
        if settings.OLLAMA_BASE_URL:
            raw_candidates.append(settings.OLLAMA_BASE_URL)
        if settings.OLLAMA_FALLBACK_URLS:
            raw_candidates.extend(settings.OLLAMA_FALLBACK_URLS)
        else:
            raw_candidates.extend(settings.get_default_ollama_urls())

        seen = set()
        self.ollama_urls: List[str] = []
        for u in raw_candidates:
            clean_u = u.rstrip("/")
            if clean_u and clean_u not in seen:
                seen.add(clean_u)
                self.ollama_urls.append(clean_u)

    async def _query_ollama(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """Queries Ollama candidate endpoints in order until one succeeds."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            for url in self.ollama_urls:
                endpoint = f"{url}/api/chat"
                try:
                    resp = await client.post(
                        endpoint,
                        json={
                            "model": self.model,
                            "messages": messages,
                            "stream": False,
                            "options": {
                                "temperature": 0.1,
                                "num_predict": 35
                            }
                        }
                    )
                    if resp.status_code == 200:
                        content = resp.json().get("message", {}).get("content", "").strip()
                        if content:
                            return content
                except Exception as e:
                    logger.debug(f"Ollama titler failed at {endpoint}: {e}")
                    continue
        return None

    async def generate_title(self, conv_id: UUID, project_path: Optional[str] = None) -> Optional[str]:
        """Generates a clean, thematic title for conversation using user messages."""
        if not self.db.pool:
            return None

        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT content
                FROM llm_messages
                WHERE conversation_id = $1 AND role = 'user'
                ORDER BY step_index ASC;
            """, conv_id)

        raw_user_msgs = [r["content"] for r in rows if r["content"] and r["content"].strip()]
        if not raw_user_msgs:
            return None

        samples = sample_user_messages(raw_user_msgs, max_samples=12, max_chars_per_msg=600)
        context_block = f"Projekt: {project_path or 'brak'}\nLiczba wypowiedzi usera: {len(raw_user_msgs)}\n\nKluczowe etapy wypowiedzi użytkownika:\n" + "\n---\n".join(samples)

        chat_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Oto kontekst i fragmenty wypowiedzi użytkownika z całej sesji:\n\n{context_block}\n\nPodaj krótki, precyzyjny tytuł (3-7 słów):"}
        ]

        raw_result = await self._query_ollama(chat_messages)
        if not raw_result:
            return None

        # Clean title: take first line, strip markdown formatting and quotes
        first_line = raw_result.split("\n")[0].strip()
        cleaned = re.sub(r"^[*_#\s\"']+|[*_#\s\"']+$", "", first_line).strip()
        if len(cleaned) > 100:
            cleaned = cleaned[:97] + "..."
        return cleaned if len(cleaned) >= 3 else None

    async def apply_new_title(
        self,
        conv_id: UUID,
        platform: str,
        external_id: str,
        started_at: datetime,
        new_title: str
    ):
        """Updates PostgreSQL conversation, document, and local markdown file."""
        if not self.db.pool:
            return

        slug = slugify_title(new_title)
        date_str = started_at.strftime("%Y-%m-%d")
        short_id = external_id[:8]
        new_rel_path = conversation_rel_path(platform, date_str, slug, short_id)
        # ta sama ochrona co w MarkdownGenerator: nie przejmujemy cudzej nazwy
        new_rel_path = avoid_collision(new_rel_path, external_id)

        async with self.db.pool.acquire() as conn:
            # 1. Update llm_conversations
            await conn.execute("""
                UPDATE llm_conversations
                SET original_title = COALESCE(original_title, title),
                    title = $1,
                    title_generated_at = NOW()
                WHERE id = $2;
            """, new_title, conv_id)

            # 2. Check and update llm_documents
            doc_row = await conn.fetchrow("""
                SELECT id, relative_path, content_markdown
                FROM llm_documents
                WHERE conversation_id = $1;
            """, conv_id)

            if doc_row:
                old_rel_path = doc_row["relative_path"]
                content_md = doc_row["content_markdown"] or ""

                # Replace title in frontmatter (handles multiline wrapped YAML strings)
                updated_md = re.sub(
                    r"^title:.*(?:\n\s+.*)*",
                    f"title: \"{new_title}\"",
                    content_md,
                    count=1,
                    flags=re.MULTILINE
                )
                # Replace first H1 title
                updated_md = re.sub(
                    r"^# .*$",
                    f"# {new_title}",
                    updated_md,
                    count=1,
                    flags=re.MULTILINE
                )

                await conn.execute("""
                    UPDATE llm_documents
                    SET relative_path = $1,
                        content_markdown = $2,
                        hash_sha256 = $3,
                        updated_at = NOW()
                    WHERE id = $4;
                """, new_rel_path, updated_md, hashlib.sha256(updated_md.encode("utf-8")).hexdigest(), doc_row["id"])

                # 3. Rename physical markdown file if export directory is present
                export_dir = settings.MARKDOWN_EXPORT_DIR
                if export_dir and export_dir.is_dir():
                    try:
                        old_file = export_dir / old_rel_path
                        new_file = export_dir / new_rel_path
                        if old_file.is_file() and old_file != new_file:
                            old_file.unlink(missing_ok=True)
                        write_if_changed(new_file, updated_md)
                        logger.debug(f"Updated markdown file: {new_rel_path}")
                    except Exception as fe:
                        logger.warning(f"Could not update file on disk ({fe}), DB updated successfully.")

    async def retitle_batch(self, batch_size: int = 5, force: bool = False) -> int:
        """
        Finds conversations that haven't been updated for 2 hours and have no generated title.
        Generates and applies new titles.
        """
        if not self.db.pool:
            return 0

        condition = ""
        if not force:
            condition = "AND c.updated_at < NOW() - INTERVAL '2 hours' AND (c.title_generated_at IS NULL OR c.title_generated_at < c.updated_at)"

        # Universal across platforms on purpose: llm_messages is populated the
        # same way regardless of source, and platforms like chatgpt carry plenty
        # of never-renamed "New chat" conversations that need this just as much
        # as claude_code/antigravity sessions do.
        query = f"""
            SELECT c.id, c.platform, c.external_id, c.title, c.project_path, c.started_at, c.updated_at
            FROM llm_conversations c
            WHERE TRUE
              {condition}
            ORDER BY c.updated_at DESC
            LIMIT $1;
        """

        async with self.db.pool.acquire() as conn:
            candidates = await conn.fetch(query, batch_size)

        if not candidates:
            return 0

        re_titled_count = 0
        for conv in candidates:
            c_id = conv["id"]
            old_title = conv["title"]
            try:
                new_title = await self.generate_title(c_id, conv["project_path"])
                if new_title and new_title != old_title:
                    await self.apply_new_title(
                        conv_id=c_id,
                        platform=conv["platform"],
                        external_id=conv["external_id"],
                        started_at=conv["started_at"],
                        new_title=new_title
                    )
                    logger.info(f"Retitled [{conv['platform']}] {conv['external_id'][:8]}: \"{old_title}\" -> \"{new_title}\"")
                    re_titled_count += 1
                else:
                    # Mark as processed so we don't repeatedly re-query empty/untitleable conversations
                    async with self.db.pool.acquire() as conn:
                        await conn.execute("UPDATE llm_conversations SET title_generated_at = NOW() WHERE id = $1;", c_id)
            except Exception as e:
                logger.warning(f"Error retitling {conv['external_id']}: {e}")

        return re_titled_count

    async def run_loop(self, interval_seconds: int = 600, batch_size: int = 5):
        """Continuous background worker loop."""
        logger.info(f"AutoTitler background worker started. Model: {self.model}, Interval: {interval_seconds}s")
        while True:
            try:
                processed = await self.retitle_batch(batch_size=batch_size)
                if processed == batch_size:
                    # There is a backlog, give a short pause then continue processing next chunk
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info("AutoTitler background worker stopped.")
                break
            except Exception as e:
                logger.error(f"Error in AutoTitler loop: {e}", exc_info=True)
                await asyncio.sleep(60)
