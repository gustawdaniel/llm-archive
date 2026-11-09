import LITELLM from './litellm-prices.json';

/**
 * Model pricing and cost estimation for LLM Archive.
 *
 * Prices come from LiteLLM's public price table (src/lib/litellm-prices.json, refresh with
 * `pnpm prices`). Lookup is exact by model id (optionally with a provider prefix), never fuzzy:
 * a model that is not in the table has no price and its cost is shown as "?".
 */

export interface ModelPricing {
	id: string;                   // LiteLLM key that matched
	displayName: string;
	provider: string;
	inputPricePerM: number;       // uncached input, USD per 1M tokens
	cacheReadPricePerM: number;   // cache hit
	cacheWritePricePerM: number;  // cache creation
	outputPricePerM: number;      // output, reasoning/thinking included
}

export interface CostCalculation {
	totalCost: number | null;     // null = model not in the price table
	totalCostFormatted: string;
	userCostFormatted: string;
	plnFormatted: string;
	inputTokens: number;
	cacheMissTokens: number;
	cacheReadTokens: number;
	cacheWriteTokens: number;
	outputTokens: number;
	reasoningTokens: number;
	activeTokens: number;
	totalTokens: number;
	inputCost: number;
	cacheReadCost: number;
	cacheWriteCost: number;
	outputCost: number;
	isFreeTier: boolean;
	pricing: ModelPricing | null;
}

type PriceRow = [number, number, number | null, number | null, string];
const TABLE = (LITELLM as unknown as { models: Record<string, PriceRow> }).models;
const PROVIDER_PREFIXES = ['anthropic', 'openai', 'deepseek', 'gemini', 'xai', 'mistral', 'groq', 'openrouter'];
const LOCAL_PRICING: ModelPricing = {
	id: 'local', displayName: 'Local / Ollama (self-hosted)', provider: 'Local',
	inputPricePerM: 0, cacheReadPricePerM: 0, cacheWritePricePerM: 0, outputPricePerM: 0
};

const USD_TO_PLN_RATE = 3.90;

export const PRICES_UPDATED: string = LITELLM.updated;

function toPricing(id: string, row: PriceRow): ModelPricing {
	const [input, output, cacheRead, cacheWrite, provider] = row;
	return {
		id,
		displayName: id,
		provider,
		inputPricePerM: input,
		outputPricePerM: output,
		cacheReadPricePerM: cacheRead ?? input,
		cacheWritePricePerM: cacheWrite ?? input
	};
}

/**
 * Exact lookup of a model in the LiteLLM table. Tries the id as is, without a provider or
 * "models/" prefix, without a context-size suffix like "[1m]", without a date suffix, and with
 * each known provider prefix. Returns null for unknown models.
 */
