<script lang="ts">
	import { base } from '$app/paths';
	import { getConversationDetail } from '$lib/api';
	import type { ConversationDetail } from '$lib/types';
	import PlatformBadge from './PlatformBadge.svelte';
	import MarkdownViewer from './MarkdownViewer.svelte';

	let { conversationId, onClose }: { conversationId: string | null; onClose: () => void } = $props();

	let loading = $state(false);
	let conversation = $state<ConversationDetail | null>(null);

	$effect(() => {
		const id = conversationId;
		if (!id) {
			conversation = null;
			return;
		}
		loading = true;
		conversation = null;
		getConversationDetail(id).then((c) => {
			conversation = c;
			loading = false;
		});
	});

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

{#if conversationId}
	<div
		class="modal-backdrop"
		onclick={onClose}
		onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}
		role="presentation"
		tabindex="-1"
	>
		<div
			class="modal-content glass-panel"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			tabindex="-1"
		>
			<div class="modal-header">
				<div class="modal-title-group">
					{#if conversation}
						<PlatformBadge platform={conversation.platform} />
						<h2>{conversation.title}</h2>
					{:else}
						<h2>Ładowanie konwersacji...</h2>
					{/if}
				</div>
				<button class="close-modal-btn" onclick={onClose}>✕</button>
			</div>

			<div class="modal-body">
				{#if loading}
					<div class="loading-state">
						<div class="spinner-large"></div>
						<p>Pobieranie dokumentu Markdown...</p>
					</div>
				{:else if conversation}
					<div class="conversation-meta-bar">
						<span>Data: {formatDate(conversation.started_at)}</span>
						{#if conversation.model}
							<span>Model: <code>{conversation.model}</code></span>
						{/if}
						{#if conversation.project_path}
							<span>Projekt: <code>{conversation.project_path}</code></span>
						{/if}
					</div>

					<div class="markdown-wrapper">
						<MarkdownViewer content={conversation.content_markdown || 'Brak treści markdown.'} />
					</div>
				{:else}
					<p class="error-text">Nie udało się załadować treści wybranej konwersacji.</p>
				{/if}
			</div>

			<div class="modal-footer">
				{#if conversation}
					<a href="{base}/conversations/{conversation.id}" class="full-view-btn">
						Otwórz w osobnym widoku ↗
					</a>
				{/if}
				<button class="close-btn" onclick={onClose}>Zamknij</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.75);
		backdrop-filter: blur(8px);
		z-index: 100;
		display: flex;
		justify-content: center;
		align-items: center;
		padding: 1.5rem;
	}

	.modal-content {
		width: 100%;
		max-width: 900px;
		max-height: 85vh;
		display: flex;
		flex-direction: column;
		background: #0d121f;
		border: 1px solid var(--border-card);
		border-radius: var(--radius-lg);
		box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
	}

	.modal-header {
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid var(--border-subtle);
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.modal-title-group {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.modal-title-group h2 {
		font-size: 1.2rem;
		font-weight: 600;
	}

	.close-modal-btn {
		background: transparent;
		border: none;
		color: var(--text-muted);
		font-size: 1.2rem;
		cursor: pointer;
	}

	.modal-body {
		padding: 1.5rem;
		overflow-y: auto;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.conversation-meta-bar {
		display: flex;
		gap: 1rem;
		font-size: 0.82rem;
		color: var(--text-muted);
		border-bottom: 1px solid var(--border-subtle);
		padding-bottom: 0.75rem;
		flex-wrap: wrap;
	}

	.modal-footer {
		padding: 1rem 1.5rem;
		border-top: 1px solid var(--border-subtle);
		display: flex;
		justify-content: flex-end;
		gap: 12px;
	}

	.full-view-btn {
		background: rgba(6, 182, 212, 0.15);
		border: 1px solid var(--color-antigravity);
		color: #38bdf8;
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		text-decoration: none;
		font-size: 0.85rem;
		font-weight: 500;
	}

	.close-btn {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid var(--border-subtle);
		color: var(--text-primary);
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.85rem;
	}

	.loading-state {
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

	.error-text {
		color: #f87171;
	}
</style>
