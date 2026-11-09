import logging
from typing import Any, Dict, List, Optional

from ..database import Database
from ..embedder import Embedder
from ..models import SearchQuery, SearchResult

logger = logging.getLogger("service.search")


class SearchService:
    """Service handling hybrid vector + full-text search with Reciprocal Rank Fusion (RRF)."""

    def __init__(self, db: Database, embedder: Optional[Embedder] = None):
        self.db = db
        self.embedder = embedder or Embedder()

    async def search(self, query: SearchQuery) -> List[SearchResult]:
        query_embeddings = await self.embedder.embed_texts([query.query])
        query_vec = query_embeddings[0] if query_embeddings else None

        results = await self.db.hybrid_search(query, query_vec)

        # Store or update the query in llm_search_queries for quick recall & graph linking
        try:
            cleaned = " ".join(query.query.strip().split())
            if len(cleaned) <= 45:
                short_title = cleaned
            else:
                truncated = cleaned[:45]
                last_space = truncated.rfind(" ")
                short_title = (truncated[:last_space] if last_space > 15 else truncated) + "…"
            await self.db.save_search_query(query.query, short_title, query_vec)
        except Exception as e:
            logger.warning(f"Failed to auto-save search query: {e}")

        return results
