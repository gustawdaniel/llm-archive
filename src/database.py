import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import asyncpg
from .config import settings
from .models import ChunkRecord, NormalizedConversation, SearchQuery, SearchResult

logger = logging.getLogger(__name__)


def _normalize_vector(emb: Any) -> Optional[List[float]]:
    """Converts a pgvector Vector, numpy array, string representation, or sequence into a List[float]."""
    if emb is None:
        return None
    if hasattr(emb, "to_list"):
        return emb.to_list()
    if hasattr(emb, "tolist"):
        return emb.tolist()
    if isinstance(emb, (list, tuple)):
        return [float(x) for x in emb]
    if isinstance(emb, str):
        cleaned = emb.strip("[]() \t\n\r")
        if not cleaned:
            return []
        return [float(x.strip()) for x in cleaned.split(",") if x.strip()]
    try:
        return list(emb)
    except Exception:
        return None


class Database:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or settings.DATABASE_URL
        self.pool: Optional[asyncpg.Pool] = None
        self._stats_cache: Optional[List[Dict[str, Any]]] = None
        self._stats_cache_time: float = 0.0

    async def connect(self):
        if not self.pool:
            import pgvector.asyncpg

            async def init_conn(conn):
                await pgvector.asyncpg.register_vector(conn)

            self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10, init=init_conn)


    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def upsert_conversation(
        self,
        conv: NormalizedConversation,
        markdown_content: str,
        rel_path: str,
        chunks: List[ChunkRecord]
    ) -> str:
        """Upsert conversation, messages, markdown doc, and vector chunks transactionally."""
        if not self.pool:
            await self.connect()

        doc_hash = hashlib.sha256(markdown_content.encode("utf-8")).hexdigest()

        def _clean_obj(val: Any) -> Any:
            if val is None:
                return None
            if isinstance(val, str):
                return val.replace("\x00", "")
            if isinstance(val, dict):
                return {k: _clean_obj(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_clean_obj(v) for v in val]
            return val

        _clean_text = _clean_obj

        # Compute token_summary for fast lookup and display
        total_in = 0
        total_out = 0
        total_cache_read = 0
        total_cache_write = 0

        meta_usage = (
            (conv.raw_metadata or {}).get("token_summary")
            or (conv.raw_metadata or {}).get("usage")
            or (conv.raw_metadata or {}).get("session_usage")
            or (conv.raw_metadata or {}).get("cumulative_token_usage")
        )
        if isinstance(meta_usage, dict):
            total_in = meta_usage.get("inputTokens") or meta_usage.get("input_tokens") or meta_usage.get("input") or 0
            total_out = meta_usage.get("outputTokens") or meta_usage.get("output_tokens") or meta_usage.get("output") or 0
            total_cache_read = meta_usage.get("cacheReadTokens") or meta_usage.get("cache_read_tokens") or meta_usage.get("cache_read") or 0
            total_cache_write = meta_usage.get("cacheWriteTokens") or meta_usage.get("cache_write_tokens") or meta_usage.get("cache_write") or 0

        if total_in == 0 and total_out == 0 and (conv.raw_metadata or {}).get("input_tokens") is not None:
            total_in = (conv.raw_metadata or {}).get("input_tokens", 0)
            total_out = (conv.raw_metadata or {}).get("output_tokens", 0)
            total_cache_read = (conv.raw_metadata or {}).get("cache_read_tokens", 0)
            total_cache_write = (conv.raw_metadata or {}).get("cache_write_tokens", 0)

        msg_in = sum((m.token_usage or {}).get("input_tokens") or (m.token_usage or {}).get("input") or 0 for m in conv.messages)
        msg_out = sum((m.token_usage or {}).get("output_tokens") or (m.token_usage or {}).get("output") or 0 for m in conv.messages)
        msg_cr = sum((m.token_usage or {}).get("cache_read_tokens") or (m.token_usage or {}).get("cache_read") or 0 for m in conv.messages)
        msg_cw = sum((m.token_usage or {}).get("cache_write_tokens") or (m.token_usage or {}).get("cache_write") or 0 for m in conv.messages)

        if total_in == 0 and total_out == 0:
            total_in = msg_in
            total_out = msg_out
            total_cache_read = msg_cr
            total_cache_write = msg_cw

        if total_in > 0 or total_out > 0 or total_cache_read > 0 or total_cache_write > 0:
            if conv.raw_metadata is None:
                conv.raw_metadata = {}
            conv.raw_metadata["token_summary"] = {
                "input_tokens": int(total_in),
                "output_tokens": int(total_out),
                "cache_read_tokens": int(total_cache_read),
                "cache_write_tokens": int(total_cache_write),
                "total_tokens": int(total_in + total_out + total_cache_read + total_cache_write)
            }

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Upsert conversation
                row = await conn.fetchrow(
                    """
                    INSERT INTO llm_conversations (
                        platform, external_id, title, project_path, git_branch,
                        device, model, started_at, updated_at, raw_metadata, last_ingested_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
                    ON CONFLICT (platform, external_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        project_path = COALESCE(EXCLUDED.project_path, llm_conversations.project_path),
                        model = COALESCE(EXCLUDED.model, llm_conversations.model),
                        updated_at = EXCLUDED.updated_at,
                        raw_metadata = EXCLUDED.raw_metadata,
                        -- True "server touched this row now" signal, independent of
                        -- updated_at (which tracks the *content's* own timestamps and
                        -- stays old for backlog conversations re-synced much later).
                        last_ingested_at = NOW()
                    RETURNING id;
                    """,
                    conv.platform,
                    conv.external_id,
                    conv.title,
                    conv.project_path,
                    conv.git_branch,
                    "rog" if (conv.device or settings.DEVICE_NAME or "").lower() in ("brain-db", "server-brain-db", "") else (conv.device or settings.DEVICE_NAME),
                    conv.model,
                    conv.started_at,
                    conv.updated_at,
                    json.dumps(_clean_obj(conv.raw_metadata or {}))
                )
                conv_id = row["id"]

                # 2. Delete existing messages and chunks for this conversation to cleanly replace
                await conn.execute("DELETE FROM llm_messages WHERE conversation_id = $1;", conv_id)
                await conn.execute("DELETE FROM llm_chunks WHERE conversation_id = $1;", conv_id)

                # 3. Batch insert messages

                if conv.messages:
                    msg_records = [
                        (
                            conv_id,
                            m.external_id,
                            m.parent_id,
                            m.step_index,
                            m.role,
                            _clean_obj(m.content) or "",
                            _clean_obj(m.reasoning_content) if m.reasoning_content else None,
                            json.dumps(_clean_obj([tc.model_dump() for tc in m.tool_calls])),
                            json.dumps(_clean_obj(m.attachments or [])),
                            json.dumps(_clean_obj(m.sources or [])),
                            json.dumps(_clean_obj(m.token_usage or {})),
                            m.created_at
                        )
                        for m in conv.messages
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO llm_messages (
                            conversation_id, external_message_id, parent_external_id,
                            step_index, role, content, reasoning_content, tool_calls,
                            attachments, sources, token_usage, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12);
                        """,
                        msg_records
                    )

                # 4. Upsert Markdown document
                await conn.execute(
                    """
                    INSERT INTO llm_documents (
                        conversation_id, relative_path, content_markdown, hash_sha256, updated_at
                    ) VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        relative_path = EXCLUDED.relative_path,
                        content_markdown = EXCLUDED.content_markdown,
                        hash_sha256 = EXCLUDED.hash_sha256,
                        updated_at = NOW();
                    """,
                    conv_id,
                    rel_path,
                    _clean_text(markdown_content),
                    doc_hash
                )

                # 5. Insert chunks
                if chunks:
                    chunk_records = []
                    for c in chunks:
                        chunk_records.append((
                            conv_id,
                            c.chunk_index,
                            _clean_text(c.header_path),
                            _clean_text(c.text_content),
                            c.embedding
                        ))

                    BATCH_SIZE = 250
                    for b_idx in range(0, len(chunk_records), BATCH_SIZE):
                        batch = chunk_records[b_idx:b_idx + BATCH_SIZE]
                        await conn.executemany(
                            """
                            INSERT INTO llm_chunks (
                                conversation_id, chunk_index, header_path, text_content, embedding
                            ) VALUES ($1, $2, $3, $4, $5);
                            """,
                            batch
                        )

                self._stats_cache = None
                return str(conv_id)

    async def get_conversation_sync_status(self, platform: str, external_id: str) -> Optional[Dict[str, Any]]:
        """Checks if a conversation already exists and returns its id and markdown hash."""
        if not self.pool:
            await self.connect()
        if not self.pool or not hasattr(self.pool, "acquire"):
            return None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.id, d.hash_sha256
                FROM llm_conversations c
                LEFT JOIN llm_documents d ON d.conversation_id = c.id
                WHERE c.platform = $1 AND c.external_id = $2;
                """,
                platform, external_id
            )
            if row:
                return {"id": str(row["id"]), "hash_sha256": row["hash_sha256"]}
            return None

    async def touch_conversation(self, conv_id: str) -> None:
        """Updates last_ingested_at timestamp for a conversation whose content has not changed."""
        if not self.pool:
            await self.connect()
        if not self.pool or not hasattr(self.pool, "acquire"):
            return

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE llm_conversations
                SET last_ingested_at = NOW()
                WHERE id = $1::uuid;
                """,
                conv_id
            )

    async def get_cached_chunk_embeddings(
        self,
        conversation_id: Optional[str],
        texts: List[str]
    ) -> Dict[str, List[float]]:
        """Retrieves existing embeddings for chunk texts from the conversation's previous chunks
        and the global embedding cache table (llm_embedding_cache)."""
        if not texts or not self.pool or not hasattr(self.pool, "acquire"):
            return {}

        # Sanitize texts: remove null bytes that cause PostgreSQL UTF-8 encoding errors
        cleaned_map: Dict[str, List[str]] = {}
        for t in texts:
            if not t:
                continue
            cleaned = t.replace("\x00", "")
            if cleaned:
                cleaned_map.setdefault(cleaned, []).append(t)

        if not cleaned_map:
            return {}

        cleaned_texts = list(cleaned_map.keys())
        results: Dict[str, List[float]] = {}

        async with self.pool.acquire() as conn:
            # 1. Reuse existing chunks from this exact conversation
            if conversation_id:
                try:
                    rows = await conn.fetch(
                        """
                        SELECT text_content, embedding
                        FROM llm_chunks
                        WHERE conversation_id = $1::uuid AND embedding IS NOT NULL AND text_content = ANY($2);
                        """,
                        conversation_id, cleaned_texts
                    )
                    for r in rows:
                        emb = _normalize_vector(r["embedding"])
                        if emb is not None:
                            results[r["text_content"]] = emb
                except Exception as e:
                    logger.warning(f"Error retrieving existing conversation chunk embeddings: {e}")

            # 2. For remaining missing texts, query global llm_embedding_cache by SHA256 hash
            missing_texts = [t for t in cleaned_texts if t not in results]
            if missing_texts:
                try:
                    hash_to_text = {
                        hashlib.sha256(t.encode("utf-8")).hexdigest(): t
                        for t in missing_texts
                    }
                    hashes = list(hash_to_text.keys())
                    rows = await conn.fetch(
                        """
                        SELECT content_hash, embedding
                        FROM llm_embedding_cache
                        WHERE content_hash = ANY($1);
                        """,
                        hashes
                    )
                    for r in rows:
                        emb = _normalize_vector(r["embedding"])
                        if emb is not None:
                            h = r["content_hash"].strip()
                            if h in hash_to_text:
                                results[hash_to_text[h]] = emb
                except Exception as e:
                    logger.warning(f"Error querying llm_embedding_cache: {e}")

        # Map results back to original uncleaned texts so callers can match their exact strings
        final_results: Dict[str, List[float]] = {}
        for cleaned, originals in cleaned_map.items():
            if cleaned in results:
                emb = results[cleaned]
                for orig in originals:
                    final_results[orig] = emb

        return final_results

    async def save_embeddings_to_cache(self, texts: List[str], embeddings: List[List[float]]) -> None:
        """Persists newly computed embeddings to llm_embedding_cache."""
        if not texts or not embeddings or not self.pool or not hasattr(self.pool, "acquire"):
            return

        records = []
        seen_hashes = set()
        for t, emb in zip(texts, embeddings):
            if not emb or not t:
                continue
            cleaned = t.replace("\x00", "")
            if not cleaned:
                continue
            norm_emb = _normalize_vector(emb)
            if not norm_emb:
                continue
            h = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                records.append((h, norm_emb))

        if not records:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO llm_embedding_cache (content_hash, embedding)
                    VALUES ($1, $2)
                    ON CONFLICT (content_hash) DO NOTHING;
                    """,
                    records
                )
        except Exception as e:
            logger.warning(f"Could not persist embeddings to cache: {e}")

    async def hybrid_search(self, query: SearchQuery, query_embedding: Optional[List[float]]) -> List[SearchResult]:
        """Perform hybrid search combining fulltext search (BM25) and vector similarity (HNSW)."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            # We use a CTE with reciprocal rank fusion (RRF)
            sql = """
            WITH semantic_search AS (
                SELECT 
                    c.id AS chunk_id,
                    c.conversation_id,
                    c.header_path,
                    c.text_content,
                    RANK() OVER (ORDER BY c.embedding <=> $1::vector) AS rank
                FROM llm_chunks c
                WHERE ($1::vector IS NOT NULL) AND (c.embedding IS NOT NULL)
                LIMIT 50
            ),


            keyword_search AS (
                SELECT 
                    c.id AS chunk_id,
                    c.conversation_id,
                    c.header_path,
                    c.text_content,
                    RANK() OVER (ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('simple', $2)) DESC) AS rank
                FROM llm_chunks c
                WHERE c.tsv @@ websearch_to_tsquery('simple', $2)
                LIMIT 50
            ),
            fused AS (
                SELECT
                    COALESCE(s.chunk_id, k.chunk_id) AS chunk_id,
                    COALESCE(s.conversation_id, k.conversation_id) AS conversation_id,
                    COALESCE(s.header_path, k.header_path) AS header_path,
                    COALESCE(s.text_content, k.text_content) AS text_content,
                    (COALESCE(1.0 / (60.0 + s.rank), 0.0) * $3) + 
                    (COALESCE(1.0 / (60.0 + k.rank), 0.0) * (1.0 - $3)) AS score
                FROM semantic_search s
                FULL OUTER JOIN keyword_search k ON s.chunk_id = k.chunk_id
            ),
            ranked AS (
                SELECT
                    f.conversation_id,
                    cv.platform,
                    cv.title,
                    cv.project_path,
                    cv.started_at,
                    f.header_path,
                    f.text_content,
                    f.score,
                    doc.relative_path,
                    tp.id AS topic_id,
                    tp.name AS topic_name,
                    -- Cap chunks per conversation so one chatty conversation can't
                    -- fill the whole results page and crowd out other matches.
                    ROW_NUMBER() OVER (PARTITION BY f.conversation_id ORDER BY f.score DESC) AS conv_rank
                FROM fused f
                JOIN llm_conversations cv ON f.conversation_id = cv.id
                LEFT JOIN llm_documents doc ON f.conversation_id = doc.conversation_id
                LEFT JOIN llm_conversation_topics ct ON f.conversation_id = ct.conversation_id
                LEFT JOIN llm_topics tp ON ct.topic_id = tp.id
                WHERE
                    ($4::text[] IS NULL OR cv.platform = ANY($4))
                    AND ($5::timestamptz IS NULL OR cv.started_at >= $5)
                    AND ($6::text IS NULL OR cv.project_path = $6)
                    AND ($8::uuid[] IS NULL OR ct.topic_id = ANY($8))
            )
            SELECT conversation_id, platform, title, project_path, started_at,
                   header_path, text_content, score, relative_path, topic_id, topic_name
            FROM ranked
            WHERE conv_rank <= 2
            ORDER BY score DESC
            LIMIT $7;
            """

            platforms = query.platforms_list
            after_dt = query.filter_after
            proj = query.effective_project_path
            topic_ids = query.topic_ids_list
            # websearch_to_tsquery ANDs every term by default; commas usually separate
            # distinct topics/phrases in a query, so treat them as OR instead.
            fts_query = re.sub(r"\s*,\s*", " or ", query.query.strip())

            rows = await conn.fetch(
                sql,
                query_embedding,
                fts_query,
                query.alpha,
                platforms,
                after_dt,
                proj,
                query.limit,
                topic_ids
            )

            results = []
            for r in rows:
                results.append(SearchResult(
                    conversation_id=str(r["conversation_id"]),
                    platform=r["platform"],
                    title=r["title"],
                    project_path=r["project_path"],
                    header_path=r["header_path"],
                    chunk_text=r["text_content"],
                    score=float(r["score"]),
                    started_at=r["started_at"],
                    relative_path=r["relative_path"],
                    topic_id=str(r["topic_id"]) if r["topic_id"] else None,
                    topic_name=r["topic_name"]
                ))
            return results

    async def list_conversations(
        self,
        platform: Optional[str] = None,
        after: Optional[datetime] = None,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List stored conversations with metadata and markdown document paths."""
        if not self.pool:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    c.id, c.platform, c.external_id, c.title, c.project_path,
                    c.git_branch, c.device, c.model, c.started_at, c.updated_at,
                    c.raw_metadata->'token_summary' as token_summary,
                    (SELECT COUNT(*) FROM llm_messages m WHERE m.conversation_id = c.id) as message_count,
                    d.relative_path
                FROM llm_conversations c
                LEFT JOIN llm_documents d ON c.id = d.conversation_id
                WHERE ($1::text IS NULL OR $1 = '' OR c.platform = $1)
                  AND ($2::timestamptz IS NULL OR c.started_at >= $2)
                  AND ($3::text IS NULL OR $3 = '' OR c.title ILIKE '%' || $3 || '%' OR c.project_path ILIKE '%' || $3 || '%')
                ORDER BY c.updated_at DESC
                LIMIT $4 OFFSET $5;
                """,
                platform,
                after,
                query,
                limit,
                offset
            )
            return [
                {
                    "id": str(r["id"]),
                    "platform": r["platform"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "project_path": r["project_path"],
                    "git_branch": r["git_branch"],
                    "device": r["device"],
                    "model": r["model"],
                    "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "token_summary": json.loads(r["token_summary"]) if isinstance(r["token_summary"], str) else r["token_summary"],
                    "message_count": r["message_count"],
                    "relative_path": r["relative_path"],
                }
                for r in rows
            ]

    async def get_sync_status(self, platform: str, limit: int = 100) -> Dict[str, Dict[str, Any]]:
        """
        Fast lookup mapping external_id -> {id, message_count, updated_at, title}
        Used by browser extensions and sync clients to detect delta updates and new chats.
        """
        if not self.pool:
            return {}

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    c.id, c.external_id, c.title, c.updated_at,
                    (SELECT COUNT(*) FROM llm_messages m WHERE m.conversation_id = c.id) as message_count
                FROM llm_conversations c
                WHERE c.platform = $1
                ORDER BY c.updated_at DESC
                LIMIT $2;
                """,
                platform,
                limit
            )
            return {
                r["external_id"]: {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                    "message_count": r["message_count"]
                }
                for r in rows
            }

    async def get_stats(self) -> List[Dict[str, Any]]:
        """Get aggregate statistics grouped by platform with in-memory TTL cache."""
        now = time.time()
        if self._stats_cache is not None and (now - self._stats_cache_time) < 30.0:
            return self._stats_cache

        if not self.pool:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                WITH conv_stats AS (
                    SELECT platform, COUNT(*) AS conversations, MAX(updated_at) AS last_sync
                    FROM llm_conversations
                    GROUP BY platform
                ),
                msg_stats AS (
                    SELECT cv.platform, COUNT(*) AS messages
                    FROM llm_messages m
                    JOIN llm_conversations cv ON m.conversation_id = cv.id
                    GROUP BY cv.platform
                ),
                chunk_stats AS (
                    SELECT cv.platform, COUNT(*) AS chunks
                    FROM llm_chunks ch
                    JOIN llm_conversations cv ON ch.conversation_id = cv.id
                    GROUP BY cv.platform
                )
                SELECT 
                    cs.platform,
                    cs.conversations,
                    COALESCE(ms.messages, 0) AS messages,
                    COALESCE(chs.chunks, 0) AS chunks,
                    cs.last_sync
                FROM conv_stats cs
                LEFT JOIN msg_stats ms ON cs.platform = ms.platform
                LEFT JOIN chunk_stats chs ON cs.platform = chs.platform
                ORDER BY cs.conversations DESC;
            """)
            # last_ingested_at (not updated_at) is the real sync-health signal: it's
            # a server-side NOW() set on every upsert, independent of the content's
            # own message timestamps. A backlog conversation re-synced today still
            # carries old message timestamps, so updated_at alone made healthy sync
            # look stale (or a dead device look falsely "recent").
            device_rows = await conn.fetch("""
                SELECT
                    COALESCE(device, 'nieokreślone') AS device,
                    COUNT(*) AS conversations,
                    MAX(last_ingested_at) AS last_sync
                FROM llm_conversations
                GROUP BY device
                ORDER BY conversations DESC;
            """)

            recent_rows = await conn.fetch("""
                WITH recent_convs AS (
                    SELECT id, platform, title, project_path, device, updated_at, last_ingested_at
                    FROM llm_conversations
                    ORDER BY last_ingested_at DESC
                    LIMIT 8
                )
                SELECT r.id, r.platform, r.title, r.project_path, r.device, r.updated_at, r.last_ingested_at, COUNT(m.id) AS message_count
                FROM recent_convs r
                LEFT JOIN llm_messages m ON m.conversation_id = r.id
                GROUP BY r.id, r.platform, r.title, r.project_path, r.device, r.updated_at, r.last_ingested_at
                ORDER BY r.last_ingested_at DESC;
            """)

            res = {
                "platforms": [
                    {
                        "platform": r["platform"],
                        "conversations": r["conversations"],
                        "messages": r["messages"],
                        "chunks": r["chunks"],
                        "last_sync": r["last_sync"].isoformat() if r["last_sync"] else None,
                    }
                    for r in rows
                ],
                "devices": [
                    {
                        "device": d["device"],
                        "conversations": d["conversations"],
                        "last_sync": d["last_sync"].isoformat() if d["last_sync"] else None,
                    }
                    for d in device_rows
                ],
                "recent_syncs": [
                    {
                        "id": str(rc["id"]),
                        "platform": rc["platform"],
                        "title": rc["title"],
                        "project_path": rc["project_path"],
                        "device": rc["device"],
                        "message_count": rc["message_count"],
                        "updated_at": rc["updated_at"].isoformat() if rc["updated_at"] else None,
                        "last_ingested_at": rc["last_ingested_at"].isoformat() if rc["last_ingested_at"] else None,
                    }
                    for rc in recent_rows
                ],
            }
            self._stats_cache = res
            self._stats_cache_time = now
            return res

    async def get_conversation_full(self, conv_id_or_ext: str) -> Optional[Dict[str, Any]]:
        """Fetch full conversation details including messages and markdown."""
        if not self.pool:
            return None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.*, d.relative_path, d.content_markdown
                FROM llm_conversations c
                LEFT JOIN llm_documents d ON c.id = d.conversation_id
                WHERE c.id::text = $1 OR c.external_id = $1;
                """,
                conv_id_or_ext
            )
            if not row:
                return None

            messages = await conn.fetch(
                """
                SELECT role, content, step_index, reasoning_content, tool_calls, attachments, sources, token_usage, created_at
                FROM llm_messages
                WHERE conversation_id = $1
                ORDER BY step_index ASC;
                """,
                row["id"]
            )

            raw_meta = json.loads(row["raw_metadata"]) if isinstance(row["raw_metadata"], str) else (row["raw_metadata"] or {})
            return {
                "id": str(row["id"]),
                "platform": row["platform"],
                "external_id": row["external_id"],
                "title": row["title"],
                "project_path": row["project_path"],
                "git_branch": row["git_branch"],
                "device": row["device"],
                "model": row["model"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "relative_path": row["relative_path"],
                "content_markdown": row["content_markdown"],
                "raw_metadata": raw_meta,
                "token_summary": raw_meta.get("token_summary"),
                "messages": [
                    {
                        "role": m["role"],
                        "content": m["content"],
                        "step_index": m["step_index"],
                        "reasoning_content": m["reasoning_content"],
                        "tool_calls": json.loads(m["tool_calls"]) if isinstance(m["tool_calls"], str) else m["tool_calls"],
                        "attachments": json.loads(m["attachments"]) if isinstance(m["attachments"], str) else m["attachments"],
                        "sources": json.loads(m["sources"]) if isinstance(m["sources"], str) else m["sources"],
                        "token_usage": json.loads(m["token_usage"]) if isinstance(m["token_usage"], str) else (m["token_usage"] or {}),
                        "created_at": m["created_at"].isoformat() if m["created_at"] else None,
                    }
                    for m in messages
                ],
            }

    async def save_search_query(
        self,
        query_text: str,
        short_title: str,
        embedding: Optional[List[float]] = None
    ) -> Optional[Dict[str, Any]]:
        """Store or update a search query with vector embedding in llm_search_queries."""
        if not self.pool:
            return None

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_search_queries (query_text, short_title, embedding, execution_count, last_executed_at)
                VALUES ($1, $2, $3, 1, NOW())
                ON CONFLICT (query_text) DO UPDATE SET
                    execution_count = llm_search_queries.execution_count + 1,
                    last_executed_at = NOW(),
                    embedding = COALESCE(EXCLUDED.embedding, llm_search_queries.embedding)
                RETURNING id, query_text, short_title, execution_count, last_executed_at, created_at;
                """,
                query_text.strip(),
                short_title.strip(),
                embedding
            )
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "query_text": row["query_text"],
                "short_title": row["short_title"],
                "execution_count": row["execution_count"],
                "last_executed_at": row["last_executed_at"].isoformat() if row["last_executed_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }

    async def get_recent_search_queries(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch recently executed/saved search queries."""
        if not self.pool:
            return []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, query_text, short_title, execution_count, last_executed_at, created_at
                FROM llm_search_queries
                ORDER BY last_executed_at DESC
                LIMIT $1;
                """,
                limit
            )
            return [
                {
                    "id": str(r["id"]),
                    "query_text": r["query_text"],
                    "short_title": r["short_title"],
                    "execution_count": r["execution_count"],
                    "last_executed_at": r["last_executed_at"].isoformat() if r["last_executed_at"] else None,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]

    # --- Topics & Knowledge Graph (see docs/topics_knowledge_graph.md) ---

    async def get_conversation_topic_texts(self, only_missing_embedding: bool = True) -> List[Dict[str, Any]]:
        """Fetch title + summary (+ chunk_index=0 "Overview" chunk fallback when
        summary is empty) for conversations to embed. Tried swapping the fallback
        to the first two real turns (chunk_index 1,2) for richer signal - that
        collapsed HDBSCAN into one giant blob (long/noisy tool-call and code
        boilerplate drowns out the topic signal); the short Title/Platform/Model
        overview clusters far better in practice, so it stays. only_missing_embedding=False forces a refetch
        of every conversation (e.g. after summaries get backfilled)."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.id,
                    c.title,
                    d.summary,
                    (SELECT ch.text_content FROM llm_chunks ch
                     WHERE ch.conversation_id = c.id AND ch.chunk_index = 0) AS overview_text
                FROM llm_conversations c
                LEFT JOIN llm_documents d ON d.conversation_id = c.id
                WHERE (NOT $1::boolean) OR (c.embedding IS NULL)
                ORDER BY c.id;
                """,
                only_missing_embedding
            )
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "overview_text": r["overview_text"],
                }
                for r in rows
            ]

    async def update_conversation_embeddings(self, updates: List[Any]) -> None:
        """updates: list of (conversation_id, embedding)."""
        if not updates:
            return
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            await conn.executemany(
                "UPDATE llm_conversations SET embedding = $1 WHERE id = $2;",
                [(emb, conv_id) for conv_id, emb in updates]
            )

    async def get_all_conversation_embeddings(self) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, title, embedding FROM llm_conversations WHERE embedding IS NOT NULL;"
            )
            return [{"id": r["id"], "title": r["title"], "embedding": r["embedding"].to_list()} for r in rows]

    async def get_conversation_snippets(self, conversation_ids: List[Any]) -> Dict[Any, str]:
        """Small helper for topic naming: the first real-turn snippet for a
        specific handful of conversation ids, used only when their title is a
        generic placeholder ("New chat" etc.) with nothing else to name from."""
        if not conversation_ids:
            return {}
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT conversation_id, text_content
                FROM llm_chunks
                WHERE conversation_id = ANY($1::uuid[]) AND chunk_index = 1;
                """,
                conversation_ids
            )
            return {r["conversation_id"]: r["text_content"] for r in rows}

    async def get_topics(self) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name, description, centroid, is_manual FROM llm_topics;")
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "centroid": r["centroid"].to_list(),
                    "is_manual": r["is_manual"],
                }
                for r in rows
            ]

    async def update_topic_centroid(self, topic_id: Any, centroid: List[float]) -> None:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE llm_topics SET centroid = $1, updated_at = NOW() WHERE id = $2;",
                centroid, topic_id
            )

    async def create_topic(
        self, name: str, centroid: List[float], description: Optional[str] = None, is_manual: bool = False
    ) -> Any:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO llm_topics (name, description, centroid, is_manual) VALUES ($1, $2, $3, $4) RETURNING id;",
                name, description, centroid, is_manual
            )
            return row["id"]

    async def update_topic(
        self,
        topic_id: Any,
        name: Optional[str] = None,
        description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> bool:
        """Partial update - only touches fields actually passed. Used for
        renaming/re-describing/re-tagging a topic from the web UI."""
        if name is None and description is None and keywords is None:
            return False
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE llm_topics SET
                    name = COALESCE($2, name),
                    description = CASE WHEN $3::boolean THEN $4 ELSE description END,
                    keywords = CASE WHEN $5::boolean THEN $6 ELSE keywords END,
                    updated_at = NOW()
                WHERE id = $1;
                """,
                topic_id, name, description is not None, description, keywords is not None, keywords
            )
            return res == "UPDATE 1"

    async def delete_topic(self, topic_id: Any) -> bool:
        """llm_conversation_topics has ON DELETE CASCADE on topic_id, so member
        assignments are removed automatically - conversations themselves are
        untouched, only the topic and its links to them disappear."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            res = await conn.execute("DELETE FROM llm_topics WHERE id = $1;", topic_id)
            return res == "DELETE 1"

    async def find_conversations_by_title(self, title_fragment: str, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, title, platform, started_at
                FROM llm_conversations
                WHERE title ILIKE '%' || $1 || '%'
                ORDER BY started_at DESC
                LIMIT $2;
                """,
                title_fragment, limit
            )
            return [
                {"id": str(r["id"]), "title": r["title"], "platform": r["platform"],
                 "started_at": r["started_at"].isoformat() if r["started_at"] else None}
                for r in rows
            ]

    async def assign_conversation_to_topic(self, conversation_id: Any, topic_id: Any, score: float = 1.0, source: str = "manual") -> None:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_conversation_topics (conversation_id, topic_id, score, source)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (conversation_id, topic_id) DO UPDATE SET
                    score = EXCLUDED.score, source = EXCLUDED.source, assigned_at = NOW();
                """,
                conversation_id, topic_id, score, source
            )

    async def unassign_conversation_from_topic(self, conversation_id: Any, topic_id: Any) -> bool:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM llm_conversation_topics WHERE conversation_id = $1 AND topic_id = $2;",
                conversation_id, topic_id
            )
            return res == "DELETE 1"

    async def get_topic_member_embeddings(self, topic_id: Any) -> List[List[float]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.embedding
                FROM llm_conversations c
                JOIN llm_conversation_topics ct ON ct.conversation_id = c.id
                WHERE ct.topic_id = $1 AND c.embedding IS NOT NULL;
                """,
                topic_id
            )
            return [r["embedding"].to_list() for r in rows]

    async def suggest_similar_conversations(self, topic_id: Any, limit: int = 10) -> List[Dict[str, Any]]:
        """kNN over the topic's OWN centroid (recomputed from whatever's been
        manually confirmed so far, not from any HDBSCAN pass), excluding
        conversations already in this topic. Pure suggestion list - assigns
        nothing, that's a separate deliberate step."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            topic = await conn.fetchrow("SELECT centroid FROM llm_topics WHERE id = $1;", topic_id)
            if not topic:
                return []
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.platform, c.started_at, 1 - (c.embedding <=> $1) AS score
                FROM llm_conversations c
                WHERE c.embedding IS NOT NULL
                  AND c.id NOT IN (SELECT conversation_id FROM llm_conversation_topics WHERE topic_id = $2)
                ORDER BY c.embedding <=> $1
                LIMIT $3;
                """,
                topic["centroid"], topic_id, limit
            )
            return [
                {"id": str(r["id"]), "title": r["title"], "platform": r["platform"],
                 "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                 "score": float(r["score"])}
                for r in rows
            ]

    async def replace_auto_topic_assignments(self, conversation_ids: List[Any], assignments: List[Any]) -> None:
        """assignments: list of (conversation_id, topic_id, score). Deletes existing
        source='auto' rows for conversation_ids first, then inserts fresh ones.
        source='manual' rows are never touched, by construction (delete filters on
        source='auto', and the insert's ON CONFLICT only updates auto rows)."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if conversation_ids:
                    await conn.execute(
                        "DELETE FROM llm_conversation_topics WHERE conversation_id = ANY($1::uuid[]) AND source = 'auto';",
                        conversation_ids
                    )
                if assignments:
                    await conn.executemany(
                        """
                        INSERT INTO llm_conversation_topics (conversation_id, topic_id, score, source)
                        VALUES ($1, $2, $3, 'auto')
                        ON CONFLICT (conversation_id, topic_id) DO UPDATE SET
                            score = EXCLUDED.score,
                            assigned_at = NOW()
                        WHERE llm_conversation_topics.source = 'auto';
                        """,
                        assignments
                    )

    async def mark_conversations_clustered(self, conversation_ids: List[Any]) -> None:
        if not conversation_ids:
            return
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE llm_conversations SET last_clustered_at = NOW() WHERE id = ANY($1::uuid[]);",
                conversation_ids
            )

    async def compute_and_store_similarity_edges(self, top_k: int = 5, min_score: float = 0.75) -> int:
        """Per-conversation indexed kNN (HNSW) queries, not an O(n^2) self-join -
        scales fine well past this project's size. Replaces the whole edge set
        each run since it's cheap at this scale (~4k conversations)."""
        if not self.pool:
            await self.connect()

        edges: Dict[Any, float] = {}
        async with self.pool.acquire() as conn:
            conv_rows = await conn.fetch(
                "SELECT id, embedding FROM llm_conversations WHERE embedding IS NOT NULL;"
            )
            for row in conv_rows:
                neighbors = await conn.fetch(
                    """
                    SELECT id, 1 - (embedding <=> $1) AS score
                    FROM llm_conversations
                    WHERE embedding IS NOT NULL AND id != $2
                    ORDER BY embedding <=> $1
                    LIMIT $3;
                    """,
                    row["embedding"], row["id"], top_k
                )
                for n in neighbors:
                    score = float(n["score"])
                    if score < min_score:
                        continue
                    a, b = row["id"], n["id"]
                    if b < a:
                        a, b = b, a
                    key = (a, b)
                    if key not in edges or score > edges[key]:
                        edges[key] = score

            async with conn.transaction():
                await conn.execute("DELETE FROM llm_similarity_edges;")
                if edges:
                    records = [(a, b, score) for (a, b), score in edges.items()]
                    await conn.executemany(
                        """
                        INSERT INTO llm_similarity_edges (conversation_id_a, conversation_id_b, score)
                        VALUES ($1, $2, $3);
                        """,
                        records
                    )
        return len(edges)

    async def get_user_messages_for_conversations(self, conversation_ids: List[Any], limit_per_conv: int = 30) -> Dict[Any, List[str]]:
        """Real user messages (not just titles) for a handful of conversations -
        used to generate a topic's description/keywords from actual content."""
        if not conversation_ids:
            return {}
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT conversation_id, content
                FROM (
                    SELECT conversation_id, content, step_index,
                           ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY step_index) AS rn
                    FROM llm_messages
                    WHERE conversation_id = ANY($1::uuid[]) AND role = 'user'
                ) ranked
                WHERE rn <= $2
                ORDER BY conversation_id, step_index;
                """,
                conversation_ids, limit_per_conv
            )
            out: Dict[Any, List[str]] = {}
            for r in rows:
                out.setdefault(r["conversation_id"], []).append(r["content"])
            return out

    async def update_topic_description(self, topic_id: Any, description: Optional[str], keywords: Optional[List[str]]) -> None:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE llm_topics SET description = $1, keywords = $2, updated_at = NOW() WHERE id = $3;",
                description, keywords, topic_id
            )

    async def get_topics_with_descriptions(self) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, description, keywords, centroid, is_manual FROM llm_topics;"
            )
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "keywords": list(r["keywords"]) if r["keywords"] else [],
                    "centroid": r["centroid"].to_list(),
                    "is_manual": r["is_manual"],
                }
                for r in rows
            ]

    async def merge_topic(self, primary_id: Any, secondary_id: Any) -> None:
        """Folds secondary into primary: reassigns its conversation_topics rows
        (skipping any conversation already scored under primary - a manual
        assignment there always wins) and deletes the now-empty secondary topic."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE llm_conversation_topics
                    SET topic_id = $1
                    WHERE topic_id = $2
                      AND conversation_id NOT IN (
                          SELECT conversation_id FROM llm_conversation_topics WHERE topic_id = $1
                      );
                    """,
                    primary_id, secondary_id
                )
                await conn.execute("DELETE FROM llm_conversation_topics WHERE topic_id = $1;", secondary_id)
                await conn.execute("DELETE FROM llm_topics WHERE id = $1;", secondary_id)

    async def list_topics_with_counts(self) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.id, t.name, t.description, t.keywords, t.is_manual, count(ct.conversation_id) AS n
                FROM llm_topics t
                LEFT JOIN llm_conversation_topics ct ON ct.topic_id = t.id
                GROUP BY t.id, t.name, t.description, t.keywords, t.is_manual
                ORDER BY n DESC, t.name ASC;
                """
            )
            return [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "description": r["description"],
                    "keywords": list(r["keywords"]) if r["keywords"] else [],
                    "is_manual": r["is_manual"],
                    "count": r["n"],
                }
                for r in rows
            ]

    async def get_topic_by_id(self, topic_id: Any) -> Optional[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT id, name, description, keywords, is_manual FROM llm_topics WHERE id = $1;",
                topic_id
            )
            if not r:
                return None
            return {
                "id": str(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "keywords": list(r["keywords"]) if r["keywords"] else [],
                "is_manual": r["is_manual"],
            }

    async def find_topics_by_name(self, name_query: str) -> List[Dict[str, Any]]:
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, description FROM llm_topics WHERE name ILIKE '%' || $1 || '%' ORDER BY name;",
                name_query
            )
            return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]

    async def get_topic_conversations_with_paths(self, topic_id: Any) -> List[Dict[str, Any]]:
        """Like get_topic_conversations but with relative_path - needed to build
        wikilinks in the topic hub markdown document, not just display titles."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.platform, d.relative_path, ct.score
                FROM llm_conversation_topics ct
                JOIN llm_conversations c ON c.id = ct.conversation_id
                LEFT JOIN llm_documents d ON d.conversation_id = c.id
                WHERE ct.topic_id = $1
                ORDER BY ct.score DESC;
                """,
                topic_id
            )
            return [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "platform": r["platform"],
                    "relative_path": r["relative_path"],
                    "score": float(r["score"]),
                }
                for r in rows
            ]

    async def get_topic_conversations(self, topic_id: Any, limit: int = 200) -> List[Dict[str, Any]]:
        """The query the analysis loop was missing: what's actually IN this
        topic. Ordered by membership score so the most representative members
        surface first."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.platform, c.started_at, ct.score, ct.source
                FROM llm_conversation_topics ct
                JOIN llm_conversations c ON c.id = ct.conversation_id
                WHERE ct.topic_id = $1
                ORDER BY ct.score DESC
                LIMIT $2;
                """,
                topic_id, limit
            )
            return [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "platform": r["platform"],
                    "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                    "score": float(r["score"]),
                    "source": r["source"],
                }
                for r in rows
            ]

    async def get_conversations_with_similarity_edges(self) -> List[Dict[str, Any]]:
        """Each conversation that has >=1 similarity edge, with its own
        relative_path and its neighbors' (relative_path, title, score) -
        undirected, so an edge (A,B) shows up under both A and B."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH undirected AS (
                    SELECT conversation_id_a AS conv_id, conversation_id_b AS neighbor_id, score FROM llm_similarity_edges
                    UNION ALL
                    SELECT conversation_id_b AS conv_id, conversation_id_a AS neighbor_id, score FROM llm_similarity_edges
                )
                SELECT
                    u.conv_id,
                    d.relative_path AS conv_path,
                    nd.relative_path AS neighbor_path,
                    nc.title AS neighbor_title,
                    u.score
                FROM undirected u
                JOIN llm_documents d ON d.conversation_id = u.conv_id
                JOIN llm_documents nd ON nd.conversation_id = u.neighbor_id
                JOIN llm_conversations nc ON nc.id = u.neighbor_id
                ORDER BY u.conv_id, u.score DESC;
                """
            )
            result: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                cid = str(r["conv_id"])
                if cid not in result:
                    result[cid] = {"relative_path": r["conv_path"], "neighbors": []}
                result[cid]["neighbors"].append({
                    "relative_path": r["neighbor_path"],
                    "title": r["neighbor_title"],
                    "score": float(r["score"]),
                })
            return list(result.values())

    async def delete_search_query(self, query_id: str) -> bool:
        """Delete a saved search query by ID."""
        if not self.pool:
            return False

        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM llm_search_queries WHERE id = $1::uuid;",
                query_id
            )
            return res == "DELETE 1"

    async def get_topic_timeline(self, topic_id: Any) -> List[Dict[str, Any]]:
        """Intensity over time: count of conversations grouped by week."""
        if not self.pool:
            await self.connect()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    date_trunc('week', c.started_at) AS period,
                    count(*) AS count
                FROM llm_conversation_topics ct
                JOIN llm_conversations c ON c.id = ct.conversation_id
                WHERE ct.topic_id = $1 AND c.started_at IS NOT NULL
                GROUP BY period
                ORDER BY period ASC;
                """,
                topic_id
            )
            return [
                {
                    "period": r["period"].strftime("%Y-%m-%d") if r["period"] else None,
                    "count": int(r["count"])
                }
                for r in rows
            ]

    async def get_topic_context_export(self, topic_id: Any, max_conversations: int = 20) -> Optional[Dict[str, Any]]:
        """Generates an executive context document for a topic, ready for Antigravity or Claude Code."""
        if not self.pool:
            await self.connect()

        topic = await self.get_topic_by_id(topic_id)
        if not topic:
            return None

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    c.id, c.title, c.platform, c.started_at,
                    d.summary, d.relative_path, ct.score
                FROM llm_conversation_topics ct
                JOIN llm_conversations c ON c.id = ct.conversation_id
                LEFT JOIN llm_documents d ON d.conversation_id = c.id
                WHERE ct.topic_id = $1
                ORDER BY c.started_at DESC NULLS LAST
                LIMIT $2;
                """,
                topic_id, max_conversations
            )

        timeline = await self.get_topic_timeline(topic_id)

        doc_lines = [
            f"# Kontekst Tematu / Projektu: {topic['name']}",
            "",
            f"> **Opis:** {topic['description'] or 'Brak opisu.'}",
        ]
        if topic.get("keywords"):
            doc_lines.append(f"> **Słowa kluczowe:** {', '.join(topic['keywords'])}")
        doc_lines.extend([
            "",
            f"## Zestawienie konwersacji (łącznie w temacie: {len(rows)})",
            ""
        ])

        for r in rows:
            dt = r["started_at"].strftime("%Y-%m-%d %H:%M") if r["started_at"] else "Nieznana data"
            doc_lines.append(f"### [{r['platform'].upper()}] {r['title']} ({dt})")
            if r["summary"]:
                doc_lines.append(f"- **Podsumowanie:** {r['summary']}")
            if r["relative_path"]:
                doc_lines.append(f"- **Notatka:** `{r['relative_path']}`")
            doc_lines.append("")

        doc_text = "\n".join(doc_lines)
        return {
            "topic": topic,
            "timeline": timeline,
            "conversations_count": len(rows),
            "markdown": doc_text
        }


