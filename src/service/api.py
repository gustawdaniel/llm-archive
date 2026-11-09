import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..config import settings
from ..models import NormalizedConversation, SearchQuery, SearchResult
from ..normalizers import (
    AntigravityNormalizer,
    ClaudeCodeNormalizer,
    ChatGPTNormalizer,
    ClaudeWebNormalizer,
    DeepSeekNormalizer,
    GrokNormalizer,
    GeminiNormalizer,
    PerplexityNormalizer,
    ClineNormalizer,
    OpenCodeNormalizer,
    AiderNormalizer,
    OMPNormalizer,
    ZedNormalizer,
    HermesNormalizer,
    CodexNormalizer,
    MarkdownGenerator,
)
from ..normalizers.mirror import MirrorNormalizer
from ..chunker import SemanticChunker
from ..embedder import Embedder
from ..database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm-archive")

import asyncio
from contextlib import asynccontextmanager
from .auto_titler import AutoTitler

db = Database()
chunker = SemanticChunker()
embedder = Embedder()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db.connect()
        logger.info("Connected to PostgreSQL pgvector database.")
    except Exception as e:
        logger.warning(f"Could not connect to PostgreSQL on startup ({e}). API running in buffer/file mode.")

    titler_task = None
    if db.pool and settings.ENABLE_AUTO_TITLER:
        titler = AutoTitler(db=db)
        titler_task = asyncio.create_task(
            titler.run_loop(interval_seconds=settings.TITLER_INTERVAL, batch_size=5)
        )
        logger.info(f"AutoTitler background worker started (interval: {settings.TITLER_INTERVAL}s).")

    yield

    if titler_task:
        titler_task.cancel()
        try:
            await titler_task
        except asyncio.CancelledError:
            pass

    await db.close()


app = FastAPI(title="Brain LLM Archive API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RawIngestRequest(BaseModel):
    platform: str  # 'antigravity', 'claude_code', 'chatgpt', 'claude_web', 'deepseek', 'grok', 'gemini'
    external_id: Optional[str] = None
    raw_data: Optional[Any] = None
    payload: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None


class ReindexRequest(BaseModel):
    platform: Optional[str] = None
    conversation_id: Optional[str] = None


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "device": settings.DEVICE_NAME,
        "database_connected": bool(db.pool is not None)
    }


_pending_embed_tasks: int = 0


@app.get("/api/v1/system/status")
async def system_status():
    """Returns real-time compute worker health, ping latency, and ingest queue depth."""
    worker_info = await embedder.get_worker_status()
    return {
        "device": settings.DEVICE_NAME,
        "database_connected": bool(db.pool is not None),
        "compute_worker": worker_info,
        "pending_embed_tasks": _pending_embed_tasks
    }


from fastapi import FastAPI, HTTPException, Query, BackgroundTasks

_embed_semaphore = asyncio.Semaphore(1)


async def _background_embed_chunks(conversation_id: str, chunks: List[Any]):
    """Background worker to calculate embeddings and update chunks in DB."""
    global _pending_embed_tasks
    _pending_embed_tasks += 1
    try:
        async with _embed_semaphore:
            chunks_needing_embed = [c for c in chunks if getattr(c, "embedding", None) is None]
            if not chunks_needing_embed:
                return

            texts = [c.text_content for c in chunks_needing_embed]
            # Check cache first: another task may have embedded these while waiting for semaphore
            cached = await db.get_cached_chunk_embeddings(conversation_id, texts)
            still_missing_chunks = []
            still_missing_texts = []
            for c in chunks_needing_embed:
                if c.text_content in cached:
                    c.embedding = cached[c.text_content]
                else:
                    still_missing_chunks.append(c)
                    still_missing_texts.append(c.text_content)

            if still_missing_texts:
                new_embeddings = await embedder.embed_texts(still_missing_texts)
                for c, emb in zip(still_missing_chunks, new_embeddings):
                    c.embedding = emb
                await db.save_embeddings_to_cache(still_missing_texts, new_embeddings)

            if db.pool:
                async with db.pool.acquire() as conn:
                    for c in chunks_needing_embed:
                        if getattr(c, "embedding", None) is not None:
                            await conn.execute(
                                """
                                UPDATE llm_chunks 
                                SET embedding = $1 
                                WHERE conversation_id = $2::uuid AND (chunk_index = $3 OR text_content = $4);
                                """,
                                c.embedding,
                                conversation_id,
                                c.chunk_index,
                                c.text_content.replace("\x00", "")
                            )
            logger.info(
                f"Background embedding completed for conversation {conversation_id} "
                f"({len(still_missing_texts)} newly computed, {len(texts) - len(still_missing_texts)} from cache)."
            )
    except Exception as e:
        logger.error(f"Error in background embedding for {conversation_id}: {e}", exc_info=True)
    finally:
        _pending_embed_tasks = max(0, _pending_embed_tasks - 1)


