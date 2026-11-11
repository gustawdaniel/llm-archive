# Brain LLM Sync — Privacy Policy

_Last updated: 2026-11-11_

Brain LLM Sync is an open-source browser extension (source: https://github.com/gustawdaniel/llm-archive) that copies **your own** conversations from AI chat websites into **your own** self-hosted archive ([LLM Archive](https://github.com/gustawdaniel/llm-archive)). It is a personal archival tool: the developer runs no server for it and receives no data from it.

## What the extension reads

On the supported AI chat websites only — `chatgpt.com`, `chat.openai.com`, `claude.ai`, `chat.deepseek.com`, `grok.com`, `gemini.google.com` — the extension reads the conversations of the signed-in user (titles, messages, timestamps, model names) in order to archive them.

It does not read any other website.

## Where the data goes

Conversation data is sent **only** to destinations the user controls:

1. the archive server address the user enters in the extension popup (default: `http://localhost:8080/api/v1/ingest`, typically a server on the user's own computer or private network), and
2. an optional local helper on the user's own computer (`http://127.0.0.1:3040`).

The extension asks for network access to the archive server address only after the user enters it, and only for that address.

No data is sent to the developer or to any third party. There is no analytics, telemetry, advertising or tracking.

## What is stored in the browser

`storage` holds the archive server address, a device name chosen by the user, identifiers of already archived conversations (to avoid duplicates), sync counters and a short local log for troubleshooting. This data never leaves the browser except as part of sending conversations to the user's own archive server.

## Selling and sharing

User data is not sold, shared, transferred to third parties, used for advertising or used for creditworthiness or lending purposes.

## Removal

Uninstalling the extension removes all of its browser storage. Archived conversations are kept in the user's own archive and are deleted there by the user.

## Contact

Questions and requests: open an issue at https://github.com/gustawdaniel/llm-archive/issues
