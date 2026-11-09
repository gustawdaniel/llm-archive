import hashlib
import logging
from typing import List, Optional
import httpx
from .config import settings

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(
        self,
        provider: Optional[str] = None,
        ollama_url: Optional[str] = None,
        ollama_urls: Optional[List[str]] = None,
        ollama_model: Optional[str] = None,
        openai_key: Optional[str] = None,
        dim: Optional[int] = None
    ):
        self.provider = provider or settings.EMBEDDING_PROVIDER
        
        # Build prioritized candidates list: rog (GPU) -> mac (GPU) -> brain-db (CPU)
        raw_candidates: List[str] = []
        if ollama_urls:
            raw_candidates.extend(ollama_urls)
        elif ollama_url:
            raw_candidates.append(ollama_url)
        
        if settings.OLLAMA_FALLBACK_URLS:
            raw_candidates.extend(settings.OLLAMA_FALLBACK_URLS)
        else:
            raw_candidates.extend(settings.get_default_ollama_urls())
            
        # Deduplicate while preserving order
        seen = set()
        self.ollama_urls: List[str] = []
        for u in raw_candidates:
            clean_u = u.rstrip("/")
            if clean_u and clean_u not in seen:
                seen.add(clean_u)
                self.ollama_urls.append(clean_u)

        self.ollama_url = self.ollama_urls[0] if self.ollama_urls else "http://localhost:11434"
        self.ollama_model = ollama_model or settings.OLLAMA_MODEL
        self.openai_key = openai_key or settings.OPENAI_API_KEY
        self.dim = dim or settings.EMBEDDING_DIM
        self._active_worker: Optional[str] = None

    @staticmethod
    def get_worker_name(url: str) -> str:
        u = url.lower()
        if "127.0.0.1" in u or "localhost" in u:
            return "local [Ollama]"
        return url

    async def get_active_worker(self) -> Optional[str]:
        """Probes candidate endpoints in priority order and returns the first healthy one."""
        async with httpx.AsyncClient(timeout=1.5) as client:
            for url in self.ollama_urls:
                try:
                    resp = await client.get(f"{url}/api/version")
                    if resp.status_code == 200:
                        if self._active_worker != url:
                            name = self.get_worker_name(url)
                            logger.info(f"Connected to Ollama compute worker: {name} at {url}")
                            self._active_worker = url
                            self.ollama_url = url
                        return url
                except Exception:
                    continue
        return None

    async def is_ollama_online(self) -> bool:
        worker = await self.get_active_worker()
        return worker is not None

    async def get_worker_status(self) -> dict:
        """Returns details about the active/reachable Ollama compute worker and its ping latency."""
        import time
        async with httpx.AsyncClient(timeout=2.0) as client:
            for url in self.ollama_urls:
                t0 = time.perf_counter()
                try:
                    resp = await client.get(f"{url}/api/version")
                    if resp.status_code == 200:
                        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                        name = self.get_worker_name(url)
                        self._active_worker = url
                        self.ollama_url = url
                        return {
                            "name": name,
                            "url": url,
                            "latency_ms": latency_ms,
                            "status": "online",
                            "model": self.ollama_model
                        }
                except Exception:
                    continue
        return {
            "name": "offline",
            "url": None,
            "latency_ms": None,
            "status": "offline",
            "model": self.ollama_model
        }

    async def embed_texts(self, texts: List[str], batch_size: int = 50) -> List[List[float]]:
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            if self.provider == "ollama":
                try:
                    embs = await self._embed_ollama(batch)
                    if len(embs) == len(batch):
                        all_embeddings.extend(embs)
                        continue
                except Exception as e:
                    logger.warning(f"All Ollama workers failed ({e}), falling back to dummy/hash embedder.")
                all_embeddings.extend([self._dummy_embed(t) for t in batch])

            elif self.provider == "openai" and self.openai_key:
                try:
                    embs = await self._embed_openai(batch)
                    all_embeddings.extend(embs)
                except Exception as e:
                    logger.warning(f"OpenAI embedding failed ({e}), falling back to dummy/hash embedder.")
                    all_embeddings.extend([self._dummy_embed(t) for t in batch])

            else:
                all_embeddings.extend([self._dummy_embed(t) for t in batch])

        return all_embeddings


    async def _embed_ollama(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # Try candidates in order: rog -> mac -> brain-db
        last_error = None
        for url in self.ollama_urls:
            name = self.get_worker_name(url)
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # 1. Try modern batch /api/embed endpoint first
                    try:
                        resp = await client.post(
                            f"{url}/api/embed",
                            json={"model": self.ollama_model, "input": texts}
                        )
                        if resp.status_code == 200:
                            embeddings = resp.json().get("embeddings") or []
                            if len(embeddings) == len(texts):
                                self._active_worker = url
                                self.ollama_url = url
                                return embeddings
                    except Exception as e:
                        logger.debug(f"Worker {name} ({url}) /api/embed failed: {e}, trying /api/embeddings")

                    # 2. Fallback to /api/embeddings (single item iteration)
                    results = []
                    for text in texts:
                        resp = await client.post(
                            f"{url}/api/embeddings",
                            json={"model": self.ollama_model, "prompt": text}
                        )
                        resp.raise_for_status()
                        emb = resp.json().get("embedding") or []
                        results.append(emb)

                    if len(results) == len(texts):
                        self._active_worker = url
                        self.ollama_url = url
                        return results
            except Exception as e:
                logger.warning(f"Ollama worker {name} ({url}) unavailable or failed: {e}. Trying next worker in chain...")
                last_error = e
                continue

        raise RuntimeError(f"All Ollama workers failed: {last_error}")


    async def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json={"input": texts, "model": settings.OPENAI_EMBEDDING_MODEL}
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return [item["embedding"] for item in data]

    def _dummy_embed(self, text: str) -> List[float]:
        """Fast deterministic pseudo-embedding for testing or when local models are offline."""
        import random
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:16], 16)
        rng = random.Random(seed)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [round(x / norm, 6) for x in vec]