async def _background_reindex_worker(platform_filter: Optional[str] = None):
    """Background worker to re-embed all chunks in batches."""
    try:
        if not db.pool:
            return
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.text_content
                FROM llm_chunks c
                JOIN llm_conversations cv ON c.conversation_id = cv.id
                WHERE ($1::text IS NULL OR cv.platform = $1)
                ORDER BY c.id;
                """,
                platform_filter
            )
            batch_size = 50
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                texts = [r["text_content"] for r in batch]
                embeddings = await embedder.embed_texts(texts)
                update_data = [(emb, r["id"]) for emb, r in zip(embeddings, batch)]
                await conn.executemany(
                    "UPDATE llm_chunks SET embedding = $1 WHERE id = $2;",
                    update_data
                )
        logger.info(f"Background reindex completed for platform={platform_filter} ({len(rows)} chunks).")
    except Exception as e:
        logger.error(f"Error in background reindex: {e}", exc_info=True)


@app.post("/api/v1/ingest")
async def ingest_conversation(
    req: RawIngestRequest,
    background_tasks: BackgroundTasks,
    async_embed: bool = Query(False, description="Compute embeddings in background")
):
    """Ingest, normalize, save markdown to disk, compute vector chunks, and persist to database."""
    normalizers = {
        "antigravity": AntigravityNormalizer(),
        "claude_code": ClaudeCodeNormalizer(),
        "chatgpt": ChatGPTNormalizer(),
        "claude_web": ClaudeWebNormalizer(),
        "deepseek": DeepSeekNormalizer(),
        "grok": GrokNormalizer(),
        "gemini": GeminiNormalizer(),
        "perplexity": PerplexityNormalizer(),
        "cline": ClineNormalizer(),
        "opencode": OpenCodeNormalizer(),
        "aider": AiderNormalizer(),
        "omp": OMPNormalizer(),
        "zed": ZedNormalizer(),
        "hermes": HermesNormalizer(),
        "codex": CodexNormalizer(),
        "mirror": MirrorNormalizer(),
    }

    norm = normalizers.get(req.platform.lower())
    if not norm:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {req.platform}")

    data = req.raw_data if req.raw_data is not None else req.payload
    if data is None:
        raise HTTPException(status_code=400, detail="Missing conversation data: provide 'raw_data' or 'payload'")

    meta = req.metadata or {}
    if not meta.get("device"):
        raise HTTPException(
            status_code=400,
            detail="metadata.device is required: the ingesting client must identify its own hostname. "
                   "Silently falling back to the server's own name mislabels provenance."
        )
    if req.external_id:
        if "conversation_id" not in meta:
            meta["conversation_id"] = req.external_id
        if "session_id" not in meta:
            meta["session_id"] = req.external_id

    try:
        conv: Optional[NormalizedConversation] = norm.parse(data, meta)
    except Exception as e:
        logger.error(f"Error parsing conversation from {req.platform}: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Parsing error: {str(e)}")

    if conv:
        dev = conv.device or meta.get("device")
        if not dev or dev.lower() in ("brain-db", "server-brain-db", "unknown", "nieokreślone"):
            dev = "rog"
        conv.device = dev
        if not conv.model:
            conv.model = meta.get("model")
        if not conv.model:
            if conv.platform == "antigravity":
                conv.model = "Gemini 3.8 Flash (High)"
            elif conv.platform == "claude_code":
                conv.model = "claude-3-7-sonnet"
            elif conv.platform == "cline":
                conv.model = "deepseek-v4.1-flash"

    # Never silently accept an empty result: this is the exact failure mode
    # that lost real data before (server parsed 0 messages from a well-formed
    # payload, still upserted the empty result, still returned 200 - the
    # daemon had no idea anything was wrong). A single archive with a single
    # operator should fail loud, not fail quiet.
    if conv is None or not conv.messages:
        raise HTTPException(
            status_code=422,
            detail=f"Parsed 0 messages for {req.platform}:{req.external_id} - refusing to upsert "
                    "(would silently overwrite any existing good data with an empty conversation)."
        )

    # Reject conversations where all messages are completely blank
    has_text = any(
        (m.content and m.content.strip()) or (m.reasoning_content and m.reasoning_content.strip()) or m.tool_calls
        for m in conv.messages
    )
    if not has_text:
        raise HTTPException(
            status_code=422,
            detail=f"Refusing to upsert {req.platform}:{req.external_id}: all {len(conv.messages)} messages have empty content."
        )

    # 1. Generate Markdown with YAML frontmatter
    md_content, rel_path = MarkdownGenerator.generate(conv)

    # 2. Write Markdown directly to the doc/llm-archive Obsidian vault
    target_md_file = settings.MARKDOWN_EXPORT_DIR / rel_path
    target_md_file.parent.mkdir(parents=True, exist_ok=True)
    target_md_file.write_text(md_content, encoding="utf-8")

    if not db.pool:
        # Previously this silently skipped the DB write and still returned
        # "status": "success" - a client had no way to know nothing was
        # persisted. Loud failure lets the daemon's retry/backoff do its job.
        raise HTTPException(status_code=503, detail="Database is not connected - ingest not persisted, retry.")

    doc_hash = hashlib.sha256(md_content.encode("utf-8")).hexdigest()

    # Fast-path: if conversation already exists with the exact same content hash, skip all re-chunking/embedding
    sync_status = await db.get_conversation_sync_status(conv.platform, conv.external_id)
    if sync_status and sync_status.get("hash_sha256") == doc_hash:
        await db.touch_conversation(sync_status["id"])
        return {
            "status": "success",
            "conversation_id": sync_status["id"],
            "platform": conv.platform,
            "title": conv.title,
            "markdown_path": str(target_md_file),
            "relative_path": rel_path,
            "total_chunks": 0,
            "total_messages": len(conv.messages),
            "embeddings_status": "cached_unchanged",
        }

    # 3. Create semantic chunks
    chunks = chunker.chunk_conversation(conv)

    db_id = None
    try:
        # Deduplication: reuse already computed embeddings for unchanged chunks
        conv_db_id = sync_status["id"] if sync_status else None
        chunk_texts = [c.text_content for c in chunks]
        cached_embeddings = await db.get_cached_chunk_embeddings(conv_db_id, chunk_texts)

        texts_to_embed = []
        chunks_to_embed = []
        for c in chunks:
            if c.text_content in cached_embeddings:
                c.embedding = cached_embeddings[c.text_content]
            else:
                chunks_to_embed.append(c)
                texts_to_embed.append(c.text_content)

        if async_embed:
            # Save to database immediately, embed missing chunks in background
            db_id = await db.upsert_conversation(conv, md_content, rel_path, chunks)
            if db_id and chunks_to_embed:
                background_tasks.add_task(_background_embed_chunks, str(db_id), chunks_to_embed)
            embeddings_status = "queued_background" if chunks_to_embed else "completed_from_cache"
        else:
            # Synchronous embedding ONLY for new/changed chunks
            if texts_to_embed:
                embeddings = await embedder.embed_texts(texts_to_embed)
                for c, emb in zip(chunks_to_embed, embeddings):
                    c.embedding = emb
                await db.save_embeddings_to_cache(texts_to_embed, embeddings)

            db_id = await db.upsert_conversation(conv, md_content, rel_path, chunks)
            embeddings_status = "completed" if texts_to_embed else "completed_from_cache"
    except Exception as e:
        logger.error(f"Database upsert error for {req.platform}:{req.external_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database upsert failed, not persisted: {e}")

    return {
        "status": "success",
        "conversation_id": db_id or conv.external_id,
        "platform": conv.platform,
        "title": conv.title,
        "markdown_path": str(target_md_file),
        "relative_path": rel_path,
        "total_chunks": len(chunks),
        "total_messages": len(conv.messages),
        "embeddings_status": embeddings_status,
    }


from .search import SearchService

search_service = SearchService(db, embedder)


@app.post("/api/v1/search")
async def search_conversations(query: SearchQuery):
    """Hybrid semantic search across past conversations."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    results = await search_service.search(query)
    return {"query": query.query, "count": len(results), "results": results}


