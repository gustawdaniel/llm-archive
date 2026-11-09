// Refreshes src/lib/litellm-prices.json from LiteLLM's public price table.
// Usage: pnpm prices
// Kept: chat models of the providers we archive; prices stored in USD per 1M tokens as
// [input, output, cacheRead|null, cacheWrite|null, provider].
import { writeFileSync } from 'node:fs';

const SOURCE = 'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json';
const PROVIDERS = new Set(['anthropic', 'openai', 'deepseek', 'gemini', 'xai', 'mistral', 'groq', 'openrouter']);
const perM = (v) => (v == null ? null : Number((v * 1e6).toPrecision(6)));

const res = await fetch(SOURCE);
if (!res.ok) throw new Error(`${SOURCE}: HTTP ${res.status}`);
const table = await res.json();

const models = {};
for (const [id, m] of Object.entries(table)) {
	if (!m || typeof m !== 'object' || m.input_cost_per_token == null) continue;
	if (!['chat', 'responses'].includes(m.mode) || !PROVIDERS.has(m.litellm_provider)) continue;
	models[id] = [
		perM(m.input_cost_per_token),
		perM(m.output_cost_per_token ?? 0),
		perM(m.cache_read_input_token_cost),
		perM(m.cache_creation_input_token_cost),
		m.litellm_provider
	];
}

const out = new URL('../src/lib/litellm-prices.json', import.meta.url);
writeFileSync(out, JSON.stringify({ source: SOURCE, updated: new Date().toISOString().slice(0, 10), models }) + '\n');
console.log(`${Object.keys(models).length} models → ${out.pathname}`);
