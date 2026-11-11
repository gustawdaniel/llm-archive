// Main-world Token Bridge for Google Gemini (gemini.google.com)
// Runs in the page's execution context (world: "MAIN") to safely expose
// WIZ CSRF token (SNlM0e) and build label (cfb2h) without violating CSP.

(function () {
  function exposeTokens() {
    try {
      const wiz = window.WIZ_global_data;
      if (wiz && wiz.SNlM0e) {
        document.documentElement.dataset.geminiAt = wiz.SNlM0e;
        document.documentElement.dataset.geminiBl = wiz.cfb2h || "boq_assistant-bard-web-server";
        document.documentElement.dataset.geminiSid = wiz.FdrFJe || "";
      }
    } catch (err) {
      // Ignored in main world
    }
  }

  exposeTokens();
  // Periodically refresh in case WIZ_global_data initializes after DOM start
  const timer = setInterval(exposeTokens, 1500);
  setTimeout(() => clearInterval(timer), 30000);
})();
