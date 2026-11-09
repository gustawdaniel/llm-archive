<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import {
		getTopic,
		suggestForTopic,
		assignToTopic,
		unassignFromTopic,
		updateTopic,
		deleteTopic,
		searchArchive,
		getTopicTimeline,
		getTopicContext
	} from '$lib/api';
	import type { TopicDetail, TopicSuggestion, SearchResultItem, TopicTimelineItem, TopicContextExport } from '$lib/types';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';
	import ConversationPreviewModal from '$lib/components/ConversationPreviewModal.svelte';

	let topicId = $derived(page.params.id ?? '');
	let topic = $state<TopicDetail | null>(null);
	let suggestions = $state<TopicSuggestion[]>([]);
	let timeline = $state<TopicTimelineItem[]>([]);
	let timelineLoading = $state(false);
	let exportModalOpen = $state(false);
	let contextExport = $state<TopicContextExport | null>(null);
	let contextLoading = $state(false);
	let copiedContext = $state(false);
	let isLoading = $state(true);
	let suggestLoading = $state(false);
	let busyId = $state<string | null>(null);
	let editing = $state(false);
	let editName = $state('');
	let editDescription = $state('');
	let editKeywords = $state<string[]>([]);
	let newKeywordInput = $state('');
	let saving = $state(false);
	let deleting = $state(false);
	let previewId = $state<string | null>(null);

	// Manual "search and attach" box - reuses the same hybrid search as the
	// main search page, results just get an "Add" button instead of a preview.
	let searchQuery = $state('');
	let searchResults = $state<SearchResultItem[]>([]);
	let searchLoading = $state(false);

	let maxTimelineCount = $derived(
		timeline.length ? Math.max(...timeline.map((t) => t.count), 1) : 1
	);

	async function loadTopic() {
		isLoading = true;
		topic = await getTopic(topicId);
		isLoading = false;
		if (topic) {
			loadSuggestions();
			loadTimeline();
		}
	}

	async function loadTimeline() {
		timelineLoading = true;
		timeline = await getTopicTimeline(topicId);
		timelineLoading = false;
	}

	async function openExportModal() {
		exportModalOpen = true;
		if (!contextExport) {
			contextLoading = true;
			contextExport = await getTopicContext(topicId);
			contextLoading = false;
		}
	}

	async function copyContextText() {
		if (!contextExport?.markdown) return;
		await navigator.clipboard.writeText(contextExport.markdown);
		copiedContext = true;
		setTimeout(() => (copiedContext = false), 2500);
	}

	async function loadSuggestions() {
		suggestLoading = true;
		suggestions = await suggestForTopic(topicId, 10);
		suggestLoading = false;
	}

	onMount(loadTopic);

	async function handleAssign(conversationId: string) {
		busyId = conversationId;
		const ok = await assignToTopic(topicId, conversationId);
		busyId = null;
		if (ok) {
			suggestions = suggestions.filter((s) => s.id !== conversationId);
			await loadTopic();
		}
	}

	async function handleUnassign(conversationId: string) {
		busyId = conversationId;
		const ok = await unassignFromTopic(topicId, conversationId);
		busyId = null;
		if (ok) await loadTopic();
	}

	function startEdit() {
		if (!topic) return;
		editName = topic.name;
		editDescription = topic.description ?? '';
		editKeywords = [...(topic.keywords ?? [])];
		newKeywordInput = '';
		editing = true;
	}

	function removeEditKeyword(kw: string) {
		editKeywords = editKeywords.filter((k) => k !== kw);
	}

	function addEditKeyword() {
		const kw = newKeywordInput.trim();
		if (kw && !editKeywords.includes(kw)) editKeywords = [...editKeywords, kw];
		newKeywordInput = '';
	}

	async function handleSave() {
		if (!topic || !editName.trim()) return;
		saving = true;
		const updated = await updateTopic(topicId, {
			name: editName.trim(),
			description: editDescription,
			keywords: editKeywords
		});
		saving = false;
		if (updated) {
			topic = { ...topic, name: updated.name, description: updated.description, keywords: updated.keywords };
			editing = false;
		}
	}

	async function handleDeleteTopic() {
		if (!topic) return;
		if (!confirm(`Usunąć temat "${topic.name}"? Konwersacje zostają, tylko grupowanie zniknie.`)) return;
		deleting = true;
		const ok = await deleteTopic(topicId);
		deleting = false;
		if (ok) goto('/topics');
	}

	async function handleSearch() {
		if (!searchQuery.trim()) return;
		searchLoading = true;
		const res = await searchArchive(searchQuery.trim());
		searchResults = res.results || [];
		searchLoading = false;
	}

	function formatDate(iso?: string | null): string {
		if (!iso) return '-';
		try {
			return new Date(iso).toLocaleDateString('pl-PL', { year: 'numeric', month: 'short', day: 'numeric' });
		} catch {
			return iso;
		}
	}

	let currentMemberIds = $derived(new Set(topic?.conversations.map((c) => c.id) ?? []));
