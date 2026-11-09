<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { listTopics, createTopic, deleteTopic } from '$lib/api';
	import type { Topic } from '$lib/types';
	import KnowledgeGraph from '$lib/components/KnowledgeGraph.svelte';

	let topics = $state<Topic[]>([]);
	let isLoading = $state(true);
	let filter = $state('');
	let newName = $state('');
	let creating = $state(false);
	let viewMode = $state<'grid' | 'graph'>('grid');

	async function load() {
		isLoading = true;
		topics = await listTopics();
		isLoading = false;
	}

	onMount(load);

	let filtered = $derived(
		filter.trim()
			? topics.filter((t) => t.name.toLowerCase().includes(filter.trim().toLowerCase()))
			: topics
	);

	async function handleCreate() {
		if (!newName.trim()) return;
		creating = true;
		const t = await createTopic(newName.trim());
		creating = false;
		if (t) {
			newName = '';
			await load();
		}
	}

	async function handleDelete(t: Topic, e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		if (!confirm(`Usunąć temat "${t.name}"? Konwersacje zostają, tylko grupowanie zniknie.`)) return;
		const ok = await deleteTopic(t.id);
		if (ok) topics = topics.filter((x) => x.id !== t.id);
	}
</script>

<svelte:head>
	<title>Tematy | Brain LLM Archive</title>
</svelte:head>

<div class="topics-page">
	<div class="page-header">
		<div>
			<h1>Tematy i Graf Wiedzy</h1>
			<p class="subtitle">
				Auto-odkryte klastry (HDBSCAN), powiązania semantyczne i ręcznie wykurowane obszary wiedzy.
			</p>
		</div>
		<div class="view-toggle glass-panel">
			<button
				class="toggle-btn"
				class:active={viewMode === 'grid'}
				onclick={() => (viewMode = 'grid')}
				title="Widok siatki kafelków"
			>
				📋 Siatka
			</button>
			<button
				class="toggle-btn"
				class:active={viewMode === 'graph'}
				onclick={() => (viewMode = 'graph')}
				title="Interaktywny graf powiązań wiedzy"
			>
				🕸️ Graf Wiedzy
			</button>
		</div>
	</div>

	{#if viewMode === 'grid'}
		<div class="toolbar glass-panel">
			<input class="filter-input" bind:value={filter} placeholder="Filtruj po nazwie..." />
			<div class="create-box">
				<input
					class="create-input"
					bind:value={newName}
					placeholder="Nowy temat, np. 'NetPocket'"
					onkeydown={(e) => e.key === 'Enter' && handleCreate()}
				/>
				<button class="create-btn" onclick={handleCreate} disabled={creating || !newName.trim()}>
					{creating ? '...' : '+ Stwórz'}
				</button>
			</div>
		</div>

		{#if isLoading}
			<div class="loading-state glass-card">
				<div class="spinner-large"></div>
				<p>Ładowanie tematów...</p>
			</div>
		{:else if filtered.length === 0}
			<div class="empty-state glass-card">
				<p>Brak tematów pasujących do filtra.</p>
			</div>
		{:else}
			<div class="topics-grid">
				{#each filtered as t}
					<a href="{base}/topics/{t.id}" class="topic-card glass-card">
						<div class="topic-card-header">
							<h3>{t.name}</h3>
							<div class="header-actions">
								<span class="badge" class:manual={t.is_manual}>{t.is_manual ? 'ręczny' : 'auto'}</span>
								<button class="delete-btn" title="Usuń temat" onclick={(e) => handleDelete(t, e)}>✕</button>
							</div>
						</div>
						<div class="count">{t.count} {t.count === 1 ? 'konwersacja' : 'konwersacji'}</div>
						{#if t.keywords?.length}
							<div class="keywords">
								{#each t.keywords.slice(0, 6) as kw}
									<span class="kw-chip">{kw}</span>
								{/each}
							</div>
						{/if}
					</a>
				{/each}
			</div>
		{/if}
	{:else}
		{#if isLoading}
			<div class="loading-state glass-card">
				<div class="spinner-large"></div>
				<p>Ładowanie grafu powiązań wiedzy...</p>
			</div>
		{:else}
			<KnowledgeGraph {topics} />
		{/if}
	{/if}
</div>

<style>
	.topics-page {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
	}

	.page-header h1 {
		font-size: 1.75rem;
		font-weight: 700;
	}

	.subtitle {
		color: var(--text-secondary);
		margin-top: 0.35rem;
	}

	.view-toggle {
		display: flex;
		background: rgba(15, 23, 42, 0.6);
		padding: 4px;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		gap: 4px;
	}

	.toggle-btn {
		background: transparent;
		border: none;
		color: var(--text-secondary);
		padding: 6px 14px;
		font-size: 0.85rem;
		font-weight: 500;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-quick);
	}

	.toggle-btn:hover {
		color: #fff;
		background: rgba(255, 255, 255, 0.05);
	}

	.toggle-btn.active {
		background: linear-gradient(135deg, rgba(6, 182, 212, 0.25), rgba(59, 130, 246, 0.25));
		color: #38bdf8;
		font-weight: 600;
		border: 1px solid rgba(6, 182, 212, 0.4);
		box-shadow: 0 0 12px rgba(6, 182, 212, 0.2);
	}

	.toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		padding: 1rem 1.25rem;
		align-items: center;
		justify-content: space-between;
	}

	.filter-input {
		flex: 1;
		min-width: 220px;
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		color: var(--text-primary);
		font-size: 0.9rem;
	}

	.create-box {
		display: flex;
		gap: 8px;
	}

	.create-input {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		color: var(--text-primary);
		font-size: 0.9rem;
		min-width: 220px;
	}

	.create-btn {
		background: linear-gradient(135deg, #06b6d4, #0284c7);
		color: #fff;
		border: none;
		border-radius: var(--radius-sm);
		padding: 8px 16px;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}

	.create-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.topics-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 1rem;
	}

	.topic-card {
		padding: 1.1rem;
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		text-decoration: none;
		color: inherit;
		transition: transform var(--transition-quick), border-color var(--transition-quick);
	}

	.topic-card:hover {
		transform: translateY(-2px);
		border-color: var(--border-focus);
	}

	.topic-card-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.5rem;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.delete-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 2px 6px;
		border-radius: 50%;
		font-size: 0.85rem;
		line-height: 1;
	}

	.delete-btn:hover {
		color: #ef4444;
		background: rgba(239, 68, 68, 0.15);
	}

	.topic-card-header h3 {
		font-size: 1.02rem;
		font-weight: 600;
		color: #fff;
	}

	.badge {
		font-size: 0.68rem;
		padding: 2px 8px;
		border-radius: var(--radius-pill);
		background: rgba(255, 255, 255, 0.06);
		color: var(--text-muted);
		white-space: nowrap;
	}

	.badge.manual {
		background: rgba(16, 185, 129, 0.15);
		color: #34d399;
		border: 1px solid rgba(16, 185, 129, 0.3);
	}

	.count {
		font-size: 0.82rem;
		color: var(--text-muted);
	}

	.keywords {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.kw-chip {
		font-size: 0.72rem;
		padding: 2px 8px;
		border-radius: var(--radius-pill);
		background: rgba(6, 182, 212, 0.1);
		color: #38bdf8;
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
