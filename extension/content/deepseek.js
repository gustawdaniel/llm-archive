// Content Script for DeepSeek (chat.deepseek.com)
// Supports Live SSE Interception, Token Bearer Auth, DOM Sidebar Scraping, and Differential Sync.

(function () {
  const ext = globalThis.browser || globalThis.chrome;
  const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.11";

  function logDiagnostic(level, message, details = null) {
    const tag = `[Brain DeepSeek v${VERSION} ${level.toUpperCase()}]`;
    const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
    if (details !== null && details !== undefined) {
      logFn(`${tag} ${message}`, details);
    } else {
      logFn(`${tag} ${message}`);
    }
    const record = {
      source: `deepseek.js (v${VERSION})`,
      level,
      message,
      details,
      timestamp: new Date().toISOString()
    };
    try {
      const p = ext.runtime.sendMessage({
        type: "DIAGNOSTIC_LOG",
        ...record
      });
      if (p && typeof p.catch === "function") {
        p.catch((err) => {
          if (!err?.message?.includes("Extension context invalidated")) {
            console.debug("[Brain Log Relay]", err?.message || err);
          }
        });
      }
    } catch (err) {
      if (!err?.message?.includes("Extension context invalidated")) {
        console.debug("[Brain Log Relay]", err?.message || err);
      }
    }
  }

  logDiagnostic("info", `DeepSeek content script loaded on ${window.location.hostname}${window.location.pathname}`);

  let isSyncing = false;
  let lastUrl = window.location.href;

  function checkUrlChange() {
    const currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
      lastUrl = currentUrl;
      logDiagnostic("info", `DeepSeek URL changed to ${window.location.pathname}`);
      setTimeout(runDeltaSync, 1000);
    }
  }

  const origPushState = history.pushState;
  if (origPushState) {
    history.pushState = function (...args) {
      const res = origPushState.apply(this, args);
      setTimeout(checkUrlChange, 100);
      return res;
    };
  }
  const origReplaceState = history.replaceState;
  if (origReplaceState) {
    history.replaceState = function (...args) {
      const res = origReplaceState.apply(this, args);
      setTimeout(checkUrlChange, 100);
      return res;
    };
  }
  window.addEventListener("popstate", () => setTimeout(checkUrlChange, 100));
  setInterval(checkUrlChange, 1500);

  // 1. Listen for background delta sync triggers
  ext.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "TRIGGER_DELTA_SYNC") {
      runDeltaSync();
    } else if (msg.type === "TRIGGER_FULL_BACKFILL") {
      runFullBackfill();
    }
  });

  // 3. Obtain authentication token from localStorage
  function getAuthToken() {
    try {
      const userToken = localStorage.getItem("userToken");
      if (!userToken) return null;
      return JSON.parse(userToken).value;
    } catch (err) {
      logDiagnostic("warn", "Failed parsing DeepSeek userToken from localStorage", { error: err.message });
      return null;
    }
  }

  // 4. Authenticated API fetch
  async function apiFetch(url) {
    const token = getAuthToken();
    const headers = {
      "Accept": "application/json",
      "Content-Type": "application/json"
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const resp = await fetch(url, { headers, credentials: "include" });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} for ${url}`);
    }

    const json = await resp.json();
    if (json.code !== 0 && json.data?.biz_code !== 0) {
      throw new Error(`DeepSeek API error: ${json.msg || json.data?.biz_msg || "Unknown error"}`);
    }

    return json.data?.biz_data || json.data || json;
  }

  // 5. Scrape visible conversation list from the sidebar DOM
  function scrapeConversationsFromDOM() {
    const sessions = [];
    const seenIds = new Set();
    const links = document.querySelectorAll('a[href*="/a/chat/s/"]');

    for (const link of links) {
      const href = link.getAttribute("href") || "";
      const match = href.match(/\/a\/chat\/s\/([a-f0-9-]+)/);
      if (!match) continue;

      const id = match[1];
      if (seenIds.has(id) || id === "new") continue;
      seenIds.add(id);

      let title = "";
      const titleEl = link.querySelector('[class*="title"], [class*="name"], [class*="text"]');
      if (titleEl) {
        title = titleEl.textContent.trim();
      }
      if (!title) {
        title = (link.textContent || "").replace(/[\u{1F4CC}\u{2B50}]/gu, "").trim();
      }
      if (!title || title.length < 2) {
        const container = link.closest('[class*="item"], [class*="conversation"], [class*="session"], [class*="chat"]');
        if (container) {
          const text = container.textContent.replace(/[\u{1F4CC}\u{2B50}]/gu, "").trim();
          if (text.length > 2) title = text;
        }
      }

      sessions.push({
        id,
        title: title || `DeepSeek ${id.substring(0, 8)}`,
        updated_at: null,
        from_dom: true
      });
    }

    return sessions;
  }

  // 6. Fetch full message history for a conversation
  async function fetchConversation(sessionId) {
    return apiFetch(`/api/v0/chat/history_messages?chat_session_id=${sessionId}&cache_version=0`);
  }

  // 7. Differential sync: compares DeepSeek conversations with Brain DB
  async function runDeltaSync() {
    if (isSyncing) {
      logDiagnostic("debug", "DeepSeek delta sync already running, skipping parallel execution.");
      return;
    }
    isSyncing = true;

    try {
      logDiagnostic("info", "Querying recent DeepSeek conversations (API + DOM)...");

      // Strategy 1: REST API fetch
      let apiSessions = [];
      try {
        const bizData = await apiFetch("/api/v0/chat_session/fetch_page");
        apiSessions = bizData.chat_sessions || [];
      } catch (err) {
        logDiagnostic("warn", "DeepSeek API fetch_page failed, falling back to DOM scraping", { error: err.message });
      }

      // Strategy 2: DOM scraping fallback/merge
      const domSessions = scrapeConversationsFromDOM();
      const sessionsMap = new Map();

      for (const s of apiSessions) {
        sessionsMap.set(s.id, {
          id: s.id,
          title: s.title || s.name || `Rozmowa ${s.id.substring(0, 8)}`,
          updated_at: s.updated_at || s.inserted_at || new Date().toISOString()
        });
      }
      for (const s of domSessions) {
        if (!sessionsMap.has(s.id)) {
          sessionsMap.set(s.id, s);
        }
      }

      const sessions = Array.from(sessionsMap.values());
      if (sessions.length === 0) {
        logDiagnostic("debug", "No DeepSeek conversations found from API or DOM.");
        return;
      }

      // Query Brain DB for sync status map
      let dbStatus = {};
      try {
        const statusRes = await new Promise((resolve) => {
          ext.runtime.sendMessage(
            { type: "GET_SYNC_STATUS", platform: "deepseek", limit: 60 },
            (res) => resolve(res)
          );
        });
        dbStatus = (statusRes && (statusRes.result?.conversations || statusRes.conversations)) || {};
      } catch (err) {
        logDiagnostic("warn", "Could not fetch DeepSeek DB status, falling back to local cache", { error: err.message });
      }

      // Read persistent local cache
      const cacheData = await ext.storage.local.get(["synced_cache_deepseek"]);
      const localCache = cacheData.synced_cache_deepseek || {};

      let syncedCount = 0;
      let consecutiveErrors = 0;
      const MAX_CONSECUTIVE_ERRORS = 3;

      for (const item of sessions) {
        const convId = item.id;
        if (!convId) continue;

        const title = item.title || "Rozmowa DeepSeek";
        const dbRecord = dbStatus[convId];
        const localRecord = localCache[convId];

        // If discovered solely from DOM (no explicit API timestamp) and already present in DB or cache, skip
        if (item.from_dom && (dbRecord || localRecord)) {
          continue;
        }

        const itemModifyTs = new Date(item.updated_at || new Date().toISOString()).getTime();

        // 1. Check local persistent cache
        if (localRecord && localRecord.updated_at) {
          const localTs = new Date(localRecord.updated_at).getTime();
          if (itemModifyTs <= localTs + 2000) {
            continue; // Already processed locally
          }
        }

        // 2. Check remote DB status
        if (dbRecord && dbRecord.updated_at) {
          const dbUpdateTs = new Date(dbRecord.updated_at).getTime();
          if (itemModifyTs <= dbUpdateTs + 2000) {
            localCache[convId] = {
              message_count: dbRecord.message_count || 0,
              updated_at: dbRecord.updated_at,
              synced_at: Date.now()
            };
            continue; // Already in DB
          }
        }

        logDiagnostic("info", `Syncing DeepSeek conversation: '${title}' (${convId})`);

        try {
          const data = await fetchConversation(convId);
          const messages = data.chat_messages || [];

          if (messages.length === 0) {
            logDiagnostic("debug", `No messages found in DeepSeek chat '${title}' (${convId}), skipping ingest.`);
            continue;
          }

          // Safeguard: Check that at least one message has actual content (top-level or in fragments)
          const hasNonEmptyContent = messages.some(m => {
            if (!m) return false;
            if ((m.content || m.text || m.message || "").trim().length > 0) return true;
            if ((m.thinking_content || m.reasoning_content || "").trim().length > 0) return true;
            if (Array.isArray(m.fragments) && m.fragments.length > 0) {
              return m.fragments.some(f => (f.content || f.text || "").trim().length > 0 || (f.results && f.results.length > 0));
            }
            return false;
          });

          if (!hasNonEmptyContent) {
            logDiagnostic("error", `⚠️ ODRZUCONO: Wszystkie ${messages.length} wiadomości w rozmowie '${title}' (${convId}) są puste! Anulowano wysyłkę.`);
            consecutiveErrors++;
            continue;
          }

          const payload = {
            chat_session: data.chat_session || { id: convId, title: title },
            chat_messages: messages
          };

          const ingestRes = await new Promise((resolve) => {
            ext.runtime.sendMessage(
              {
                type: "INGEST_PAYLOAD",
                platform: "deepseek",
                payload: payload,
                metadata: {
                  conversation_id: convId,
                  title: title,
                  device: "browser-extension",
                  sync_method: "rest_api"
                }
              },
              (res) => resolve(res)
            );
          });

          if (ingestRes && ingestRes.status === "success") {
            logDiagnostic("success", `Synced DeepSeek chat: '${title}' (${convId})`);
            syncedCount++;
            consecutiveErrors = 0;
            localCache[convId] = {
              message_count: messages.length,
              updated_at: item.updated_at,
              synced_at: Date.now()
            };
            await ext.storage.local.set({ synced_cache_deepseek: localCache });
          } else {
            consecutiveErrors++;
            logDiagnostic("warn", `Ingest error for DeepSeek '${title}': ${ingestRes?.message || "Unknown error"}`);
            if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
              logDiagnostic("warn", `⏸️ Wstrzymano synchronizację DeepSeek po ${consecutiveErrors} błędach.`);
              break;
            }
          }

          // Polite rate limiting between sessions
          await new Promise((r) => setTimeout(r, 1200));
        } catch (fetchErr) {
          consecutiveErrors++;
          logDiagnostic("error", `Failed fetching messages for DeepSeek chat ${convId}`, { error: fetchErr.message });
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            logDiagnostic("warn", `⏸️ Wstrzymano synchronizację po ${consecutiveErrors} błędach.`);
            break;
          }
        }
      }

      if (syncedCount > 0) {
        logDiagnostic("success", `DeepSeek delta sync completed: ${syncedCount} conversations ingested.`);
      } else {
        logDiagnostic("debug", "DeepSeek delta sync completed: All conversations up-to-date.");
      }
    } catch (e) {
      logDiagnostic("error", "DeepSeek delta sync error", { error: e.message });
    } finally {
      isSyncing = false;
    }
  }

  // 8. Full Backfill
  async function runFullBackfill() {
    logDiagnostic("info", "Starting DeepSeek Full Backfill...");
    await runDeltaSync();
  }

  // Initial delta scan 3 seconds after page load
  setTimeout(runDeltaSync, 3000);
})();