@app.get("/api/v1/search/queries")
async def get_search_queries(limit: int = Query(25, ge=1, le=100)):
    """Get recently executed search queries for quick selection and graph linking."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    queries = await db.get_recent_search_queries(limit=limit)
    return {"queries": queries}


@app.delete("/api/v1/search/queries/{query_id}")
async def delete_search_query(query_id: str):
    """Delete a saved search query by ID."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    success = await db.delete_search_query(query_id)
    if not success:
        raise HTTPException(status_code=404, detail="Query not found")
    return {"status": "deleted", "id": query_id}


class AskRequest(BaseModel):
    query: str
    limit: int = 5


@app.post("/api/v1/rag/ask")
@app.post("/api/v1/ask")
async def ask_infinite_memory_endpoint(req: AskRequest):
    """Infinite Memory Q&A (RAG) over entire conversation memory with local Ollama synthesis."""
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="Zapytanie nie może być puste.")

    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    # 1. Hybrid semantic search across archive (top 3 chunks for fast context)
    sq = SearchQuery(query=req.query.strip(), limit=min(req.limit, 4))
    search_results = await search_service.search(sq)

    # 2. Build context blocks & citation list
    context_parts = []
    sources = []
    for idx, r in enumerate(search_results):
        sources.append({
            "id": r.conversation_id,
            "title": r.title or "Bez tytułu",
            "platform": r.platform,
            "score": round(r.score, 4),
            "snippet": r.chunk_text[:300] if r.chunk_text else "",
            "started_at": r.started_at,
            "topic_name": r.topic_name
        })
        context_parts.append(
            f"--- ŹRÓDŁO {idx + 1} ({r.platform}: {r.title or 'N/A'}) ---\n"
            f"{r.chunk_text[:800]}"
        )

    context_str = "\n\n".join(context_parts) if context_parts else "Brak pasujących konwersacji w bazie wiedzy."

    system_prompt = (
        "Jesteś osobistym asystentem wiedzy Daniela Gustawa (Brain OS Infinite Memory).\n"
        "Odpowiadaj precyzyjnie i zwięźle w języku polskim, wyłącznie na podstawie faktów z podanych źródeł.\n"
        "Wymieniaj konkretne decyzje, technologie i plany."
    )
    user_prompt = f"Pytanie: {req.query.strip()}\n\nKontekst:\n{context_str}\n\nZwięzła odpowiedź:"

    # 3. Call local Ollama
    answer = None
    model_used = "qwen2.5:3b"
    import httpx

    ollama_urls = [settings.OLLAMA_BASE_URL] + [u for u in settings.OLLAMA_FALLBACK_URLS if u != settings.OLLAMA_BASE_URL]
    for url in ollama_urls:
        if not url:
            continue
        # Try qwen2.5:3b first (faster on CPU), then qwen2.5:7b
        for candidate_model in ["qwen2.5:3b", "qwen2.5:7b"]:
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    res = await client.post(
                        f"{url.rstrip('/')}/api/chat",
                        json={
                            "model": candidate_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            "stream": False,
                            "options": {"temperature": 0.2, "num_predict": 300}
                        }
                    )
                    if res.status_code == 200:
                        data = res.json()
                        answer = data.get("message", {}).get("content", "").strip()
                        if answer:
                            model_used = f"ollama/{candidate_model}"
                            break
            except Exception as e:
                logger.debug(f"Ollama call to {url} with {candidate_model} failed: {e}")
        if answer:
            break

    # Fallback to direct extractive synthesis if LLM is unreachable
    if not answer:
        if search_results:
            answer = (
                f"Znaleziono {len(search_results)} powiązanych wątków w pamięci cyfrowej.\n\n"
                f"Główny kontekst z konwersacji **„{search_results[0].title}”** ({search_results[0].platform}):\n\n"
                f"> {search_results[0].chunk_text[:500]}..."
            )
            model_used = "extractive-fallback"
        else:
            answer = "Nie znalazłem w pamięci żadnych konwersacji bezpośrednio odpowiadających na to zapytanie."
            model_used = "none"

    return {
        "query": req.query.strip(),
        "answer": answer,
        "model": model_used,
        "sources": sources
    }


