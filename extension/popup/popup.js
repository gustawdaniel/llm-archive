const ext = globalThis.browser || globalThis.chrome;

document.addEventListener("DOMContentLoaded", async () => {
  const syncedCountEl = document.getElementById("syncedCount");
  const lastTitleEl = document.getElementById("lastTitle");
  const lastTimeEl = document.getElementById("lastTime");
  const backendInput = document.getElementById("backendInput");
  const btnSaveConfig = document.getElementById("btnSaveConfig");
  const btnSyncNow = document.getElementById("btnSyncNow");
  const btnBackfill = document.getElementById("btnBackfill");
  const statusMsg = document.getElementById("statusMessage");
  const extVersionEl = document.getElementById("extVersion");

  const manifest = ext.runtime?.getManifest ? ext.runtime.getManifest() : null;
  if (extVersionEl && manifest?.version) {
    extVersionEl.textContent = `v${manifest.version}`;
  }

  const deviceInput = document.getElementById("deviceInput");

  // Load stored state
  const data = await ext.storage.local.get([
    "backendUrl",
    "deviceName",
    "syncedCount",
    "lastSyncTime",
    "lastSyncTitle"
  ]);

  const btnGrantPerms = document.getElementById("btnGrantPerms");

  // Check permissions for Firefox / MV3
  try {
    if (ext.permissions && ext.permissions.contains) {
      const hasPerms = await ext.permissions.contains({ origins: ["<all_urls>"] });
      if (!hasPerms && btnGrantPerms) {
        btnGrantPerms.style.display = "block";
        btnGrantPerms.addEventListener("click", async () => {
          try {
            const granted = await ext.permissions.request({ origins: ["<all_urls>"] });
            if (granted) {
              btnGrantPerms.style.display = "none";
              statusMsg.textContent = "Uprawnienia sieciowe przyznane!";
              setTimeout(() => (statusMsg.textContent = "Wszystkie usługi aktywne"), 2500);
            }
          } catch (e) {
            console.warn("Permission request failed", e);
          }
        });
      }
    }
  } catch (_) {}

  if (data.deviceName) {
    deviceInput.value = data.deviceName;
  } else {
    // Query background for detected device name
    try {
      ext.runtime.sendMessage({ type: "GET_DEVICE_INFO" }, (res) => {
        if (res && res.device) deviceInput.value = res.device;
      });
    } catch (_) {}
  }

  // Migrate legacy brain-llm backend to direct Tailscale IP
  if (data.backendUrl && !data.backendUrl.includes("brain-llm")) {
    backendInput.value = data.backendUrl;
  } else {
    backendInput.value = "http://localhost:8080/api/v1/ingest";
  }
  if (data.syncedCount !== undefined) syncedCountEl.textContent = data.syncedCount;
  if (data.lastSyncTitle) lastTitleEl.textContent = data.lastSyncTitle;
  if (data.lastSyncTime) {
    const dt = new Date(data.lastSyncTime);
    lastTimeEl.textContent = dt.toLocaleTimeString();
  }

  // Save config
  btnSaveConfig.addEventListener("click", async () => {
    const val = backendInput.value.trim();
    const dev = deviceInput.value.trim();
    const updates = {};
    if (val) updates.backendUrl = val;
    if (dev) updates.deviceName = dev;

    // Also request permissions on user click
    try {
      if (ext.permissions && ext.permissions.request) {
        await ext.permissions.request({ origins: ["<all_urls>"] });
        if (btnGrantPerms) btnGrantPerms.style.display = "none";
      }
    } catch (_) {}

    if (Object.keys(updates).length > 0) {
      await ext.storage.local.set(updates);
      statusMsg.textContent = "Konfiguracja zapisana pomyślnie!";
      setTimeout(() => (statusMsg.textContent = "Wszystkie usługi aktywne"), 2500);
    }
  });

  // Sync Delta Now (broadcast to all open LLM tabs)
  btnSyncNow.addEventListener("click", async () => {
    statusMsg.textContent = "Wysyłam żądanie delta sync...";
    let sentCount = 0;
    try {
      const tabs = await ext.tabs.query({
        url: [
          "https://chatgpt.com/*",
          "https://chat.openai.com/*",
          "https://claude.ai/*",
          "https://chat.deepseek.com/*",
          "https://grok.com/*",
          "https://x.com/i/grok*",
          "https://gemini.google.com/*"
        ]
      });
      for (const tab of tabs) {
        if (tab && tab.id) {
          try {
            const p = ext.tabs.sendMessage(tab.id, { type: "TRIGGER_DELTA_SYNC" });
            if (p && typeof p.catch === "function") p.catch(() => {});
            sentCount++;
          } catch (_) {}
        }
      }
      // Also message active tab if not already covered
      const activeTabs = await ext.tabs.query({ active: true, currentWindow: true });
      if (activeTabs[0]?.id && !tabs.some(t => t.id === activeTabs[0].id)) {
        try {
          const p = ext.tabs.sendMessage(activeTabs[0].id, { type: "TRIGGER_DELTA_SYNC" });
          if (p && typeof p.catch === "function") p.catch(() => {});
        } catch (_) {}
      }
    } catch (_) {}
    statusMsg.textContent = `Wysłano sync (${sentCount} kart AI)`;
    setTimeout(() => (statusMsg.textContent = "Wszystkie usługi aktywne"), 2500);
  });

  // Full Backfill
  btnBackfill.addEventListener("click", async () => {
    if (!confirm("Rozpocząć pobieranie całej historii konwersacji z aktywnej karty? Może to zająć od kilkunastu sekund do paru minut.")) {
      return;
    }
    statusMsg.textContent = "Pobieram historię wstecz...";
    try {
      const tabs = await ext.tabs.query({ active: true, currentWindow: true });
      if (tabs[0]?.id) {
        const p = ext.tabs.sendMessage(tabs[0].id, { type: "TRIGGER_FULL_BACKFILL" });
        if (p && typeof p.catch === "function") p.catch(() => {});
      }
    } catch (_) {}
  });
});
