// Content Script for Google Gemini (gemini.google.com)
// Supports Instant RPC Extraction (hNvQHb), Direct Catalog Discovery (MaZiqc),
// Reverse Chronological Ordering, and Smart Differential Catch-Up Sync.

(function () {
  const ext = globalThis.browser || globalThis.chrome;
  const VERSION = (ext?.runtime?.getManifest && ext.runtime.getManifest()?.version) || "1.0.18";

  function logDiagnostic(level, message, details = null) {
    const tag = `[Brain Gemini v${VERSION} ${level.toUpperCase()}]`;
    const logFn = console[level === "error" ? "error" : level === "warn" ? "warn" : "log"];
    if (details !== null && details !== undefined) {
      logFn(`${tag} ${message}`, details);
    } else {
      logFn(`${tag} ${message}`);
    }
    try {
      const p = ext.runtime.sendMessage({
        type: "DIAGNOSTIC_LOG",
        source: `gemini.js (v${VERSION})`,
        level,
        message,
        details,
        timestamp: new Date().toISOString()
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

  logDiagnostic("info", `Gemini content script loaded on ${window.location.pathname}`);

  // ============================================================================
  // 1. EMBEDDED REVERSE-ENGINEERED GEMINI RPC FETCHER (hNvQHb + MaZiqc)
  // ============================================================================

  const RPC_TURNS = "hNvQHb";
  const RPC_LIST = "MaZiqc";
  const FILENAME_REGEX = /^[^/\\:*?"<>|$]{1,120}\.[a-z0-9]{2,6}$/i;
  const CARD_CONTENT_REGEX = /^https?:\/\/googleusercontent\.com\/card_content\/\d+/;
  const ARTIFACTS_REGEX = /https?:\/\/googleusercontent\.com\/(?:\w+\/)+\d+\n*/g;

  // Recursively collect attachment filenames from user turn structures
  function collectFilenames(node, names = []) {
    if (typeof node === "string") {
      if (FILENAME_REGEX.test(node) && !names.includes(node)) {
        names.push(node);
      }
    } else if (Array.isArray(node)) {
      for (const child of node) {
        collectFilenames(child, names);
      }
    }
    return names;
  }

  // Recursively search for longest non-empty string in nested arrays
  function findDeepestString(node) {
    if (typeof node === "string" && node.trim().length > 0) {
      return node.trim();
    }
    if (Array.isArray(node)) {
      let longest = "";
      for (const child of node) {
        const found = findDeepestString(child);
        if (found && found.length > longest.length) {
          longest = found;
        }
      }
      return longest;
    }
    return "";
  }

  const GeminiRPCFetcher = {
    /**
     * Resolves CSRF token (SNlM0e), build label (cfb2h), and session ID (FdrFJe).
     * Works across Chrome/Firefox MV3 isolated worlds via DOM script inspection and bridge.
     */
    async getTokens() {
      let at = null;
      let bl = "boq_assistant-bard-web-server";
      let sid = null;

      // 1. Direct dataset check (populated by world: MAIN gemini_token_bridge.js)
      if (typeof document !== "undefined" && document.documentElement?.dataset?.geminiAt) {
        at = document.documentElement.dataset.geminiAt;
        bl = document.documentElement.dataset.geminiBl || bl;
        sid = document.documentElement.dataset.geminiSid || null;
        if (at) return { at, bl, sid };
      }

      // 2. Direct window check (when running in page context or main world)
      if (typeof window !== "undefined" && window.WIZ_global_data) {
        at = window.WIZ_global_data.SNlM0e || null;
        bl = window.WIZ_global_data.cfb2h || bl;
        sid = window.WIZ_global_data.FdrFJe || null;
        if (at) return { at, bl, sid };
      }

      // 3. Firefox wrappedJSObject access
      if (typeof window !== "undefined" && window.wrappedJSObject && window.wrappedJSObject.WIZ_global_data) {
        const wiz = window.wrappedJSObject.WIZ_global_data;
        at = wiz.SNlM0e || null;
        bl = wiz.cfb2h || bl;
        sid = wiz.FdrFJe || null;
        if (at) return { at, bl, sid };
      }

      // 4. Scan DOM <script> elements (works in isolated worlds)
      if (typeof document !== "undefined") {
        const scripts = document.querySelectorAll("script");
        for (let i = 0; i < scripts.length; i++) {
          const text = scripts[i].textContent || "";
          if (text.includes("SNlM0e")) {
            const atMatch = text.match(/["']SNlM0e["']\s*:\s*["']([^"']+)["']/);
            const blMatch = text.match(/["']cfb2h["']\s*:\s*["']([^"']+)["']/);
            const sidMatch = text.match(/["']FdrFJe["']\s*:\s*["']([^"']+)["']/);
            if (atMatch && atMatch[1]) at = atMatch[1];
            if (blMatch && blMatch[1]) bl = blMatch[1];
            if (sidMatch && sidMatch[1]) sid = sidMatch[1];
            if (at) return { at, bl, sid };
          }
        }
      }

      // 3. Fallback: inject a temporary bridge script into DOM to access main-world WIZ_global_data
      const bridgeTokens = await new Promise((resolve) => {
        if (typeof document === "undefined") return resolve(null);

        const eventName = "__gemini_rpc_tokens_" + Math.random().toString(36).substring(2);
        const handler = (e) => {
          window.removeEventListener(eventName, handler);
          resolve(e.detail);
        };
        window.addEventListener(eventName, handler);

        const script = document.createElement("script");
        script.textContent = `
          try {
            const wiz = window.WIZ_global_data || {};
            window.dispatchEvent(new CustomEvent('${eventName}', {
              detail: {
                at: wiz.SNlM0e || null,
                bl: wiz.cfb2h || 'boq_assistant-bard-web-server',
                sid: wiz.FdrFJe || null
              }
            }));
          } catch(e) {
            window.dispatchEvent(new CustomEvent('${eventName}', { detail: null }));
          }
        `;
        (document.head || document.documentElement).appendChild(script);
        script.remove();

        setTimeout(() => {
          window.removeEventListener(eventName, handler);
          resolve(null);
        }, 1500);
      });

      if (bridgeTokens && bridgeTokens.at) {
        at = bridgeTokens.at;
        bl = bridgeTokens.bl || bl;
        sid = bridgeTokens.sid || sid;
        return { at, bl, sid };
      }

      if (at) return { at, bl, sid };
      return null;
    },

    /**
     * Parses chunked batchexecute response from Google.
     * Google sends: )]}'\n<byte_length>\n[[...]]\n<byte_length>\n...
     */
    parseBatchExecuteResponse(rawText, targetRpcId = RPC_TURNS) {
      if (!rawText) return null;

      const lines = rawText.split("\n");
      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("[[") && trimmed.endsWith("]]")) {
          try {
            const parsed = JSON.parse(trimmed);
            if (Array.isArray(parsed) && parsed.length > 0) {
              for (const entry of parsed) {
                if (Array.isArray(entry) && entry[0] === "wrb.fr" && entry[1] === targetRpcId && typeof entry[2] === "string") {
                  return JSON.parse(entry[2]);
                }
                if (Array.isArray(entry) && entry[1] === targetRpcId && typeof entry[2] === "string") {
                  return JSON.parse(entry[2]);
                }
              }
            }
          } catch (parseErr) {
            console.debug("[Brain Gemini RPC Array Parse]", parseErr);
          }
        }
      }

      // Fallback: search for wrb.fr and targetRpcId pattern in raw text
      try {
        const matchRegex = new RegExp(`\\["wrb\\.fr"\\s*,\\s*"${targetRpcId}"\\s*,\\s*"([\\s\\S]*?)"\\s*,`, "m");
        const match = rawText.match(matchRegex);
        if (match && match[1]) {
          const unescaped = JSON.parse(`"${match[1]}"`);
          return JSON.parse(unescaped);
        }
      } catch (regexParseErr) {
        console.debug("[Brain Gemini RPC Regex Parse]", regexParseErr);
      }

      return null;
    },

    /**
     * Calls Google batchexecute RPC endpoint.
     */
    async executeRpc(rpcId, innerPayload, sourcePath = "/app") {
      const tokens = await this.getTokens();
      if (!tokens || !tokens.at) {
        logDiagnostic("warn", `Nie można wywołać RPC ${rpcId}: brak tokenu SNlM0e (CSRF).`);
        return null;
      }

      const lang = (typeof navigator !== "undefined" && navigator.language ? navigator.language.split("-")[0] : "pl");
      const queryParams = [
        `rpcids=${encodeURIComponent(rpcId)}`,
        `source-path=${encodeURIComponent(sourcePath)}`,
        tokens.bl ? `bl=${encodeURIComponent(tokens.bl)}` : "",
        tokens.sid ? `f.sid=${encodeURIComponent(tokens.sid)}` : "",
        `hl=${encodeURIComponent(lang)}`,
        `_reqid=${Math.floor(100000 + (Date.now() % 900000))}`
      ].filter(Boolean).join("&");

      const freq = JSON.stringify([[[rpcId, JSON.stringify(innerPayload), null, "generic"]]]);
      const body = `f.req=${encodeURIComponent(freq)}&at=${encodeURIComponent(tokens.at)}`;
      const url = `https://gemini.google.com/_/BardChatUi/data/batchexecute?${queryParams}`;

      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        },
        body: body
      });

      if (!res.ok) {
        logDiagnostic("error", `Błąd HTTP ${res.status} ${res.statusText} podczas wywołania RPC ${rpcId}.`);
        return null;
      }

      const rawText = await res.text();
      const parsedData = this.parseBatchExecuteResponse(rawText, rpcId);
      if (!parsedData) {
        logDiagnostic("warn", `Nie udało się sparsować odpowiedzi dla RPC ${rpcId} (${rawText.length} bajtów). Początek: ${rawText.slice(0, 160)}...`);
        return null;
      }

      return parsedData;
    },

    /**
     * NATIVE CONVERSATION CATALOG DISCOVERY (MaZiqc)
     * Fetches recent & pinned conversations directly from Google's backend catalog.
     * Zero scrolling required!
     */
    async listConversations(options = {}) {
      const limit = options.limit || 100;
      const discovered = new Map();

      logDiagnostic("info", `[RPC MaZiqc] Pobieranie katalogu rozmów z serwera Google (limit: ${limit})...`);

      const configs = [
        { label: "przypięte", flag: 1 },
        { label: "standardowe", flag: 0 }
      ];

      for (const cfg of configs) {
        try {
          const innerPayload = [limit, null, [cfg.flag, null, 1]];
          const data = await this.executeRpc(RPC_LIST, innerPayload, "/app");
          if (!data) continue;

          const chatList = (Array.isArray(data) && Array.isArray(data[2])) ? data[2] : (Array.isArray(data) ? data : []);

          for (const item of chatList) {
            if (!Array.isArray(item) || item.length < 2) continue;

            const rawCid = String(item[0] || "");
            if (!rawCid) continue;
            const cleanId = rawCid.replace(/^c_/, "");
            const title = String(item[1] || `Gemini ${cleanId.slice(0, 8)}`).trim();
            const isPinned = Boolean(item[2]);

            let isoTime = new Date().toISOString();
            if (Array.isArray(item[5]) && typeof item[5][0] === "number") {
              const sec = item[5][0];
              const nanos = item[5][1] || 0;
              isoTime = new Date(sec * 1000 + Math.round(nanos / 1e6)).toISOString();
            }

            if (!discovered.has(cleanId)) {
              discovered.set(cleanId, {
                id: cleanId,
                title: title,
                url: `https://gemini.google.com/app/${cleanId}`,
                is_pinned: isPinned,
                timestamp: isoTime,
                section: isPinned ? "Przypięte" : "Historia",
                order: discovered.size
              });
            }
          }
        } catch (err) {
          logDiagnostic("warn", `Błąd pobierania rozmów ${cfg.label} przez MaZiqc: ${err.message}`);
        }
      }

      const results = Array.from(discovered.values());
      logDiagnostic("info", `[RPC MaZiqc] ✅ Wykryto ${results.length} rozmów bezpośrednio z API Google.`);
      return results;
    },

    /**
     * Extracts clean message turns from the inner chat data structure (hNvQHb).
     */
    extractTurns(chatData, rawConvId) {
      if (!chatData || !Array.isArray(chatData[0])) return [];
      const turns = chatData[0];
      const messages = [];

      // Regenerated responses leave several candidate drafts:
      // the one referenced by the next turn's parent pointer turn[1][2] is the branch actually continued.
      const chosenCandidates = {};
      for (const turn of turns) {
        if (Array.isArray(turn[1]) && typeof turn[1][2] === "string") {
          chosenCandidates[turn[1][2]] = true;
        }
      }

      const seenAttachments = new Set();

      for (let t = 0; t < turns.length; t++) {
        const turn = turns[t];
        if (!turn) continue;

        let isoTimestamp = new Date().toISOString();
        if (turn[4] && typeof turn[4][0] === "number") {
          const seconds = turn[4][0];
          const nanos = turn[4][1] || 0;
          isoTimestamp = new Date(seconds * 1000 + Math.round(nanos / 1e6)).toISOString();
        }

        // 1. User Message
        const userTurnId = (turn[0] && turn[0][1]) || `${rawConvId}_u_${t}`;
        let userText = "";
        if (turn[2] && Array.isArray(turn[2][0])) {
          userText = typeof turn[2][0][0] === "string" ? turn[2][0][0] : "";
        } else if (typeof turn[2] === "string") {
          userText = turn[2];
        }
        if (!userText && turn[2]) {
          userText = findDeepestString(turn[2]);
        }

        const attachments = [];
        if (turn[2]) {
          const names = collectFilenames(turn[2], []);
          names.forEach(name => {
            if (!seenAttachments.has(name)) {
              seenAttachments.add(name);
              attachments.push(name);
            }
          });
        }

        if (userText || attachments.length > 0) {
          let content = userText.trim();
          if (attachments.length > 0) {
            const attachMarker = `\n\n> [Załączniki: ${attachments.join(", ")}]`;
            content = content ? content + attachMarker : attachMarker.trim();
          }

          messages.push({
            id: userTurnId,
            author: "USER",
            role: "user",
            parts: [{ text: content }],
            attachments: attachments,
            created_at: isoTimestamp,
            step_index: 0
          });
        }

        // 2. Assistant Message
        const candidates = (turn[3] && Array.isArray(turn[3][0])) ? turn[3][0] : [];
        if (candidates.length > 0) {
          const pick = candidates.find(c => Array.isArray(c) && chosenCandidates[c[0]]) || candidates[0];
          const assistantId = (pick && pick[0]) || (turn[1] && turn[1][2]) || `${rawConvId}_a_${t}`;

          let assistantText = "";
          if (pick && Array.isArray(pick[1]) && typeof pick[1][0] === "string") {
            assistantText = pick[1][0];
          }
          if ((!assistantText || CARD_CONTENT_REGEX.test(assistantText)) && pick && Array.isArray(pick[22])) {
            assistantText = typeof pick[22][0] === "string" ? pick[22][0] : assistantText;
          }
          if (!assistantText && pick) {
            assistantText = findDeepestString(pick);
          }
          if (assistantText) {
            assistantText = assistantText.replace(ARTIFACTS_REGEX, "").trim();
          }

          let thoughts = "";
          if (pick && Array.isArray(pick[37]) && Array.isArray(pick[37][0]) && typeof pick[37][0][0] === "string") {
            thoughts = pick[37][0][0].trim();
          }

          if (assistantText) {
            messages.push({
              id: assistantId,
              author: "ASSISTANT",
              role: "assistant",
              parts: [{ text: assistantText }],
              thoughts: thoughts || null,
              created_at: isoTimestamp,
              step_index: 0
            });
          }
        }
      }

      return messages;
    },

    /**
     * Fetches conversation details via Google Gemini batchexecute RPC (hNvQHb).
     */
    async fetchConversation(sessionId, options = {}) {
      const cleanId = sessionId.replace(/^c_/, "");
      const convId = `c_${cleanId}`;
      const limit = options.limit || 100;

      logDiagnostic("info", `[RPC hNvQHb] Rozpoczęto pobieranie pełnej rozmowy dla ${cleanId}...`);

      let allMessages = [];
      let cursor = null;
      let page = 0;
      const maxPages = options.fetchAll !== false ? 50 : 1;

      while (page < maxPages) {
        page++;

        // Modern 8-element payload format: [convId, limit, cursor, 1, [0], [4], null, 1]
        let innerPayload = [convId, limit, cursor, 1, [0], [4], null, 1];
        let chatData = await this.executeRpc(RPC_TURNS, innerPayload, `/app/${cleanId}`);

        // If format A returned null, retry once with alternative candidate filter [1]
        if (!chatData) {
          innerPayload = [convId, limit, cursor, 1, [1], [4], null, 1];
          chatData = await this.executeRpc(RPC_TURNS, innerPayload, `/app/${cleanId}`);
        }

        // If still null, retry with legacy format [convId, limit, cursor]
        if (!chatData) {
          innerPayload = [convId, limit, cursor];
          chatData = await this.executeRpc(RPC_TURNS, innerPayload, `/app/${cleanId}`);
        }

        if (!chatData) {
          logDiagnostic("warn", `[RPC hNvQHb] Nie udało się uzyskać danych rozmowy dla ${cleanId}.`);
          return null;
        }

        const pageMessages = this.extractTurns(chatData, cleanId);
        if (pageMessages.length === 0 && allMessages.length === 0) {
          logDiagnostic("warn", `[RPC hNvQHb] Odpowiedź z serwera sparsowana, ale zawiera 0 wiadomości dla ${cleanId}.`);
          return null;
        }

        // Google returns turns newest first in chatData[0].
        if (cursor) {
          allMessages = pageMessages.concat(allMessages);
        } else {
          allMessages = pageMessages;
        }

        const nextCursor = (typeof chatData[1] === "string" && chatData[1]) ||
                           (typeof chatData[2] === "string" && chatData[2]) || null;
        if (!nextCursor || nextCursor === cursor) {
          break;
        }
        cursor = nextCursor;

        if (typeof options.onProgress === "function") {
          options.onProgress(allMessages.length, `Pobrano ${allMessages.length} wiadomości przez RPC (strona ${page})...`);
        }
      }

      // CRITICAL: Google returns turns newest first!
      // Reverse so the conversation flows chronologically from first message to last.
      allMessages.reverse();

      // Re-index steps sequentially
      allMessages.forEach((m, idx) => { m.step_index = idx; });

      // Title heuristic from first user turn
      let title = `Gemini ${cleanId.substring(0, 8)}`;
      const firstUserMsg = allMessages.find(m => m.author === "USER" || m.role === "user");
      if (firstUserMsg && firstUserMsg.parts && firstUserMsg.parts[0]?.text) {
        const firstLine = firstUserMsg.parts[0].text.split("\n")[0].replace(/^>\s*\[.*?\]\s*/, "").trim();
        if (firstLine.length > 0) {
          title = firstLine.substring(0, 100);
        }
      }

      logDiagnostic("info", `[RPC hNvQHb] ✅ Sukces! Pobrano łącznie ${allMessages.length} wiadomości dla "${title}" (${cleanId}).`);

      return {
        conversation_id: cleanId,
        title: title,
        url: `https://gemini.google.com/app/${cleanId}`,
        model: "gemini-2.5-pro",
        messages: allMessages
      };
    }
  };

  // ============================================================================
  // 2. TITLE EXTRACTION & HELPER UTILITIES
  // ============================================================================

  function isGenericTitle(title) {
    if (!title) return true;
    const lower = title.toLowerCase().trim();
    return (
      lower === "gemini" ||
      lower === "gemini chat" ||
      lower === "rozmowa z gemini" ||
      lower.startsWith("rozmowa z gemini") ||
      lower === "rozmowa gemini" ||
      lower === "chat with gemini" ||
      lower === "new chat" ||
      lower === "nowa rozmowa" ||
      lower === "nowy czat" ||
      lower === "untitled" ||
      lower.startsWith("gemini c_") ||
      /^gemini [a-f0-9]{8}$/i.test(lower)
    );
  }

  function extractGeminiTitle(convId, fallbackPrompt = "") {
    const cleanId = (convId || "").replace(/^c_/, "");

    // 1. If currently viewing this conversation, check document.title
    const currentPath = window.location.pathname || "";
    if (cleanId && currentPath.includes(cleanId) && document.title) {
      const docClean = document.title
        .replace(/\s*[-–|•]\s*Gemini.*$/i, "")
        .replace(/^Gemini\s*[-–|•]\s*/i, "")
        .trim();
      if (docClean && !isGenericTitle(docClean)) {
        return docClean;
      }
    }

    // 2. Check sidebar link text for this conversation
    const sidebarLink = document.querySelector(`a[href*="${cleanId}"]`);
    if (sidebarLink) {
      const titleElem = sidebarLink.querySelector(".conversation-title, [data-test-id='conversation-title'], .conversation-title-text, .title-text, .title");
      let rawText = titleElem ? titleElem.innerText : "";
      if (!rawText) {
        rawText = (sidebarLink.innerText || sidebarLink.textContent || "")
          .replace(/\b(chat|more_vert|delete|edit|share|menu|tune|pin|unpin)\b/gi, "")
          .trim();
      }
      const clean = rawText.split("\n")[0].trim().replace(/\s+/g, " ");
      if (clean && !isGenericTitle(clean)) {
        return clean;
      }
    }

    // 3. Specific conversation title element in the active panel (never generic h1 branding)
    const specificElems = document.querySelectorAll(
      "header [data-test-id='conversation-title'], [aria-label*='Tytuł czatu'], [aria-label*='Chat title']"
    );
    for (const elem of specificElems) {
      const text = (elem.innerText || "").trim().replace(/\n+/g, " ");
      if (text && !isGenericTitle(text)) {
        return text;
      }
    }

    // 4. Fallback to the first user prompt line if available
    if (fallbackPrompt && !isGenericTitle(fallbackPrompt)) {
      return fallbackPrompt;
    }

    return fallbackPrompt || `Gemini ${cleanId.substring(0, 8)}`;
  }

  // ============================================================================
  // 3. ACTIVE CHAT SYNC
  // ============================================================================

  let lastActiveSyncedId = null;
  let lastActiveMsgCount = 0;

  async function syncActiveChat(force = false) {
    const urlMatch = window.location.href.match(/\/(?:app|chat)\/([a-zA-Z0-9_-]{6,})/);
    if (!urlMatch) {
      logDiagnostic("debug", `Brak identyfikatora czatu Gemini w URL: ${window.location.href}`);
      return;
    }
    const convId = urlMatch[1];
    if (["library", "videos", "students", "search", "settings", "help", "prompts"].includes(convId.toLowerCase())) {
      return;
    }

    try {
      logDiagnostic("info", `Rozpoczęto synchronizację aktywnego czatu Gemini: ${convId} (force: ${force})`);
      // 1. Try RPC first (instant, full history, no DOM scrolling)
      const rpcConv = await GeminiRPCFetcher.fetchConversation(convId);
      if (rpcConv && rpcConv.messages.length > 0) {
        if (!force && lastActiveSyncedId === convId && rpcConv.messages.length === lastActiveMsgCount) {
          logDiagnostic("debug", `Aktywny czat ${convId} niezmieniony (${rpcConv.messages.length} msgs), pomijam.`);
          return;
        }

        // Resolve title (sidebar > prompt > fallback, never generic h1)
        rpcConv.title = extractGeminiTitle(convId, rpcConv.title);

        logDiagnostic("info", `Aktywny czat pobrany przez RPC: '${rpcConv.title}' (${rpcConv.messages.length} msgs)`, { convId, msgs: rpcConv.messages.length });

        await ext.runtime.sendMessage({
          type: "INGEST_PAYLOAD",
          platform: "gemini",
          payload: rpcConv,
          metadata: { device: "browser-extension", sync_method: "rpc" }
        });

        lastActiveSyncedId = convId;
        lastActiveMsgCount = rpcConv.messages.length;
        return;
      }
    } catch (err) {
      logDiagnostic("warn", `RPC fetch nie powiódł się dla ${convId}, przełączam na DOM: ${err.message}`);
    }

    // 2. Fallback: DOM scraping
    scrapeAndIngestDOM(convId, force);
  }

  function scrapeAndIngestDOM(convId, force = false) {
    try {
      const title = extractGeminiTitle(convId);

      const USER_SELECTORS = [
        "user-query",
        "[data-test-id='user-query']",
        ".user-query",
        "[class*='user-query']",
        ".query-content",
        "[class*='query-content']",
        "[class*='query-text']",
        "chat-turn [class*='user']"
      ].join(", ");

      const MODEL_SELECTORS = [
        "model-response",
        "[data-test-id='model-response']",
        ".model-response",
        "[class*='model-response']",
        "message-content",
        "markdown-renderer",
        "[class*='response-container']",
        "chat-turn [class*='model']"
      ].join(", ");

      const root = document.querySelector("main, [role='main'], chat-window") || document.body;
      let userEls = Array.from(root.querySelectorAll(USER_SELECTORS))
        .filter(el => !el.closest("aside, nav, side-navigation-v2, mat-sidenav, [role='navigation']"));
      let modelEls = Array.from(root.querySelectorAll(MODEL_SELECTORS))
        .filter(el => !el.closest("aside, nav, side-navigation-v2, mat-sidenav, [role='navigation']"));

      // Deduplicate nested elements
      userEls = userEls.filter(el => !userEls.some(other => other !== el && other.contains(el)));
      modelEls = modelEls.filter(el => !modelEls.some(other => other !== el && other.contains(el)));

      const turns = [];
      userEls.forEach(el => turns.push({ element: el, role: "user", author: "USER" }));
      modelEls.forEach(el => turns.push({ element: el, role: "assistant", author: "ASSISTANT" }));

      // Sort naturally in document DOM order
      turns.sort((a, b) => {
        if (a.element === b.element) return 0;
        const pos = a.element.compareDocumentPosition(b.element);
        if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
        if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
        return 0;
      });

      const messages = [];
      turns.forEach((turn, idx) => {
        const clone = turn.element.cloneNode(true);
        clone.querySelectorAll("button, .action-buttons, .copy-button, .edit-button, [aria-label*='Copy'], [aria-label*='Edit']").forEach(b => b.remove());
        const text = (clone.innerText || clone.textContent || "").trim();
        if (text) {
          messages.push({
            id: `${convId}_${turn.role}_${idx}`,
            author: turn.author,
            role: turn.role,
            parts: [{ text }],
            created_at: new Date().toISOString(),
            step_index: idx
          });
        }
      });

      if (messages.length > 0) {
        if (!force && lastActiveSyncedId === convId && messages.length === lastActiveMsgCount) {
          logDiagnostic("debug", `Aktywny czat ${convId} DOM niezmieniony (${messages.length} msgs), pomijam.`);
          return;
        }

        logDiagnostic("info", `Aktywny czat pobrany z DOM: '${title}' (${messages.length} wiadomości)`);

        ext.runtime.sendMessage({
          type: "INGEST_PAYLOAD",
          platform: "gemini",
          payload: {
            conversation_id: convId,
            title: title,
            model: "gemini-2.5-pro",
            messages: messages
          },
          metadata: { device: "browser-extension", sync_method: "dom" }
        });

        lastActiveSyncedId = convId;
        lastActiveMsgCount = messages.length;
      } else {
        logDiagnostic("warn", `DOM fallback: Nie znaleziono wiadomości dla czatu ${convId}. Sprawdź selektory.`);
      }
    } catch (e) {
      logDiagnostic("error", `Błąd DOM scraping fallback: ${e.message}`);
    }
  }

  // ============================================================================
  // 4. SMART CATCH-UP & SIDEBAR CRAWLER (with MaZiqc Catalog Integration)
  // ============================================================================

  let isCatchUpRunning = false;

  // Passive link scanner for sidebar (zero DOM manipulation, zero clicks, zero scrolling)
  function collectVisibleLinks(conversationsMap) {
    const links = document.querySelectorAll('a[href*="/app/"]');
    let addedCount = 0;

    links.forEach((link) => {
      const href = link.getAttribute("href") || link.href || "";
      const match = href.match(/\/app\/([a-zA-Z0-9_-]{6,})/);
      if (match) {
        const id = match[1];
        if (["library", "videos", "students", "search", "settings", "help", "prompts"].includes(id.toLowerCase())) {
          return;
        }
        if (!conversationsMap.has(id)) {
          const titleEl = link.querySelector('[class*="title"], [class*="text"], span, div');
          let title = titleEl?.innerText ||
                      link.getAttribute("title") ||
                      link.getAttribute("aria-label") ||
                      link.innerText || "";
          title = title.replace(/\n+/g, " ").trim();
          if (!title || isGenericTitle(title)) {
            title = `Gemini ${id.substring(0, 8)}`;
          }

          conversationsMap.set(id, {
            id: id,
            title: title,
            href: link.href || `https://gemini.google.com/app/${id}`
          });
          addedCount++;
        }
      }
    });

    return addedCount;
  }

  /**
   * Discover conversations cleanly and completely non-intrusively:
   * 1. Primary: Google's native RPC MaZiqc discovers up to 100/200 pinned & recent chats instantly in background.
   * 2. Passive Fallback: Read any existing visible /app/ links from current DOM without clicking or scrolling.
   */
  async function discoverAllSidebarConversations(deepScan = false) {
    const conversations = new Map();

    // 1. First, query Google's native catalog RPC (MaZiqc) - discovers all pinned & recent chats instantly
    try {
      const rpcItems = await GeminiRPCFetcher.listConversations({ limit: deepScan ? 200 : 100 });
      if (Array.isArray(rpcItems) && rpcItems.length > 0) {
        for (const item of rpcItems) {
          conversations.set(item.id, {
            id: item.id,
            title: item.title,
            href: item.url || `https://gemini.google.com/app/${item.id}`,
            is_pinned: item.is_pinned,
            timestamp: item.timestamp
          });
        }
        logDiagnostic("info", `[Smart Catch-Up] Wykryto ${rpcItems.length} rozmów bezpośrednio z API Google (MaZiqc).`);
      }
    } catch (rpcErr) {
      logDiagnostic("warn", `[Smart Catch-Up] Błąd pobierania katalogu przez MaZiqc: ${rpcErr.message}`);
    }

    // 2. Passive scan: collect any visible links from DOM (zero clicking, zero scroll events)
    try {
      const domCount = collectVisibleLinks(conversations);
      if (domCount > 0) {
        logDiagnostic("debug", `[Smart Catch-Up] Dodano ${domCount} rozmów z aktualnie otwartego paska bocznego.`);
      }
    } catch (domErr) {
      logDiagnostic("debug", `[Smart Catch-Up] Błąd pasywnego odczytu linków: ${domErr.message}`);
    }

    return Array.from(conversations.values());
  }

  async function runSmartCatchUpSync(deepScan = false) {
    if (isCatchUpRunning) return;
    isCatchUpRunning = true;

    try {
      logDiagnostic("info", "Inicjalizacja inteligentnej synchronizacji historii Gemini...");

      // Krok 1: Pobierz znane konwersacje z bazy danych Brain
      const statusRes = await new Promise((resolve) => {
        ext.runtime.sendMessage(
          { type: "GET_SYNC_STATUS", platform: "gemini", limit: 300 },
          (res) => resolve(res)
        );
      });

      const dbMap = (statusRes && statusRes.status === "success" && statusRes.result?.conversations) || {};

      // Krok 2: Wyszukaj wszystkie rozmowy za pomocą MaZiqc API + uzupełnienia z DOM
      const convItems = await discoverAllSidebarConversations(deepScan);
      logDiagnostic("info", `Wykryto łącznie ${convItems.length} rozmów w katalogu Gemini.`);

      if (convItems.length === 0) {
        logDiagnostic("info", "Brak konwersacji w katalogu ani w DOM. Oczekiwanie na interakcję użytkownika.");
        return;
      }

      // Krok 3: Wybierz kandydatów (brakujące w bazie lub pierwsze 10 z nowymi wiadomościami)
      const candidates = [];
      const currentUrlMatch = window.location.href.match(/\/(?:app|chat)\/([a-zA-Z0-9_-]{6,})/);
      const activeId = currentUrlMatch ? currentUrlMatch[1] : null;

      for (let i = 0; i < convItems.length; i++) {
        const item = convItems[i];
        if (activeId && item.id === activeId) {
          continue; // Aktualnie otwarty czat jest obsługiwany przez syncActiveChat
        }

        const inDb = dbMap[item.id];
        if (!inDb) {
          candidates.push({ id: item.id, title: item.title, reason: "missing_in_db" });
        } else if (i < 10) {
          const knownCount = inDb.message_count || 0;
          candidates.push({ id: item.id, title: item.title, reason: "recent_active_check", knownCount });
        }
      }

      if (candidates.length === 0) {
        logDiagnostic("info", `Wszystkie ${convItems.length} wykryte rozmowy są już zsynchronizowane z bazą Brain.`);
        return;
      }

      logDiagnostic("info", `Znaleziono ${candidates.length} rozmów do pobrania w tle przez Google RPC (hNvQHb):`, candidates);

      // Krok 4: Pobieraj rozmowy sekwencyjnie w tle przez natywny RPC (hNvQHb)
      let consecutiveErrors = 0;
      for (const item of candidates) {
        await new Promise((r) => setTimeout(r, 1200));

        try {
          const conv = await GeminiRPCFetcher.fetchConversation(item.id);
          if (!conv || !conv.messages || conv.messages.length === 0) {
            logDiagnostic("warn", `Pusta odpowiedź RPC dla czatu ${item.id}`);
            continue;
          }

          if (item.knownCount && conv.messages.length <= item.knownCount) {
            logDiagnostic("debug", `Brak nowych wiadomości w ${item.id} (${conv.messages.length} vs znane ${item.knownCount}), pomijam.`);
            continue;
          }

          if (item.title && !isGenericTitle(item.title)) {
            conv.title = item.title;
          } else {
            conv.title = extractGeminiTitle(item.id, conv.title);
          }

          logDiagnostic("info", `Pobrano w tle przez RPC '${conv.title}' (${conv.messages.length} msgs, powód: ${item.reason}). Ingestuję...`);

          const ingestRes = await new Promise((resolve) => {
            ext.runtime.sendMessage({
              type: "INGEST_PAYLOAD",
              platform: "gemini",
              payload: conv,
              metadata: {
                device: "browser-extension",
                sync_method: "smart_catchup",
                reason: item.reason
              }
            }, (res) => resolve(res));
          });

          if (ingestRes && ingestRes.status === "success") {
            logDiagnostic("info", `✅ Zsynchronizowano czat ${item.id}: '${conv.title}' (${conv.messages.length} wiadomości)`);
            consecutiveErrors = 0;
          } else {
            consecutiveErrors++;
            logDiagnostic("warn", `Błąd zapisu czatu ${item.id}: ${ingestRes?.message || "Nieznany błąd"}`);
            if (consecutiveErrors >= 5) {
              logDiagnostic("warn", `Wstrzymano pobieranie po ${consecutiveErrors} błędach.`);
              break;
            }
          }
        } catch (itemErr) {
          consecutiveErrors++;
          logDiagnostic("error", `Błąd pobierania RPC dla ${item.id}: ${itemErr.message}`);
          if (consecutiveErrors >= 5) {
            logDiagnostic("warn", `Wstrzymano pobieranie po ${consecutiveErrors} błędach.`);
            break;
          }
        }
      }

      logDiagnostic("info", `🏁 Zakończono synchronizację w tle dla ${candidates.length} rozmów Gemini.`);
    } catch (err) {
      logDiagnostic("error", `Błąd procedury synchronizacji: ${err.message}`);
    } finally {
      isCatchUpRunning = false;
    }
  }

  // ============================================================================
  // 5. TRIGGERS, SPA URL WATCHER & MUTATION OBSERVER
  // ============================================================================

  // Listen for background alarm triggers
  ext.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "TRIGGER_DELTA_SYNC" || msg.type === "TRIGGER_FULL_BACKFILL") {
      logDiagnostic("info", `Odebrano sygnał ${msg.type} (force: ${Boolean(msg.force)}) dla ${window.location.pathname}`);
      syncActiveChat(Boolean(msg.force));
      const isDeep = msg.type === "TRIGGER_FULL_BACKFILL";
      setTimeout(() => runSmartCatchUpSync(isDeep), 800);
      if (sendResponse) sendResponse({ status: "acknowledged", convId: window.location.pathname });
      return true;
    }
  });

  // Fast URL watcher for Single Page Application navigation
  let lastSeenUrl = window.location.href;
  function checkUrlChange() {
    if (window.location.href !== lastSeenUrl) {
      lastSeenUrl = window.location.href;
      logDiagnostic("debug", `Detected SPA URL change to: ${window.location.pathname}`);
      hasAttemptedExpand = false;
      syncActiveChat();
      setTimeout(() => runSmartCatchUpSync(false), 2500);
    }
  }

  // Intercept history.pushState and history.replaceState for instant SPA transition detection
  const origPushState = history.pushState;
  if (origPushState) {
    history.pushState = function (...args) {
      const res = origPushState.apply(this, args);
      setTimeout(checkUrlChange, 50);
      return res;
    };
  }
  const origReplaceState = history.replaceState;
  if (origReplaceState) {
    history.replaceState = function (...args) {
      const res = origReplaceState.apply(this, args);
      setTimeout(checkUrlChange, 50);
      return res;
    };
  }

  // Intercept user clicks on links/chats for instant sync
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!target) return;
    const link = target.closest ? target.closest("a[href]") : null;
    if (link) {
      const href = link.getAttribute("href") || link.href || "";
      const match = href.match(/\/(?:app|chat)\/([a-zA-Z0-9_-]{6,})/);
      if (match) {
        logDiagnostic("debug", `User clicked conversation link: ${match[1]}`);
        setTimeout(syncActiveChat, 800);
      }
    }
  }, true);

  setInterval(checkUrlChange, 1000);
  window.addEventListener("popstate", () => {
    hasAttemptedExpand = false;
    setTimeout(syncActiveChat, 300);
    setTimeout(() => runSmartCatchUpSync(false), 1500);
  });

  // Watch for DOM changes in active chat
  let syncTimer = null;
  const debouncedSync = () => {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncActiveChat, 2000);
  };

  const observer = new MutationObserver(debouncedSync);
  const container = document.querySelector("main") || document.body;
  if (container) {
    observer.observe(container, { childList: true, subtree: true });
  }

  // Initial sync on tab load
  setTimeout(syncActiveChat, 1500);

  // Catch-up check after catalog & sidebar render (3.5 seconds after load)
  setTimeout(() => runSmartCatchUpSync(false), 3500);
})();
