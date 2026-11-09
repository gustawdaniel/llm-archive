const DEFAULT_BACKEND = "http://localhost:8080/api/v1/ingest";
const ext = globalThis.browser || globalThis.chrome;
const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.4";

async function getDeviceName() {
  const data = await ext.storage.local.get(["deviceName"]);
  if (data.deviceName && data.deviceName.trim()) {
    return data.deviceName.trim();
  }

  // 1. Try local daemon/logger auto-discovery on localhost:3040/device
  try {
    const res = await fetch("http://127.0.0.1:3040/device", { method: "GET" });
    if (res.ok) {
      const info = await res.json();
      const detected = (info.device || info.hostname || "").trim();
      if (detected) {
        await ext.storage.local.set({ deviceName: detected });
        logDiagnostic("info", `Auto-detected device hostname from local service: '${detected}'`);
        return detected;
      }
    }
  } catch (_) {}

  // 2. Fallback to platform info
  try {
    if (ext.runtime.getPlatformInfo) {
      const plat = await ext.runtime.getPlatformInfo();
      const fallback = plat.os === "mac" ? "mac" : "rog";
      await ext.storage.local.set({ deviceName: fallback });
      logDiagnostic("info", `Platform fallback device name set: '${fallback}' (os: ${plat.os})`);
      return fallback;
    }
  } catch (_) {}

  return "rog";
}

const ALL_LLM_URLS = [
  "https://chatgpt.com/*",
  "https://chat.openai.com/*",
  "https://claude.ai/*",
  "https://chat.deepseek.com/*",
  "https://grok.com/*",
  "https://x.com/i/grok*",
  "https://gemini.google.com/*"
];

async function ensureDeltaSyncAlarm() {
  try {
    const data = await ext.storage.local.get(["backendUrl", "syncIntervalMinutes"]);
    if (!data.backendUrl) {
      await ext.storage.local.set({ backendUrl: DEFAULT_BACKEND });
    }
    const interval = data.syncIntervalMinutes || 15;
    if (ext.alarms && ext.alarms.get) {
      ext.alarms.get("delta_sync_alarm", (existing) => {
        if (!existing) {
          ext.alarms.create("delta_sync_alarm", { periodInMinutes: interval });
          logDiagnostic("info", `Registered delta_sync_alarm (every ${interval} minutes).`);
        }
      });
    }
  } catch (err) {
    logDiagnostic("warn", "Failed setting up delta sync alarm", { error: err.message });
  }
}

// Initialize defaults
ext.runtime.onInstalled.addListener(async () => {
  await ensureDeltaSyncAlarm();
  const device = await getDeviceName();
  logDiagnostic("info", `Extension installed (v${VERSION}) for device '${device}'.`);
});

if (ext.runtime.onStartup) {
  ext.runtime.onStartup.addListener(async () => {
    logDiagnostic("info", `Browser startup detected, verifying alarms...`);
    await ensureDeltaSyncAlarm();
  });
}
ensureDeltaSyncAlarm();

// Listen for alarms (Periodic Delta Sync for Mobile catch-up)
if (ext.alarms && ext.alarms.onAlarm) {
  ext.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === "delta_sync_alarm") {
      logDiagnostic("debug", "Running scheduled delta sync alarm...");
      try {
        const tabs = await ext.tabs.query({ url: ALL_LLM_URLS });
        logDiagnostic("debug", `Scheduled alarm: broadcasting TRIGGER_DELTA_SYNC to ${tabs.length} open LLM tab(s)...`);
        for (const tab of tabs) {
          if (tab && tab.id) {
            try {
              const p = ext.tabs.sendMessage(tab.id, { type: "TRIGGER_DELTA_SYNC" });
              if (p && typeof p.catch === "function") p.catch(() => {});
            } catch (_) {}
          }
        }
      } catch (err) {
        logDiagnostic("warn", "Delta sync tab query error", { error: err.message });
      }
    }
  });
}

