# 🧠 Brain LLM Archive & Semantic Retrieval

System pobierania, normalizacji i semantycznego wyszukiwania pełnej historii komunikacji z LLM (Web, Mobile, Desktop CLI) dla ekosystemu `brain`.

---

## 🎯 Możliwości i Obsługiwane Źródła

1. **Agenty Programistyczne i CLI**:
   - **Antigravity**: parsowanie transkryptów sesji (`~/.gemini/antigravity-ide/brain/*/.system_generated/logs/transcript*.jsonl`), narzędzi (`run_command`, `view_file`, `replace_file_content`) i artefaktów.
   - **Claude Code**: parsowanie sesji (`~/.claude/projects/*/*.jsonl`), historii zapytań i wywołań narzędzi.
2. **Platformy Webowe & Mobile**:
   - **ChatGPT**: obsługa zrzutów GDPR (`conversations.json`) oraz zsynchronizowanych w chmurze sesji webowych/mobilnych.
   - **Claude (Anthropic)**: zrzuty konta oraz internal API (`/api/organizations/.../chat_conversations`).
   - **DeepSeek**: historia sesji z `chat.deepseek.com`.
   - **Grok & Gemini**: zrzuty i web intercepting.
3. **Most Mobilny (Mobile Gap Solution)**:
   - Rozszerzenie przeglądarkowe w tle wykonuje cykliczny *Delta Sync* (`GET /conversations?limit=15`).
   - Nowe lub zaktualizowane na smartfonie wątki (`updated_at`) są automatycznie wykrywane i zaciągane do bazy.
4. **Normalizacja do Markdown (Obsidian Vault)**:
   - Zunifikowany format z YAML Frontmatter (metadane, projekt, model, znaczniki czasu, tagi).
   - Zwijane sekcje narzędzi (`<details><summary>🛠️ Tool Call</summary>`).
   - Bezpośredni zapis do katalogu `doc/llm-archive/`.
5. **Hybrydowe Wyszukiwanie Semantyczne (`PostgreSQL + pgvector`)**:
   - Połączenie wektorowego przeszukiwania HNSW (Cosine Distance) z modelem subwordowym `bge-m3` oraz wyszukiwania pełnotekstowego (`tsvector` + GIN, RRF). Literówki i odmiany są naturalnie obsługiwane przez tokenizację subwordową modelu, a słowa kluczowe przez leksykalny FTS.

---

## 🚀 Szybki Start (CLI)

```bash
cd apps/llm-archive

# 1. Instalacja zależności
make install

# 2. Przeskanowanie lokalnych sesji agentów
make scan

# 3. Znormalizowanie sesji i zapis do doc/llm-archive/
make ingest

# 4. Jednorazowy / okresowy import paczek Takeout (idempotentny)
make import-takeout
# lub bezpośrednio przez CLI:
uv run python -m src.cli.main import-takeout /sciezka/do/takeout-extracted

# 5. Uruchomienie lokalnego demona w tle (real-time sync Antigravity + Claude Code)
make watch

# 6. Uruchomienie serwera Ingest & Search API lokalnie do developmentu (port 8080)
# Produkcyjnie API działa jako kontener Docker na brain-db — patrz docs/network_and_sync.md
make serve
```

---

## 🔄 Real-time sync sesji agentów (Antigravity + Claude Code)

Historia z lokalnych sesji Antigravity i Claude Code trafia do archiwum dwiema **niezależnymi** ścieżkami — ważne żeby ich nie mylić:

1. **Import historyczny / zbiorczy (`brain-llm import-takeout`, jednorazowy)** — parsuje wszystkie pliki na dysku i embeduje je lokalnie (wymaga Ollamy z modelem `bge-m3` na maszynie, na której uruchamiasz import). Używać do pierwszego załadowania danych albo dużego backfillu.
2. **Demon czasu rzeczywistego (`daemon/agent_watcher.py`, ciągły)** — pollowanie plików transkryptów co 5s, buforowanie w lokalnym SQLite WAL (`~/.local/share/brain-llm/local_buffer.db`) i wysyłka przez HTTP do `POST /api/v1/ingest` na `brain-db`. Embedding liczony jest **po stronie serwera** (nie potrzeba lokalnej Ollamy). To jedyny mechanizm, który dowozi *nowe* wiadomości bez ręcznego importu.

**Demon musi działać osobno na każdej maszynie, na której pracujesz z agentami:**

| Maszyna | Mechanizm | Status |
|---|---|---|
| `rog` | systemd user unit `llm-agent-watcher` | `systemctl --user status llm-agent-watcher` |
| `mac` | launchd agent `com.brain.llm-agent-watcher` | `launchctl list \| grep llm-agent-watcher` |

Instalacja demona na nowej maszynie (macOS):
```bash
cp apps/llm-archive/daemon/com.brain.llm-agent-watcher.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.brain.llm-agent-watcher.plist
```
Linux (systemd user unit): `apps/llm-archive/daemon/llm-agent-watcher.service` → `~/.config/systemd/user/`, potem `systemctl --user enable --now llm-agent-watcher`.

