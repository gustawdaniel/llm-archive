/**
 * Brain LLM Archive - DeepSeek Interactive Console Probe
 * 
 * Sposób użycia:
 * 1. Otwórz https://chat.deepseek.com w przeglądarce i zaloguj się.
 * 2. Otwórz DevTools (F12) -> Console.
 * 3. Wklej ten kod i naciśnij Enter.
 * 4. Uruchom:
 *    await DeepSeekProbe.diagnose("5089000b-129b-4dcd-b31e-501017b5548e");
 * 5. Skopiuj pełny payload z treścią do schowka:
 *    await DeepSeekProbe.copyPayload("5089000b-129b-4dcd-b31e-501017b5548e");
 */

(function () {
  const DeepSeekProbe = {
    getToken() {
      try {
        const raw = localStorage.getItem("userToken");
        if (!raw) return null;
        return JSON.parse(raw).value;
      } catch (e) {
        return null;
      }
    },

    async testEndpoints(sessionId) {
      const token = this.getToken();
      console.log("%c[DeepSeek Probe] Token autoryzacyjny:", "color: #4caf50; font-weight: bold", token ? "Znaleziony ✅" : "BRAK ❌ (zaloguj się ponownie)");

      const headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
      };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      // Endpoint A (stary, błędny z v1.0.0 bez cache_version)
      const urlA = `/api/v0/chat_session/history_messages?chat_session_id=${sessionId}`;
      console.log(`\n%c1. Testowanie Endpoint A (stary z chat_session): ${urlA}`, "color: #ff9800; font-weight: bold");
      try {
        const respA = await fetch(urlA, { headers, credentials: "include" });
        console.log(`   Status: HTTP ${respA.status}`);
        const jsonA = await respA.json();
        const msgsA = jsonA.data?.biz_data?.chat_messages || jsonA.data?.chat_messages || [];
        console.log(`   Liczba wiadomości: ${msgsA.length}`);
        if (msgsA[0]) {
          console.log("   Klucze w pierwszej wiadomości:", Object.keys(msgsA[0]));
          console.log("   Próbka treści:", {
            content: msgsA[0].content,
            text: msgsA[0].text,
            role: msgsA[0].role
          });
        }
      } catch (e) {
        console.error("   Błąd Endpoint A:", e);
      }

      // Endpoint B (używany przez deepseek-exporter)
      const urlB = `/api/v0/chat/history_messages?chat_session_id=${sessionId}&cache_version=0`;
      console.log(`\n%c2. Testowanie Endpoint B (z deepseek-exporter): ${urlB}`, "color: #00bcd4; font-weight: bold");
      try {
        const respB = await fetch(urlB, { headers, credentials: "include" });
        console.log(`   Status: HTTP ${respB.status}`);
        const jsonB = await respB.json();
        const dataB = jsonB.data?.biz_data || jsonB.data || {};
        const msgsB = dataB.chat_messages || [];
        console.log(`   Liczba wiadomości: ${msgsB.length}`);
        if (msgsB[0]) {
          console.log("   Klucze w pierwszej wiadomości:", Object.keys(msgsB[0]));
          console.log("   Próbka treści wiadomości 1 (User):", {
            role: msgsB[0].role,
            content_preview: (msgsB[0].content || msgsB[0].text || "").slice(0, 150),
            thinking_preview: (msgsB[0].thinking_content || "").slice(0, 150)
          });
        }
        if (msgsB[1]) {
          console.log("   Próbka treści wiadomości 2 (Assistant):", {
            role: msgsB[1].role,
            content_preview: (msgsB[1].content || msgsB[1].text || "").slice(0, 150),
            thinking_preview: (msgsB[1].thinking_content || "").slice(0, 150)
          });
        }
      } catch (e) {
        console.error("   Błąd Endpoint B:", e);
      }
    },

    async copyPayload(sessionId) {
      const token = this.getToken();
      const headers = { "Accept": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const url = `/api/v0/chat/history_messages?chat_session_id=${sessionId}&cache_version=0`;
      const resp = await fetch(url, { headers, credentials: "include" });
      const json = await resp.json();
      const data = json.data?.biz_data || json.data || {};
      const payload = {
        platform: "deepseek",
        payload: {
          chat_session: data.chat_session || { id: sessionId, title: "Zastąpienie Claude Code" },
          chat_messages: data.chat_messages || []
        },
        metadata: {
          conversation_id: sessionId,
          title: data.chat_session?.title || "Zastąpienie Claude Code",
          device: "rog",
          sync_method: "console_probe"
        }
      };

      const str = JSON.stringify(payload, null, 2);
      await navigator.clipboard.writeText(str);
      console.log(`%c[DeepSeek Probe] Pomyślnie skopiowano payload (${str.length} znaków) do schowka!`, "color: #4caf50; font-weight: bold");
      console.log("Możesz teraz wkleić ten payload bezpośrednio do ingest w terminalu:");
      console.log("xclip -selection clipboard -o | curl -X POST http://127.0.0.1:3040/ingest -H 'Content-Type: application/json' -d @-");
    },

    async diagnose(sessionId = null) {
      if (!sessionId) {
        const match = window.location.pathname.match(/\/a\/chat\/s\/([a-f0-9-]+)/);
        sessionId = match ? match[1] : "5089000b-129b-4dcd-b31e-501017b5548e";
      }
      console.log(`%c=== DIAGNOSTYKA DEEPSEEK DLA ROZMOWY: ${sessionId} ===`, "color: #9c27b0; font-weight: bold; font-size: 15px");
      await this.testEndpoints(sessionId);
    }
  };

  window.DeepSeekProbe = DeepSeekProbe;
  console.log("%c[Brain LLM Sync] DeepSeekProbe załadowany! Wpisz: await DeepSeekProbe.diagnose()", "color: #4caf50; font-weight: bold; font-size: 14px");
})();