// Handle incoming payloads and queries from content scripts
ext.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "DIAGNOSTIC_LOG") {
    logDiagnostic(request.level || "info", request.message, request.details, request.source || "content");
    sendResponse({ status: "ok" });
    return true;
  }

  if (request.type === "INGEST_PAYLOAD") {
    handleIngest(request.platform, request.payload, request.metadata)
      .then((res) => sendResponse({ status: "success", result: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true; // Keep channel open for async response
  }

  if (request.type === "GET_DEVICE_INFO") {
    getDeviceName()
      .then((dev) => sendResponse({ status: "success", device: dev }))
      .catch(() => sendResponse({ status: "error", device: "rog" }));
    return true; // Keep channel open for async response
  }

  if (request.type === "GET_SYNC_STATUS") {
    handleGetSyncStatus(request.platform, request.limit)
      .then((res) => sendResponse({ status: "success", result: res }))
      .catch((err) => sendResponse({ status: "error", message: err.message }));
    return true; // Keep channel open for async response
  }
});

function logDiagnostic(level, message, details = null, source = "background.js") {
  const shortSource = source.replace(/\.js.*$/, "");
  const tag = `[Brain ${shortSource} v${VERSION} ${level.toUpperCase()}]`;
  const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
  if (details !== null && details !== undefined) {
    logFn(`${tag} ${message}`, details);
  } else {
    logFn(`${tag} ${message}`);
  }
  try {
    fetch("http://127.0.0.1:3040/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        version: VERSION,
        level,
        message,
        details,
        timestamp: new Date().toISOString()
      })
    }).catch(() => {});
  } catch (_) {}
}

async function resolveTargetUrl() {
  // If local bridge is active on 127.0.0.1:3040, prefer it (bypasses browser CORS & host_permissions)
  try {
    const bridgeCheck = await fetch("http://127.0.0.1:3040/health", { method: "GET" });
    if (bridgeCheck.ok) {
      return "http://127.0.0.1:3040/ingest";
    }
  } catch (_) {}

  const { backendUrl } = await ext.storage.local.get(["backendUrl"]);
  if (!backendUrl || backendUrl === LEGACY_BACKEND || backendUrl.includes("brain-llm")) {
    await ext.storage.local.set({ backendUrl: DEFAULT_BACKEND });
    return DEFAULT_BACKEND;
  }
  return backendUrl;
}

async function handleGetSyncStatus(platform, limit = 50) {
  const platformCacheKey = `synced_cache_${platform}`;
  const stored = (await ext.storage.local.get([platformCacheKey])) || {};
  const localCache = stored[platformCacheKey] || {};

  let target = await resolveTargetUrl();
  let statusUrl;
  if (target.includes("127.0.0.1:3040")) {
    statusUrl = `http://127.0.0.1:3040/sync/status?platform=${encodeURIComponent(platform)}&limit=${limit}`;
  } else {
    const baseUrl = target.replace(/\/api\/v1(\/ingest)?\/?$/, "");
    statusUrl = `${baseUrl}/api/v1/sync/status?platform=${encodeURIComponent(platform)}&limit=${limit}`;
  }

  logDiagnostic("debug", `Querying DB sync status from ${statusUrl}...`);
  let response;
  try {
    response = await fetch(statusUrl, {
      method: "GET",
      headers: { Accept: "application/json" }
    });
  } catch (err) {
    if (!statusUrl.includes("127.0.0.1:3040")) {
      try {
        const bridgeUrl = `http://127.0.0.1:3040/sync/status?platform=${encodeURIComponent(platform)}&limit=${limit}`;
        response = await fetch(bridgeUrl, {
          method: "GET",
          headers: { Accept: "application/json" }
        });
        logDiagnostic("info", `Sync status fetched via local logger bridge (127.0.0.1:3040)`);
      } catch (_) {
        // Fall back to persistent local cache
        logDiagnostic("warn", `Remote sync status unreachable (${err.message}), falling back to local cache (${Object.keys(localCache).length} chats cached)`);
        return { platform, count: Object.keys(localCache).length, conversations: localCache, offline: true };
      }
    } else {
      // Fall back to persistent local cache
      logDiagnostic("warn", `Bridge sync status unreachable (${err.message}), falling back to local cache (${Object.keys(localCache).length} chats cached)`);
      return { platform, count: Object.keys(localCache).length, conversations: localCache, offline: true };
    }
  }

  if (!response.ok) {
    const errText = await response.text();
    logDiagnostic("error", `Sync status error HTTP ${response.status}`, { url: statusUrl, body: errText });
    return { platform, count: Object.keys(localCache).length, conversations: localCache, offline: true };
  }

  const result = await response.json();
  // Merge remote DB status with local cache
  const remoteConvs = result.conversations || {};
  const mergedConvs = { ...localCache, ...remoteConvs };
  result.conversations = mergedConvs;
  result.count = Object.keys(mergedConvs).length;

  // Persist updated merged cache locally
  await ext.storage.local.set({ [platformCacheKey]: mergedConvs });
  logDiagnostic("info", `DB sync status received: ${result.count} known conversations (DB + local cache).`, { platform, count: result.count });
  return result;
}