Diagnostyka: logi (`journalctl --user -u llm-agent-watcher` na Linuksie, `~/.local/share/brain-llm/watcher.err` na macOS) i stan bufora (`sqlite3 ~/.local/share/brain-llm/local_buffer.db "SELECT platform, synced, retry_count, last_error FROM pending_sessions WHERE synced=0;"`) pokazują dokładnie, które sesje jeszcze czekają na wysyłkę i dlaczego.

---

## 🧩 Wtyczka do Przeglądarki (`apps/llm-archive/extension`)

Osobny mechanizm od demona agentów powyżej — obsługuje platformy webowe/mobilne (ChatGPT, Claude, Gemini, Grok, DeepSeek), nie Antigravity/Claude Code.

1. Otwórz w przeglądarce (Chrome, Brave, Edge, Zen) stronę rozszerzeń (`chrome://extensions`).
2. Włącz **Tryb dewelopera (Developer mode)**.
3. Kliknij **Załaduj rozpakowane (Load unpacked)** i wybierz folder `apps/llm-archive/extension` w swoim lokalnym katalogu repo.
4. W popupie wtyczki wpisz adres backendu ingest: `http://localhost:8080/api/v1/ingest`.
5. Kliknij **⚡ Synchronizuj Teraz (Delta)** lub **📥 Pełny Eksport Historii (Wstecz)**.

## Dostep do moich danych

- ChatGPT: https://chatgpt.com/#settings/DataControls
- Gemini: https://takeout.google.com/?utm_source=gemini
- Claude: https://platform.claude.com/settings/privacy
- Claude: https://claude.ai/new#settings/data-privacy-controls
- Grok: https://accounts.x.ai/account?redirect=grok-com&theme=dark#data
- Perplexity: https://www.perplexity.ai/settings/account



```bash
psql -h localhost -U postgres -d brain_knowledge
```

---

## 🔌 MCP dla agentów (HTTP)

Archiwum wystawia MCP (JSON-RPC po HTTP) pod `http://localhost:3001/api/v1/mcp`. Narzędzia: `search_llm_history`, `get_llm_conversation`, `get_llm_stats`.

| Agent | Konfiguracja |
|---|---|
| Claude Code | `claude mcp add --transport http -s user llm-archive http://localhost:3001/api/v1/mcp` |
| Codex | `~/.codex/config.toml`: `[mcp_servers.llm-archive]` + `url = "http://localhost:3001/api/v1/mcp"` |
| Antigravity | `~/.gemini/{antigravity,antigravity-ide,config}/mcp_config.json`: `"llm-archive": {"serverUrl": "http://localhost:3001/api/v1/mcp"}` |
| opencode | `~/.config/opencode/opencode.jsonc`: `"mcp": {"llm-archive": {"type": "remote", "url": "http://localhost:3001/api/v1/mcp", "enabled": true}}` |
| Zed | `~/.config/zed/settings.json`: `"context_servers": {"llm-archive": {"url": "http://localhost:3001/api/v1/mcp"}}` |

## Inteligentne Nadawanie Tytułów (Auto-Titler)

Lokalne sesje agentów programistycznych (Claude Code, Antigravity) często posiadają nieczytelne lub surowe tytuły utworzone z pierwszego zapytania użytkownika (np. `"kurwa"`, `"zobacz"`, `"pnpm exec..."`).

`AutoTitler` analizuje wypowiedzi użytkownika z całej konwersacji i nadaje precyzyjny tytuł:
- **Tło / Worker**: W API działa proces w tle (`ENABLE_AUTO_TITLER=true`), który co `TITLER_INTERVAL` (domyślnie 10 min) wyszukuje konwersacje nieaktualizowane od minimum 2 godzin (`updated_at < NOW() - INTERVAL '2 hours'`) i wymagające nadania tytułu (`title_generated_at IS NULL OR title_generated_at < updated_at`).
- **Próbkowanie tematyczne**: Wybiera do 12 reprezentatywnych wypowiedzi użytkownika (początek, środek, koniec), do 600 znaków każda, dając modelowi pełne pokrycie tematyczne bez przepełniania kontekstu.
- **Model**: Wykorzystuje model `qwen2.5:7b` działający lokalnie na ROG (RTX 4090).
- **Archiwum**: Zachowuje surowy tytuł w kolumnie `original_title`, aktualizuje `title` oraz `title_generated_at`, a także aktualizuje plik w `doc/llm-archive/` wg konwencji `YYYY-MM-DD_slug-tytulu_shortid.md` wraz z nagłówkiem i frontmatterem YAML.

Ręczne przeliczenie z CLI:
```bash
# Przelicz do 10 zakwalifikowanych konwersacji
brain-llm retitle

# Wymuś przeliczenie większej liczby konwersacji
brain-llm retitle --limit 20 --force
```

