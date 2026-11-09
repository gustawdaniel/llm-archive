<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { searchArchive, getSavedQueries, deleteSavedQuery, listTopics } from '$lib/api';
	import type { SearchResultItem, SavedQuery, Topic } from '$lib/types';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';
	import ConversationPreviewModal from '$lib/components/ConversationPreviewModal.svelte';

	let query = $state('');
	let selectedPlatform = $state<string>('');
	let selectedTopicId = $state<string>('');
	let availableTopics = $state<Topic[]>([]);
	let isLoading = $state(false);
	let results = $state<SearchResultItem[]>([]);
	let searchPerformed = $state(false);

	// Saved/Recent queries state
	let savedQueries = $state<SavedQuery[]>([]);
	let activeTab = $state<'recent' | 'examples'>('recent');

	// Preview modal state
	let previewId = $state<string | null>(null);

	const platforms = [
		{ id: '', label: 'Wszystkie platformy' },
		{ id: 'antigravity', label: 'Antigravity' },
		{ id: 'claude_code', label: 'Claude Code' },
		{ id: 'cline', label: 'Cline' },
		{ id: 'chatgpt', label: 'ChatGPT' },
		{ id: 'claude_web', label: 'Claude Web' },
		{ id: 'deepseek', label: 'DeepSeek' },
		{ id: 'gemini', label: 'Gemini' },
		{ id: 'grok', label: 'Grok' }
	];

	async function loadSavedQueries() {
		try {
			savedQueries = await getSavedQueries();
		} catch (e) {
			console.error('Failed to load saved queries:', e);
		}
	}

	async function loadTopics() {
		try {
			availableTopics = await listTopics();
		} catch (e) {
			console.error('Failed to load topics:', e);
		}
	}

	async function handleDeleteQuery(id: string, e: MouseEvent) {
		e.stopPropagation();
		const ok = await deleteSavedQuery(id);
		if (ok) {
			savedQueries = savedQueries.filter(q => q.id !== id);
		}
	}

	onMount(() => {
		loadSavedQueries();
		loadTopics();
	});

	async function executeSearch() {
		if (!query.trim()) return;
		isLoading = true;
		searchPerformed = true;
		try {
			const res = await searchArchive(query, selectedPlatform || undefined, 20, selectedTopicId || undefined);
			results = res.results || [];
			loadSavedQueries();
		} catch (err) {
			console.error('Search error:', err);
		} finally {
			isLoading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			executeSearch();
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
	<title>Wyszukiwarka | Brain LLM Archive</title>
</svelte:head>

<div class="search-page">
	<div class="hero-section">
		<h1 class="hero-title">Zunifikowane Archiwum LLM</h1>
		<p class="hero-subtitle">
			Hybrydowe wyszukiwanie semantyczne (pgvector HNSW) oraz pełnotekstowe (RRF) w całej historii ChatGPT, Claude, Antigravity i DeepSeek.
		</p>

		<!-- Search Bar -->
		<div class="search-box glass-panel">
			<div class="search-input-wrapper">
				<svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<circle cx="11" cy="11" r="8"></circle>
					<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
				</svg>
				<input
					type="text"
					bind:value={query}
					onkeydown={handleKeydown}
					placeholder="Szukaj w wiedzy LLM, np. 'architektura pgvector', 'jak naprawić błąd w Caddyfile'..."
					class="search-input"
				/>
				{#if query}
					<button class="clear-btn" onclick={() => { query = ''; results = []; searchPerformed = false; }}>
						✕
					</button>
				{/if}
			</div>

			<button class="submit-btn" onclick={executeSearch} disabled={isLoading}>
				{#if isLoading}
					<span class="spinner"></span>
					Szukam...
				{:else}
					Szukaj
				{/if}
			</button>
		</div>

		<!-- Platform & Topic Filter Row -->
		<div class="filter-row">
			<div class="filter-chips">
				{#each platforms as p}
					<button
						class="chip"
						class:active={selectedPlatform === p.id}
						onclick={() => { selectedPlatform = p.id; if (query) executeSearch(); }}
					>
						{p.label}
					</button>
				{/each}
			</div>

			{#if availableTopics.length > 0}
				<div class="topic-filter-box">
					<select
						bind:value={selectedTopicId}
						onchange={() => { if (query) executeSearch(); }}
						class="topic-facet-select"
					>
						<option value="">Wszystkie tematy ({availableTopics.length})</option>
						{#each availableTopics as t}
							<option value={t.id}>{t.name} ({t.count})</option>
						{/each}
					</select>
				</div>
			{/if}
		</div>
	</div>

	<!-- Results Section -->
	<div class="results-section">
		{#if isLoading}
			<div class="loading-state glass-card">
				<div class="spinner-large"></div>
				<p>Przeszukiwanie indeksów wektorowych i pełnotekstowych...</p>
			</div>
		{:else if searchPerformed && results.length === 0}
			<div class="empty-state glass-card">
				<div class="empty-icon">🔍</div>
				<h3>Brak wyników dla zapytania</h3>
				<p>Spróbuj zmienić słowa kluczowe lub zresetować filtr platformy.</p>
			</div>
		{:else if results.length > 0}
			<div class="results-header">
				<h2>Znalezione fragmenty ({results.length})</h2>
			</div>

			<div class="results-list">
				{#each results as item, index}
					<div class="result-card glass-card">
						<div class="card-header">
							<div class="card-title-group">
								<PlatformBadge platform={item.platform} />
								<h3 class="card-title">{item.title}</h3>
								{#if item.topic_name}
									<a href="{base}/topics/{item.topic_id}" class="topic-tag-badge" title="Przejdź do klastra tematycznego">
										🏷️ {item.topic_name}
									</a>
								{/if}
							</div>
							<div class="card-meta">
								<span class="score-badge" title="Wskaźnik fuzji RRF: {item.score.toFixed(5)}">
									Trafność: {results[0]?.score ? Math.round((item.score / results[0].score) * 100) : 100}%
								</span>
								<span class="date-badge">{formatDate(item.started_at)}</span>
							</div>
						</div>

						{#if item.header_path}
							<div class="context-path">
								<code>{item.header_path}</code>
							</div>
						{/if}

						<div class="chunk-snippet">
							<p>{item.chunk_text}</p>
						</div>

						<div class="card-footer">
							<div class="file-path">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
									<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
									<polyline points="14 2 14 8 20 8"></polyline>
								</svg>
								<span>doc/llm-archive/{item.relative_path || ''}</span>
							</div>

							<div class="action-buttons">
								<button class="preview-btn" onclick={() => (previewId = item.conversation_id)}>
									Podgląd
								</button>
								<a href="{base}/conversations/{item.conversation_id}" class="open-link">
									Otwórz pełną stronę →
								</a>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="initial-suggestions glass-card">
				<div class="suggestions-header">
					<div class="suggestions-tabs">
						<button 
							class="tab-btn" 
							class:active={activeTab === 'recent'}
							onclick={() => activeTab = 'recent'}
						>
							<span class="tab-icon">📌</span>
							<span>Ostatnie & Zapisane ({savedQueries.length})</span>
						</button>
						<button 
							class="tab-btn" 
							class:active={activeTab === 'examples'}
							onclick={() => activeTab = 'examples'}
						>
							<span class="tab-icon">💡</span>
							<span>Przykłady Startowe</span>
						</button>
					</div>
					<span class="vector-badge">
						<span class="vector-dot"></span>
						Zwektoryzowane (bge-m3)
					</span>
				</div>

				{#if activeTab === 'recent'}
					{#if savedQueries.length > 0}
						<div class="suggestion-pills">
							{#each savedQueries as sq}
								<div class="query-pill-wrapper" title="{sq.query_text} (uruchomiono {sq.execution_count}x)">
									<button 
										class="suggestion-pill recent-query-btn" 
										onclick={() => { query = sq.query_text; executeSearch(); }}
									>
										<span class="pill-text">{sq.short_title}</span>
										{#if sq.execution_count > 1}
											<span class="exec-count">{sq.execution_count}</span>
										{/if}
									</button>
									<button 
										class="delete-query-btn" 
										title="Usuń to zapytanie z bazy"
										onclick={(e) => handleDeleteQuery(sq.id, e)}
									>
										✕
									</button>
								</div>
							{/each}
						</div>
					{:else}
						<p class="empty-queries-text">Brak wcześniejszych zapytań. Wpisz dowolne pytanie powyżej, aby automatycznie je zwektoryzować i zapisać.</p>
					{/if}
				{:else}
					<div class="suggestion-pills">
						<button class="suggestion-pill" onclick={() => { query = 'bge-m3 Ollama pgvector'; executeSearch(); }}>
							"bge-m3 Ollama pgvector"
						</button>
						<button class="suggestion-pill" onclick={() => { query = 'Caddy reverse proxy tailscale'; executeSearch(); }}>
							"Caddy reverse proxy tailscale"
						</button>
						<button class="suggestion-pill" onclick={() => { query = 'Syncthing daemon backup'; executeSearch(); }}>
							"Syncthing daemon backup"
						</button>
						<button class="suggestion-pill" onclick={() => { query = 'Claude Code JSONL parser'; executeSearch(); }}>
							"Claude Code JSONL parser"
						</button>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<ConversationPreviewModal conversationId={previewId} onClose={() => (previewId = null)} />
<style>
	.search-page {
		display: flex;
		flex-direction: column;
		gap: 2.5rem;
	}

	.hero-section {
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.25rem;
		padding: 1rem 0;
	}

	.hero-title {
		font-size: 2.5rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		background: linear-gradient(135deg, #ffffff 40%, #38bdf8 100%);
		background-clip: text;
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
	}

	.hero-subtitle {
		max-width: 680px;
		color: var(--text-secondary);
		font-size: 1.05rem;
		line-height: 1.6;
	}

	.search-box {
		width: 100%;
		max-width: 840px;
		display: flex;
		gap: 12px;
		padding: 8px 12px;
		background: rgba(15, 23, 42, 0.85);
		border-radius: var(--radius-pill);
		border: 1px solid var(--border-card);
		box-shadow: 0 16px 40px -12px rgba(0, 0, 0, 0.7);
		transition: border-color var(--transition-quick), box-shadow var(--transition-quick);
	}

	.search-box:focus-within {
		border-color: var(--border-focus);
		box-shadow: 0 0 30px rgba(6, 182, 212, 0.25);
	}

	.search-input-wrapper {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		padding-left: 12px;
	}

	.search-icon {
		color: var(--text-muted);
	}

	.search-input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--text-primary);
		font-size: 1.05rem;
		font-family: inherit;
	}

	.search-input::placeholder {
		color: var(--text-muted);
	}

	.clear-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 1rem;
		padding: 4px 8px;
	}

	.submit-btn {
		background: linear-gradient(135deg, #06b6d4, #0284c7);
		color: #ffffff;
		border: none;
		border-radius: var(--radius-pill);
		padding: 10px 24px;
		font-size: 0.95rem;
		font-weight: 600;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		transition: transform var(--transition-quick), opacity var(--transition-quick);
	}

	.submit-btn:hover:not(:disabled) {
		transform: scale(1.02);
		box-shadow: 0 0 16px rgba(6, 182, 212, 0.4);
	}

	.submit-btn:disabled {
		opacity: 0.7;
		cursor: not-allowed;
	}

	.filter-row {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		max-width: 860px;
	}

	.filter-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
	}

	.topic-filter-box {
		display: flex;
		align-items: center;
	}

	.topic-facet-select {
		background: rgba(15, 23, 42, 0.7);
		border: 1px solid rgba(168, 85, 247, 0.4);
		color: #e9d5ff;
		padding: 6px 14px;
		border-radius: var(--radius-pill);
		font-size: 0.82rem;
		font-family: inherit;
		cursor: pointer;
		outline: none;
		transition: all var(--transition-quick);
	}

	.topic-facet-select:focus,
	.topic-facet-select:hover {
		border-color: #c084fc;
		background: rgba(15, 23, 42, 0.9);
	}

	.chip {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		color: var(--text-secondary);
		padding: 6px 14px;
		border-radius: var(--radius-pill);
		font-size: 0.82rem;
		cursor: pointer;
		transition: all var(--transition-quick);
	}

	.chip:hover {
		color: var(--text-primary);
		background: rgba(255, 255, 255, 0.08);
	}

	.chip.active {
		background: rgba(6, 182, 212, 0.15);
		border-color: var(--color-antigravity);
		color: #38bdf8;
		font-weight: 600;
	}

	.topic-tag-badge {
		font-size: 0.75rem;
		padding: 2px 8px;
		border-radius: var(--radius-pill);
		background: rgba(168, 85, 247, 0.15);
		border: 1px solid rgba(168, 85, 247, 0.35);
		color: #d8b4fe;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		transition: all var(--transition-quick);
	}

	.topic-tag-badge:hover {
		background: rgba(168, 85, 247, 0.3);
		border-color: #c084fc;
		color: #ffffff;
	}

	.results-section {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.results-header h2 {
		font-size: 1.25rem;
		color: var(--text-primary);
	}

	.results-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.result-card {
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.card-title-group {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.card-title {
		font-size: 1.1rem;
		font-weight: 600;
		color: #ffffff;
	}

	.card-meta {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.score-badge {
		background: rgba(16, 185, 129, 0.12);
		border: 1px solid rgba(16, 185, 129, 0.3);
		color: #34d399;
		font-size: 0.75rem;
		font-family: var(--font-mono);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.date-badge {
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.context-path code {
		font-size: 0.78rem;
		color: var(--text-secondary);
		background: rgba(255, 255, 255, 0.05);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.chunk-snippet {
		background: rgba(9, 13, 22, 0.5);
		border-left: 3px solid var(--border-focus);
		padding: 10px 14px;
		border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
		font-size: 0.92rem;
		color: #cbd5e1;
		line-height: 1.6;
	}

	.card-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		font-size: 0.8rem;
		color: var(--text-muted);
		border-top: 1px solid rgba(255, 255, 255, 0.04);
		padding-top: 0.75rem;
	}

	.file-path {
		display: flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-mono);
	}

	.action-buttons {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.preview-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 4px 12px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.82rem;
		transition: all var(--transition-quick);
	}

	.preview-btn:hover {
		background: rgba(255, 255, 255, 0.12);
		border-color: var(--border-card);
	}

	.open-link {
		color: var(--text-accent);
		text-decoration: none;
		font-weight: 500;
	}

	.open-link:hover {
		text-decoration: underline;
	}

	.initial-suggestions {
		padding: 1.5rem 1.75rem;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.suggestions-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		border-bottom: 1px solid var(--border-subtle);
		padding-bottom: 0.85rem;
		flex-wrap: wrap;
		gap: 0.75rem;
	}

	.suggestions-tabs {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.tab-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: transparent;
		border: 1px solid transparent;
		color: var(--text-muted);
		padding: 6px 14px;
		border-radius: var(--radius-pill);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		transition: all var(--transition-quick);
	}

	.tab-btn:hover {
		color: var(--text-primary);
		background: rgba(255, 255, 255, 0.04);
	}

	.tab-btn.active {
		color: #ffffff;
		background: rgba(6, 182, 212, 0.15);
		border-color: rgba(6, 182, 212, 0.3);
		font-weight: 600;
	}

	.vector-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.75rem;
		color: var(--text-muted);
		background: rgba(255, 255, 255, 0.03);
		padding: 4px 10px;
		border-radius: var(--radius-pill);
		font-family: var(--font-mono);
	}

	.vector-dot {
		width: 6px;
		height: 6px;
		background-color: #a855f7;
		border-radius: 50%;
		box-shadow: 0 0 6px #a855f7;
	}

	.suggestion-pills {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: flex-start;
	}

	.query-pill-wrapper {
		display: inline-flex;
		align-items: center;
		background: rgba(15, 23, 42, 0.6);
		border: 1px solid rgba(56, 189, 248, 0.2);
		border-radius: var(--radius-pill);
		transition: all var(--transition-quick);
		max-width: 320px;
	}

	.query-pill-wrapper:hover {
		border-color: rgba(56, 189, 248, 0.4);
		background: rgba(15, 23, 42, 0.8);
		transform: translateY(-1px);
	}

	.recent-query-btn {
		background: transparent !important;
		border: none !important;
		padding: 6px 8px 6px 12px !important;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 270px;
		color: #e2e8f0 !important;
	}

	.pill-text {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.exec-count {
		background: rgba(56, 189, 248, 0.18);
		color: #38bdf8;
		font-size: 0.72rem;
		padding: 1px 5px;
		border-radius: 10px;
		font-weight: 600;
	}

	.delete-query-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		padding: 4px 8px;
		cursor: pointer;
		font-size: 0.75rem;
		border-radius: 50%;
		transition: all 0.15s ease;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.delete-query-btn:hover {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.15);
	}

	.empty-queries-text {
		color: var(--text-muted);
		font-size: 0.88rem;
		margin: 1rem 0;
	}

	.suggestion-pill {
		background: rgba(6, 182, 212, 0.08);
		border: 1px solid rgba(6, 182, 212, 0.2);
		color: #38bdf8;
		padding: 6px 14px;
		border-radius: var(--radius-pill);
		cursor: pointer;
		font-size: 0.85rem;
		font-family: var(--font-mono);
		transition: all var(--transition-quick);
	}

	.suggestion-pill:hover {
		background: rgba(6, 182, 212, 0.18);
		transform: translateY(-1px);
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

	.empty-icon {
		font-size: 2.5rem;
	}

	.spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #ffffff;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
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

	/* Modal styles now live in ConversationPreviewModal.svelte, shared with /topics. */
</style>
