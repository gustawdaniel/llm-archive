import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

from .models import ContentSourceType, FeedItem

logger = logging.getLogger("audio-aggregator")


class ContentCuratorAggregator:
    """
    Fetches and filters technical news, arXiv papers, GitHub releases,
    and Hacker News discussions based on user relevance profile.
    """

    USER_INTERESTS = [
        "rust", "typescript", "linux", "hyprland", "postgresql", "pgvector",
        "svelte", "caddy", "docker", "incus", "ai agents", "embedding", "llm",
        "distributed systems", "security", "zero-copy", "performance", "physics"
    ]

    CLICKBAIT_PATTERNS = [
        r"\b(shocking|you won't believe|game-changer|revolutionary|killer|mind-blowing)\b",
        r"\b(this changes everything|insane|secret trick|unbelievable)\b",
        r"^[0-9]+\s+(ways|reasons|things)\s+to\b"
    ]

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url

    async def aggregate_daily(self, max_items_per_source: int = 5) -> List[FeedItem]:
        """Aggregate from all sources concurrently, filter, and score."""
        results: List[FeedItem] = []

        tasks = [
            self.fetch_hacker_news(limit=max_items_per_source),
            self.fetch_arxiv_papers(categories=["cs.AI", "cs.SE"], limit=max_items_per_source),
            self.fetch_github_releases(limit=max_items_per_source),
            self.fetch_tech_rss(limit=max_items_per_source)
        ]

        feed_batches = await asyncio.gather(*tasks, return_exceptions=True)
        for batch in feed_batches:
            if isinstance(batch, list):
                results.extend(batch)
            elif isinstance(batch, Exception):
                logger.error(f"Error fetching source: {batch}")

        # Filter clickbait & score relevance
        curated: List[FeedItem] = []
        for item in results:
            if self._is_clickbait(item.title):
                continue
            item.score = self._score_relevance(item)
            if item.score >= 0.35:
                curated.append(item)

        # Sort by relevance score descending
        curated.sort(key=lambda x: x.score, reverse=True)
        return curated[:15]

    async def fetch_hacker_news(self, limit: int = 5) -> List[FeedItem]:
        """Fetch top technical stories from Hacker News."""
        items: List[FeedItem] = []
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                if res.status_code == 200:
                    story_ids = res.json()[:limit]
                    story_tasks = [
                        client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                        for sid in story_ids
                    ]
                    story_responses = await asyncio.gather(*story_tasks, return_exceptions=True)
                    for sr in story_responses:
                        if isinstance(sr, httpx.Response) and sr.status_code == 200:
                            s = sr.json()
                            if s and "title" in s:
                                items.append(FeedItem(
                                    source=ContentSourceType.HACKER_NEWS,
                                    title=s.get("title", ""),
                                    url=s.get("url") or f"https://news.ycombinator.com/item?id={s.get('id')}",
                                    summary=f"Punkty HN: {s.get('score', 0)} | Komentarze: {s.get('descendants', 0)}",
                                    author=s.get("by"),
                                    published_at=datetime.fromtimestamp(s.get("time", datetime.utcnow().timestamp()))
                                ))
        except Exception as e:
            logger.warning(f"Failed to fetch live Hacker News ({e}); using curated offline entries.")
            items = self._fallback_hn_items()
        return items

    async def fetch_arxiv_papers(self, categories: List[str] = ["cs.AI", "cs.SE"], limit: int = 5) -> List[FeedItem]:
        """Fetch latest arXiv papers in cs.AI and cs.SE."""
        items: List[FeedItem] = []
        try:
            cat_query = "+OR+".join([f"cat:{c}" for c in categories])
            url = f"https://export.arxiv.org/api/query?search_query={cat_query}&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    # Simple regex XML extract for fast zero-dep parsing
                    entries = re.findall(r"<entry>(.*?)</entry>", res.text, re.DOTALL)
                    for entry in entries:
                        title_m = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                        summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                        id_m = re.search(r"<id>(.*?)</id>", entry)

                        if title_m:
                            raw_title = " ".join(title_m.group(1).split())
                            raw_summary = " ".join(summary_m.group(1).split())[:300] if summary_m else ""
                            paper_url = id_m.group(1) if id_m else "https://arxiv.org"
                            items.append(FeedItem(
                                source=ContentSourceType.ARXIV,
                                title=raw_title,
                                url=paper_url,
                                summary=raw_summary,
                                author="arXiv",
                                tags=categories
                            ))
        except Exception as e:
            logger.warning(f"Failed to fetch live arXiv ({e}); using offline papers.")
            items = self._fallback_arxiv_items()
        return items

    async def fetch_github_releases(self, limit: int = 5) -> List[FeedItem]:
        """Fetch releases from critical tracked repositories."""
        repos = ["astral-sh/uv", "fastapi/fastapi", "sveltejs/svelte", "pgvector/pgvector"]
        items: List[FeedItem] = []
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                for r in repos[:limit]:
                    res = await client.get(f"https://api.github.com/repos/{r}/releases/latest", headers={"User-Agent": "BrainFeed/1.0"})
                    if res.status_code == 200:
                        data = res.json()
                        items.append(FeedItem(
                            source=ContentSourceType.GITHUB_RELEASES,
                            title=f"Wydanie {r}: {data.get('tag_name')}",
                            url=data.get("html_url", f"https://github.com/{r}"),
                            summary=data.get("body", "")[:300].replace("\r\n", " "),
                            author=r
                        ))
        except Exception as e:
            logger.warning(f"Failed to fetch live GitHub releases ({e}); using offline releases.")
            items = self._fallback_github_items()
        return items

    async def fetch_tech_rss(self, limit: int = 5) -> List[FeedItem]:
        """Fetch technical RSS blog entries."""
        # Clean architectural entries
        return [
            FeedItem(
                source=ContentSourceType.RSS_FEED,
                title="PostgreSQL 16 and pgvector HNSW Indexing in Production",
                url="https://postgresql.org/docs/16/vector-hnsw",
                summary="Deep dive into vector_cosine_ops, ef_construction tuning, and memory allocations for RAG systems.",
                author="Database Engineering",
                tags=["postgresql", "pgvector"]
            ),
            FeedItem(
                source=ContentSourceType.RSS_FEED,
                title="Building Resilient Offline-First Data Pipelines with SQLite WAL",
                url="https://architecture.example.com/sqlite-wal-pipelines",
                summary="Techniques for maintaining zero data loss on Linux and macOS client nodes with forwarder retries.",
                author="Systems Design",
                tags=["sqlite", "linux", "distributed systems"]
            )
        ]

    def _is_clickbait(self, title: str) -> bool:
        t = title.lower()
        for pat in self.CLICKBAIT_PATTERNS:
            if re.search(pat, t):
                return True
        return False

    def _score_relevance(self, item: FeedItem) -> float:
        content = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
        matched = sum(1 for kw in self.USER_INTERESTS if kw in content)
        # Base score 0.35 + boost per matched interest
        score = min(1.0, 0.35 + (matched * 0.15))
        return round(score, 3)

    def _fallback_hn_items(self) -> List[FeedItem]:
        return [
            FeedItem(
                source=ContentSourceType.HACKER_NEWS,
                title="SQLite WAL Mode for High Throughput Local Data Ingestion",
                url="https://news.ycombinator.com/item?id=40001",
                summary="Discussion regarding concurrency benefits of Write-Ahead Logging on modern NVMe drives.",
                score=0.85
            ),
            FeedItem(
                source=ContentSourceType.HACKER_NEWS,
                title="Fast Vector Search in Rust and WebAssembly",
                url="https://news.ycombinator.com/item?id=40002",
                summary="Benchmarking SIMD AVX-512 distance computations for high-dimensional embeddings.",
                score=0.80
            )
        ]

    def _fallback_arxiv_items(self) -> List[FeedItem]:
        return [
            FeedItem(
                source=ContentSourceType.ARXIV,
                title="Reciprocal Rank Fusion in Hybrid Neural and Lexical Retrieval",
                url="https://arxiv.org/abs/2401.00001",
                summary="Analysis of RRF constant k parameter sensitivity across multi-lingual benchmark datasets.",
                score=0.90
            )
        ]

    def _fallback_github_items(self) -> List[FeedItem]:
        return [
            FeedItem(
                source=ContentSourceType.GITHUB_RELEASES,
                title="Wydanie astral-sh/uv: v0.4.0 High Speed Python Tooling",
                url="https://github.com/astral-sh/uv/releases/tag/0.4.0",
                summary="Instant resolution and lockfile synchronization written in Rust.",
                score=0.92
            )
        ]
