import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import settings
from ..database import Database
from ..embedder import Embedder
from ..models import SearchQuery

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
logger = logging.getLogger("mcp-server")


class BrainArchiveMCPServer:
    def __init__(self):
        self.db = Database()
        self.embedder = Embedder()

    async def initialize_db(self):
        try:
            await self.db.connect()
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")

    async def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "brain-llm-archive",
                        "version": "1.0.0"
                    }
                }
            }

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [
                        {
                            "name": "search_llm_history",
                            "description": "Wyszukaj w pełnej historii konwersacji z modeli LLM (ChatGPT, Claude, Claude Code, Antigravity, DeepSeek, Grok, Gemini). Łączy wektory (HNSW) i wyszukiwanie pełnotekstowe (RRF).",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "Treść zapytania, np. 'jak naprawić błąd w Caddyfile' lub 'architektura bazy pgvector'"
                                    },
                                    "platform": {
                                        "description": "Opcjonalny filtr platformy (ciąg tekstowy lub tablica): 'antigravity', 'claude_code', 'chatgpt', 'claude_web', 'deepseek', 'grok', 'gemini'"
                                    },
                                    "after": {
                                        "type": "string",
                                        "description": "Opcjonalny filtr daty w formacie ISO (np. '2026-01-01')"
                                    },
                                    "limit": {
                                        "type": "integer",
                                        "description": "Maksymalna liczba fragmentów (domyślnie 10)",
                                        "default": 10
                                    }
                                },
                                "required": ["query"]
                            }
                        },
                        {
                            "name": "get_llm_conversation",
                            "description": "Pobierz pełną treść wybranej konwersacji lub dokumentu Markdown po ID lub ścieżce.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "conversation_id": {
                                        "type": "string",
                                        "description": "UUID konwersacji lub external_id"
                                    }
                                },
                                "required": ["conversation_id"]
                            }
                        },
                        {
                            "name": "get_llm_stats",
                            "description": "Pobierz zestawienie statystyk archiwum LLM: liczba konwersacji, wiadomości i chunków per platforma.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                    ]
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "search_llm_history":
                query_str = args.get("query", "")
                platform = args.get("platform")
                after = args.get("after")
                limit = int(args.get("limit", 10))

                if not self.db.pool:
                    await self.initialize_db()

                query_vec = None
                if query_str:
                    embs = await self.embedder.embed_texts([query_str])
                    if embs:
                        query_vec = embs[0]

                from ..models import SearchFilters
                filters = SearchFilters(platform=platform, after=after)
                sq = SearchQuery(query=query_str, platform=platform, filters=filters, limit=limit)
                results = await self.db.hybrid_search(sq, query_vec)

                if not results:
                    text_out = f"Brak wyników dla zapytania: '{query_str}'"
                else:
                    lines = [f"### Wyniki wyszukiwania w historii LLM ({len(results)} znalezionych):\n"]
                    for idx, r in enumerate(results, 1):
                        lines.append(f"**{idx}. [{r.platform.upper()}] {r.title}** (Score: {r.score:.4f})")
                        lines.append(f"*Data: {r.started_at.strftime('%Y-%m-%d')} | Plik: `doc/llm-archive/{r.relative_path or ''}`*")
                        lines.append(f"Kontekst: `{r.header_path}`")
                        lines.append(f"> {r.chunk_text.replace(chr(10), ' ')}")
                        lines.append("")
                    text_out = "\n".join(lines)

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": text_out}]
                    }
                }

            elif tool_name == "get_llm_conversation":
                conv_id = args.get("conversation_id", "")
                if not self.db.pool:
                    await self.initialize_db()

                data = await self.db.get_conversation_full(conv_id)
                if not data:
                    text_out = f"Nie odnaleziono konwersacji o ID: {conv_id}"
                else:
                    text_out = data.get("content_markdown") or json.dumps(data, indent=2, ensure_ascii=False)

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": text_out}]
                    }
                }

            elif tool_name == "get_llm_stats":
                if not self.db.pool:
                    await self.initialize_db()

                stats = await self.db.get_stats()
                lines = ["### Statystyki Brain LLM Archive:\n"]
                lines.append("| Platforma | Konwersacje | Wiadomości | Chunki | Ostatnia Sync |")
                lines.append("| :--- | :--- | :--- | :--- | :--- |")
                total_c, total_m, total_ch = 0, 0, 0
                for r in stats:
                    c, m, ch = r["conversations"], r["messages"], r["chunks"]
                    total_c += c
                    total_m += m
                    total_ch += ch
                    last = r["last_sync"].strftime("%Y-%m-%d %H:%M") if r["last_sync"] else "-"
                    lines.append(f"| **{r['platform']}** | {c:,} | {m:,} | {ch:,} | {last} |")
                lines.append(f"| **RAZEM** | **{total_c:,}** | **{total_m:,}** | **{total_ch:,}** | - |")
                text_out = "\n".join(lines)

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": text_out}]
                    }
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

    async def run_stdio(self):
        await self.initialize_db()
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            raw_text = line.decode("utf-8").strip()
            if not raw_text:
                continue

            try:
                req = json.loads(raw_text)
                res = await self.handle_request(req)
                if res:
                    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                logger.error(f"Error handling MCP line: {e}", exc_info=True)


if __name__ == "__main__":
    server = BrainArchiveMCPServer()
    asyncio.run(server.run_stdio())
