# Publishing Brain LLM Sync (Chrome Web Store, Firefox Add-ons)

Store texts and permission justifications: [`STORE_LISTING.md`](STORE_LISTING.md). Privacy policy: [`PRIVACY.md`](PRIVACY.md).

## How releases flow

```
monorepo brain (private)                 public repo gustawdaniel/llm-archive
apps/llm-archive/  ── make publish ──▶   extension/ + .github/workflows/extension.yml
                       (tag vYYYY.MM.N)          │ tag v* (free GitHub runner)
                                                 ▼
                                build → pytest → web-ext lint → artifacts
                                 └─ if extension/manifest.json "version" changed
                                    since the previous tag:
                                    Chrome Web Store: chrome-webstore-upload-cli (upload + publish)
                                    Firefox AMO:      web-ext sign --channel listed
```

- The stores are updated **only when the extension version changes**; bump it with `python extension/build.py --bump patch` before tagging. Other releases of the repo only build, test and lint the extension.
- Browsers update the installed extension automatically once the store publishes the new version (Chrome after its review, Firefox after AMO review).
- Manual run: *Actions → Browser extension → Run workflow*, option `publish` uploads even without a version change (the stores still reject a version that is not higher than the published one).

## Packages (`python extension/build.py` → `extension/dist/`)

| File | For |
|---|---|
| `brain-llm-sync-chrome-store.zip` | Chrome Web Store (MV3, no `key` field — the store rejects it) |
| `brain-llm-sync-chrome.zip` | local unpacked install in Chromium (contains `key` → stable ID) |
| `brain-llm-sync-firefox.xpi` / `.zip` | Firefox AMO (MV3, `background.scripts`, gecko ID `brain-llm-sync@brain-os.local`) |

## First version (by hand, once per store)

The first upload creates the listing (and, in Chrome, the extension ID). Use the texts from `STORE_LISTING.md`.

1. **Chrome:** [Developer Dashboard](https://chrome.google.com/webstore/devconsole) → *New item* → upload `brain-llm-sync-chrome-store.zip` → fill *Store listing*, *Privacy practices*, *Distribution* (public) → *Submit for review*. Leave *Official URL* empty: it accepts only sites verified in Google Search Console, which github.com cannot be; the repository goes in *Homepage URL* and *Support URL*. The extension ID is in the item URL.
2. **Firefox:** [Submit a new add-on](https://addons.mozilla.org/developers/addon/submit/) → *On this site* (listed) → upload `brain-llm-sync-firefox.xpi` → source code: *No* → fill listing → submit.

## Secrets in `gustawdaniel/llm-archive` (Settings → Secrets and variables → Actions)

| Secret | Where to get it |
|---|---|
| `CHROME_PUBLISHER_ID` | the ID in the Developer Dashboard URL: `chrome.google.com/webstore/devconsole/<publisher-id>` |
| `CHROME_EXTENSION_ID` | `mehkfmeloifcbdhbeojfbnledbgnlmnf` (from the item URL after the first upload) |
| `CHROME_CLIENT_ID`, `CHROME_CLIENT_SECRET`, `CHROME_REFRESH_TOKEN` | Google Cloud project with **Chrome Web Store API** enabled → OAuth client → refresh token with scope `https://www.googleapis.com/auth/chromewebstore`. Step-by-step guide: https://github.com/fregante/chrome-webstore-upload-keys |
| `AMO_JWT_ISSUER`, `AMO_JWT_SECRET` | https://addons.mozilla.org/developers/addon/api/key/ → *Generate new credentials* |

Without the secrets the workflow still builds, tests and lints; the store steps are skipped.

## Checks before a release

- `python extension/build.py && python -m pytest -q --noconftest tests/test_extension.py::test_extension_build_and_manifests && npx web-ext@10.8.0 lint --source-dir extension/dist/firefox` — 0 errors, 0 warnings.
- Network destinations stay as described in `PRIVACY.md` (user's archive address, `127.0.0.1:3040`); any new one needs `PRIVACY.md` and the store disclosures updated first.
