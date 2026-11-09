// Content Script for Claude (claude.ai)
// Supports Organization Resolution, REST API sync, Active Chat Real-Time Sync, and SPA Navigation.

(function () {
  const ext = globalThis.browser || globalThis.chrome;
  const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.19";

  function logDiagnostic(level, message, details = null) {
    const tag = `[Brain Claude v${VERSION} ${level.toUpperCase()}]`;
    const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
    if (details !== null && details !== undefined) {
      logFn(`${tag} ${message}`, details);
    } else {
      logFn(`${tag} ${message}`);
    }

    const record = {
      source: `claude.js (v${VERSION})`,
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

  logDiagnostic("info", `Claude content script loaded on ${window.location.hostname}${window.location.pathname}`);

  let lastUrl = window.location.href;
  let activeSyncLock = false;
  let lastActiveSyncedId = null;

  function getActiveConversationId() {
    const match = window.location.pathname.match(/\/chat\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  }

  ext.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "TRIGGER_DELTA_SYNC") {
      logDiagnostic("info", "Received TRIGGER_DELTA_SYNC for Claude");
      syncActiveChat("manual_trigger");
      runClaudeSync();
    } else if (msg.type === "TRIGGER_FULL_BACKFILL") {
      logDiagnostic("info", "Received TRIGGER_FULL_BACKFILL for Claude");
      runClaudeBackfill();
    }
  });

  async function getOrgId() {
    try {
      const resp = await fetch("/api/organizations", { credentials: "include" });
      if (!resp.ok) return null;
      const orgs = await resp.json();
      return orgs[0]?.uuid || null;
    } catch (e) {
      return null;
    }
  }

  async function syncActiveChat(reason = "realtime") {
    const chatId = getActiveConversationId();
    if (!chatId) return;

    if (activeSyncLock) return;
    activeSyncLock = true;

    try {
      const orgId = await getOrgId();
      if (!orgId) return;

      logDiagnostic("debug", `Checking active Claude conversation ${chatId} (trigger: ${reason})...`);
      await fetchAndIngestClaudeChat(orgId, chatId, reason);
      lastActiveSyncedId = chatId;
    } catch (e) {
      logDiagnostic("error", `Error syncing active Claude chat ${chatId}`, { error: e.message });
    } finally {
      activeSyncLock = false;
    }
  }

  async function fetchAndIngestClaudeChat(orgId, chatId, syncMethod = "rest_api") {
    try {
      const resp = await fetch(`/api/organizations/${orgId}/chat_conversations/${chatId}?tree=True`, {
        credentials: "include"
      });
      if (!resp.ok) {
        logDiagnostic("warn", `HTTP ${resp.status} fetching Claude conversation ${chatId}`);
        return;
      }

      const chatData = await resp.json();
      const msgCount = (chatData.chat_messages || []).length;
      if (msgCount === 0) return;

      logDiagnostic("info", `Syncing Claude chat: '${chatData.name || "Rozmowa"}' (${chatId}, ${msgCount} msgs)`);

      const ingestRes = await new Promise((resolve) => {
        ext.runtime.sendMessage(
          {
            type: "INGEST_PAYLOAD",
            platform: "claude_web",
            payload: chatData,
            metadata: {
              conversation_id: chatId,
              title: chatData.name,
              device: "browser-extension",
              sync_method: syncMethod
            }
          },
          (res) => resolve(res)
        );
      });

      if (ingestRes && ingestRes.status === "success") {
        logDiagnostic("success", `✅ Synced Claude chat: '${chatData.name}' (${chatId})`);
      }
    } catch (e) {
      logDiagnostic("error", `Failed to fetch/ingest Claude chat ${chatId}`, { error: e.message });
    }
  }

  async function runClaudeSync() {
    const orgId = await getOrgId();
    if (!orgId) return;

    try {
      const resp = await fetch(`/api/organizations/${orgId}/chat_conversations`, {
        credentials: "include"
      });
      if (!resp.ok) return;

      const convs = await resp.json();
      const storageKey = "claude_last_synced_time";
      const stored = await ext.storage.local.get([storageKey]);
      const lastSync = stored[storageKey] || 0;

      let maxUpdateTime = lastSync;

      for (const c of convs.slice(0, 15)) {
        const updateTs = new Date(c.updated_at).getTime();
        if (updateTs > lastSync) {
          logDiagnostic("info", `Ingesting updated Claude conversation: ${c.name} (${c.uuid})`);
          await fetchAndIngestClaudeChat(orgId, c.uuid, "delta_sync");
          if (updateTs > maxUpdateTime) maxUpdateTime = updateTs;
          await new Promise((r) => setTimeout(r, 1000));
        }
      }

      await ext.storage.local.set({ [storageKey]: maxUpdateTime });
    } catch (e) {
      logDiagnostic("warn", "Claude sync error", { error: e.message });
    }
  }

  async function runClaudeBackfill() {
    const orgId = await getOrgId();
    if (!orgId) return;

    try {
      const resp = await fetch(`/api/organizations/${orgId}/chat_conversations`, {
        credentials: "include"
      });
      if (!resp.ok) return;

      const convs = await resp.json();
      logDiagnostic("info", `Backfilling ${convs.length} Claude conversations...`);

      for (const c of convs) {
        await fetchAndIngestClaudeChat(orgId, c.uuid, "backfill");
        await new Promise((r) => setTimeout(r, 1000));
      }
      logDiagnostic("success", `Claude backfill completed (${convs.length} chats).`);
    } catch (e) {
      logDiagnostic("error", "Claude backfill error", { error: e.message });
    }
  }

  // SPA navigation hook
  function checkUrlChange() {
    const currentUrl = window.location.href;
    if (currentUrl !== lastUrl) {
      lastUrl = currentUrl;
      const newChatId = getActiveConversationId();
      logDiagnostic("info", `Claude URL change detected: ${window.location.pathname} (activeId: ${newChatId || "none"})`);
      if (newChatId) {
        setTimeout(() => syncActiveChat("spa_navigation"), 800);
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
  window.addEventListener("popstate", () => setTimeout(checkUrlChange, 100));
  setInterval(checkUrlChange, 1000);

  // Initial sync
  setTimeout(() => {
    syncActiveChat("initial_load");
    runClaudeSync();
  }, 3000);
})();
