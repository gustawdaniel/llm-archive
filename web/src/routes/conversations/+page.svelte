<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { getConversations } from '$lib/api';
	import type { ConversationSummary } from '$lib/types';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';
	import RamIcon from '$lib/components/RamIcon.svelte';
	import { calculateTokenCost, formatCompactTokens, formatFullTokens } from '$lib/pricing';

	let conversations = $state<ConversationSummary[]>([]);
	let selectedPlatform = $state<string>('');
	let limit = $state(20);
	let offset = $state(0);
	let totalCount = $state(0);
	let isLoading = $state(true);
	let errorMessage = $state<string | null>(null);

	const platforms = [
		{ id: '', label: 'Wszystkie' },
		{ id: 'antigravity', label: 'Antigravity' },
		{ id: 'claude_code', label: 'Claude Code' },
		{ id: 'cline', label: 'Cline' },
		{ id: 'opencode', label: 'OpenCode' },
		{ id: 'aider', label: 'Aider' },
		{ id: 'codex', label: 'Codex' },
		{ id: 'omp', label: 'Oh My Pi (OMP)' },
		{ id: 'zed', label: 'Zed' },
		{ id: 'hermes', label: 'Hermes' },
		{ id: 'chatgpt', label: 'ChatGPT' },
		{ id: 'claude_web', label: 'Claude Web' },
		{ id: 'deepseek', label: 'DeepSeek' },
		{ id: 'gemini', label: 'Gemini' },
		{ id: 'grok', label: 'Grok' }
	];

	async function loadData() {
		isLoading = true;
		errorMessage = null;
		try {
			const res = await getConversations(selectedPlatform || undefined, limit, offset);
			conversations = res.conversations || [];
			totalCount = res.count || conversations.length;
		} catch (e: any) {
			console.error('Failed to load conversations:', e);
			errorMessage = e?.message || 'Nie udało się połączyć z API LLM Archive.';
			conversations = [];
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		const initialPlatform = params.get('platform');
		if (initialPlatform && initialPlatform.trim()) {
			selectedPlatform = initialPlatform.trim();
		}
		loadData();

		const onPopState = () => {
			const p = new URLSearchParams(window.location.search).get('platform') || '';
			if (p !== selectedPlatform) {
				selectedPlatform = p;
				offset = 0;
				loadData();
			}
		};
		window.addEventListener('popstate', onPopState);
		return () => window.removeEventListener('popstate', onPopState);
	});

	function handlePlatformChange(p: string) {
		selectedPlatform = p;
		offset = 0;
		const url = new URL(window.location.href);
		if (p) {
			url.searchParams.set('platform', p);
		} else {
			url.searchParams.delete('platform');
		}
		window.history.pushState({}, '', url.toString());
		loadData();
	}

	function nextPage() {
		offset += limit;
		loadData();
	}

	function prevPage() {
		if (offset >= limit) {
			offset -= limit;
			loadData();
		}
	}

	function formatDate(iso: string): string {
		try {
			return new Date(iso).toLocaleDateString('pl-PL', {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}
</script>

<svelte:head>
	<title>Przeglądarka Konwersacji | Brain LLM Archive</title>
</svelte:head>

<div class="conversations-page">
	<div class="page-header">
		<div>
			<h1 class="page-title">Przeglądarka Konwersacji</h1>
			<p class="page-subtitle">Wszystkie zindeksowane wątki z podziałem na modele, projekty i gałęzie gita.</p>
		</div>

		<div class="filter-group">
			{#each platforms as p}
				<button
					class="filter-chip"
					class:active={selectedPlatform === p.id}
					onclick={() => handlePlatformChange(p.id)}
				>
					{p.label}
				</button>
			{/each}
		</div>
	</div>

	{#if isLoading}
		<div class="loading-state glass-card">
			<div class="spinner-large"></div>
			<p>Pobieranie listy konwersacji z PostgreSQL...</p>
		</div>
	{:else if errorMessage}
		<div class="empty-state glass-card">
			<p style="color: #f87171; font-weight: 500;">{errorMessage}</p>
			<button class="page-btn" onclick={loadData} style="margin-top: 1rem;">
				Spróbuj ponownie
			</button>
		</div>
	{:else if conversations.length === 0}
		<div class="empty-state glass-card">
			<p>Brak konwersacji dla wybranego filtra.</p>
		</div>
	{:else}
		<div class="conversation-grid">
			{#each conversations as c}
				<a href="{base}/conversations/{c.id}" class="conv-card glass-card">
					<div class="card-top">
						<PlatformBadge platform={c.platform} />
						<span class="msg-badge">{c.message_count || 0} wiadomości</span>
					</div>

					<h3 class="conv-title">{c.title || 'Bez tytułu'}</h3>

					{#if c.project_path}
						<div class="conv-project">
							<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
							</svg>
							<span>{c.project_path}</span>
						</div>
					{/if}

					<div class="card-bottom">
						<span class="conv-date">{formatDate(c.started_at)}</span>
						<div class="card-tags">
							{#if c.model}
								<span class="model-tag" title="Model: {c.model}">
									<RamIcon size={12} />
									<span>{c.model}</span>
								</span>
							{/if}
							{#if c.token_summary && (c.token_summary.total_tokens || c.token_summary.input_tokens)}
								{@const costCalc = calculateTokenCost(c.token_summary, c.model, c.platform)}
								<span 
									class="token-chip" 
									title="Aktywne tokeny: {formatFullTokens(costCalc.activeTokens)} {costCalc.cacheReadTokens > 0 ? `(+${formatCompactTokens(costCalc.cacheReadTokens)} cache)` : ''} • Szacowany koszt: {costCalc.userCostFormatted}"
								>
									<span class="tok-val">{formatCompactTokens(costCalc.activeTokens || costCalc.totalTokens)} tok</span>
									{#if costCalc.userCostFormatted}
										<span class="tok-cost">{costCalc.userCostFormatted}</span>
									{/if}
								</span>
							{/if}
						</div>
					</div>
				</a>
			{/each}
		</div>

		<!-- Pagination Bar -->
		<div class="pagination-bar glass-card">
			<span>Pokazano {conversations.length} wpisów (od {offset + 1})</span>
			<div class="pagination-buttons">
				<button class="page-btn" disabled={offset === 0} onclick={prevPage}>
					← Poprzednia strona
				</button>
				<button class="page-btn" disabled={conversations.length < limit} onclick={nextPage}>
					Następna strona →
				</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.conversations-page {
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		flex-wrap: wrap;
		gap: 1.5rem;
	}

	.page-title {
		font-size: 1.8rem;
		font-weight: 700;
		color: #ffffff;
	}

	.page-subtitle {
		color: var(--text-secondary);
		font-size: 0.95rem;
		margin-top: 0.25rem;
	}

	.filter-group {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.filter-chip {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		color: var(--text-secondary);
		padding: 4px 12px;
		border-radius: var(--radius-pill);
		font-size: 0.8rem;
		cursor: pointer;
		transition: all var(--transition-quick);
	}

	.filter-chip:hover {
		color: var(--text-primary);
		background: rgba(255, 255, 255, 0.08);
	}

	.filter-chip.active {
		background: rgba(6, 182, 212, 0.15);
		border-color: var(--color-antigravity);
		color: #38bdf8;
		font-weight: 600;
	}

	.conversation-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
		gap: 1.25rem;
	}

	.conv-card {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		text-decoration: none;
		color: inherit;
	}

	.card-top {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.msg-badge {
		font-size: 0.75rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
		background: rgba(255, 255, 255, 0.05);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.conv-title {
		font-size: 1.05rem;
		font-weight: 600;
		color: #ffffff;
		line-height: 1.4;
		display: -webkit-box;
		line-clamp: 2;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.conv-project {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		color: var(--text-muted);
		font-family: var(--font-mono);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.card-bottom {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: auto;
		padding-top: 0.75rem;
		border-top: 1px solid rgba(255, 255, 255, 0.04);
		font-size: 0.78rem;
	}

	.conv-date {
		color: var(--text-muted);
	}

	.card-tags {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.model-tag {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-mono);
		color: #c084fc;
		background: rgba(168, 85, 247, 0.12);
		border: 1px solid rgba(168, 85, 247, 0.25);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.token-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-mono);
		color: #e2e8f0;
		background: rgba(15, 23, 42, 0.6);
		border: 1px solid rgba(255, 255, 255, 0.08);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.tok-cost {
		color: #34d399;
		font-weight: 600;
	}

	.pagination-bar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem 1.5rem;
		font-size: 0.85rem;
		color: var(--text-secondary);
	}

	.pagination-buttons {
		display: flex;
		gap: 8px;
	}

	.page-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
		transition: all var(--transition-quick);
	}

	.page-btn:hover:not(:disabled) {
		background: rgba(255, 255, 255, 0.12);
	}

	.page-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.loading-state, .empty-state {
		padding: 3rem;
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		color: var(--text-secondary);
	}

	.spinner-large {
		width: 32px;
		height: 32px;
		border: 3px solid rgba(6, 182, 212, 0.2);
		border-top-color: #06b6d4;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
