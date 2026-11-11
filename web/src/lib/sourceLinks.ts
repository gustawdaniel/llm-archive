// Rules for reconstructing a link back to where a conversation actually lives.
//
// Cloud platforms: external_id is (for most platforms) the same id the
// platform's own web UI uses in its URL, captured at import time. Verified
// against real data in the archive DB (2026-09-24) - see docs/network_and_sync.md.
//
// Gemini is the one exception worth a comment: external_id has two possible
// shapes depending on which importer touched a given conversation.
//   - Google Takeout ("My Activity") import extracts the real conversation id
//     straight out of the captured `gemini.google.com/app/<id>` URL - a 16-32
//     char hex string. Reconstructible.
//   - When Takeout had no URL for an activity entry (e.g. a "cleared feedback"
//     entry), the importer falls back to an ISO timestamp as external_id, e.g.
//     "2026-04-05T16:48:20.894Z". Not a real id - no link exists to rebuild.
// The regex below is what tells these two cases apart. Don't loosen it to
// "match anything" - a false positive just links to a 404 on Gemini's side.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const GEMINI_ID_RE = /^[0-9a-f]{16,32}$/i;

export type SourceUrlPlatform =
	| 'chatgpt'
	| 'claude_web'
	| 'deepseek'
	| 'grok'
	| 'perplexity'
	| 'gemini';

/**
 * Best-effort reconstruction of the original conversation URL on the source
 * platform. Returns null when the platform has no such thing (local
 * agent tools - see LOCAL_PLATFORMS) or when external_id doesn't look like
 * a real platform id (e.g. Gemini's timestamp-fallback case).
 */
export function buildSourceUrl(platform: string, externalId: string | undefined | null): string | null {
	if (!externalId) return null;

	switch (platform) {
		case 'chatgpt':
			return UUID_RE.test(externalId) ? `https://chatgpt.com/c/${externalId}` : null;
		case 'claude_web':
			return UUID_RE.test(externalId) ? `https://claude.ai/chat/${externalId}` : null;
		case 'deepseek':
			return UUID_RE.test(externalId) ? `https://chat.deepseek.com/a/chat/s/${externalId}` : null;
		case 'grok':
			return UUID_RE.test(externalId) ? `https://grok.com/chat/${externalId}` : null;
		case 'perplexity':
			// Perplexity's real URL is `/search/<title-slug>-<id-suffix>` - we only
			// have the bare uuid, so this is a best-effort guess that may 404.
			// Fine per product decision: the DeepSeek/Gemini browser extension
			// approach is the intended long-term fix for this platform anyway.
			return UUID_RE.test(externalId) ? `https://www.perplexity.ai/search/${externalId}` : null;
		case 'gemini':
			return GEMINI_ID_RE.test(externalId) ? `https://gemini.google.com/app/${externalId}` : null;
		default:
			return null;
	}
}

/** Platforms that are local CLI/IDE tools with no web-viewable conversation at all. */
export const LOCAL_PLATFORMS = new Set(['antigravity', 'claude_code', 'cline', 'opencode', 'aider', 'omp', 'zed', 'hermes', 'codex', 'goose']);

export function isLocalPlatform(platform: string): boolean {
	return LOCAL_PLATFORMS.has(platform);
}
