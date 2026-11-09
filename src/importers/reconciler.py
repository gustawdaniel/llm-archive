import asyncio
import hashlib
import logging
from typing import Callable, Dict, List, Optional
from pathlib import Path

from ..config import settings
from ..database import Database
from ..embedder import Embedder
from ..chunker import SemanticChunker
from ..models import NormalizedConversation
from ..normalizers import MarkdownGenerator

logger = logging.getLogger("importer.reconciler")


class ArchiveReconciler:
    def __init__(self, db: Optional[Database] = None, embedder: Optional[Embedder] = None):
        self.db = db
        self.embedder = embedder or Embedder()
        self.chunker = SemanticChunker()
        self.known_hashes: Dict[str, Dict[str, str]] = {}

    async def get_existing_hashes(self, platform: str) -> Dict[str, str]:
        """Fetch external_id -> hash_sha256 for existing conversations in PostgreSQL."""
        if platform in self.known_hashes:
            return self.known_hashes[platform]

        hashes: Dict[str, str] = {}
        if self.db and self.db.pool:
            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT cv.external_id, doc.hash_sha256
                    FROM llm_conversations cv
                    JOIN llm_documents doc ON cv.id = doc.conversation_id
                    WHERE cv.platform = $1;
                    """,
                    platform
                )
                hashes = {r["external_id"]: r["hash_sha256"] for r in rows}
        self.known_hashes[platform] = hashes
        return self.known_hashes[platform]

    async def import_conversations(
        self,
        conversations: List[NormalizedConversation],
        force_reindex: bool = False,
        concurrency: int = 4,
        on_progress: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, int]:
        total = len(conversations)
        stats = {"total": total, "imported": 0, "updated": 0, "skipped": 0, "failed": 0}
        if not conversations:
            return stats

        # Pre-fetch existing hashes for all platforms present in this batch
        platforms = set(c.platform for c in conversations)
        for p in platforms:
            if p not in self.known_hashes or force_reindex:
                if force_reindex:
                    self.known_hashes[p] = {}
                else:
                    await self.get_existing_hashes(p)

        sem = asyncio.Semaphore(max(1, concurrency))
        lock = asyncio.Lock()
        processed_count = 0

        async def _process_one(conv: NormalizedConversation):
            nonlocal processed_count
            async with sem:
                try:
                    existing_hashes = self.known_hashes.get(conv.platform, {})

                    # 1. Generate Markdown and calculate content hash
                    md_content, rel_path = MarkdownGenerator.generate(conv)
                    content_hash = hashlib.sha256(md_content.encode("utf-8")).hexdigest()

                    # 2. Check deduplication / reconciliation
                    existing_hash = existing_hashes.get(conv.external_id)
                    if existing_hash == content_hash and not force_reindex:
                        async with lock:
                            stats["skipped"] += 1
                            processed_count += 1
                            if on_progress:
                                on_progress(processed_count, total)
                        return

                    # 3. Always write Markdown locally (Obsidian sync)
                    target_file = settings.MARKDOWN_EXPORT_DIR / rel_path
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text(md_content, encoding="utf-8")

                    # 4. Compute chunks & embeddings if database is connected
                    if self.db and self.db.pool:
                        chunks = self.chunker.chunk_conversation(conv)
                        texts = [c.text_content for c in chunks]
                        embs = await self.embedder.embed_texts(texts)
                        for c, emb in zip(chunks, embs):
                            c.embedding = emb

                        await self.db.upsert_conversation(conv, md_content, rel_path, chunks)

                    async with lock:
                        if existing_hash:
                            stats["updated"] += 1
                        else:
                            stats["imported"] += 1
                        existing_hashes[conv.external_id] = content_hash
                        processed_count += 1
                        if on_progress:
                            on_progress(processed_count, total)

                except Exception as e:
                    logger.error(f"Failed to reconcile conversation {conv.external_id}: {e}", exc_info=True)
                    async with lock:
                        stats["failed"] += 1
                        processed_count += 1
                        if on_progress:
                            on_progress(processed_count, total)

        await asyncio.gather(*[_process_one(c) for c in conversations])
        return stats
