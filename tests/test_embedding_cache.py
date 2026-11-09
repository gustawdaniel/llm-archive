import hashlib
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from src.service.api import app, db, embedder

client = TestClient(app)

@pytest.mark.asyncio
async def test_cached_unchanged_conversation():
    fake_conv = {
        "platform": "antigravity",
        "external_id": "conv-test-cached-1",
        "payload": [
            {"role": "user", "content": "Cześć", "step_index": 1, "created_at": "2026-09-27T12:00:00Z"},
            {"role": "assistant", "content": "Dzień dobry!", "step_index": 2, "created_at": "2026-09-27T12:00:01Z"}
        ],
        "metadata": {
            "conversation_id": "conv-test-cached-1",
            "device": "rog",
            "model": "Gemini 3.8 Flash (High)",
            "title": "Cached Conversation Test"
        }
    }

    with patch.object(db, "pool", True), \
         patch.object(db, "get_conversation_sync_status", new_callable=AsyncMock) as mock_sync_status, \
         patch.object(db, "touch_conversation", new_callable=AsyncMock) as mock_touch, \
         patch.object(embedder, "embed_texts", new_callable=AsyncMock) as mock_embed:

        from src.normalizers import AntigravityNormalizer, MarkdownGenerator
        import hashlib
        conv = AntigravityNormalizer().parse(fake_conv["payload"], fake_conv["metadata"])
        conv.device = "rog"
        conv.model = "Gemini 3.8 Flash (High)"
        md, _ = MarkdownGenerator.generate(conv)
        expected_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()

        mock_sync_status.return_value = {"id": "uuid-12345", "hash_sha256": expected_hash}

        res = client.post("/api/v1/ingest", json=fake_conv)
        assert res.status_code == 200
        data = res.json()
        assert data["embeddings_status"] == "cached_unchanged"
        assert data["conversation_id"] == "uuid-12345"

        mock_embed.assert_not_called()
        mock_touch.assert_called_once_with("uuid-12345")


@pytest.mark.asyncio
async def test_chunk_level_embedding_deduplication():
    fake_conv = {
        "platform": "antigravity",
        "external_id": "conv-test-dedup-1",
        "payload": [
            {"role": "user", "content": "Krok 1", "step_index": 1, "created_at": "2026-09-27T12:00:00Z"},
            {"role": "assistant", "content": "Odpowiedź 1", "step_index": 2, "created_at": "2026-09-27T12:00:01Z"},
            {"role": "user", "content": "Krok 2", "step_index": 3, "created_at": "2026-09-27T12:00:02Z"},
            {"role": "assistant", "content": "Odpowiedź 2", "step_index": 4, "created_at": "2026-09-27T12:00:03Z"}
        ],
        "metadata": {
            "device": "rog",
            "model": "Gemini 3.8 Flash (High)",
            "title": "Dedup Conversation Test"
        }
    }

    with patch.object(db, "pool", True), \
         patch.object(db, "get_conversation_sync_status", new_callable=AsyncMock) as mock_sync_status, \
         patch.object(db, "get_cached_chunk_embeddings", new_callable=AsyncMock) as mock_cached_chunks, \
         patch.object(db, "save_embeddings_to_cache", new_callable=AsyncMock) as mock_save_cache, \
         patch.object(db, "upsert_conversation", new_callable=AsyncMock, return_value="uuid-dedup-1"), \
         patch.object(embedder, "embed_texts", new_callable=AsyncMock) as mock_embed:

        mock_sync_status.return_value = {"id": "uuid-dedup-1", "hash_sha256": "old-hash-999"}

        from src.normalizers import AntigravityNormalizer
        from src.chunker import SemanticChunker
        conv = AntigravityNormalizer().parse(fake_conv["payload"], fake_conv["metadata"])
        conv.device = "rog"
        conv.model = "Gemini 3.8 Flash (High)"
        chunks = SemanticChunker().chunk_conversation(conv)

        # Mock cache returning chunks 0 and 1, only chunk 2 is new
        mock_cached_chunks.return_value = {
            chunks[0].text_content: [0.1] * 1024,
            chunks[1].text_content: [0.2] * 1024
        }
        mock_embed.return_value = [[0.9] * 1024]

        res = client.post("/api/v1/ingest", json=fake_conv)
        assert res.status_code == 200
        data = res.json()
        assert data["embeddings_status"] == "completed"

        # embedder should ONLY be called for the 1 missing chunk, NOT all 3!
        mock_embed.assert_called_once()
        embedded_texts = mock_embed.call_args[0][0]
        assert len(embedded_texts) == 1
        assert embedded_texts[0] == chunks[2].text_content

        # Cache should save the newly computed embedding
        mock_save_cache.assert_called_once_with(embedded_texts, [[0.9] * 1024])


def test_normalize_vector_types():
    from src.database import _normalize_vector
    import pgvector

    v = pgvector.Vector([0.1, 0.2, 0.3])
    assert _normalize_vector(v) == pytest.approx([0.1, 0.2, 0.3])
    assert _normalize_vector("[0.4, 0.5, 0.6]") == pytest.approx([0.4, 0.5, 0.6])
    assert _normalize_vector([0.7, 0.8]) == pytest.approx([0.7, 0.8])
    assert _normalize_vector((0.9, 1.0)) == pytest.approx([0.9, 1.0])
    assert _normalize_vector(None) is None
    assert _normalize_vector("") == []


@pytest.mark.asyncio
async def test_get_cached_chunk_embeddings_with_vector_and_null_bytes():
    from src.database import Database
    import pgvector
    from unittest.mock import MagicMock

    test_db = Database(dsn="postgresql://fake")
    mock_conn = AsyncMock()
    mock_pool = MagicMock()

    class FakeAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    mock_pool.acquire.return_value = FakeAcquire()
    test_db.pool = mock_pool

    # Mock chunk row returning a pgvector.Vector object
    mock_conn.fetch.side_effect = [
        # Call 1: llm_chunks
        [{"text_content": "clean chunk 1", "embedding": pgvector.Vector([0.1, 0.2])}],
        # Call 2: llm_embedding_cache
        [{"content_hash": hashlib.sha256("clean chunk 2".encode("utf-8")).hexdigest(), "embedding": pgvector.Vector([0.3, 0.4])}]
    ]

    # Input texts containing a null byte \x00
    texts = ["clean chunk 1\x00", "clean chunk 2", "clean chunk 3"]
    cached = await test_db.get_cached_chunk_embeddings("uuid-test", texts)

    # Both chunk 1 and chunk 2 should be resolved, even though chunk 1 had a null byte
    assert "clean chunk 1\x00" in cached
    assert cached["clean chunk 1\x00"] == pytest.approx([0.1, 0.2])
    assert "clean chunk 2" in cached
    assert cached["clean chunk 2"] == pytest.approx([0.3, 0.4])
    assert "clean chunk 3" not in cached

    # Verify that the query passed to Postgres had the null byte sanitized away
    first_fetch_args = mock_conn.fetch.call_args_list[0][0]
    assert "clean chunk 1\x00" not in first_fetch_args[2]
    assert "clean chunk 1" in first_fetch_args[2]

