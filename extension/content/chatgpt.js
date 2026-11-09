// Content Script for ChatGPT (chatgpt.com / chat.openai.com)
// Supports Session Bearer Extraction, REST API listing, Sidebar DOM fallback,
// Active Chat Real-Time Sync, SPA Navigation Tracking, DOM Mutation Detection, and Differential Sync.

(function () {
  const ext = globalThis.browser || globalThis.chrome;
  const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.19";

  // 1. Diagnostic logger: Console + Extension Background + Direct HTTP to host rog (127.0.0.1:3040)
  function logDiagnostic(level, message, details = null) {
    const tag = `[Brain ChatGPT v${VERSION} ${level.toUpperCase()}]`;
    const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
    if (details !== null && details !== undefined) {
      logFn(`${tag} ${message}`, details);
    } else {
      logFn(`${tag} ${message}`);
    }

    const record = {
      source: `chatgpt.js (v${VERSION})`,
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
      if (p && p.catch) p.catch(() => {});
    } catch (_) {}
  }

  logDiagnostic("info", `ChatGPT content script loaded on ${window.location.hostname}${window.location.pathname}`);

  let isSyncing = false;
  let activeSyncLock = false;
  let cachedToken = null;
  let tokenExpiry = 0;
  let lastActiveSyncedId = null;
  let lastActiveMsgCount = 0;
  let lastUrl = window.location.href;

  // 2. Extract active conversation ID from URL path (e.g. /c/6ac14ca5-... or /chat/...)
  function getActiveConversationId() {
    const match = window.location.pathname.match(/\/(?:c|chat)\/([a-zA-Z0-9-]+)/);
    if (!match) return null;
    const id = match[1];
    if (["new", "share", "admin", "settings", "g"].includes(id.toLowerCase())) {
      return null;
    }
    return id;
  }

  // 3. Obtain session token (Bearer token from NextAuth /api/auth/session)
  async function getSessionToken(forceRefresh = false) {
    const now = Date.now();
    if (!forceRefresh && cachedToken && tokenExpiry > now + 60000) {
      return cachedToken;
    }

    try {
      const resp = await fetch("/api/auth/session", { credentials: "include" });
      if (!resp.ok) {
        logDiagnostic("warn", `Session check returned HTTP ${resp.status}`);
        return null;
      }
      const data = await resp.json();
      if (!data.accessToken) {
        logDiagnostic("warn", "No accessToken found in session response.");
        return null;
      }

      cachedToken = data.accessToken;
      tokenExpiry = data.expires ? new Date(data.expires).getTime() : now + 3600000;
      return cachedToken;
    } catch (e) {
      logDiagnostic("error", "Error fetching session token", { error: e.message });
      return null;
    }
  }

  // 4. Fetch full conversation payload
  async function fetchConversation(convId, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const resp = await fetch(`/backend-api/conversation/${convId}`, {
      headers,
      credentials: "include"
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} fetching conversation ${convId}`);
    }

    return await resp.json();
  }

  // 5. Detect if ChatGPT is currently generating/streaming response
  function isGeneratingResponse() {
    // A. Stop button present
    const stopBtn = document.querySelector(
      'button[data-testid="stop-button"], ' +
      'button[data-testid="fruitjuice-stop-button"], ' +
      'button[aria-label="Stop generating"], ' +
      'button[aria-label="Stop streaming"], ' +
      'button[aria-label="Zatrzymaj generowanie"], ' +
      'button[aria-label="Zatrzymaj"]'
    );
    if (stopBtn) return true;

    // B. Streaming DOM indicator
    const streamingEl = document.querySelector('.result-streaming, [data-is-streaming="true"], span.streaming-cursor');
    if (streamingEl) return true;

    return false;
  }

  // 6. Schedule post-generation sync when response completes
  let generationPollingTimer = null;
  function schedulePostGenerationSync() {
    if (generationPollingTimer) return;
    logDiagnostic("debug", "Waiting for ChatGPT generation to complete...");
    generationPollingTimer = setInterval(() => {
      if (!isGeneratingResponse()) {
        clearInterval(generationPollingTimer);
        generationPollingTimer = null;
        logDiagnostic("info", "ChatGPT generation completed! Triggering sync in 1.8s...");
        setTimeout(() => {
          syncActiveChat("stream_finished");
          runDeltaSync();
        }, 1800);
      }
    }, 800);
  }

  // 7. Synchronize the active conversation in real time
  async function syncActiveChat(reason = "realtime") {
    const convId = getActiveConversationId();
    if (!convId) {
      logDiagnostic("debug", `syncActiveChat skipped: no active conversation ID in URL (${window.location.pathname})`);
      return;
    }

    if (activeSyncLock) {
      logDiagnostic("debug", `syncActiveChat already in progress for ${convId}, skipping parallel execution.`);
      return;
    }

    if (isGeneratingResponse()) {
      logDiagnostic("debug", `ChatGPT is currently generating response for ${convId}, delaying sync...`);
      schedulePostGenerationSync();
      return;
    }

    activeSyncLock = true;
    try {
      logDiagnostic("debug", `Checking active conversation ${convId} (trigger: ${reason})...`);
      const token = await getSessionToken();
      if (!token) {
        logDiagnostic("warn", "Cannot sync active conversation: missing session token.");
        return;
      }

      const fullData = await fetchConversation(convId, token);
      const mapping = fullData.mapping || {};
      const mappingKeys = Object.keys(mapping);
      let msgCount = 0;
      let hasContent = false;

      for (const k of mappingKeys) {
        const m = mapping[k]?.message;
        if (m) {
          msgCount++;
          const parts = m.content?.parts || [];
          for (const p of parts) {
            if (typeof p === "string" && p.trim().length > 0) hasContent = true;
          }
        }
      }

      if (msgCount === 0 || !hasContent) {
        logDiagnostic("debug", `Active conversation ${convId} has no messages yet.`);
        return;
      }

      // Check local cache
      const cacheData = await ext.storage.local.get(["synced_cache_chatgpt"]);
      const localCache = cacheData.synced_cache_chatgpt || {};
      const cached = localCache[convId];

      const updateTimeStr = fullData.update_time
        ? new Date(fullData.update_time * 1000).toISOString()
        : (fullData.create_time ? new Date(fullData.create_time * 1000).toISOString() : new Date().toISOString());

      if (cached && cached.message_count === msgCount && lastActiveSyncedId === convId) {
        logDiagnostic("debug", `Active conversation ${convId} unchanged (${msgCount} msgs), skipping ingest.`);
        return;
      }

      const title = fullData.title || (document.title || "").replace(/\s*\|\s*ChatGPT$/i, "").trim() || `Rozmowa ${convId.substring(0, 8)}`;
      logDiagnostic("info", `Syncing active ChatGPT conversation: '${title}' (${convId}, ${msgCount} msgs, trigger: ${reason})`);

      const ingestRes = await new Promise((resolve) => {
        ext.runtime.sendMessage(
          {
            type: "INGEST_PAYLOAD",
            platform: "chatgpt",
            payload: fullData,
            metadata: {
              conversation_id: convId,
              title: title,
              device: "browser-extension",
              sync_method: reason
            }
          },
          (res) => resolve(res)
        );
      });

      if (ingestRes && ingestRes.status === "success") {
        logDiagnostic("success", `✅ Active chat synced: '${title}' (${convId}, ${msgCount} msgs)`);
        lastActiveSyncedId = convId;
        lastActiveMsgCount = msgCount;
        localCache[convId] = {
          message_count: msgCount,
          updated_at: updateTimeStr,
          synced_at: Date.now()
        };
        await ext.storage.local.set({ synced_cache_chatgpt: localCache });
      } else {
        logDiagnostic("warn", `Ingest error for active chat ${convId}: ${ingestRes?.message || "Unknown error"}`);
      }
    } catch (err) {
      logDiagnostic("error", `Failed syncing active chat ${convId}`, { error: err.message });
    } finally {
      activeSyncLock = false;
    }
  }

  // 8. Scan sidebar DOM as complementary fallback
  function scanSidebarDOM() {
    const selectors = [
      'nav a[href*="/c/"]',
      'aside a[href*="/c/"]',
      '[role="navigation"] a[href*="/c/"]',
      'a[href*="/c/"]',
      'nav a[href*="/chat/"]'
    ];

    let links = [];
    for (const sel of selectors) {
      links = Array.from(document.querySelectorAll(sel));
      if (links.length > 0) break;
    }

    const items = [];
    const seen = new Set();
    for (const link of links) {
      const href = link.getAttribute("href") || "";
      const match = href.match(/\/(?:c|chat)\/([a-zA-Z0-9-]+)/);
      if (!match) continue;

      const convId = match[1];
      if (seen.has(convId)) continue;
      seen.add(convId);

      let title = "";
      const titleDiv = link.querySelector("div[title], .relative.grow, div.truncate");
      if (titleDiv) title = titleDiv.getAttribute("title") || titleDiv.innerText || "";
      if (!title) {
        title = (link.innerText || link.textContent || "")
          .split("\n")[0]
          .replace(/\b(delete|rename|archive|share|menu|more)\b/gi, "")
          .trim();
      }

      items.push({
        id: convId,
        title: title || `Rozmowa ${convId.substring(0, 8)}`,
        create_time: null,
        update_time: null,
        from_dom: true
      });
    }

    return items;
  }

  // 9. Differential sync: compares ChatGPT conversations against Brain DB and local cache
  async function runDeltaSync() {
    if (isSyncing) {
      logDiagnostic("debug", "Delta sync already running, skipping parallel execution.");
      return;
    }
    isSyncing = true;

    try {
      const token = await getSessionToken();
      if (!token) {
        logDiagnostic("warn", "Cannot run delta sync: missing session token (not logged in?).");
        return;
      }

      logDiagnostic("info", "Querying recent conversations from ChatGPT API...");
      const headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      };

      let apiItems = [];
      try {
        const resp = await fetch("/backend-api/conversations?offset=0&limit=25&order=updated", {
          headers,
          credentials: "include"
        });
        if (resp.ok) {
          const data = await resp.json();
          apiItems = data.items || [];
        } else {
          logDiagnostic("warn", `ChatGPT list endpoint returned HTTP ${resp.status}`);
        }
      } catch (apiErr) {
        logDiagnostic("warn", "Failed calling backend-api/conversations", { error: apiErr.message });
      }

      // Merge with visible sidebar DOM links
      const domItems = scanSidebarDOM();
      const candidatesMap = new Map();

      for (const item of apiItems) {
        candidatesMap.set(item.id, item);
      }
      for (const item of domItems) {
        if (!candidatesMap.has(item.id)) {
          candidatesMap.set(item.id, item);
        }
      }

      // Always include currently active conversation from URL
      const activeId = getActiveConversationId();
      if (activeId && !candidatesMap.has(activeId)) {
        candidatesMap.set(activeId, {
          id: activeId,
          title: (document.title || "").replace(/\s*\|\s*ChatGPT$/i, "").trim() || `Rozmowa ${activeId.substring(0, 8)}`,
          create_time: null,
          update_time: null,
          from_active_url: true
        });
        logDiagnostic("debug", `Added active conversation from URL to sync candidates: ${activeId}`);
      }

      const items = Array.from(candidatesMap.values());
      if (items.length === 0) {
        logDiagnostic("debug", "No ChatGPT conversations found from API or DOM.");
        return;
      }

      // Query Brain DB for sync status map
      let dbStatus = {};
      try {
        const statusRes = await new Promise((resolve) => {
          ext.runtime.sendMessage(
            { type: "GET_SYNC_STATUS", platform: "chatgpt", limit: 60 },
            (res) => resolve(res)
          );
        });
        dbStatus = (statusRes && (statusRes.result?.conversations || statusRes.conversations)) || {};
      } catch (err) {
        logDiagnostic("warn", "Could not fetch DB sync status, falling back to local cache", { error: err.message });
      }

      // Read persistent local cache
      const cacheData = await ext.storage.local.get(["synced_cache_chatgpt"]);
      const localCache = cacheData.synced_cache_chatgpt || {};

      let syncedCount = 0;
      let consecutiveErrors = 0;
      const MAX_CONSECUTIVE_ERRORS = 3;

      for (const item of items) {
        const convId = item.id;
        if (!convId) continue;

        const title = item.title || "Rozmowa ChatGPT";
        const dbRecord = dbStatus[convId];
        const localRecord = localCache[convId];

        // If discovered solely from DOM (no explicit API timestamp) and already present, skip
        if (item.from_dom && !item.from_active_url && (dbRecord || localRecord)) {
          continue;
        }

        const updateTimeStr = item.update_time || item.create_time || new Date().toISOString();
        const itemUpdateTs = new Date(updateTimeStr).getTime();

        // 1. Check local persistent cache
        if (localRecord && localRecord.updated_at && !item.from_active_url) {
          const localTs = new Date(localRecord.updated_at).getTime();
          if (itemUpdateTs <= localTs + 2000) {
            continue; // Already processed locally
          }
        }

        // 2. Check remote DB status
        if (dbRecord && dbRecord.updated_at && !item.from_active_url) {
          const dbUpdateTs = new Date(dbRecord.updated_at).getTime();
          if (itemUpdateTs <= dbUpdateTs + 2000) {
            localCache[convId] = {
              message_count: dbRecord.message_count || 0,
              updated_at: dbRecord.updated_at,
              synced_at: Date.now()
            };
            continue; // Already in DB
          }
        }

        logDiagnostic("info", `Syncing ChatGPT conversation: '${title}' (${convId})`);

        try {
          const fullData = await fetchConversation(convId, token);
          const mappingKeys = Object.keys(fullData.mapping || {});
          let msgCount = 0;
          let hasContent = false;
          for (const k of mappingKeys) {
            const m = fullData.mapping[k]?.message;
            if (m) {
              msgCount++;
              const parts = m.content?.parts || [];
              for (const p of parts) {
                if (typeof p === "string" && p.trim().length > 0) hasContent = true;
              }
            }
          }

          if (msgCount === 0 || !hasContent) {
            logDiagnostic("warn", `⚠️ Wszystkie wiadomości w ChatGPT '${title}' (${convId}) są puste (lub brak wiadomości). Pomijam ingest.`);
            continue;
          }

          // If active chat and same count, skip
          if (item.from_active_url && localRecord && localRecord.message_count === msgCount) {
            continue;
          }

          const ingestRes = await new Promise((resolve) => {
            ext.runtime.sendMessage(
              {
                type: "INGEST_PAYLOAD",
                platform: "chatgpt",
                payload: fullData,
                metadata: {
                  conversation_id: convId,
                  title: fullData.title || title,
                  device: "browser-extension",
                  sync_method: "rest_api"
                }
              },
              (res) => resolve(res)
            );
          });

          if (ingestRes && ingestRes.status === "success") {
            logDiagnostic("success", `Synced ChatGPT chat: '${fullData.title || title}' (${convId})`);
            syncedCount++;
            consecutiveErrors = 0;
            localCache[convId] = {
              message_count: msgCount,
              updated_at: updateTimeStr,
              synced_at: Date.now()
            };
            await ext.storage.local.set({ synced_cache_chatgpt: localCache });
          } else {
            consecutiveErrors++;
            logDiagnostic("warn", `Ingest error for '${title}': ${ingestRes?.message || "Unknown error"}`);
            if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
              logDiagnostic("warn", `⏸️ Wstrzymano synchronizację ChatGPT po ${consecutiveErrors} kolejnych błędach.`);
              break;
            }
          }

          // Polite rate-limiting between conversations
          await new Promise((r) => setTimeout(r, 1200));
        } catch (fetchErr) {
          consecutiveErrors++;
          logDiagnostic("error", `Failed fetching messages for ChatGPT chat ${convId}`, { error: fetchErr.message });
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            logDiagnostic("warn", `⏸️ Wstrzymano synchronizację po ${consecutiveErrors} błędach pobierania.`);
            break;
          }
        }
      }

      if (syncedCount > 0) {
        logDiagnostic("success", `ChatGPT delta sync completed: ${syncedCount} conversations ingested.`);
      } else {
        logDiagnostic("debug", "ChatGPT delta sync completed: All conversations already up-to-date.");
      }
    } catch (e) {
      logDiagnostic("error", "ChatGPT delta sync error", { error: e.message });
    } finally {
      isSyncing = false;
    }
  }

  // 10. Full Historical Backfill
  async function runFullBackfill(onProgress) {
    const token = await getSessionToken();
    if (!token) {
      logDiagnostic("warn", "Cannot run full backfill: missing token.");
      return;
    }

    let offset = 0;
    const limit = 28;
    let totalSynced = 0;
    let hasMore = true;

    logDiagnostic("info", "Starting ChatGPT Full Historical Backfill...");

    while (hasMore) {
      try {
        const resp = await fetch(`/backend-api/conversations?offset=${offset}&limit=${limit}&order=updated`, {
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          credentials: "include"
        });

        if (!resp.ok) break;

        const data = await resp.json();
        const items = data.items || [];
        if (items.length === 0) {
          hasMore = false;
          break;
        }

        for (const item of items) {
          try {
            const fullData = await fetchConversation(item.id, token);
            await new Promise((resolve) => {
              ext.runtime.sendMessage({
                type: "INGEST_PAYLOAD",
                platform: "chatgpt",
                payload: fullData,
                metadata: {
                  conversation_id: item.id,
                  title: fullData.title || item.title,
                  device: "browser-extension",
                  sync_method: "backfill"
                }
              }, resolve);
            });
            totalSynced++;
            if (onProgress) onProgress({ totalSynced, currentTitle: item.title });
            await new Promise((r) => setTimeout(r, 1200));
          } catch (itemErr) {
            logDiagnostic("warn", `Backfill failed for ${item.id}`, { error: itemErr.message });
          }
        }

        offset += limit;
        if (items.length < limit) {
          hasMore = false;
        }
      } catch (e) {
        logDiagnostic("error", "Backfill iteration error", { error: e.message });
        break;
      }
    }
    logDiagnostic("success", `ChatGPT Full Backfill complete! Synced ${totalSynced} conversations.`);
  }

  // 11. SPA Navigation Tracking & History Hook
  function checkUrlChange() {
    const currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
      const oldUrl = lastUrl;
      lastUrl = currentUrl;
      const newConvId = getActiveConversationId();
      logDiagnostic("info", `SPA URL transition detected: ${new URL(oldUrl).pathname} -> ${new URL(currentUrl).pathname} (activeId: ${newConvId || "none"})`);
      if (newConvId) {
        setTimeout(() => syncActiveChat("spa_navigation"), 800);
        setTimeout(() => runDeltaSync(), 2500);
      }
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

  window.addEventListener("popstate", () => {
    setTimeout(checkUrlChange, 100);
  });

  setInterval(checkUrlChange, 1000);

  // 12. DOM MutationObserver: Stream start & finish detection (100% CSP safe)
  let wasGenerating = false;
  let streamEndDebounce = null;
  let domChangeDebounce = null;

  function onDomMutations() {
    const isGenerating = isGeneratingResponse();

    if (isGenerating && !wasGenerating) {
      wasGenerating = true;
      logDiagnostic("debug", "ChatGPT response stream started (stop button / indicator active)");
    } else if (!isGenerating && wasGenerating) {
      wasGenerating = false;
      logDiagnostic("info", "ChatGPT response stream finished! Triggering sync in 1.8s...");
      clearTimeout(streamEndDebounce);
      streamEndDebounce = setTimeout(() => {
        syncActiveChat("stream_finished");
        runDeltaSync();
      }, 1800);
      return;
    }

    // Debounced fallback: if DOM mutations occur in active chat but stop for 3.5s while idle, sync
    const activeId = getActiveConversationId();
    if (activeId && !isGenerating) {
      clearTimeout(domChangeDebounce);
      domChangeDebounce = setTimeout(() => {
        syncActiveChat("dom_settled");
      }, 3500);
    }
  }

  const observer = new MutationObserver(onDomMutations);
  function setupObserver() {
    const target = document.querySelector("main") || document.body;
    if (target) {
      observer.observe(target, { childList: true, subtree: true, characterData: false });
      logDiagnostic("debug", "Attached MutationObserver to main container");
    } else {
      setTimeout(setupObserver, 1000);
    }
  }
  setupObserver();

  // 13. User action listeners: click on links, prompt submission, tab visibility
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!target) return;

    // A. Conversation links
    const link = target.closest ? target.closest('a[href*="/c/"], a[href*="/chat/"]') : null;
    if (link) {
      const href = link.getAttribute("href") || link.href || "";
      const match = href.match(/\/(?:c|chat)\/([a-zA-Z0-9-]+)/);
      if (match) {
        logDiagnostic("debug", `User clicked conversation link: ${match[1]}`);
        setTimeout(() => syncActiveChat("user_click"), 1000);
      }
    }

    // B. Send button click
    const sendBtn = target.closest ? target.closest('button[data-testid="send-button"], button[aria-label="Send prompt"], button[aria-label="Wyślij wiadomość"]') : null;
    if (sendBtn) {
      logDiagnostic("debug", "User clicked Send button in ChatGPT");
      setTimeout(checkUrlChange, 300);
      setTimeout(checkUrlChange, 800);
      setTimeout(checkUrlChange, 1500);
    }
  }, true);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      const target = e.target;
      if (target && (target.id === "prompt-textarea" || target.matches?.('textarea, [contenteditable="true"]'))) {
        logDiagnostic("debug", "User pressed Enter in ChatGPT prompt box");
        setTimeout(checkUrlChange, 300);
        setTimeout(checkUrlChange, 800);
        setTimeout(checkUrlChange, 1500);
      }
    }
  }, true);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      logDiagnostic("debug", "Tab hidden, checking for uncommitted active chat sync...");
      syncActiveChat("tab_hidden");
    } else if (document.visibilityState === "visible") {
      logDiagnostic("debug", "Tab focused/visible, checking for updates...");
      checkUrlChange();
      setTimeout(() => syncActiveChat("tab_focused"), 600);
    }
  });

  // 14. Extension message listener
  ext.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "TRIGGER_DELTA_SYNC") {
      logDiagnostic("info", "Received TRIGGER_DELTA_SYNC from extension");
      syncActiveChat("manual_trigger");
      runDeltaSync();
    } else if (msg.type === "TRIGGER_FULL_BACKFILL") {
      logDiagnostic("info", "Received TRIGGER_FULL_BACKFILL from extension");
      runFullBackfill((progress) => {
        ext.runtime.sendMessage({ type: "BACKFILL_PROGRESS", progress });
      });
    }
  });

  // 15. Initial sync on page load
  setTimeout(() => {
    logDiagnostic("debug", "Running initial active chat sync (1.5s after load)...");
    syncActiveChat("initial_load");
  }, 1500);

  setTimeout(() => {
    logDiagnostic("debug", "Running initial delta sync (3.5s after load)...");
    runDeltaSync();
  }, 3500);
})();
