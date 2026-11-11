const ext = globalThis.browser || globalThis.chrome;

document.addEventListener("DOMContentLoaded", async () => {
  const syncedCountEl = document.getElementById("syncedCount");
  const lastTitleEl = document.getElementById("lastTitle");
  const lastTimeEl = document.getElementById("lastTime");
  const backendInput = document.getElementById("backendInput");
  const deviceInput = document.getElementById("deviceInput");
  const deviceBadge = document.getElementById("deviceBadge");
  const btnSaveConfig = document.getElementById("btnSaveConfig");
  const btnTestConn = document.getElementById("btnTestConn");
  const btnSyncNow = document.getElementById("btnSyncNow");
  const btnBackfill = document.getElementById("btnBackfill");
  const statusMsg = document.getElementById("statusMessage");
  const extVersionEl = document.getElementById("extVersion");
  const statusBadge = document.getElementById("statusBadge");
  const bridgeDot = document.getElementById("bridgeDot");
  const bridgeText = document.getElementById("bridgeText");
  const apiDot = document.getElementById("apiDot");
  const apiText = document.getElementById("apiText");
  const troubleshootBox = document.getElementById("troubleshootBox");
  const troubleshootTitle = document.getElementById("troubleshootTitle");
  const troubleshootDesc = document.getElementById("troubleshootDesc");
  const btnGrantPerms = document.getElementById("btnGrantPerms");
  const toggleLogsBtn = document.getElementById("toggleLogsBtn");
  const diagnosticsPanel = document.getElementById("diagnosticsPanel");
  const linkDocs = document.getElementById("linkDocs");

  // Display version
  try {
    const manifest = ext.runtime?.getManifest ? ext.runtime.getManifest() : null;
    if (extVersionEl && manifest?.version) {
      extVersionEl.textContent = `v${manifest.version}`;
    }
  } catch (err) {
    console.error("[Brain Popup] Failed reading manifest version:", err);
  }

  // Copy command buttons helper
  document.querySelectorAll(".btn-copy-cmd").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cmd = btn.getAttribute("data-cmd");
      if (!cmd) return;
      try {
        await navigator.clipboard.writeText(cmd);
        const originalText = btn.textContent;
        btn.textContent = "✓ Skopiowano";
        setTimeout(() => {
          btn.textContent = originalText;
        }, 2000);
      } catch (copyErr) {
        console.error("[Brain Popup] Clipboard copy error:", copyErr);
        prompt("Skopiuj polecenie:", cmd);
      }
    });
  });

  // Docs link handler
  if (linkDocs) {
    linkDocs.addEventListener("click", (e) => {
      e.preventDefault();
      const docsUrl = "https://github.com/gustawdaniel/llm-archive/blob/main/extension/README.md";
      try {
        if (ext.tabs && ext.tabs.create) {
          ext.tabs.create({ url: docsUrl });
        } else {
          window.open(docsUrl, "_blank");
        }
      } catch (navErr) {
        console.error("[Brain Popup] Failed opening docs tab:", navErr);
        window.open(docsUrl, "_blank");
      }
    });
  }

  // Helper to refresh stats display from storage
  async function refreshStats() {
    try {
      const data = await ext.storage.local.get([
        "backendUrl",
        "deviceName",
        "syncedCount",
        "lastSyncTime",
        "lastSyncTitle"
      ]);
      if (data.deviceName) {
        deviceInput.value = data.deviceName;
        deviceBadge.textContent = data.deviceName;
      }
      if (data.syncedCount !== undefined) syncedCountEl.textContent = data.syncedCount;
      if (data.lastSyncTitle) lastTitleEl.textContent = data.lastSyncTitle;
      if (data.lastSyncTime) {
        try {
          const dt = new Date(data.lastSyncTime);
          lastTimeEl.textContent = dt.toLocaleTimeString();
        } catch (_) {}
      }
    } catch (err) {
      console.warn("[Brain Popup] Error refreshing stats:", err);
    }
  }

  // Live storage change listener
  if (ext.storage && ext.storage.onChanged) {
    ext.storage.onChanged.addListener((changes, area) => {
      if (area === "local") {
        if (changes.syncedCount) syncedCountEl.textContent = changes.syncedCount.newValue;
        if (changes.lastSyncTitle) lastTitleEl.textContent = changes.lastSyncTitle.newValue;
        if (changes.lastSyncTime) {
          try {
            const dt = new Date(changes.lastSyncTime.newValue);
            lastTimeEl.textContent = dt.toLocaleTimeString();
          } catch (_) {}
        }
      }
    });
  }

  // Load stored state initially
  await refreshStats();

  const stored = await ext.storage.local.get(["backendUrl", "deviceName"]);
  if (stored.backendUrl && !stored.backendUrl.includes("brain-llm")) {
    backendInput.value = stored.backendUrl;
  } else {
    backendInput.value = "http://localhost:8080/api/v1/ingest";
  }

  if (!stored.deviceName) {
    try {
      ext.runtime.sendMessage({ type: "GET_DEVICE_INFO" }, (res) => {
        if (ext.runtime.lastError) return;
        if (res && res.device) {
          deviceInput.value = res.device;
          deviceBadge.textContent = res.device;
        }
      });
    } catch (_) {}
  }

  // Check and display connection status
  async function checkConnections() {
    let bridgeOk = false;
    let bridgeLatency = 0;
    let bridgeErrorMsg = "";

    // 1. Check local proxy bridge (127.0.0.1:3040/health)
    try {
      const start = Date.now();
      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), 4000);
      const bridgeRes = await fetch("http://127.0.0.1:3040/health", {
        method: "GET",
        signal: ctrl.signal
      });
      clearTimeout(tid);
      bridgeLatency = Date.now() - start;
      if (bridgeRes.ok) {
        bridgeOk = true;
      } else {
        bridgeErrorMsg = `HTTP ${bridgeRes.status}`;
      }
    } catch (err) {
      bridgeErrorMsg = err.name === "AbortError" ? "Timeout (4s)" : (err.message || "Brak połączenia");
    }

    // 2. Check direct backend
    let directOk = false;
    const targetUrl = backendInput.value.trim() || "http://localhost:8080/api/v1/ingest";
    const healthUrl = targetUrl.replace(/\/ingest\/?$/, "/health").replace(/\/api\/v1\/?$/, "/health");
    try {
      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), 2000);
      const directRes = await fetch(healthUrl, {
        method: "GET",
        signal: ctrl.signal
      });
      clearTimeout(tid);
      if (directRes.ok || directRes.status === 404 || directRes.status === 405) {
        directOk = true;
      }
    } catch (_) {}

    // Update Bridge Dot & Text
    if (bridgeOk) {
      bridgeDot.className = "status-dot green";
      bridgeText.textContent = `3040: OK (${bridgeLatency}ms)`;
    } else {
      bridgeDot.className = "status-dot red";
      bridgeText.textContent = `3040: Offline`;
    }

    // Update API Dot & Text
    if (directOk) {
      apiDot.className = "status-dot green";
      apiText.textContent = "API: OK";
    } else {
      apiDot.className = "status-dot amber";
      apiText.textContent = bridgeOk ? "API: via 3040" : "API: Nieosiągalne";
    }

    // Update Badge & Troubleshooting Box
    if (bridgeOk) {
      statusBadge.className = "badge online";
      statusBadge.textContent = "Online (:3040)";
      troubleshootBox.className = "troubleshoot-box";
    } else if (directOk) {
      statusBadge.className = "badge degraded";
      statusBadge.textContent = "Mostek 3040 Offline";
      troubleshootBox.className = "troubleshoot-box visible warning";
      troubleshootTitle.textContent = "⚠️ Mostek proxy (3040) jest offline";
      troubleshootDesc.textContent = `Wtyczka korzysta obecnie z bezpośredniego połączenia do ${targetUrl}, ale lokalny rejestrator zdarzeń nie działa (${bridgeErrorMsg}). Uruchom usługę poniższym poleceniem:`;
    } else {
      statusBadge.className = "badge offline";
      statusBadge.textContent = "Brak połączenia";
      troubleshootBox.className = "troubleshoot-box visible error";
      troubleshootTitle.textContent = "❌ Brak połączenia z bazą i mostkiem";
      troubleshootDesc.textContent = `Nie można nawiązać połączenia z 127.0.0.1:3040 (${bridgeErrorMsg}) ani z API (${targetUrl}). Uruchom instalator lub sprawdź logi:`;
    }
  }

  // Initial connection verification
  await checkConnections();

  // Test button
  btnTestConn.addEventListener("click", async () => {
    btnTestConn.textContent = "Sprawdzam...";
    btnTestConn.disabled = true;
    try {
      await checkConnections();
      statusMsg.className = "footer success";
      statusMsg.textContent = "Status połączeń zaktualizowany";
    } catch (err) {
      statusMsg.className = "footer error";
      statusMsg.textContent = `Błąd testu: ${err.message}`;
    } finally {
      btnTestConn.textContent = "🔍 Test połączenia";
      btnTestConn.disabled = false;
      setTimeout(() => {
        statusMsg.className = "footer";
        statusMsg.textContent = "Wszystkie usługi aktywne";
      }, 3000);
    }
  });


  // Host permission only for the user's own server, never for every site: the
  // extension needs it to POST conversations to the configured backend URL.
  function backendOrigins() {
    try {
      const u = new URL(backendInput.value.trim() || "http://localhost:8080/api/v1/ingest");
      return [`${u.protocol}//${u.hostname}/*`];
    } catch (_) {
      return [];
    }
  }

  // Check optional permissions for Firefox / MV3
  try {
    if (ext.permissions && ext.permissions.contains) {
      const hasPerms = await ext.permissions.contains({ origins: backendOrigins() });
      if (!hasPerms && btnGrantPerms) {
        btnGrantPerms.style.display = "block";
        btnGrantPerms.addEventListener("click", async () => {
          try {
            const granted = await ext.permissions.request({ origins: backendOrigins() });
            if (granted) {
              btnGrantPerms.style.display = "none";
              statusMsg.className = "footer success";
              statusMsg.textContent = "Uprawnienia sieciowe przyznane!";
              await checkConnections();
            } else {
              statusMsg.className = "footer error";
              statusMsg.textContent = "Odrzucono uprawnienia sieciowe";
            }
          } catch (e) {
            console.error("[Brain Popup] Permission request failed:", e);
            statusMsg.className = "footer error";
            statusMsg.textContent = `Błąd uprawnień: ${e.message}`;
          }
        });
      }
    }
  } catch (permCheckErr) {
    console.debug("[Brain Popup] Permissions check non-fatal error:", permCheckErr.message);
  }

  // Save config
  btnSaveConfig.addEventListener("click", async () => {
    const val = backendInput.value.trim();
    const dev = deviceInput.value.trim();
    const updates = {};
    if (val) updates.backendUrl = val;
    if (dev) {
      updates.deviceName = dev;
      deviceBadge.textContent = dev;
    }

    try {
      if (ext.permissions && ext.permissions.request) {
        const origins = backendOrigins();
        if (origins.length) await ext.permissions.request({ origins });
        if (btnGrantPerms) btnGrantPerms.style.display = "none";
      }
    } catch (permErr) {
      console.warn("[Brain Popup] Permission request on save failed:", permErr.message);
    }

    try {
      if (Object.keys(updates).length > 0) {
        await ext.storage.local.set(updates);
        statusMsg.className = "footer success";
        statusMsg.textContent = "Konfiguracja zapisana pomyślnie!";
        await checkConnections();
      }
    } catch (saveErr) {
      console.error("[Brain Popup] Failed saving configuration:", saveErr);
      statusMsg.className = "footer error";
      statusMsg.textContent = `Błąd zapisu: ${saveErr.message}`;
    }
  });

  // Sync Delta Now (with dynamic script injection for orphaned tabs)
  btnSyncNow.addEventListener("click", async () => {
    statusMsg.className = "footer";
    statusMsg.textContent = "Wyszukuję otwarte karty AI...";
    let sentCount = 0;
    let tabs = [];

    const SCRIPT_MAP = {
      "chatgpt.com": "content/chatgpt.js",
      "openai.com": "content/chatgpt.js",
      "claude.ai": "content/claude.js",
      "deepseek.com": "content/deepseek.js",
      "grok.com": "content/grok.js",
      "x.com": "content/grok.js",
      "gemini.google.com": "content/gemini.js"
    };

    try {
      tabs = await ext.tabs.query({
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
    } catch (queryErr) {
      console.error("[Brain Popup] Tab query failed:", queryErr);
      statusMsg.className = "footer error";
      statusMsg.textContent = `Błąd kart: ${queryErr.message}`;
      return;
    }

    if (!tabs || tabs.length === 0) {
      statusMsg.className = "footer error";
      statusMsg.textContent = "Brak kart AI (otwórz ChatGPT, Claude, DeepSeek, Grok lub Gemini).";
      return;
    }

    statusMsg.textContent = `Wysyłam sygnał do ${tabs.length} kart AI...`;

    for (const tab of tabs) {
      if (!tab || !tab.id) continue;

      let delivered = false;
      try {
        const res = await new Promise((resolve, reject) => {
          ext.tabs.sendMessage(tab.id, { type: "TRIGGER_DELTA_SYNC", force: true }, (response) => {
            if (ext.runtime.lastError) {
              reject(new Error(ext.runtime.lastError.message));
            } else {
              resolve(response);
            }
          });
        });
        if (res) delivered = true;
      } catch (sendErr) {
        // Tab was likely open prior to extension reload; attempt dynamic script injection
        if (ext.scripting && ext.scripting.executeScript && tab.url) {
          const matchedDomain = Object.keys(SCRIPT_MAP).find((d) => tab.url.includes(d));
          if (matchedDomain) {
            try {
              if (matchedDomain === "gemini.google.com") {
                await ext.scripting.executeScript({
                  target: { tabId: tab.id },
                  files: ["content/gemini_token_bridge.js"],
                  world: "MAIN"
                }).catch(() => {});
              }
              await ext.scripting.executeScript({
                target: { tabId: tab.id },
                files: [SCRIPT_MAP[matchedDomain]]
              });
              await new Promise((r) => setTimeout(r, 200));
              ext.tabs.sendMessage(tab.id, { type: "TRIGGER_DELTA_SYNC", force: true });
              delivered = true;
            } catch (injectErr) {
              console.warn(`[Brain Popup] Injection into tab ${tab.id} failed:`, injectErr.message);
            }
          }
        }
      }
      if (delivered) sentCount++;
    }

    statusMsg.className = "footer success";
    statusMsg.textContent = `✓ Wysłano delta sync (${sentCount}/${tabs.length} kart AI)`;
    // Refresh stats after short delays to catch ingested conversations
    setTimeout(refreshStats, 1200);
    setTimeout(refreshStats, 3000);
  });

  // Full Backfill
  btnBackfill.addEventListener("click", async () => {
    let activeTabs = [];
    try {
      activeTabs = await ext.tabs.query({ active: true, currentWindow: true });
    } catch (queryErr) {
      console.error("[Brain Popup] Active tab query error:", queryErr);
      statusMsg.className = "footer error";
      statusMsg.textContent = `Błąd: ${queryErr.message}`;
      return;
    }

    const currentTab = activeTabs[0];
    if (!currentTab || !currentTab.url) {
      statusMsg.className = "footer error";
      statusMsg.textContent = "Nie można zidentyfikować aktywnej karty.";
      return;
    }

    const isLlmTab = [
      "chatgpt.com",
      "chat.openai.com",
      "claude.ai",
      "chat.deepseek.com",
      "grok.com",
      "gemini.google.com"
    ].some((domain) => currentTab.url.includes(domain));

    if (!isLlmTab) {
      statusMsg.className = "footer error";
      statusMsg.textContent = "Przejdź najpierw na kartę czatu AI (np. ChatGPT, Claude, Gemini), aby uruchomić pełny eksport.";
      return;
    }

    if (!confirm("Rozpocząć pobieranie całej historii z aktywnej karty? Może to zająć od kilkunastu sekund do paru minut.")) {
      return;
    }

    statusMsg.className = "footer";
    statusMsg.textContent = "Pobieram pełną historię wstecz...";
    try {
      ext.tabs.sendMessage(currentTab.id, { type: "TRIGGER_FULL_BACKFILL", force: true }, (res) => {
        if (ext.runtime.lastError) {
          statusMsg.className = "footer error";
          statusMsg.textContent = `Błąd: ${ext.runtime.lastError.message}. Odśwież kartę czatu.`;
        } else {
          statusMsg.className = "footer success";
          statusMsg.textContent = "✓ Rozpoczęto pełny eksport w tle";
        }
      });
    } catch (backfillErr) {
      console.error("[Brain Popup] Full backfill dispatch failed:", backfillErr);
      statusMsg.className = "footer error";
      statusMsg.textContent = `Błąd: ${backfillErr.message}`;
    }
  });

  // Load diagnostics directly from logger daemon (127.0.0.1:3040/logs) with fallbacks
  async function loadDiagnostics() {
    diagnosticsPanel.textContent = "Pobieram logi diagnostyczne...";
    let logs = [];

    // 1. Try local daemon proxy (127.0.0.1:3040/logs)
    try {
      const res = await fetch("http://127.0.0.1:3040/logs", { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        logs = await res.json();
      }
    } catch (err) {
      console.debug("[Brain Popup] Local daemon /logs not reachable:", err.message);
    }

    // 2. Fallback to background worker memory
    if (!logs || logs.length === 0) {
      try {
        const bgRes = await new Promise((resolve) => {
          ext.runtime.sendMessage({ type: "GET_DIAGNOSTICS" }, resolve);
        });
        logs = bgRes?.logs || [];
      } catch (err) {
        console.debug("[Brain Popup] Background diagnostics error:", err.message);
      }
    }

    if (!logs || logs.length === 0) {
      diagnosticsPanel.textContent = "Brak zarejestrowanych logów. Uruchom synchronizację lub odśwież kartę z czatem AI.";
      return;
    }

    // Take last 40 logs, show newest first
    const recent = logs.slice(-40).reverse();
    diagnosticsPanel.replaceChildren();
    recent.forEach((l) => {
      let ts = "";
      if (l.timestamp) {
        try {
          ts = new Date(l.timestamp).toLocaleTimeString();
        } catch (_) {
          ts = l.timestamp;
        }
      } else if (l.time) {
        ts = l.time;
      }
      const src = l.source || "ext";
      const lvl = (l.level || "info").toLowerCase();
      const lineEl = document.createElement("div");
      lineEl.className = `log-line ${lvl}`;
      lineEl.textContent = `[${ts}] [${lvl.toUpperCase()}] [${src}] ${l.message || ""}`;
      if (l.details) {
        const detSpan = document.createElement("span");
        detSpan.style.color = "#64748b";
        detSpan.textContent = ` ${JSON.stringify(l.details).slice(0, 150)}`;
        lineEl.appendChild(detSpan);
      }
      diagnosticsPanel.appendChild(lineEl);
    });
  }

  // Toggle diagnostics panel
  if (toggleLogsBtn && diagnosticsPanel) {
    toggleLogsBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      const isVisible = diagnosticsPanel.classList.toggle("visible");
      toggleLogsBtn.textContent = isVisible
        ? "📋 Ukryj logi diagnostyczne ▴"
        : "📋 Pokaż ostatnie logi diagnostyczne ▾";

      if (isVisible) {
        await loadDiagnostics();
      }
    });
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
});
