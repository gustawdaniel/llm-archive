// Content Script for Grok (grok.com / x.com/i/grok)
// Automatically syncs conversations using Grok's REST API with differential catch-up.

(function () {
  const ext = globalThis.browser || globalThis.chrome;
  const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.1";

  function logDiagnostic(level, message, details = null) {
    const tag = `[Brain Grok v${VERSION} ${level.toUpperCase()}]`;
    const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
    if (details !== null && details !== undefined) {
      logFn(`${tag} ${message}`, details);
    } else {
      logFn(`${tag} ${message}`);
    }
    try {
      const p = ext.runtime.sendMessage({
        type: "DIAGNOSTIC_LOG",
        source: `grok.js (v${VERSION})`,
        level,
        message,
        details,
        timestamp: new Date().toISOString()
      });
      if (p && p.catch) p.catch(() => {});
    } catch (_) {}
  }

  logDiagnostic("info", `Grok content script active on ${window.location.hostname}${window.location.pathname}`);

  let liveGrokDebounce = null;
  let isSyncing = false;

  ext.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "TRIGGER_DELTA_SYNC") {
      runDeltaSync();
    } else if (msg.type === "TRIGGER_FULL_BACKFILL") {
      runFullBackfill((progress) => {
        ext.runtime.sendMessage({ type: "BACKFILL_PROGRESS", progress });
      });
    }
  });

  // 1. Intercept live completion on grok.com / x.com
  function injectGrokInterceptor() {
    try {
      const script = document.createElement("script");
      script.textContent = `
        (function() {
          const origFetch = window.fetch;
          window.fetch = async function(...args) {
            const response = await origFetch.apply(this, args);
            try {
              const url = (args[0] && args[0].url) || args[0] || "";
              if (typeof url === "string" && (url.includes("/rest/app-chat/conversations") || url.includes("/chat/completion") || url.includes("/responses"))) {
                window.postMessage({ type: "GROK_ACTIVITY_COMPLETED" }, "*");
              }
            } catch (_) {}
            return response;
          };
        })();
      `;
      (document.head || document.documentElement).appendChild(script);
      script.remove();
    } catch (e) {
      logDiagnostic("warn", "Grok interceptor injection error", { error: e.message });
    }
  }

  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "GROK_ACTIVITY_COMPLETED") {
      clearTimeout(liveGrokDebounce);
      liveGrokDebounce = setTimeout(async () => {
        logDiagnostic("debug", "Grok live activity detected, running delta sync...");
        await runDeltaSync();
      }, 3000);
    }
  });

  injectGrokInterceptor();

  // 2. Fetch conversation responses from Grok REST API
  async function fetchConversationResponses(convId) {
    const url = `/rest/app-chat/conversations/${convId}/responses`;
    const resp = await fetch(url, { credentials: "include" });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} fetching responses for ${convId}`);
    }
    return await resp.json();
  }

  // 3. Differential sync: checks Brain DB status map and ingests missing/updated conversations
  async function runDeltaSync() {
    if (isSyncing) {
      logDiagnostic("debug", "Delta sync already running, skipping parallel execution.");
      return;
    }
    isSyncing = true;

    try {
      logDiagnostic("info", "Querying recent conversations from Grok API...");
      const resp = await fetch("/rest/app-chat/conversations?pageSize=60", {
        credentials: "include"
      });
      if (!resp.ok) {
        logDiagnostic("warn", `Failed to list Grok conversations: HTTP ${resp.status}`);
        return;
      }

      const data = await resp.json();
      const items = data.conversations || data.items || (Array.isArray(data) ? data : []);
      if (!items.length) {
        logDiagnostic("debug", "No Grok conversations returned from list endpoint.");
        return;
      }

      // Query Brain backend for sync status map of Grok chats
      let dbStatus = {};
      try {
        const statusRes = await new Promise((resolve) => {
          ext.runtime.sendMessage(
            { type: "GET_SYNC_STATUS", platform: "grok", limit: 60 },
            (res) => resolve(res)
          );
        });
        dbStatus = (statusRes && (statusRes.result?.conversations || statusRes.conversations)) || {};
      } catch (err) {
        logDiagnostic("warn", "Could not fetch DB sync status, falling back to local cache", { error: err.message });
      }

      // Read persistent local cache
      const cacheData = await ext.storage.local.get(["synced_cache_grok"]);
      const localCache = cacheData.synced_cache_grok || {};

      let syncedCount = 0;
      let consecutiveErrors = 0;
      const MAX_CONSECUTIVE_ERRORS = 3;

      for (const item of items) {
        const convId = item.conversationId || item.id || item.conversation_id;
        if (!convId) continue;

        const title = item.title || "Rozmowa Grok";
        const modifyTimeStr = item.modifyTime || item.updated_at || item.createTime || item.created_at || new Date().toISOString();
        const itemModifyTs = new Date(modifyTimeStr).getTime();

        // 1. Check local persistent cache
        const localRecord = localCache[convId];
        if (localRecord && localRecord.modifyTime) {
          const localTs = new Date(localRecord.modifyTime).getTime();
          if (itemModifyTs <= localTs + 2000) {
            continue; // Already processed locally!
          }
        }

        // 2. Check remote DB status
        const dbRecord = dbStatus[convId];
        if (dbRecord && dbRecord.updated_at) {
          const dbUpdateTs = new Date(dbRecord.updated_at).getTime();
          if (itemModifyTs <= dbUpdateTs + 2000) {
            localCache[convId] = {
              messageCount: dbRecord.message_count || 0,
              modifyTime: dbRecord.updated_at,
              syncedAt: Date.now()
            };
            continue; // Already in DB!
          }
        }

        logDiagnostic("info", `Syncing Grok conversation: '${title}' (${convId})`);

        try {
          const responsesData = await fetchConversationResponses(convId);
          const rawResponses = responsesData.responses || [];

          if (rawResponses.length === 0) {
            logDiagnostic("debug", `No responses in Grok chat '${title}' (${convId}), skipping ingest.`);
            continue;
          }

          const payload = {
            conversation_id: convId,
            title: title,
            model: "grok-3",
            conversation: {
              conversationId: convId,
              title: title,
              createTime: item.createTime,
              modifyTime: item.modifyTime
            },
            responses: rawResponses.map((r) => ({
              responseId: r.responseId,
              sender: r.sender,
              message: r.message,
              createTime: r.createTime,
              parentResponseId: r.parentResponseId
            }))
          };

          const ingestRes = await new Promise((resolve) => {
            ext.runtime.sendMessage(
              {
                type: "INGEST_PAYLOAD",
                platform: "grok",
                payload: payload,
                metadata: { device: "browser-extension", sync_method: "rest_api" }
              },
              (res) => resolve(res)
            );
          });

          if (ingestRes && ingestRes.status === "success") {
            logDiagnostic("success", `Synced Grok chat: '${title}' (${convId})`);
            syncedCount++;
            consecutiveErrors = 0;
            localCache[convId] = {
              messageCount: rawResponses.length,
              modifyTime: modifyTimeStr,
              syncedAt: Date.now()
            };
            await ext.storage.local.set({ synced_cache_grok: localCache });
          } else {
            consecutiveErrors++;
            logDiagnostic("warn", `Ingest error for '${title}': ${ingestRes?.message || "Unknown error"}`);
            if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
              logDiagnostic("warn", `⏸️ Wstrzymano synchronizację po ${consecutiveErrors} kolejnych błędach. Sprawdź połączenie z serwerem lub uprawnienia wtyczki.`);
              break;
            }
          }

          // Polite rate-limiting between chats
          await new Promise((r) => setTimeout(r, 600));
        } catch (fetchErr) {
          consecutiveErrors++;
          logDiagnostic("error", `Failed fetching messages for Grok chat ${convId}`, { error: fetchErr.message });
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            logDiagnostic("warn", `⏸️ Wstrzymano synchronizację po ${consecutiveErrors} kolejnych błędach pobierania.`);
            break;
          }
        }
      }

      if (syncedCount > 0) {
        logDiagnostic("success", `Grok delta sync completed: ${syncedCount} conversations ingested.`);
      } else {
        logDiagnostic("debug", "Grok delta sync completed: All conversations already up-to-date.");
      }
    } catch (e) {
      logDiagnostic("error", "Grok delta sync error", { error: e.message });
    } finally {
      isSyncing = false;
    }
  }

  // 4. Full Backfill
  async function runFullBackfill(onProgress) {
    if (isSyncing) return;
    isSyncing = true;

    try {
      logDiagnostic("info", "Starting full Grok backfill...");
      const resp = await fetch("/rest/app-chat/conversations?pageSize=100", { credentials: "include" });
      if (!resp.ok) return;

      const data = await resp.json();
      const items = data.conversations || data.items || [];
      let count = 0;

      for (const item of items) {
        const convId = item.conversationId || item.id || item.conversation_id;
        if (!convId) continue;

        try {
          const responsesData = await fetchConversationResponses(convId);
          const rawResponses = responsesData.responses || [];

          if (rawResponses.length > 0) {
            const payload = {
              conversation_id: convId,
              title: item.title || "Rozmowa Grok",
              model: "grok-3",
              conversation: {
                conversationId: convId,
                title: item.title || "Rozmowa Grok",
                createTime: item.createTime,
                modifyTime: item.modifyTime
              },
              responses: rawResponses.map((r) => ({
                responseId: r.responseId,
                sender: r.sender,
                message: r.message,
                createTime: r.createTime,
                parentResponseId: r.parentResponseId
              }))
            };

            ext.runtime.sendMessage({
              type: "INGEST_PAYLOAD",
              platform: "grok",
              payload: payload,
              metadata: { device: "browser-extension", sync_method: "backfill" }
            });
          }
        } catch (e) {
          logDiagnostic("warn", `Backfill failed for ${convId}`, { error: e.message });
        }

        count++;
        if (onProgress) onProgress({ current: count, total: items.length });
        await new Promise((r) => setTimeout(r, 800));
      }

      logDiagnostic("success", `Full Grok backfill completed: processed ${count} conversations.`);
    } catch (e) {
      logDiagnostic("error", "Grok backfill error", { error: e.message });
    } finally {
      isSyncing = false;
    }
  }

  // Initial trigger after page has stabilized
  setTimeout(runDeltaSync, 4000);
})();