</script>

<svelte:head>
	<title>{topic?.name ?? 'Temat'} | Brain LLM Archive</title>
</svelte:head>

<div class="topic-page">
	<a href="{base}/topics" class="back-link">← Wszystkie tematy</a>

	{#if isLoading}
		<div class="loading-state glass-card">
			<div class="spinner-large"></div>
			<p>Ładowanie tematu...</p>
		</div>
	{:else if !topic}
		<div class="empty-state glass-card">
			<p>Nie znaleziono tematu.</p>
		</div>
	{:else}
		<div class="topic-header glass-panel">
			{#if editing}
				<div class="edit-form">
					<input class="edit-name" bind:value={editName} placeholder="Nazwa tematu" />
					<textarea class="edit-description" bind:value={editDescription} placeholder="Opis (opcjonalnie)" rows="3"
					></textarea>
					<div class="edit-keywords">
						{#each editKeywords as kw}
							<span class="kw-chip editable">
								{kw}
								<button class="kw-remove" onclick={() => removeEditKeyword(kw)} title="Usuń słowo kluczowe">✕</button>
							</span>
						{/each}
						<input
							class="kw-input"
							bind:value={newKeywordInput}
							placeholder="+ nowe słowo kluczowe"
							onkeydown={(e) => {
								if (e.key === 'Enter') { e.preventDefault(); addEditKeyword(); }
							}}
						/>
					</div>
					<div class="edit-actions">
						<button class="save-btn" onclick={handleSave} disabled={saving || !editName.trim()}>
							{saving ? 'Zapisywanie...' : 'Zapisz'}
						</button>
						<button class="cancel-btn" onclick={() => (editing = false)}>Anuluj</button>
					</div>
				</div>
			{:else}
				<div class="header-top">
					<h1>{topic.name}</h1>
					<span class="badge" class:manual={topic.is_manual}>{topic.is_manual ? 'ręczny' : 'auto'}</span>
					<div class="header-actions">
						<button class="export-btn" onclick={openExportModal} title="Przygotuj prompt i brief startowy dla sesji Antigravity">
							⚡ Eksportuj do Antigravity
						</button>
						<button class="edit-btn" onclick={startEdit}>Edytuj</button>
						<button class="delete-topic-btn" onclick={handleDeleteTopic} disabled={deleting}>
							{deleting ? '...' : 'Usuń temat'}
						</button>
					</div>
				</div>
				{#if topic.description}
					<p class="description">{topic.description}</p>
				{/if}
				{#if topic.keywords?.length}
					<div class="keywords">
						{#each topic.keywords as kw}
							<span class="kw-chip">{kw}</span>
						{/each}
					</div>
				{/if}

				{#if timeline.length > 0}
					<div class="timeline-container">
						<div class="timeline-meta">
							<span class="timeline-title">Aktywność w czasie</span>
							<span class="timeline-count">{timeline.reduce((acc, t) => acc + t.count, 0)} rozmów w {timeline.length} tyg.</span>
						</div>
						<div class="timeline-bars">
							{#each timeline as item}
								<div class="timeline-col" title="{item.period}: {item.count} rozmów">
									<div
										class="timeline-fill"
										style="height: {Math.max((item.count / maxTimelineCount) * 100, 10)}%"
									></div>
									<span class="timeline-label">{item.period.slice(5)}</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<div class="columns">
			<!-- Members -->
			<div class="column">
				<h2>W temacie ({topic.conversations.length})</h2>
				<div class="member-list">
					{#each topic.conversations as c}
						<div class="member-row glass-card">
							<div class="member-info">
								<PlatformBadge platform={c.platform} />
								<button class="preview-title-btn" onclick={() => (previewId = c.id)}>{c.title}</button>
							</div>
							<div class="member-meta">
								<span class="source-badge" class:manual={c.source === 'manual'}>{c.source}</span>
								<span class="date">{formatDate(c.started_at)}</span>
								<button
									class="unassign-btn"
									disabled={busyId === c.id}
									onclick={() => handleUnassign(c.id)}
									title="Odczep od tematu"
								>
									✕
								</button>
							</div>
						</div>
					{:else}
						<p class="empty-hint">Pusto - dopnij pierwszą konwersację przez wyszukiwanie poniżej.</p>
					{/each}
				</div>
			</div>

			<!-- Suggestions + manual search -->
			<div class="column">
				<div class="column-header-row">
					<h2>Sugestie</h2>
					<button class="refresh-btn" onclick={loadSuggestions} disabled={suggestLoading}>
						{suggestLoading ? '...' : '↻ Odśwież'}
					</button>
				</div>
				<p class="hint">
					Liczone z centroidu tego, co już przypięte - im więcej zatwierdzisz, tym trafniejsze kolejne.
				</p>
				<div class="suggestion-list">
					{#each suggestions as s}
						<div class="suggestion-row glass-card">
							<div class="suggestion-info">
								<PlatformBadge platform={s.platform} />
								<button class="preview-title-btn" onclick={() => (previewId = s.id)}>{s.title}</button>
								<span class="score-badge">{s.score.toFixed(2)}</span>
							</div>
							<button class="assign-btn" disabled={busyId === s.id} onclick={() => handleAssign(s.id)}>
								{busyId === s.id ? '...' : '+ Dodaj'}
							</button>
						</div>
					{:else}
						{#if !suggestLoading}
							<p class="empty-hint">Brak sugestii - przypnij coś najpierw, żeby mieć od czego liczyć podobieństwo.</p>
						{/if}
					{/each}
				</div>

				<h2 class="search-heading">Szukaj i dopnij ręcznie</h2>
				<div class="search-box">
					<input
						bind:value={searchQuery}
						placeholder="Szukaj konwersacji..."
						onkeydown={(e) => e.key === 'Enter' && handleSearch()}
					/>
					<button onclick={handleSearch} disabled={searchLoading}>Szukaj</button>
				</div>
				<div class="suggestion-list">
					{#each searchResults as r}
						<div class="suggestion-row glass-card">
							<div class="suggestion-info">
								<PlatformBadge platform={r.platform} />
								<button class="preview-title-btn" onclick={() => (previewId = r.conversation_id)}>{r.title}</button>
							</div>
							{#if currentMemberIds.has(r.conversation_id)}
								<span class="already-in">już w temacie</span>
							{:else}
								<button
									class="assign-btn"
									disabled={busyId === r.conversation_id}
									onclick={() => handleAssign(r.conversation_id)}
								>
									{busyId === r.conversation_id ? '...' : '+ Dodaj'}
								</button>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		</div>
	{/if}
</div>

<ConversationPreviewModal conversationId={previewId} onClose={() => (previewId = null)} />

{#if exportModalOpen}
	<div class="modal-overlay" onclick={() => (exportModalOpen = false)} role="dialog" aria-modal="true">
		<div class="modal-card glass-panel" onclick={(e) => e.stopPropagation()}>
			<div class="modal-header">
				<h2>⚡ Kontekst i Prompt dla Antigravity</h2>
				<button class="modal-close-btn" onclick={() => (exportModalOpen = false)}>✕</button>
			</div>
			
			<div class="modal-body">
				<p class="modal-desc">
					Skopiuj poniższy skonsolidowany brief i wklej go bezpośrednio do sesji z Antigravity lub Claude Code. Zawiera chronologię, podsumowania i powiązane notatki.
				</p>

				{#if contextLoading}
					<div class="modal-loading">
						<div class="spinner-large"></div>
						<p>Generowanie kontekstu...</p>
					</div>
				{:else if contextExport}
					<div class="export-actions-bar">
						<button class="copy-primary-btn" onclick={copyContextText}>
							{copiedContext ? '✓ Skopiowano do schowka!' : '📋 Kopiuj pełny prompt startowy'}
						</button>
						<span class="export-count-badge">{contextExport.conversations_count} uwzględnionych sesji</span>
					</div>

					<pre class="markdown-preview"><code>{contextExport.markdown}</code></pre>
				{:else}
					<p class="empty-hint">Nie udało się pobrać kontekstu.</p>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.export-btn {
		background: linear-gradient(135deg, rgba(168, 85, 247, 0.25), rgba(99, 102, 241, 0.25));
		border: 1px solid rgba(168, 85, 247, 0.5);
		color: #e9d5ff;
		padding: 5px 14px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.8rem;
		font-weight: 600;
		transition: all 0.2s ease;
	}

	.export-btn:hover {
		background: linear-gradient(135deg, rgba(168, 85, 247, 0.4), rgba(99, 102, 241, 0.4));
		border-color: #c084fc;
		color: #ffffff;
		transform: translateY(-1px);
	}

	.timeline-container {
		margin-top: 0.5rem;
		padding: 0.75rem 1rem;
		border-radius: var(--radius-sm);
		background: rgba(255, 255, 255, 0.02);
		border: 1px solid var(--border-subtle);
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.timeline-meta {
		display: flex;
		justify-content: space-between;
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.timeline-title {
		font-weight: 600;
		color: var(--text-secondary);
	}

	.timeline-bars {
		display: flex;
		align-items: flex-end;
		gap: 6px;
		height: 48px;
		padding-top: 4px;
		overflow-x: auto;
	}

	.timeline-col {
		flex: 1;
		min-width: 14px;
		height: 100%;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		align-items: center;
		gap: 2px;
	}

	.timeline-fill {
		width: 100%;
		background: linear-gradient(to top, rgba(99, 102, 241, 0.6), rgba(168, 85, 247, 0.9));
		border-radius: 2px 2px 0 0;
		transition: height 0.3s ease;
	}

	.timeline-col:hover .timeline-fill {
		background: linear-gradient(to top, #6366f1, #c084fc);
	}

	.timeline-label {
		font-size: 0.6rem;
		color: var(--text-muted);
		writing-mode: vertical-rl;
		transform: rotate(180deg);
		max-height: 24px;
		display: none;
	}

	/* Modal Styles */
	.modal-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.75);
		backdrop-filter: blur(6px);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 999;
		padding: 1.5rem;
	}

	.modal-card {
		width: 100%;
		max-width: 760px;
		max-height: 85vh;
		background: #0f172a;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: var(--radius-md);
		display: flex;
		flex-direction: column;
		box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
		overflow: hidden;
	}

	.modal-header {
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--border-subtle);
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.modal-header h2 {
		font-size: 1.15rem;
		font-weight: 700;
		color: #f1f5f9;
		margin: 0;
	}

	.modal-close-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 4px 8px;
		border-radius: 4px;
	}

	.modal-close-btn:hover {
		color: #ffffff;
		background: rgba(255, 255, 255, 0.08);
	}

	.modal-body {
		padding: 1.25rem;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}

	.modal-desc {
		font-size: 0.85rem;
		color: var(--text-secondary);
		line-height: 1.4;
		margin: 0;
	}

	.export-actions-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.copy-primary-btn {
		background: linear-gradient(135deg, #8b5cf6, #6366f1);
		color: #ffffff;
		border: none;
		border-radius: var(--radius-sm);
		padding: 8px 18px;
		font-weight: 600;
		font-size: 0.9rem;
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.copy-primary-btn:hover {
		background: linear-gradient(135deg, #7c3aed, #4f46e5);
		transform: translateY(-1px);
	}

	.export-count-badge {
		font-size: 0.75rem;
		color: var(--text-muted);
		background: rgba(255, 255, 255, 0.04);
		padding: 4px 10px;
		border-radius: 9999px;
		border: 1px solid var(--border-subtle);
	}

	.markdown-preview {
		background: rgba(0, 0, 0, 0.4);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 1rem;
		max-height: 360px;
		overflow-y: auto;
		font-family: monospace;
		font-size: 0.8rem;
		line-height: 1.45;
		color: #cbd5e1;
		white-space: pre-wrap;
	}

	.modal-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		padding: 3rem 0;
		color: var(--text-muted);
	}

	.back-link {
		color: var(--text-muted);
		text-decoration: none;
		font-size: 0.85rem;
	}

	.back-link:hover {
		color: var(--text-primary);
	}

	.topic-header {
		padding: 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.header-top {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.header-actions {
		display: flex;
		gap: 8px;
		margin-left: auto;
	}

	.edit-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 5px 12px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.8rem;
	}

	.delete-topic-btn {
		background: rgba(239, 68, 68, 0.1);
		border: 1px solid rgba(239, 68, 68, 0.3);
		color: #f87171;
		padding: 5px 12px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.8rem;
	}

	.delete-topic-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.edit-form {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.edit-name {
		font-size: 1.2rem;
		font-weight: 700;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		color: var(--text-primary);
	}

	.edit-description {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		color: var(--text-primary);
		font-family: inherit;
		font-size: 0.9rem;
		resize: vertical;
	}

	.edit-actions {
		display: flex;
		gap: 8px;
	}

	.save-btn {
		background: linear-gradient(135deg, #06b6d4, #0284c7);
		color: #fff;
		border: none;
		border-radius: var(--radius-sm);
		padding: 6px 16px;
		font-weight: 600;
		cursor: pointer;
	}

	.save-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.cancel-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 6px 16px;
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.header-top h1 {
		font-size: 1.6rem;
		font-weight: 700;
	}

	.badge {
		font-size: 0.7rem;
		padding: 3px 10px;
		border-radius: var(--radius-pill);
		background: rgba(255, 255, 255, 0.06);
		color: var(--text-muted);
	}

	.badge.manual {
		background: rgba(16, 185, 129, 0.15);
		color: #34d399;
		border: 1px solid rgba(16, 185, 129, 0.3);
	}

	.description {
		color: var(--text-secondary);
		line-height: 1.5;
	}

	.keywords {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.kw-chip {
		font-size: 0.75rem;
		padding: 3px 10px;
		border-radius: var(--radius-pill);
		background: rgba(6, 182, 212, 0.1);
		color: #38bdf8;
	}

	.edit-keywords {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}

	.kw-chip.editable {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 6px 3px 10px;
	}

	.kw-remove {
		background: transparent;
		border: none;
		color: #38bdf8;
		cursor: pointer;
		padding: 0 2px;
		font-size: 0.7rem;
		line-height: 1;
		opacity: 0.7;
	}

	.kw-remove:hover {
		opacity: 1;
		color: #ef4444;
	}

	.kw-input {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-pill);
		padding: 3px 12px;
		color: var(--text-primary);
		font-size: 0.75rem;
		min-width: 160px;
	}

	.columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.5rem;
	}

	@media (max-width: 900px) {
		.columns {
			grid-template-columns: 1fr;
		}
	}

	.column h2 {
		font-size: 1.05rem;
		margin-bottom: 0.5rem;
	}

	.column-header-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.refresh-btn {
		background: rgba(255, 255, 255, 0.06);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.78rem;
	}

	.hint {
		font-size: 0.78rem;
		color: var(--text-muted);
		margin-bottom: 0.6rem;
	}

	.member-list,
	.suggestion-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.member-row,
	.suggestion-row {
		padding: 0.65rem 0.9rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.member-info,
	.suggestion-info {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		min-width: 0;
	}

	.preview-title-btn {
		background: transparent;
		border: none;
		padding: 0;
		color: var(--text-primary);
		font-size: 0.88rem;
		font-family: inherit;
		cursor: pointer;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: left;
		flex: 1;
		min-width: 0;
	}

	.preview-title-btn:hover {
		text-decoration: underline;
		color: #38bdf8;
	}

	.member-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.source-badge {
		padding: 1px 7px;
		border-radius: var(--radius-pill);
		background: rgba(255, 255, 255, 0.06);
	}

	.source-badge.manual {
		background: rgba(16, 185, 129, 0.15);
		color: #34d399;
	}

	.unassign-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 2px 6px;
		border-radius: 50%;
	}

	.unassign-btn:hover {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.15);
	}

	.score-badge {
		font-size: 0.72rem;
		font-family: var(--font-mono);
		color: #34d399;
	}

	.assign-btn {
		background: rgba(6, 182, 212, 0.15);
		border: 1px solid rgba(6, 182, 212, 0.3);
		color: #38bdf8;
		padding: 4px 12px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.8rem;
		white-space: nowrap;
	}

	.assign-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.already-in {
		font-size: 0.75rem;
		color: var(--text-muted);
		white-space: nowrap;
	}

	.search-heading {
		margin-top: 1.5rem;
	}

	.search-box {
		display: flex;
		gap: 8px;
		margin-bottom: 0.75rem;
	}

	.search-box input {
		flex: 1;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		color: var(--text-primary);
		font-size: 0.88rem;
	}

	.search-box button {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 8px 16px;
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.empty-hint {
		font-size: 0.82rem;
		color: var(--text-muted);
		padding: 0.5rem 0;
	}

	.loading-state,
	.empty-state {
		padding: 3rem;
		text-align: center;
		color: var(--text-secondary);
	}

	.spinner-large {
		width: 32px;
		height: 32px;
		border: 3px solid rgba(6, 182, 212, 0.2);
		border-top-color: #06b6d4;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
		margin: 0 auto 1rem;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