# Mount podcast RSS server if available
try:
    from ..audio_feed.rss_server import app as podcast_app
    app.mount("/podcast", podcast_app)
    app.mount("/api/v1/podcast", podcast_app)
except Exception as e:
    logger.warning(f"Could not mount podcast RSS app: {e}")




@app.get("/api/v1/conversations")
async def get_conversations(
    platform: Optional[str] = Query(None, description="Filter by platform name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List indexed conversations with message counts and metadata."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    if not platform or not platform.strip():
        platform = None

    conversations = await db.list_conversations(platform=platform, limit=limit, offset=offset)
    return {
        "count": len(conversations),
        "limit": limit,
        "offset": offset,
        "conversations": conversations,
    }


TOOL_OUTPUT_PREVIEW_CHARS = 8000
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{1000,}")


def _trim_tool_output(value: Any) -> Any:
    """Long Claude Code sessions carry tool outputs with base64 screenshots and
    PDF pages (one 4.8k-message session was 46 MB of tool_calls) - the viewer
    only prints them as text, so drop base64 and cap the rest."""
    if not isinstance(value, str) or len(value) <= TOOL_OUTPUT_PREVIEW_CHARS:
        return value
    value = _BASE64_RUN.sub(lambda m: f"<base64 {len(m.group(0)) // 1024} KB pominięte>", value)
    if len(value) > TOOL_OUTPUT_PREVIEW_CHARS:
        value = value[:TOOL_OUTPUT_PREVIEW_CHARS] + f"\n… [ucięto {len(value) - TOOL_OUTPUT_PREVIEW_CHARS} znaków, pełne: ?full_tools=true]"
    return value


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation_detail(conversation_id: str, full_tools: bool = Query(False)):
    """Get full details and Markdown content of a specific conversation."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    conv = await db.get_conversation_full(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not full_tools:
        for msg in conv.get("messages") or []:
            for call in msg.get("tool_calls") or []:
                if isinstance(call, dict) and "output" in call:
                    call["output"] = _trim_tool_output(call["output"])
    return conv


from ..topics import TopicClusterer

topic_clusterer = TopicClusterer(db, embedder)


class CreateTopicRequest(BaseModel):
    name: str
    description: Optional[str] = None


class AssignTopicRequest(BaseModel):
    conversation_id: str


class UpdateTopicRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None


@app.get("/api/v1/topics")
async def list_topics():
    """List all topics (auto-discovered + manually curated) with member counts."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    return {"topics": await db.list_topics_with_counts()}


@app.post("/api/v1/topics")
async def create_topic(req: CreateTopicRequest):
    """Create a new, empty, manually-curated topic - see docs/topics_knowledge_graph.md."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic_id = await topic_clusterer.create_manual_topic(req.name, description=req.description)
    return {"id": str(topic_id), "name": req.name}


@app.get("/api/v1/topics/{topic_id}")
async def get_topic(topic_id: str):
    """Topic metadata + its current members."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic["conversations"] = await db.get_topic_conversations(topic_id, limit=500)
    return topic


@app.patch("/api/v1/topics/{topic_id}")
async def update_topic(topic_id: str, req: UpdateTopicRequest):
    """Rename/re-describe/re-tag a topic - centroid is untouched (regenerate
    separately if it no longer fits after a big membership change)."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    await db.update_topic(topic_id, name=req.name, description=req.description, keywords=req.keywords)
    return await db.get_topic_by_id(topic_id)


@app.delete("/api/v1/topics/{topic_id}")
async def delete_topic(topic_id: str):
    """Deletes the topic and its membership links. Conversations themselves
    are untouched - only the grouping disappears."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    removed = await db.delete_topic(topic_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "deleted", "id": topic_id}


@app.get("/api/v1/topics/{topic_id}/suggest")
async def suggest_for_topic(topic_id: str, limit: int = Query(10, ge=1, le=50)):
    """Candidates similar to what's already manually confirmed in this topic -
    a suggestion list only, assigns nothing."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"suggestions": await topic_clusterer.suggest(topic_id, limit=limit)}


@app.post("/api/v1/topics/{topic_id}/assign")
async def assign_to_topic(topic_id: str, req: AssignTopicRequest):
    """Manually attach a conversation to a topic (source='manual' - never
    overwritten by the automatic reclustering job)."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    await topic_clusterer.assign(topic_id, req.conversation_id)
    return {"status": "assigned", "topic_id": topic_id, "conversation_id": req.conversation_id}


@app.delete("/api/v1/topics/{topic_id}/assign/{conversation_id}")
async def unassign_from_topic(topic_id: str, conversation_id: str):
    """Detach a conversation from a topic."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    removed = await topic_clusterer.unassign(topic_id, conversation_id)
    if not removed:
        raise HTTPException(status_code=404, detail="That conversation wasn't assigned to this topic")
    return {"status": "unassigned", "topic_id": topic_id, "conversation_id": conversation_id}


@app.get("/api/v1/topics/{topic_id}/timeline")
async def get_topic_timeline_endpoint(topic_id: str):
    """Weekly intensity timeline of conversations within the topic."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    topic = await db.get_topic_by_id(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    timeline = await db.get_topic_timeline(topic_id)
    return {"topic_id": topic_id, "timeline": timeline}


@app.get("/api/v1/topics/{topic_id}/context")
async def get_topic_context_endpoint(
    topic_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max recent conversations in export")
):
    """Executive markdown context document for a topic, formatted for Antigravity or Claude Code."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")
    ctx = await db.get_topic_context_export(topic_id, max_conversations=limit)
    if not ctx:
        raise HTTPException(status_code=404, detail="Topic not found")
    return ctx


@app.get("/api/v1/sync/status")
async def get_sync_status(
    platform: str = Query(..., description="Platform identifier, e.g. gemini, chatgpt, claude"),
    limit: int = Query(100, ge=1, le=500, description="Max recent conversations to check")
):
    """
    Returns sync status map for recent conversations of a platform:
    { "external_id": { "id": "...", "message_count": 10, "updated_at": "..." } }
    Allows browser extensions and mobile clients to detect missing or updated chats without spamming.
    """
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    status_map = await db.get_sync_status(platform.lower(), limit=limit)
    return {
        "platform": platform.lower(),
        "count": len(status_map),
        "conversations": status_map
    }


@app.get("/api/v1/stats")
async def get_archive_stats():
    """Get archive summary statistics: counts per platform, total messages, chunks, and latest sync."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    stats_data = await db.get_stats()
    platforms = stats_data.get("platforms", []) if isinstance(stats_data, dict) else stats_data
    devices = stats_data.get("devices", []) if isinstance(stats_data, dict) else []
    recent_syncs = stats_data.get("recent_syncs", []) if isinstance(stats_data, dict) else []

    total_convs = sum(r.get("conversations", 0) for r in platforms)
    total_msgs = sum(r.get("messages", 0) for r in platforms)
    total_chunks = sum(r.get("chunks", 0) for r in platforms)

    return {
        "total_conversations": total_convs,
        "total_messages": total_msgs,
        "total_chunks": total_chunks,
        "platforms": platforms,
        "devices": devices,
        "recent_syncs": recent_syncs,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/v1/reindex")
async def reindex_conversations(
    req: Optional[ReindexRequest] = None,
    background_tasks: BackgroundTasks = None,
    async_mode: bool = Query(False, description="Run reindexing as a background task")
):
    """Trigger re-indexing and re-embedding for conversations."""
    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection is not available.")

    platform_filter = req.platform if req else None

    if async_mode and background_tasks:
        background_tasks.add_task(_background_reindex_worker, platform_filter)
        return {
            "status": "reindexing_started",
            "mode": "background",
            "platform": platform_filter
        }

    # Synchronous reindex in batches
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.text_content
            FROM llm_chunks c
            JOIN llm_conversations cv ON c.conversation_id = cv.id
            WHERE ($1::text IS NULL OR cv.platform = $1)
            ORDER BY c.id;
            """,
            platform_filter
        )

        batch_size = 50
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            texts = [r["text_content"] for r in batch]
            embeddings = await embedder.embed_texts(texts)
            update_data = [(emb, r["id"]) for emb, r in zip(embeddings, batch)]
            await conn.executemany(
                "UPDATE llm_chunks SET embedding = $1 WHERE id = $2;",
                update_data
            )

    return {
        "status": "reindexed",
        "chunks_updated": len(rows),
        "platform": platform_filter,
    }


from .mcp_server import BrainArchiveMCPServer
mcp_server_instance = BrainArchiveMCPServer()


@app.post("/mcp")
@app.post("/api/v1/mcp")
async def mcp_http_endpoint(req: Dict[str, Any]):
    """HTTP transport for Model Context Protocol (MCP) JSON-RPC 2.0."""
    if db.pool and not mcp_server_instance.db.pool:
        mcp_server_instance.db.pool = db.pool
    res = await mcp_server_instance.handle_request(req)
    if res is None:
        return {"status": "ok"}
    return res