export function getPricingForModel(modelName?: string, platform?: string): ModelPricing | null {
	const raw = (modelName || '').toLowerCase().trim();
	if (!raw) return null;
	if (raw.startsWith('ollama') || raw.startsWith('local') || (platform || '').toLowerCase() === 'ollama') {
		return LOCAL_PRICING;
	}

	const base = raw.replace(/^models\//, '').replace(/\[[^\]]*\]$/, '');
	const bare = base.includes('/') ? base.slice(base.indexOf('/') + 1) : base;
	const undated = bare.replace(/-\d{8}$/, '').replace(/-latest$/, '');
	const names = [...new Set([base, bare, undated])];
	const candidates = [...names, ...names.flatMap(n => PROVIDER_PREFIXES.map(p => `${p}/${n}`))];

	for (const key of candidates) {
		if (TABLE[key]) return toPricing(key, TABLE[key]);
	}
	return null;
}

function formatUsd(v: number): string {
	if (v >= 0.01) return `$${v.toFixed(2)}`;
	if (v > 0) return `$${v.toFixed(4)}`;
	return '$0.00';
}

/**
 * Cost of a token usage record.
 *
 * Providers count prompt tokens differently: Anthropic's input_tokens EXCLUDE cache reads and
 * writes, while OpenAI/DeepSeek-style input_tokens INCLUDE cached tokens. Anthropic semantics
 * are used for Anthropic models and Claude platforms; otherwise cached tokens are subtracted
 * from input when input is large enough to contain them.
 */
export function calculateTokenCost(
	usage: any,
	modelName?: string,
	platform?: string
): CostCalculation {
	const pricing = getPricingForModel(modelName, platform);
	const u = usage && typeof usage === 'object' ? usage : {};

	const inputTokens = Number(u.input_tokens ?? u.inputTokens ?? u.tokensIn ?? u.input ?? 0);
	const outputTokens = Number(u.output_tokens ?? u.outputTokens ?? u.tokensOut ?? u.output ?? 0);
	const cacheReadTokens = Number(
		u.cache_read_tokens ?? u.cacheReadTokens ?? u.cacheReads ?? u.cache_read ?? u.cache_read_input_tokens ?? u.cached_input_tokens ?? 0
	);
	const cacheWriteTokens = Number(
		u.cache_write_tokens ?? u.cacheWriteTokens ?? u.cacheWrites ?? u.cache_write ?? u.cache_creation_input_tokens ?? 0
	);
	const reasoningTokens = Number(
		u.thinking_tokens ?? u.reasoning_tokens ?? u.reasoning_output_tokens ?? u.thinkingTokens ?? 0
	);

	const plat = (platform || '').toLowerCase();
	const anthropicSemantics = pricing?.provider === 'anthropic' || plat === 'claude_code' || plat === 'claude_web';
	let cacheMissTokens = inputTokens;
	if (!anthropicSemantics) {
		if (inputTokens >= cacheReadTokens + cacheWriteTokens) {
			cacheMissTokens = inputTokens - cacheReadTokens - cacheWriteTokens;
		} else if (inputTokens >= cacheReadTokens) {
			cacheMissTokens = inputTokens - cacheReadTokens;
		}
	}

	const activeTokens = cacheMissTokens + outputTokens;
	const totalTokens = Number(u.total_tokens ?? u.totalTokens ?? u.total ?? 0) ||
		(anthropicSemantics ? inputTokens + cacheReadTokens + cacheWriteTokens + outputTokens : inputTokens + outputTokens);

	const inputCost = pricing ? (cacheMissTokens / 1_000_000) * pricing.inputPricePerM : 0;
	const cacheReadCost = pricing ? (cacheReadTokens / 1_000_000) * pricing.cacheReadPricePerM : 0;
	const cacheWriteCost = pricing ? (cacheWriteTokens / 1_000_000) * pricing.cacheWritePricePerM : 0;
	const outputCost = pricing ? (outputTokens / 1_000_000) * pricing.outputPricePerM : 0;
	const totalCost = pricing ? inputCost + cacheReadCost + cacheWriteCost + outputCost : null;

	const totalCostFormatted = totalCost === null ? '?' : formatUsd(totalCost);
	const isFreeTier = (modelName || '').toLowerCase().includes('free');
	const userCostFormatted = isFreeTier ? '$0.00 (Free)' : totalCostFormatted;
	const pln = totalCost === null ? null : totalCost * USD_TO_PLN_RATE;
	const plnFormatted = pln === null ? '? zł' : pln >= 0.01 ? `${pln.toFixed(2)} zł` : `${pln.toFixed(3)} zł`;

	return {
		totalCost,
		totalCostFormatted,
		userCostFormatted,
		plnFormatted,
		inputTokens,
		cacheMissTokens,
		cacheReadTokens,
		cacheWriteTokens,
		outputTokens,
		reasoningTokens,
		activeTokens,
		totalTokens,
		inputCost,
		cacheReadCost,
		cacheWriteCost,
		outputCost,
		isFreeTier,
		pricing
	};
}

/**
 * Formats token count compactly (e.g., 3.48k, 3.26M, or 542).
 */
export function formatCompactTokens(count: number): string {
	if (!count || isNaN(count)) return '0';
	if (count >= 1_000_000) {
		return `${(count / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`;
	}
	if (count >= 1_000) {
		return `${(count / 1_000).toFixed(1).replace(/\.0$/, '')}k`;
	}
	return count.toLocaleString('pl-PL');
}

/**
 * Full formatted token count with thousands separator.
 */
export function formatFullTokens(count: number): string {
	if (!count || isNaN(count)) return '0';
	return count.toLocaleString('pl-PL');
}
