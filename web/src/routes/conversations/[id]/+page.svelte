<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { getConversationDetail } from '$lib/api';
	import type { ConversationDetail } from '$lib/types';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';
	import MarkdownViewer from '$lib/components/MarkdownViewer.svelte';
	import ChatMessage from '$lib/components/ChatMessage.svelte';
	import LocalAccessModal from '$lib/components/LocalAccessModal.svelte';
	import RamIcon from '$lib/components/RamIcon.svelte';
	import { calculateTokenCost, formatCompactTokens, formatFullTokens, PRICES_UPDATED } from '$lib/pricing';
	import { buildSourceUrl, isLocalPlatform } from '$lib/sourceLinks';

	let conversation = $state<ConversationDetail | null>(null);
	let isLoading = $state(true);
	let copySuccess = $state(false);
	let localAccessOpen = $state(false);
	let showCostDetails = $state(false);

	// Tabs and filtering
	let activeTab = $state<'chat' | 'markdown' | 'raw'>('chat');
	let isPlainMode = $state(false);
	let roleFilter = $state<string>('all');
	let searchQuery = $state<string>('');

	const id = $derived(page.params.id);

	async function loadDetail() {
		if (!id) return;
		isLoading = true;
		try {
			conversation = await getConversationDetail(id);
		} catch (e) {
			console.error('Failed to load conversation details:', e);
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		const searchParams = new URLSearchParams(window.location.search);
		if (searchParams.get('plain') === '1' || searchParams.get('plain') === 'true') {
			isPlainMode = true;
		} else if (searchParams.get('raw') === '1' || searchParams.get('raw') === 'true' || searchParams.get('format') === 'raw') {
			activeTab = 'raw';
		}
		loadDetail();
	});

	async function copyMarkdown() {
		if (!conversation?.content_markdown) return;
		
		// 1. Try modern clipboard API (works in HTTPS or localhost)
		try {
			if (navigator.clipboard && window.isSecureContext) {
				await navigator.clipboard.writeText(conversation.content_markdown);
				copySuccess = true;
				setTimeout(() => { copySuccess = false; }, 2500);
				return;
			}
		} catch (err) {
			console.warn('navigator.clipboard failed:', err);
		}

		// 2. Resilient fallback for HTTP / non-secure contexts (e.g. http://archive)
		try {
			const textArea = document.createElement('textarea');
			textArea.value = conversation.content_markdown;
			textArea.style.position = 'fixed';
			textArea.style.left = '-9999px';
			textArea.style.top = '-9999px';
			textArea.setAttribute('readonly', '');
			document.body.appendChild(textArea);
			textArea.select();
			const successful = document.execCommand('copy');
			document.body.removeChild(textArea);
			if (successful) {
				copySuccess = true;
				setTimeout(() => { copySuccess = false; }, 2500);
				return;
			}
		} catch (fallbackErr) {
			console.error('execCommand fallback failed:', fallbackErr);
		}

		// 3. If automatic copy is blocked, switch directly to raw view for manual selection
		activeTab = 'raw';
	}

	function formatDate(iso?: string): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleDateString('pl-PL', {
				year: 'numeric',
				month: 'long',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	const sourceUrl = $derived(
		conversation ? buildSourceUrl(conversation.platform, conversation.external_id) : null
	);
	const isLocal = $derived(conversation ? isLocalPlatform(conversation.platform) : false);

	const messages = $derived(conversation?.messages || []);

	const filteredMessages = $derived.by(() => {
		let list = messages;
		if (roleFilter !== 'all') {
			if (roleFilter === 'tools') {
				list = list.filter(m => (m.tool_calls && m.tool_calls.length > 0) || m.role === 'tool');
			} else {
				list = list.filter(m => m.role.toLowerCase() === roleFilter);
			}
		}
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			list = list.filter(m => 
				m.content.toLowerCase().includes(q) ||
				(m.reasoning_content && m.reasoning_content.toLowerCase().includes(q)) ||
				(m.tool_calls && JSON.stringify(m.tool_calls).toLowerCase().includes(q))
			);
		}
		return list;
	});

	// Long agent sessions have thousands of messages - mounting every
	// ChatMessage at once freezes the tab, so render them in pages.
	const MESSAGE_PAGE = 150;
	let visibleCount = $state(MESSAGE_PAGE);
	$effect(() => {
		roleFilter;
		searchQuery;
		visibleCount = MESSAGE_PAGE;
	});
	const visibleMessages = $derived(filteredMessages.slice(0, visibleCount));

	// Same for the rendered Markdown tab: multi-MB sessions only render a head.
	const MARKDOWN_RENDER_LIMIT = 500_000;
	const markdownTooLarge = $derived((conversation?.content_markdown?.length ?? 0) > MARKDOWN_RENDER_LIMIT);

	const stats = $derived.by(() => {
		const total = messages.length;
		const userCount = messages.filter(m => m.role.toLowerCase() === 'user' || m.role.toLowerCase() === 'human').length;
		const assistantCount = messages.filter(m => m.role.toLowerCase() === 'assistant' || m.role.toLowerCase() === 'model').length;
		const toolCount = messages.reduce((acc, m) => acc + (m.tool_calls ? m.tool_calls.length : 0), 0);
		return { total, userCount, assistantCount, toolCount };
	});

	const usageStats = $derived.by(() => {
		if (!conversation) return null;

		const sessionUsage = conversation.token_summary || 
			conversation.raw_metadata?.token_summary ||
			conversation.raw_metadata?.usage || 
			conversation.raw_metadata?.aggregateUsage;

		if (sessionUsage && (sessionUsage.inputTokens || sessionUsage.input_tokens || sessionUsage.outputTokens || sessionUsage.output_tokens || sessionUsage.totalTokens || sessionUsage.total_tokens)) {
			return calculateTokenCost(sessionUsage, conversation.model, conversation.platform);
		}

		let inTok = 0;
		let outTok = 0;
		let cacheRead = 0;
		let cacheWrite = 0;
		let hasAny = false;

		for (const m of messages) {
			if (m.token_usage) {
				inTok += Number(m.token_usage.input_tokens ?? m.token_usage.inputTokens ?? m.token_usage.input ?? 0);
				outTok += Number(m.token_usage.output_tokens ?? m.token_usage.outputTokens ?? m.token_usage.output ?? 0);
				cacheRead += Number(m.token_usage.cache_read_tokens ?? m.token_usage.cacheReadTokens ?? m.token_usage.cache_read ?? 0);
				cacheWrite += Number(m.token_usage.cache_write_tokens ?? m.token_usage.cacheWriteTokens ?? m.token_usage.cache_write ?? 0);
				if (inTok > 0 || outTok > 0 || m.token_usage.total_tokens || m.token_usage.total) {
					hasAny = true;
				}
			}
		}

		if (hasAny) {
			return calculateTokenCost({
				input_tokens: inTok,
				output_tokens: outTok,
				cache_read_tokens: cacheRead,
				cache_write_tokens: cacheWrite,
				total_tokens: inTok + outTok + cacheRead + cacheWrite
			}, conversation.model, conversation.platform);
		}

		return null;
	});
</script>

<svelte:head>
	<title>{conversation?.title || 'Konwersacja'} | Brain LLM Archive</title>
</svelte:head>

{#if isPlainMode}
	<div class="plain-markdown-wrapper">
		<div class="plain-markdown-bar">
			<a href={page.url.pathname} class="plain-back-btn">← Powrót do widoku ze stylami</a>
			<button class="plain-action-btn" onclick={copyMarkdown}>
				{copySuccess ? '✓ Skopiowano Markdown!' : '📋 Kopiuj pełny Markdown'}
			</button>
			<span class="plain-note">Widok czystego tekstu bez styli CSS. Użyj <strong>Ctrl+A</strong> i <strong>Ctrl+C</strong>, aby zaznaczyć i skopiować całość.</span>
		</div>
		<pre class="plain-markdown-content">{conversation?.content_markdown || (isLoading ? 'Pobieranie treści markdown z bazy...' : 'Brak treści markdown.')}</pre>
	</div>
{:else}
<div class="detail-page">
	<div class="top-nav">
		<a href="{base}/conversations" class="back-link">
			← Powrót do listy
		</a>

		<div class="top-actions">
			{#if conversation}
				<a 
					href="{base}/conversations/{id}/raw" 
					target="_blank"
					rel="noopener noreferrer"
					class="raw-link-btn" 
					title="Otwórz surowy tekst Markdown w nowej karcie (text/plain)"
				>
					📄 Raw
				</a>
				<button class="copy-btn" onclick={copyMarkdown} title="Skopiuj zawartość Markdown do schowka">
					{#if copySuccess}
						✓ Skopiowano!
					{:else}
						📋 Kopiuj
					{/if}
				</button>
			{/if}
		</div>
	</div>

	{#if isLoading}
		<div class="loading-state glass-card">
			<div class="spinner-large"></div>
			<p>Pobieranie dokumentu konwersacji z bazy...</p>
		</div>
	{:else if conversation}
		<header class="conv-header glass-card">
			<div class="header-main">
				<div class="title-row">
					<PlatformBadge platform={conversation.platform} />
					<h1 class="header-title">{conversation.title || 'Bez tytułu'}</h1>
					{#if sourceUrl}
						<a
							class="source-link-icon"
							href={sourceUrl}
							target="_blank"
							rel="noopener noreferrer"
							title="Otwórz oryginalną konwersację na {conversation.platform}"
						>
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
								<polyline points="15 3 21 3 21 9"></polyline>
								<line x1="10" y1="14" x2="21" y2="3"></line>
							</svg>
						</a>
					{:else if isLocal}
						<button
							class="source-link-icon"
							onclick={() => localAccessOpen = true}
							title="Pokaż jak dostać się do plików tej sesji na dysku"
						>
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
							</svg>
						</button>
					{/if}
				</div>

				<div class="meta-tags">
					<span class="meta-item">
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<circle cx="12" cy="12" r="10"></circle>
							<polyline points="12 6 12 12 16 14"></polyline>
						</svg>
						{formatDate(conversation.started_at)}
					</span>

					{#if conversation.project_path}
						<span class="meta-item">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
							</svg>
							<code>{conversation.project_path}</code>
						</span>
					{/if}

					{#if conversation.git_branch}
						<span class="meta-item">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<line x1="6" y1="3" x2="6" y2="15"></line>
								<circle cx="18" cy="6" r="3"></circle>
								<circle cx="6" cy="18" r="3"></circle>
								<path d="M18 9a9 9 0 0 1-9 9"></path>
							</svg>
							<code>{conversation.git_branch}</code>
						</span>
					{/if}

					{#if conversation.model}
						<span class="meta-item model-ram-pill" title="Model użyty w tej sesji: {conversation.model}">
							<RamIcon size={14} />
							<span>{conversation.model}</span>
						</span>
					{/if}

					{#if conversation.relative_path}
						<span class="meta-item file-pill">
							Plik: <code>doc/llm-archive/{conversation.relative_path}</code>
						</span>
					{/if}
				</div>

				<!-- Stats Counter Pills -->
				<div class="quick-stats">
					<div class="stat-badge">
						<span class="stat-number">{stats.total}</span>
						<span class="stat-label">wiadomości</span>
					</div>
					<div class="stat-badge user-stat">
						<span class="stat-number">{stats.userCount}</span>
						<span class="stat-label">użytkownik</span>
					</div>
					<div class="stat-badge assistant-stat">
						<span class="stat-number">{stats.assistantCount}</span>
						<span class="stat-label">asystent</span>
					</div>
					{#if stats.toolCount > 0}
						<div class="stat-badge tool-stat">
							<span class="stat-number">{stats.toolCount}</span>
							<span class="stat-label">narzędzi</span>
						</div>
					{/if}

					{#if usageStats && (usageStats.totalTokens > 0 || usageStats.activeTokens > 0)}
						<button 
							type="button"
							class="stat-badge token-stat" 
							onclick={() => showCostDetails = !showCostDetails}
							title="Aktywne tokeny: {formatFullTokens(usageStats.activeTokens)} ({formatCompactTokens(usageStats.cacheMissTokens)} prompt + {formatCompactTokens(usageStats.outputTokens)} odpowiedź). {usageStats.cacheReadTokens > 0 ? `Cache hit: ${formatFullTokens(usageStats.cacheReadTokens)}.` : ''} Kliknij po szczegóły."
						>
							<span class="stat-icon-wrapper"><RamIcon size={14} /></span>
							<span class="stat-number">{formatCompactTokens(usageStats.activeTokens || usageStats.totalTokens)}</span>
							<span class="stat-label">tokenów {usageStats.cacheReadTokens > 0 ? `(+${formatCompactTokens(usageStats.cacheReadTokens)} c)` : ''}</span>
						</button>

						<button 
							type="button"
							class="stat-badge cost-stat" 
							onclick={() => showCostDetails = !showCostDetails}
							title="{usageStats.isFreeTier ? `Koszt rzeczywisty: $0.00 (Plan darmowy). Wycena API: ${usageStats.totalCostFormatted} USD (${usageStats.plnFormatted}).` : usageStats.pricing ? `Szacunek wg cennika LiteLLM (${usageStats.pricing.id}): ${usageStats.totalCostFormatted} USD (${usageStats.plnFormatted}).` : `Model ${conversation.model || '(nieznany)'} nie występuje w cenniku LiteLLM: koszt nieznany.`} Kliknij po szczegóły."
						>
							<span class="stat-icon-wrapper">💰</span>
							<span class="stat-number">{usageStats.userCostFormatted}</span>
							<span class="stat-label">{usageStats.isFreeTier ? 'plan darmowy' : 'koszt est.'}</span>
						</button>
					{/if}
				</div>

				{#if showCostDetails && usageStats}
					<div class="cost-breakdown-card glass-panel">
						<div class="breakdown-header">
							<div class="breakdown-title">
								<RamIcon size={16} />
								<span>Kalkulacja tokenów i kosztów: <strong>{usageStats.pricing?.id ?? `${conversation.model || 'nieznany model'} (brak w cenniku)`}</strong></span>
							</div>
							<button type="button" class="close-breakdown-btn" onclick={() => showCostDetails = false}>✕</button>
						</div>

						<div class="breakdown-grid">
							<div class="breakdown-col">
								<span class="col-title">Tokeny aktywne (Netto)</span>
								<div class="col-stat">
									<span class="col-val">{formatFullTokens(usageStats.activeTokens)}</span>
									<span class="col-sub">({formatCompactTokens(usageStats.activeTokens)} tok)</span>
								</div>
								<div class="cache-detail">
									<span>• Wyjście / Odpowiedź: {formatFullTokens(usageStats.outputTokens)} {usageStats.pricing ? `($${usageStats.pricing.outputPricePerM}/1M)` : ''}</span>
									<span>• Wejście / Nowy kontekst: {formatFullTokens(usageStats.cacheMissTokens)} {usageStats.pricing ? `($${usageStats.pricing.inputPricePerM}/1M)` : ''}</span>
								</div>
							</div>

							<div class="breakdown-col">
								<span class="col-title">Pamięć podręczna (Prompt Cache)</span>
								<div class="col-stat">
									<span class="col-val">{formatFullTokens(usageStats.cacheReadTokens)}</span>
									<span class="col-sub">({formatCompactTokens(usageStats.cacheReadTokens)} tok)</span>
								</div>
								<div class="cache-detail">
									{#if usageStats.cacheReadTokens > 0}
										{#if usageStats.pricing}<span>• Stawka Cache Hit: ${usageStats.pricing.cacheReadPricePerM} / 1M tokenów</span>{/if}
										<span>• Łączny wolumen transferu: {formatFullTokens(usageStats.totalTokens)} tok</span>
									{:else}
										<span>Brak użycia pamięci podręcznej prompt cache</span>
									{/if}
								</div>
							</div>

							<div class="breakdown-col highlight-col">
								<span class="col-title">Rozliczenie finansowe</span>
								<div class="col-stat">
									{#if usageStats.isFreeTier}
										<span class="cost-big text-free">$0.00 USD</span>
										<span class="col-sub">(0.00 zł)</span>
									{:else}
										<span class="cost-big">{usageStats.totalCostFormatted} USD</span>
										<span class="col-sub">({usageStats.plnFormatted})</span>
									{/if}
								</div>
								<div class="cache-detail">
									{#if usageStats.isFreeTier}
										<span class="free-tier-tag">✨ Plan darmowy (Wycena API: {usageStats.totalCostFormatted} / {usageStats.plnFormatted})</span>
									{:else}
										<span>{usageStats.pricing ? `Cennik LiteLLM (${usageStats.pricing.provider}), stan na ${PRICES_UPDATED}` : 'Brak modelu w cenniku LiteLLM'}</span>
									{/if}
								</div>
							</div>
						</div>
					</div>
				{/if}
			</div>
		</header>

		<!-- Mode Switcher Tabs & Filter Toolbar -->
		<div class="view-controls glass-card">
			<div class="tabs-group">
				<button 
					class="tab-btn" 
					class:active={activeTab === 'chat'} 
					onclick={() => activeTab = 'chat'}
				>
					<span class="tab-icon">💬</span>
					<span>Czat / Wiadomości</span>
					<span class="tab-count">{messages.length}</span>
				</button>

				<button 
					class="tab-btn" 
					class:active={activeTab === 'markdown'} 
					onclick={() => activeTab = 'markdown'}
				>
					<span class="tab-icon">📄</span>
					<span>Pełny Markdown</span>
				</button>

				<button 
					class="tab-btn" 
					class:active={activeTab === 'raw'} 
					onclick={() => activeTab = 'raw'}
				>
					<span class="tab-icon">📝</span>
					<span>Czysty Markdown (bez CSS)</span>
				</button>
			</div>

			{#if activeTab === 'chat' && messages.length > 0}
				<div class="filters-group">
					<div class="filter-pill-selector">
						<button 
							class="filter-pill" 
							class:active={roleFilter === 'all'} 
							onclick={() => roleFilter = 'all'}
						>
							Wszystkie ({messages.length})
						</button>
						<button 
							class="filter-pill" 
							class:active={roleFilter === 'user'} 
							onclick={() => roleFilter = 'user'}
						>
							Użytkownik ({stats.userCount})
						</button>
						<button 
							class="filter-pill" 
							class:active={roleFilter === 'assistant'} 
							onclick={() => roleFilter = 'assistant'}
						>
							Asystent ({stats.assistantCount})
						</button>
						{#if stats.toolCount > 0}
							<button 
								class="filter-pill" 
								class:active={roleFilter === 'tools'} 
								onclick={() => roleFilter = 'tools'}
							>
								Narzędzia ({stats.toolCount})
							</button>
						{/if}
					</div>

					<div class="search-box">
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<circle cx="11" cy="11" r="8"></circle>
							<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
						</svg>
						<input 
							type="text" 
							placeholder="Filtruj w konwersacji..." 
							bind:value={searchQuery}
						/>
						{#if searchQuery}
							<button class="clear-search" onclick={() => searchQuery = ''}>✕</button>
						{/if}
					</div>
				</div>
			{/if}
		</div>

		<!-- Main Content Panels -->
		{#if activeTab === 'chat'}
			{#if messages.length === 0}
				<div class="empty-state glass-card">
					<p>Brak szczegółowych wiadomości w tej sesji. Przełącz na widok <strong>Pełny Markdown</strong>.</p>
				</div>
			{:else if filteredMessages.length === 0}
				<div class="empty-state glass-card">
					<p>Brak wiadomości pasujących do filtra.</p>
					<button class="reset-filter-btn" onclick={() => { roleFilter = 'all'; searchQuery = ''; }}>
						Wyczyść filtry
					</button>
				</div>
			{:else}
				<div class="chat-feed">
					{#each visibleMessages as msg (msg.step_index)}
						<ChatMessage message={msg} modelName={conversation.model} />
					{/each}
				</div>
				{#if visibleCount < filteredMessages.length}
					<div class="load-more">
						<span>Pokazano {visibleCount} z {filteredMessages.length}</span>
						<button class="reset-filter-btn" onclick={() => visibleCount += MESSAGE_PAGE}>
							Pokaż kolejne {Math.min(MESSAGE_PAGE, filteredMessages.length - visibleCount)}
						</button>
					</div>
				{/if}
			{/if}
		{:else if activeTab === 'markdown'}
			<div class="content-panel glass-panel">
				{#if markdownTooLarge}
					<div class="load-more">
						<span>Markdown ma {((conversation.content_markdown?.length ?? 0) / 1_000_000).toFixed(1)} MB — renderuję pierwsze {MARKDOWN_RENDER_LIMIT / 1000} KB.</span>
						<button class="reset-filter-btn" onclick={() => activeTab = 'raw'}>Pełny tekst</button>
					</div>
				{/if}
				<MarkdownViewer content={(markdownTooLarge ? conversation.content_markdown?.slice(0, MARKDOWN_RENDER_LIMIT) : conversation.content_markdown) || 'Brak treści markdown.'} />
			</div>
		{:else}
			<div class="raw-panel glass-panel">
				<div class="raw-panel-header">
					<span class="raw-hint">💡 Czysty tekst Markdown bez styli CSS — kliknij w tekst, użyj <strong>Ctrl+A</strong> i <strong>Ctrl+C</strong>, aby zaznaczyć całość.</span>
					<div class="raw-actions">
						<button class="raw-action-btn" onclick={copyMarkdown}>
							{copySuccess ? '✓ Skopiowano całość!' : '📋 Kopiuj całość'}
						</button>
						<a href="?plain=1" class="raw-action-link" target="_blank" title="Otwórz czysty tekst bez żadnych styli">
							↗ Nowa karta (bez CSS)
						</a>
					</div>
				</div>
				<pre class="raw-text-block" tabindex="0">{conversation.content_markdown || 'Brak treści markdown.'}</pre>
			</div>
		{/if}
	{:else}
		<div class="empty-state glass-card">
			<p>Nie odnaleziono konwersacji o podanym identyfikatorze.</p>
		</div>
	{/if}
</div>
{/if}

{#if conversation && isLocal}
	<LocalAccessModal
		bind:open={localAccessOpen}
		platform={conversation.platform}
		externalId={conversation.external_id}
		device={conversation.device}
		projectPath={conversation.project_path}
	/>
{/if}

<style>
	.detail-page {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.top-nav {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.back-link {
		color: var(--text-secondary);
		text-decoration: none;
		font-size: 0.9rem;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		transition: color var(--transition-quick);
	}

	.back-link:hover {
		color: var(--text-accent);
	}

	.top-actions {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.plain-link-btn, .raw-link-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid rgba(255, 255, 255, 0.15);
		color: #e2e8f0;
		padding: 6px 12px;
		border-radius: var(--radius-sm);
		text-decoration: none;
		font-size: 0.82rem;
		font-weight: 500;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		transition: all var(--transition-quick);
	}

	.plain-link-btn:hover, .raw-link-btn:hover {
		background: rgba(56, 189, 248, 0.15);
		border-color: rgba(56, 189, 248, 0.4);
		color: #38bdf8;
	}

	.copy-btn {
		background: rgba(6, 182, 212, 0.12);
		border: 1px solid var(--color-antigravity);
		color: #38bdf8;
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		transition: all var(--transition-quick);
	}

	.copy-btn:hover {
		background: rgba(6, 182, 212, 0.22);
	}

	/* Plain unstyled mode */
	.plain-markdown-wrapper {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem 1rem 3rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
	}

	.plain-markdown-bar {
		display: flex;
		align-items: center;
		gap: 14px;
		flex-wrap: wrap;
		margin-bottom: 1.25rem;
		padding-bottom: 1rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.15);
	}

	.plain-back-btn {
		color: #38bdf8;
		text-decoration: none;
		font-size: 0.85rem;
		font-weight: 600;
		background: rgba(56, 189, 248, 0.1);
		padding: 6px 12px;
		border-radius: 4px;
		border: 1px solid rgba(56, 189, 248, 0.3);
	}

	.plain-back-btn:hover {
		background: rgba(56, 189, 248, 0.2);
	}

	.plain-action-btn {
		background: rgba(16, 185, 129, 0.15);
		border: 1px solid rgba(16, 185, 129, 0.4);
		color: #34d399;
		padding: 6px 14px;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 600;
	}

	.plain-note {
		color: #94a3b8;
		font-size: 0.8rem;
	}

	.plain-markdown-content {
		white-space: pre-wrap;
		word-break: break-word;
		font-family: inherit;
		font-size: 0.95rem;
		line-height: 1.65;
		color: #f8fafc;
		background: #020617;
		padding: 1.5rem;
		border-radius: 6px;
		border: 1px solid #1e293b;
		user-select: text;
	}

	/* Raw panel in standard tabs */
	.raw-panel {
		padding: 1.25rem;
	}

	.raw-panel-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding-bottom: 0.75rem;
		margin-bottom: 1rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
		flex-wrap: wrap;
		gap: 10px;
	}

	.raw-hint {
		font-size: 0.82rem;
		color: #94a3b8;
	}

	.raw-actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.raw-action-btn {
		background: rgba(56, 189, 248, 0.12);
		border: 1px solid rgba(56, 189, 248, 0.35);
		color: #38bdf8;
		padding: 5px 12px;
		border-radius: 4px;
		font-size: 0.8rem;
		font-weight: 500;
		cursor: pointer;
	}

	.raw-action-btn:hover {
		background: rgba(56, 189, 248, 0.22);
	}

	.raw-action-link {
		color: #94a3b8;
		font-size: 0.8rem;
		text-decoration: underline;
	}

	.raw-action-link:hover {
		color: #e2e8f0;
	}

	.raw-text-block {
		white-space: pre-wrap;
		word-break: break-word;
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.88rem;
		line-height: 1.6;
		color: #f1f5f9;
		background: #090d16;
		padding: 1.25rem;
		border-radius: 6px;
		user-select: text;
		border: 1px solid rgba(255, 255, 255, 0.06);
		max-height: 75vh;
		overflow-y: auto;
	}

	.conv-header {
		padding: 1.5rem;
	}

	.title-row {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-bottom: 0.85rem;
	}

	.source-link-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border-radius: var(--radius-sm);
		border: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(255, 255, 255, 0.04);
		color: var(--text-muted);
		cursor: pointer;
		flex-shrink: 0;
		transition: all var(--transition-quick);
	}

	.source-link-icon:hover {
		color: #38bdf8;
		border-color: rgba(6, 182, 212, 0.4);
		background: rgba(6, 182, 212, 0.1);
	}

	.header-title {
		font-size: 1.55rem;
		font-weight: 700;
		color: #ffffff;
		line-height: 1.3;
	}

	.meta-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 0.82rem;
		color: var(--text-muted);
		margin-bottom: 1rem;
	}

	.meta-item {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.meta-item code {
		font-family: var(--font-mono);
		color: var(--text-secondary);
		background: rgba(255, 255, 255, 0.05);
		padding: 2px 6px;
		border-radius: 4px;
	}


	.model-ram-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: #c084fc;
		background: rgba(168, 85, 247, 0.12);
		border: 1px solid rgba(168, 85, 247, 0.3);
		padding: 2px 8px;
		border-radius: 4px;
		font-family: var(--font-mono);
		font-weight: 500;
	}

	.file-pill {
		color: var(--text-secondary);
	}

	/* Quick Stats */
	.quick-stats {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		padding-top: 0.85rem;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}

	.stat-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.08);
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		font-size: 0.78rem;
		cursor: default;
	}

	button.stat-badge {
		cursor: pointer;
		transition: all var(--transition-quick);
	}

	.stat-icon-wrapper {
		display: inline-flex;
		align-items: center;
		color: var(--text-muted);
	}

	.token-stat {
		border-color: rgba(168, 85, 247, 0.3);
		background: rgba(168, 85, 247, 0.08);
	}
	button.token-stat:hover {
		border-color: rgba(168, 85, 247, 0.6);
		background: rgba(168, 85, 247, 0.16);
	}
	.token-stat .stat-number {
		color: #e9d5ff;
	}
	.token-stat .stat-icon-wrapper {
		color: #c084fc;
	}

	.cost-stat {
		border-color: rgba(52, 211, 153, 0.35);
		background: rgba(52, 211, 153, 0.08);
	}
	button.cost-stat:hover {
		border-color: rgba(52, 211, 153, 0.7);
		background: rgba(52, 211, 153, 0.16);
	}
	.cost-stat .stat-number {
		color: #34d399;
	}

	/* Cost Breakdown Card */
	.cost-breakdown-card {
		margin-top: 1rem;
		padding: 1rem 1.25rem;
		background: rgba(15, 23, 42, 0.85);
		border: 1px solid rgba(168, 85, 247, 0.35);
		border-radius: var(--radius-md);
		animation: fadeIn 0.2s ease-out;
	}

	.breakdown-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.85rem;
		padding-bottom: 0.6rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.08);
	}

	.breakdown-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.88rem;
		color: #e2e8f0;
	}

	.breakdown-title strong {
		color: #c084fc;
	}

	.close-breakdown-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.9rem;
		padding: 2px 6px;
		border-radius: 4px;
	}

	.close-breakdown-btn:hover {
		color: #ffffff;
		background: rgba(255, 255, 255, 0.1);
	}

	.breakdown-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 1rem;
	}

	.breakdown-col {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 0.75rem;
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid rgba(255, 255, 255, 0.05);
		border-radius: var(--radius-sm);
	}

	.breakdown-col.highlight-col {
		background: rgba(52, 211, 153, 0.05);
		border-color: rgba(52, 211, 153, 0.25);
	}

	.col-title {
		font-size: 0.73rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
	}

	.col-stat {
		display: flex;
		align-items: baseline;
		gap: 6px;
		margin: 4px 0;
	}

	.col-val {
		font-size: 1.15rem;
		font-weight: 700;
		font-family: var(--font-mono);
		color: #f8fafc;
	}

	.cost-big {
		font-size: 1.25rem;
		font-weight: 700;
		font-family: var(--font-mono);
		color: #34d399;
	}
	.cost-big.text-free {
		color: #60a5fa;
	}

	.col-sub {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.cache-detail {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.75rem;
		color: var(--text-secondary);
		margin-top: 4px;
	}

	.free-tier-tag {
		color: #38bdf8;
		font-weight: 500;
	}

	.stat-number {
		font-weight: 700;
		font-family: var(--font-mono);
		color: var(--text-primary);
	}

	.stat-label {
		color: var(--text-muted);
	}

	.user-stat {
		border-color: rgba(6, 182, 212, 0.25);
		background: rgba(6, 182, 212, 0.06);
	}
	.user-stat .stat-number {
		color: #38bdf8;
	}

	.assistant-stat {
		border-color: rgba(168, 85, 247, 0.25);
		background: rgba(168, 85, 247, 0.06);
	}
	.assistant-stat .stat-number {
		color: #c084fc;
	}

	.tool-stat {
		border-color: rgba(245, 158, 11, 0.25);
		background: rgba(245, 158, 11, 0.06);
	}
	.tool-stat .stat-number {
		color: #fbbf24;
	}

	/* View Controls (Tabs + Filters) */
	.view-controls {
		padding: 0.75rem 1.25rem;
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}

	.tabs-group {
		display: flex;
		gap: 6px;
		background: rgba(0, 0, 0, 0.25);
		padding: 4px;
		border-radius: var(--radius-md);
		border: 1px solid rgba(255, 255, 255, 0.05);
	}

	.tab-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		border: none;
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 500;
		transition: all var(--transition-quick);
	}

	.tab-btn:hover {
		color: var(--text-primary);
	}

	.tab-btn.active {
		background: rgba(255, 255, 255, 0.1);
		color: #ffffff;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.tab-count {
		font-size: 0.72rem;
		font-family: var(--font-mono);
		background: rgba(255, 255, 255, 0.1);
		padding: 1px 6px;
		border-radius: 10px;
	}

	.filters-group {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
	}

	.filter-pill-selector {
		display: flex;
		gap: 4px;
	}

	.filter-pill {
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.08);
		color: var(--text-muted);
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		font-size: 0.75rem;
		cursor: pointer;
		transition: all var(--transition-quick);
	}

	.filter-pill:hover {
		color: var(--text-secondary);
		border-color: rgba(255, 255, 255, 0.18);
	}

	.filter-pill.active {
		background: rgba(6, 182, 212, 0.15);
		border-color: #06b6d4;
		color: #38bdf8;
		font-weight: 500;
	}

	.search-box {
		display: flex;
		align-items: center;
		gap: 6px;
		background: rgba(0, 0, 0, 0.3);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: var(--radius-sm);
		padding: 4px 10px;
		color: var(--text-muted);
	}

	.search-box input {
		background: transparent;
		border: none;
		outline: none;
		color: var(--text-primary);
		font-size: 0.8rem;
		width: 160px;
	}

	.search-box input::placeholder {
		color: var(--text-muted);
	}

	.clear-search {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.75rem;
		padding: 0 2px;
	}

	.clear-search:hover {
		color: var(--text-primary);
	}

	/* Chat Feed */
	.load-more {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		margin: 1.5rem 0;
		color: var(--text-muted, #94a3b8);
	}

	.chat-feed {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	/* Markdown Panel */
	.content-panel {
		padding: 2rem;
		background: rgba(13, 18, 31, 0.8);
		border-radius: var(--radius-md);
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

	.reset-filter-btn {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.15);
		color: var(--text-primary);
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.8rem;
		transition: background var(--transition-quick);
	}

	.reset-filter-btn:hover {
		background: rgba(255, 255, 255, 0.15);
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
