/**
 * Brain LLM Archive - ChatGPT Interactive Console Probe & Sync Extractor (v1.0.11)
 * 
 * Sposób użycia w konsoli DevTools (F12) na https://chatgpt.com:
 * 1. Wklej ten skrypt do konsoli i naciśnij Enter.
 * 2. Przetestuj pobranie rozmowy:
 *    const chat = await ChatGPTProbe.getConversation("6ab66273-7f38-83eb-b06c-40314e108cbb");
 *    console.log(chat);
 * 3. Zbadaj elementy paska bocznego w DOM:
 *    ChatGPTProbe.inspectDOM();
 * 4. Skopiuj pełny payload rozmowy do schowka (gotowy format ingest):
 *    await ChatGPTProbe.copyPayload("6ab66273-7f38-83eb-b06c-40314e108cbb");
 */

(function () {
  const BRIDGE_URL = "http://127.0.0.1:3040";

  const Logger = {
    send(level, message, details = null) {
      const styles = {
        info: "color: #00bcd4; font-weight: bold",
        success: "color: #4caf50; font-weight: bold",
        warn: "color: #ff9800; font-weight: bold",
        error: "color: #f44336; font-weight: bold"
      };
      console.log(`%c[Brain ChatGPT Probe ${level.toUpperCase()}] %c${message}`, styles[level] || "", "color: inherit", details || "");
      // Uwaga: fetch do 127.0.0.1 z konsoli strony jest blokowany przez CSP strony chatgpt.com.
      // W rozszerzeniu (extension) zapytania wysyła background.js, który ma host_permissions i omija CSP strony.
    }
  };

  const ChatGPTProbe = {
    token: null,
    userInfo: null,
    lastFetchedConversation: null,

    // 1. Pobranie tokena sesyjnego (Bearer) z NextAuth
    async getSessionToken(forceRefresh = false) {
      if (this.token && !forceRefresh) return this.token;
      Logger.send("info", "Pobieranie tokena sesyjnego z /api/auth/session...");
      try {
        const resp = await fetch("/api/auth/session", { credentials: "include" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
        const data = await resp.json();
        if (!data.accessToken) throw new Error("Brak accessToken w odpowiedzi sesji.");
        this.token = data.accessToken;
        this.userInfo = data.user;
        Logger.send("success", `Uzyskano token sesyjny dla: ${data.user?.email || "użytkownika"} (wygasa: ${data.expires})`);
        return this.token;
      } catch (err) {
        Logger.send("error", `Nie udało się pobrać sesji: ${err.message}`);
        return null;
      }
    },

    // 2. Pobieranie listy konwersacji przez oficjalne backend-api ChatGPT
    async listAPI(limit = 20, offset = 0) {
      const token = await this.getSessionToken();
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const url = `/backend-api/conversations?offset=${offset}&limit=${limit}&order=updated`;
      Logger.send("info", `Pobieranie listy rozmów: GET ${url}`);
      try {
        const resp = await fetch(url, { headers, credentials: "include" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
        const data = await resp.json();
        const items = data.items || [];
        Logger.send("success", `Otrzymano ${items.length} rozmów z backend-api (łącznie: ${data.total || "?"})`);
        console.table(items.map(it => ({
          id: it.id,
          title: it.title,
          updated_at: it.update_time,
          created_at: it.create_time
        })));
        return items;
      } catch (err) {
        Logger.send("error", `Błąd listAPI: ${err.message}`);
        return [];
      }
    },

    // 3. Szczegółowa inspekcja drzewa DOM w poszukiwaniu paska bocznego
    inspectDOM() {
      console.log("%c--- INSPEKCJA DOM PASKA BOCZNEGO CHATGPT ---", "color: #9c27b0; font-weight: bold");
      
      const navElements = document.querySelectorAll("nav, aside, [role='navigation']");
      console.log(`1. Kontenery nawigacji (nav/aside/[role=navigation]): ${navElements.length}`);
      navElements.forEach((el, idx) => {
        console.log(`   [${idx}] <${el.tagName.toLowerCase()}> class="${el.className.slice(0, 80)}" aria-label="${el.getAttribute('aria-label') || ''}" visible=${el.offsetParent !== null}`);
      });

      const allLinks = Array.from(document.querySelectorAll("a"));
      const chatLinks = allLinks.filter(a => {
        const h = a.getAttribute("href") || "";
        return h.includes("/c/") || h.includes("/chat/") || h.includes("/g/");
      });

      console.log(`2. Wszystkie linki <a> na stronie: ${allLinks.length}, linki pasujące do rozmów: ${chatLinks.length}`);
      if (chatLinks.length > 0) {
        console.log("   Przykładowe linki rozmów:");
        chatLinks.slice(0, 5).forEach(l => {
          console.log(`   - href="${l.getAttribute('href')}" text="${l.innerText.trim().slice(0, 40)}"`);
        });
      } else {
        console.log("   ⚠️ Brak linków z '/c/'. Sprawdzam elementy z atrybutami data-testid lub historią...");
        const testIdElements = document.querySelectorAll("[data-testid*='history'], [data-testid*='conversation'], [data-testid*='chat']");
        console.log(`   Elementy z data-testid (*history*, *conversation*, *chat*): ${testIdElements.length}`);
        testIdElements.forEach(el => console.log(`   - <${el.tagName.toLowerCase()} data-testid="${el.getAttribute('data-testid')}">`));
      }

      // Sprawdzenie czy pasek boczny jest zwinięty
      const toggleBtn = document.querySelector("button[aria-label*='sidebar' i], button[aria-label*='pasek' i], button[data-testid*='sidebar' i]");
      if (toggleBtn) {
        console.log(`3. Przycisk zwijania/rozwijania paska: <button aria-label="${toggleBtn.getAttribute('aria-label')}">`);
      }
      return { navCount: navElements.length, chatLinksCount: chatLinks.length };
    },

    // 4. Ekstrakcja listy konwersacji z DOM (z poszerzonymi selektorami)
    scanSidebar() {
      Logger.send("info", "Skanowanie widocznego drzewa DOM paska bocznego...");
      
      const selectors = [
        'nav a[href*="/c/"]',
        'aside a[href*="/c/"]',
        '[role="navigation"] a[href*="/c/"]',
        'a[href*="/c/"]',
        'nav a[href*="/chat/"]',
        'a[href*="/chat/"]'
      ];

      let links = [];
      for (const sel of selectors) {
        links = Array.from(document.querySelectorAll(sel));
        if (links.length > 0) break;
      }

      if (links.length === 0) {
        Logger.send("warn", "Nie znaleziono linków rozmów w DOM paska bocznego. Uruchom ChatGPTProbe.inspectDOM() aby zbadać strukturę.");
        return [];
      }

      const results = [];
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

        results.push({
          id: convId,
          title: title || `Rozmowa ${convId.substring(0, 8)}`,
          href: href,
          is_active: window.location.pathname.includes(convId)
        });
      }

      Logger.send("success", `Znaleziono ${results.length} konwersacji w pasku bocznym DOM`);
      console.table(results);
      return results;
    },

    // 5. Pobieranie pełnej zawartości pojedynczej konwersacji
    async getConversation(id) {
      if (!id) {
        Logger.send("error", "Wymagane ID konwersacji!");
        return null;
      }
      const token = await this.getSessionToken();
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const url = `/backend-api/conversation/${id}`;
      Logger.send("info", `Pobieranie pełnej rozmowy: GET ${url}`);
      try {
        const resp = await fetch(url, { headers, credentials: "include" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
        const data = await resp.json();
        this.lastFetchedConversation = data;

        const mappingKeys = Object.keys(data.mapping || {});
        let msgCount = 0;
        for (const k of mappingKeys) {
          if (data.mapping[k]?.message) msgCount++;
        }
        Logger.send("success", `✅ Pobrano rozmowę: "${data.title}" (${msgCount} wiadomości, ID: ${data.conversation_id || id})`);
        return data;
      } catch (err) {
        Logger.send("error", `Błąd getConversation ${id}: ${err.message}`);
        return null;
      }
    },

    // 6. Skopiowanie gotowego payloadu do schowka
    async copyPayload(id) {
      const fullData = await this.getConversation(id);
      if (!fullData) return;

      const payload = {
        platform: "chatgpt",
        payload: fullData,
        metadata: {
          conversation_id: id,
          title: fullData.title,
          device: "rog",
          sync_method: "console_probe"
        }
      };

      const jsonStr = JSON.stringify(payload, null, 2);
      await navigator.clipboard.writeText(jsonStr);
      Logger.send("success", `📋 Skopiowano pełny payload JSON rozmowy "${fullData.title}" (${jsonStr.length} znaków) do schowka!`);
      console.log("Możesz teraz przetestować curl w terminalu:");
      console.log(`curl -X POST http://127.0.0.1:3040/ingest -H "Content-Type: application/json" -d @<(xclip -o -selection clipboard)`);
    }
  };

  window.ChatGPTProbe = ChatGPTProbe;
  console.log("%c[Brain LLM Sync] ChatGPTProbe v1.0.11 załadowany!", "color: #4caf50; font-weight: bold; font-size: 14px");
})();