async function handleIngest(platform, payload, metadata) {
  let target = await resolveTargetUrl();
  const deviceName = await getDeviceName();

  const msgCount = payload.messages ? payload.messages.length : (payload.responses ? payload.responses.length : 0);
  logDiagnostic("info", `Sending ${platform} chat to backend: '${payload.title}' (${msgCount} msgs, convId: ${payload.conversation_id}, device: ${deviceName})`, {
    platform,
    convId: payload.conversation_id,
    device: deviceName,
    messageCount: msgCount,
    syncMethod: metadata?.sync_method
  });

  const mergedMetadata = {
    ...(metadata || {}),
    device: deviceName
  };

  const bodyData = JSON.stringify({
    platform: platform,
    payload: payload,
    metadata: mergedMetadata
  });

  let response;
  try {
    response = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: bodyData
    });
  } catch (err) {
    logDiagnostic("warn", `Direct ingest failed (${err.message}), trying local bridge http://127.0.0.1:3040/ingest...`);
    try {
      response = await fetch("http://127.0.0.1:3040/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: bodyData
      });
      logDiagnostic("info", `Ingested conversation via local logger bridge (127.0.0.1:3040)`);
    } catch (bridgeErr) {
      logDiagnostic("error", `Local bridge also unreachable (${bridgeErr.message}). Check permissions or network.`);
      throw err;
    }
  }

  if (!response.ok) {
    const errText = await response.text();
    logDiagnostic("error", `Backend ingest failed (HTTP ${response.status}): ${errText}`, { target, status: response.status });
    throw new Error(`Backend error ${response.status}: ${errText}`);
  }

  const result = await response.json();
  logDiagnostic("success", `✅ Ingested ${platform} conversation: '${result.title}' (DB ID: ${result.conversation_id}, device: ${deviceName})`, {
    dbId: result.conversation_id,
    title: result.title,
    totalMessages: result.total_messages
  });

  // Update sync stats
  const stats = (await ext.storage.local.get(["syncedCount"])) || { syncedCount: 0 };
  await ext.storage.local.set({
    syncedCount: (stats.syncedCount || 0) + 1,
    lastSyncTime: new Date().toISOString(),
    lastSyncTitle: result.title
  });

  // Automatically record this conversation in the platform's local persistent cache
  const platformCacheKey = `synced_cache_${platform}`;
  const stored = (await ext.storage.local.get([platformCacheKey])) || {};
  const localCache = stored[platformCacheKey] || {};
  const externalConvId = payload.conversation_id || metadata?.conversation_id || result.conversation_id;
  if (externalConvId) {
    localCache[externalConvId] = {
      message_count: result.total_messages || msgCount,
      updated_at: payload.updated_at || payload.modifyTime || new Date().toISOString(),
      synced_at: Date.now()
    };
    await ext.storage.local.set({ [platformCacheKey]: localCache });
  }

  return result;
}

