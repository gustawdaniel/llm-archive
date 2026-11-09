<script lang="ts">
	import { base } from '$app/paths';
	import { askInfiniteMemory, type RagAskResponse, type RagSource } from '$lib/api';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';
	import MarkdownViewer from '$lib/components/MarkdownViewer.svelte';

	let query = $state('');
	let isLoading = $state(false);
	let responseData = $state<RagAskResponse | null>(null);
	let errorMessage = $state<string | null>(null);
	let copied = $state(false);

	const samplePrompts = [
		'Co ustaliłem w temacie architektury ClickHouse i Postgres?',
		'Jakie decyzje architektoniczne podjąłem dla Brain OS?',
		'Podsumuj moje rozmowy dotyczące szukania nowej pracy',
		'Gdzie leży konfiguracja telemetrii okien i keyloggera?'
	];

	async function handleAsk(promptText?: string) {
		const targetQuery = (promptText !== undefined ? promptText : query).trim();
		if (!targetQuery) return;

		query = targetQuery;
		isLoading = true;
		errorMessage = null;
		responseData = null;

		try {
			const res = await askInfiniteMemory(targetQuery, 5);
			responseData = res;
		} catch (err: any) {
			console.error('Ask error:', err);
			errorMessage = err?.message || 'Wystąpił błąd podczas przeszukiwania pamięci cyfrowej.';
		} finally {
			isLoading = false;
		}
	}

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleAsk();
		}
	}

	async function copyAnswer() {
		if (!responseData?.answer) return;
		try {
			await navigator.clipboard.writeText(responseData.answer);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch (e) {
			console.warn('Copy failed:', e);
		}
	}
</script>

<svelte:head>
	<title>Infinite Memory Q&A • Brain LLM Archive</title>
</svelte:head>

<div class="ask-container">
	<div class="hero">
		<div class="hero-badge">
			<span class="sparkle">✨</span>
			<span>RAG Knowledge Retrieval & Synthesis</span>
		</div>
		<h1 class="hero-title">
			<span class="gradient-text">Infinite Memory</span>
			<span class="hero-subtext">Czat z Twoim Życiem Cyfrowym</span>
		</h1>
		<p class="hero-desc">
			Zadaj dowolne pytanie w języku naturalnym. Silnik przeszukuje <strong>58,000+</strong> zarchiwizowanych wiadomości z modeli AI, notatek oraz telemetrii i syntetyzuje precyzyjną odpowiedź z bezpośrednimi cytatami i linkami do konwersacji.
		</p>
	</div>

	<!-- Search & Input Box -->
	<div class="input-card">
		<div class="input-wrapper">
			<span class="input-icon">🔍</span>
			<input
				type="text"
				bind:value={query}
				onkeydown={handleKeyDown}
				placeholder="np. Co ustaliłem w temacie ClickHouse vs Postgres?..."
				disabled={isLoading}
			/>
			<button class="send-btn" onclick={() => handleAsk()} disabled={isLoading || !query.trim()}>
				{#if isLoading}
					<span class="spinner"></span>
					<span>Myślę...</span>
				{:else}
					<span>Zapytaj</span>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<line x1="22" y1="2" x2="11" y2="13"></line>
						<polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
					</svg>
				{/if}
			</button>
		</div>

		<!-- Sample prompt chips -->
		<div class="chips-row">
			<span class="chips-label">Przykłady:</span>
			{#each samplePrompts as p}
				<button class="chip" onclick={() => handleAsk(p)} disabled={isLoading}>
					{p}
				</button>
			{/each}
		</div>
	</div>

	<!-- Loading Skeleton -->
	{#if isLoading}
		<div class="loading-box">
			<div class="thinking-header">
				<div class="pulse-ring"></div>
				<span>Przeszukuję pamięć wektorową i generuję syntezę...</span>
			</div>
			<div class="skeleton-line" style="width: 90%;"></div>
			<div class="skeleton-line" style="width: 75%;"></div>
			<div class="skeleton-line" style="width: 60%;"></div>
		</div>
	{/if}

	<!-- Error Alert -->
	{#if errorMessage}
		<div class="error-banner">
			<span class="err-icon">⚠️</span>
			<div class="err-text">
				<strong>Błąd syntezy</strong>
				<p>{errorMessage}</p>
			</div>
		</div>
	{/if}

	<!-- Result Section -->
	{#if responseData && !isLoading}
		<div class="answer-section">
			<div class="answer-card">
				<div class="answer-header">
					<div class="model-badge">
						<span class="indicator-dot"></span>
						<span>Model: {responseData.model}</span>
					</div>
					<button class="copy-btn" onclick={copyAnswer}>
						{#if copied}
							<span>✓ Skopiowano</span>
						{:else}
							<span>📋 Kopiuj odpowiedź</span>
						{/if}
					</button>
				</div>

				<MarkdownViewer content={responseData.answer} />
			</div>

			<!-- Sources Section -->
			<div class="sources-card">
				<div class="sources-header">
					<h3>📚 Cytowane Źródła & Powiązane Konwersacje ({responseData.sources.length})</h3>
					<span class="sources-hint">Kliknij, aby otworzyć pełną rozmowę w archiwum</span>
				</div>

				<div class="sources-grid">
					{#each responseData.sources as src}
						<a href={`${base}/conversations/${src.id}`} class="source-item" target="_blank" rel="noopener">
							<div class="source-top">
								<PlatformBadge platform={src.platform} />
								<span class="score-badge">Dopasowanie: {(src.score * 100).toFixed(1)}%</span>
							</div>
							<div class="source-title">{src.title}</div>
							{#if src.snippet}
								<div class="source-snippet">
									„{src.snippet}...”
								</div>
							{/if}
							<div class="source-footer">
								<span class="open-link">Otwórz konwersację ↗</span>
								{#if src.topic_name}
									<span class="topic-pill">🏷️ {src.topic_name}</span>
								{/if}
							</div>
						</a>
					{/each}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.ask-container {
		max-width: 1000px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.hero {
		text-align: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.75rem;
		margin-top: 1rem;
	}

	.hero-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 14px;
		background: rgba(139, 92, 246, 0.15);
		border: 1px solid rgba(139, 92, 246, 0.35);
		border-radius: 999px;
		font-size: 0.8rem;
		font-family: var(--font-mono);
		color: #c4b5fd;
	}

	.hero-title {
		font-size: 2.4rem;
		font-weight: 800;
		display: flex;
		flex-direction: column;
		gap: 4px;
		line-height: 1.15;
	}

	.gradient-text {
		background: linear-gradient(135deg, #a78bfa 0%, #38bdf8 50%, #34d399 100%);
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
	}

	.hero-subtext {
		font-size: 1.25rem;
		font-weight: 500;
		color: var(--text-secondary);
	}

	.hero-desc {
		max-width: 680px;
		color: var(--text-muted);
		font-size: 0.95rem;
		line-height: 1.6;
	}

	.input-card {
		background: rgba(18, 24, 38, 0.85);
		backdrop-filter: blur(12px);
		border: 1px solid rgba(139, 92, 246, 0.25);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
		box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.input-wrapper {
		display: flex;
		align-items: center;
		gap: 12px;
		background: rgba(10, 14, 23, 0.9);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		padding: 6px 10px 6px 16px;
		transition: border-color 0.2s, box-shadow 0.2s;
	}

	.input-wrapper:focus-within {
		border-color: #8b5cf6;
		box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.2);
	}

	.input-icon {
		font-size: 1.2rem;
		opacity: 0.7;
	}

	input {
		flex: 1;
		background: transparent;
		border: none;
		outline: none;
		color: var(--text-primary);
		font-size: 1.05rem;
		padding: 8px 0;
	}

	input::placeholder {
		color: var(--text-muted);
	}

	.send-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		background: linear-gradient(135deg, #7c3aed 0%, #6366f1 100%);
		color: #ffffff;
		border: none;
		border-radius: var(--radius-sm);
		font-size: 0.95rem;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.send-btn:hover:not(:disabled) {
		opacity: 0.9;
		transform: translateY(-1px);
		box-shadow: 0 4px 16px rgba(124, 58, 237, 0.4);
	}

	.send-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.chips-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		font-size: 0.8rem;
	}

	.chips-label {
		color: var(--text-muted);
		font-weight: 500;
	}

	.chip {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: 999px;
		padding: 4px 12px;
		color: var(--text-secondary);
		font-size: 0.78rem;
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.chip:hover:not(:disabled) {
		background: rgba(139, 92, 246, 0.15);
		border-color: rgba(139, 92, 246, 0.4);
		color: #c4b5fd;
	}

	.loading-box {
		background: rgba(18, 24, 38, 0.6);
		border: 1px dashed rgba(139, 92, 246, 0.3);
		border-radius: var(--radius-md);
		padding: 2rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.thinking-header {
		display: flex;
		align-items: center;
		gap: 10px;
		color: #c4b5fd;
		font-size: 0.95rem;
		font-weight: 600;
	}

	.pulse-ring {
		width: 12px;
		height: 12px;
		background: #8b5cf6;
		border-radius: 50%;
		box-shadow: 0 0 10px #8b5cf6;
		animation: pulse 1.5s infinite;
	}

	.skeleton-line {
		height: 14px;
		background: rgba(255, 255, 255, 0.05);
		border-radius: 4px;
		animation: shimmer 1.5s infinite linear;
	}

	@keyframes shimmer {
		0% { opacity: 0.3; }
		50% { opacity: 0.7; }
		100% { opacity: 0.3; }
	}

	.error-banner {
		background: rgba(239, 68, 68, 0.1);
		border: 1px solid rgba(239, 68, 68, 0.3);
		border-radius: var(--radius-md);
		padding: 1rem 1.25rem;
		display: flex;
		gap: 12px;
		color: #fca5a5;
	}

	.answer-section {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.answer-card {
		background: rgba(18, 24, 38, 0.95);
		border: 1px solid rgba(139, 92, 246, 0.35);
		border-radius: var(--radius-lg);
		padding: 2rem;
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
	}

	.answer-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
		padding-bottom: 1rem;
		border-bottom: 1px solid var(--border-subtle);
	}

	.model-badge {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.8rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.indicator-dot {
		width: 8px;
		height: 8px;
		background: #10b981;
		border-radius: 50%;
		box-shadow: 0 0 6px #10b981;
	}

	.copy-btn {
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 6px 12px;
		font-size: 0.8rem;
		color: var(--text-secondary);
		cursor: pointer;
		transition: all 0.2s;
	}

	.copy-btn:hover {
		background: rgba(255, 255, 255, 0.1);
		color: var(--text-primary);
	}

	.markdown-body {
		color: var(--text-primary);
		line-height: 1.7;
		font-size: 1.02rem;
	}

	.markdown-body :global(p) {
		margin-bottom: 1rem;
	}

	.markdown-body :global(strong) {
		color: #f8fafc;
	}

	.markdown-body :global(code) {
		font-family: var(--font-mono);
		background: rgba(255, 255, 255, 0.08);
		padding: 2px 6px;
		border-radius: 4px;
		font-size: 0.88em;
		color: #a78bfa;
	}

	.markdown-body :global(pre) {
		background: rgba(9, 13, 22, 0.8);
		border: 1px solid var(--border-subtle);
		padding: 1rem;
		border-radius: 8px;
		overflow-x: auto;
		margin: 1rem 0;
	}

	.markdown-body :global(blockquote) {
		border-left: 3px solid #8b5cf6;
		padding-left: 1rem;
		color: #cbd5e1;
		margin: 1rem 0;
		background: rgba(139, 92, 246, 0.05);
		padding: 0.75rem 1rem;
		border-radius: 0 8px 8px 0;
	}

	.sources-card {
		background: rgba(15, 20, 32, 0.85);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-lg);
		padding: 1.75rem;
	}

	.sources-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 1.25rem;
		flex-wrap: wrap;
		gap: 8px;
	}

	.sources-header h3 {
		font-size: 1.05rem;
		font-weight: 700;
		color: #f1f5f9;
		margin: 0;
	}

	.sources-hint {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.sources-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 1rem;
	}

	.source-item {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 1rem;
		background: rgba(10, 14, 23, 0.8);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		text-decoration: none;
		color: inherit;
		transition: all 0.2s ease;
	}

	.source-item:hover {
		border-color: #8b5cf6;
		transform: translateY(-2px);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
		background: rgba(20, 26, 42, 0.9);
	}

	.source-top {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.score-badge {
		font-size: 0.72rem;
		font-family: var(--font-mono);
		color: #34d399;
		background: rgba(16, 185, 129, 0.1);
		padding: 2px 6px;
		border-radius: 4px;
	}

	.source-title {
		font-size: 0.92rem;
		font-weight: 600;
		color: #f8fafc;
		line-height: 1.35;
	}

	.source-snippet {
		font-size: 0.8rem;
		color: var(--text-secondary);
		line-height: 1.5;
		max-height: 4.5em;
		overflow: hidden;
		display: -webkit-box;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
	}

	.source-footer {
		margin-top: auto;
		padding-top: 6px;
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.78rem;
	}

	.open-link {
		color: #8b5cf6;
		font-weight: 600;
	}

	.topic-pill {
		font-size: 0.72rem;
		color: var(--text-muted);
		background: rgba(255, 255, 255, 0.05);
		padding: 1px 6px;
		border-radius: 4px;
	}

	.spinner {
		width: 14px;
		height: 14px;
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
