# Brain LLM Sync — store listing texts

Copy-paste source for the Chrome Web Store and Firefox Add-ons (AMO) forms. Keep in sync with `manifest.json` and `PRIVACY.md`.

## Common

| Field | Value |
|---|---|
| Name | Brain LLM Sync |
| Summary (≤132 chars, = manifest `description`) | Background sync of ChatGPT, Claude, DeepSeek, Grok and Gemini conversations to personal Brain knowledge base. |
| Category | Chrome: **Productivity → Tools** · AMO: **Other** (or *Privacy & Security* is wrong — it does not protect privacy) |
| Language | English |
| Homepage | https://github.com/gustawdaniel/llm-archive |
| Support | https://github.com/gustawdaniel/llm-archive/issues |
| Privacy policy | https://github.com/gustawdaniel/llm-archive/blob/main/extension/PRIVACY.md |
| License (AMO) | GNU Affero General Public License v3.0 |
| Icon | `icons/icon-128.png` |
| Screenshots | `store/screenshot-*.png` (1280×800) |

## Description

Brain LLM Sync keeps a private archive of your conversations with AI assistants.

While you use ChatGPT, Claude, DeepSeek, Grok or Gemini in your browser, the extension copies your conversations — titles, messages, timestamps and models — into LLM Archive, an open-source, self-hosted archive with full-text and semantic search that you run on your own computer or server.

• Your data, your server: conversations go only to the archive address you set, never to the developer or third parties.
• Background sync: new and updated conversations are picked up automatically in the background (every 15 minutes by default) while a supported tab is open, plus a one-click backfill of older history.
• No duplicates: already archived conversations are remembered and skipped.
• Works with ChatGPT, Claude, DeepSeek, Grok and Gemini.
• Open source (AGPL-3.0): https://github.com/gustawdaniel/llm-archive

Setup: install LLM Archive (see the repository), open the extension popup, enter your archive address (e.g. http://localhost:8080/api/v1/ingest or the address of your server) and allow access to it when the browser asks.

This extension is for archiving your own conversations only. It does not work without a running LLM Archive server.

## Chrome Web Store — Privacy practices tab

**Single purpose**
> Synchronizes the user's own conversations from AI chat websites (ChatGPT, Claude, DeepSeek, Grok, Gemini) into the user's self-hosted LLM Archive server.

**Permission justifications**

| Permission | Justification |
|---|---|
| `storage` | Stores the archive server address, the device name, identifiers of already archived conversations (to skip duplicates), sync counters and a short troubleshooting log. |
| `alarms` | Schedules the periodic background check for new or updated conversations while supported AI tabs are open. |
| `tabs` | Finds open tabs of the supported AI websites to trigger a sync in them when the user presses "Sync now" or a scheduled sync runs. |
| `scripting` | Injects the sync content script into supported AI tabs that were open before the extension was installed or updated, so they can be synced without a reload. |
| Host permissions (AI websites) | Read the signed-in user's conversations on chatgpt.com, chat.openai.com, claude.ai, chat.deepseek.com, grok.com and gemini.google.com — the only sites the extension works on. |
| Host permissions (localhost, 127.0.0.1) | Send archived conversations to the user's own archive server or local helper on the same computer. |
| Optional host permission `<all_urls>` | Requested at runtime only for the single archive server address the user enters (e.g. a server in their private network), never for all sites. Needed to send conversations to that self-hosted server. |
| Remote code | No — all code is in the package. |

**Data usage** (check): *Personal communications* (the conversations), *Website content* (conversation pages on the supported AI sites).
Certify all three: not sold to third parties; not used or transferred for purposes unrelated to the single purpose; not used for creditworthiness or lending.

## Firefox Add-ons — submission notes

- Channel: **listed**. Source code submission: **not required** (no minification or bundling; the package equals the repository files).
- `data_collection_permissions` in the manifest declares `personalCommunications` and `websiteContent` (sent only to the user's own server); Firefox shows this at install.
- Notes for reviewers:
  > The extension archives the user's own AI chat conversations into the user's self-hosted LLM Archive (https://github.com/gustawdaniel/llm-archive). Data is sent only to the server address configured in the popup (default http://localhost:8080) or to a local helper at 127.0.0.1:3040. To test: run LLM Archive as described in the repository README, keep the default address, open chatgpt.com or claude.ai while signed in, then press "Sync now" in the popup.
