# Brain LLM Sync Browser Extension (Chrome & Firefox)

Rozszerzenie przeglądarkowe do automatycznej i okresowej synchronizacji historii czatów z serwisów webowych (**ChatGPT**, **Claude**, **DeepSeek**, **Grok**, **Google Gemini**) bezpośrednio do Twojej lokalnej bazy wiedzy Brain (`brain_knowledge` na PostgreSQL 16 + pgvector).

Działa w 100% natywnie zarówno w przeglądarkach **Firefox** (Gecko) jak i **Chromium** (Chrome, Brave, Edge, Opera, Arc).

---

## 🚀 Błyskawiczna instalacja (Automatyczna dla wszystkich przeglądarek)

Najprostszą metodą instalacji jest uruchomienie zintegrowanego instalatora:

```bash
# Z katalogu repozytorium:
brain ext install

# Lub bezpośrednio ze skryptu w tym folderze:
./install.sh
```

Skrypt automatycznie:
- Kompiluje wersje dla Chromium i Firefox (`build.py`).
- Wstrzykuje stały klucz RSA i ID Chromium: `elbboflhncejfnmfjkfhilochellanjh`.
- Instaluje plik `.xpi` i konfiguruje `user.js` we wszystkich profilach **Zen Browser** oraz **Mozilla Firefox**.
- Rejestruje polityki Enterprise (`policies.json`) z uprawnieniem `force_installed`.
- Rejestruje `External Extensions` dla **Google Chrome**, **Chromium** oraz **Microsoft Edge**.
- Uruchamia i sprawdza stan daemona proxy/loggera na porcie `3040`.

---

## 🛠 Ręczna instalacja i debugowanie

### Opcja A: Mozilla Firefox / Zen Browser (Gecko)

1. **Zarządzanie dodatkami**:
   - Otwórz: `about:addons` — lista zainstalowanych dodatków.
2. **Debugowanie i wczytywanie na żywo**:
   - Otwórz: `about:debugging#/runtime/this-firefox`
   - Kliknij **"Wczytaj dodatek tymczasowy..."** (*Load Temporary Add-on*).
   - Wybierz plik:
     * `dist/firefox/manifest.json` (wersja deweloperska rozpakowana), LUB
     * `dist/brain-llm-sync-firefox.xpi` (gotowy pakiet produkcyjny).
   - Przycisk **"Przeładuj"** (*Reload*) natychmiast aplikuje Twoje zmiany w kodzie bez restartu przeglądarki!

---

### Opcja B: Google Chrome / Chromium / Brave / Edge

1. Otwórz w przeglądarce: `chrome://extensions` (lub `edge://extensions`).
2. Włącz przełącznik **"Tryb dewelopera"** (*Developer mode*) w prawym górnym rogu.
3. Kliknij **"Załaduj rozpakowane"** (*Load unpacked*).
4. Wybierz folder:
   - `dist/chrome/` (dzięki wbudowanemu kluczowi RSA rozszerzenie ma zawsze stałe ID: `elbboflhncejfnmfjkfhilochellanjh`).

---

## 🖥️ Diagnostyka i Logi na Żywo (`brain ext`)

Wtyczka wysyła zdarzenia i błędy do lokalnego loggera działającego pod `http://127.0.0.1:3040`:

```bash
# Podgląd logów synchronizacji w czasie rzeczywistym
brain ext logs

# Sprawdzenie statusu serwera proxy / loggera
brain ext status

# Test odpowiedzi HTTP healthcheck
curl http://127.0.0.1:3040/health
```

## 🛠 Narzędzia i Budowanie

Projekt posiada zintegrowany generator i linter:

- **Budowanie obu dystrybucji**:
  ```bash
  python3 build.py
  ```
  Generuje:
  - `dist/chrome/` – manifest Chromium MV3 (`service_worker`)
  - `dist/firefox/` – manifest Firefox MV3 (`scripts`, `gecko.id: brain-llm-sync@brain-os.local`)
  - `dist/brain-llm-sync-chrome.zip` – paczka dla Chrome Web Store
  - `dist/brain-llm-sync-firefox.xpi` / `.zip` – paczka dla AMO (Firefox Add-ons)

- **Weryfikacja Mozilla Web-Ext**:
  ```bash
  npx -y web-ext lint --source-dir dist/firefox
  ```
  *Wynik: 0 błędów, 0 ostrzeżeń.*

- **Testy jednostkowe**:
  ```bash
  cd ../ && uv run pytest tests/test_extension.py
  ```

---

## 🔄 Architektura Cross-Browser

1. **Uniwersalny runtime API**:
   Wszystkie skrypty używają `const ext = globalThis.browser || globalThis.chrome;`, co gwarantuje pełną zgodność z modelem asynchronicznym w obu środowiskach.
2. **Dual-mode Background**:
   - Chromium korzysta z Service Workera (`background.service_worker`).
   - Firefox korzysta z Event Page (`background.scripts`).
3. **Prywatność i uprawnienia Gecko**:
   Zgodność z wytycznymi AMO od listopada 2025 (`data_collection_permissions: { required: ["none"] }`).
