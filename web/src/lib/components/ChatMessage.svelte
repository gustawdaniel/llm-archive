<script lang="ts">
	import type { ConversationMessage } from '$lib/types';
	import MarkdownViewer from './MarkdownViewer.svelte';
	import RamIcon from './RamIcon.svelte';
	import { calculateTokenCost, formatCompactTokens, formatFullTokens } from '$lib/pricing';

	let { message, modelName = '' }: { message: ConversationMessage; modelName?: string } = $props();

	let copied = $state(false);
	let showRawJson = $state(false);

	async function copyText() {
		const textToCopy = message.content || (message.reasoning_content ? `[Reasoning]\n${message.reasoning_content}` : '');
		if (!textToCopy) return;
		try {
			await navigator.clipboard.writeText(textToCopy);
			copied = true;
			setTimeout(() => {
				copied = false;
			}, 2000);
		} catch (err) {
			console.error('Failed to copy message text:', err);
		}
	}

	function formatDate(iso?: string): string {
		if (!iso) return '';
		try {
			const d = new Date(iso);
			return d.toLocaleString('pl-PL', {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	function formatToolArg(val: any): string {
		if (val === null || val === undefined) return '';
		if (typeof val === 'string') return val;
		try {
			return JSON.stringify(val, null, 2);
		} catch {
			return String(val);
		}
	}

	const isAssistant = $derived(
		message.role.toLowerCase() === 'assistant' || message.role.toLowerCase() === 'model'
	);

	const tokenCost = $derived.by(() => {
		if (!message.token_usage) return null;
		const usage = message.token_usage;
		if (!usage.input_tokens && !usage.output_tokens && !usage.inputTokens && !usage.outputTokens && !usage.total_tokens && !usage.input && !usage.output && !usage.total) {
			return null;
		}
		return calculateTokenCost(usage, modelName);
	});

	const roleConfig = $derived.by(() => {
		switch (message.role.toLowerCase()) {
			case 'user':
			case 'human':
				return {
					label: 'Użytkownik',
					icon: '👤',
					className: 'role-user'
				};
			case 'assistant':
			case 'model':
				return {
					label: modelName ? `Asystent (${modelName})` : 'Asystent',
					icon: '🤖',
					className: 'role-assistant'
				};
			case 'tool':
				return {
					label: 'Narzędzie',
					icon: '⚙️',
					className: 'role-tool'
				};
			case 'system':
				return {
					label: 'System',
					icon: '🛡️',
					className: 'role-system'
				};
			default:
				return {
					label: message.role,
					icon: '💬',
					className: 'role-default'
				};
		}
	});

	const hasTools = $derived(message.tool_calls && message.tool_calls.length > 0);
	const hasReasoning = $derived(!!message.reasoning_content && message.reasoning_content.trim().length > 0);
	const hasContent = $derived(!!message.content && message.content.trim().length > 0);
	const hasAttachments = $derived(message.attachments && message.attachments.length > 0);
	const hasSources = $derived(message.sources && message.sources.length > 0);
</script>

<article class="chat-message {roleConfig.className}">
	<header class="message-header">
		<div class="header-left">
			<span class="role-badge">
				{#if isAssistant}
					<RamIcon size={14} class="role-ram-icon" />
				{:else}
					<span class="role-icon">{roleConfig.icon}</span>
				{/if}
				<span class="role-label">{roleConfig.label}</span>
			</span>
			<span class="step-index">#{message.step_index + 1}</span>
		</div>

		<div class="header-right">
			{#if tokenCost && (tokenCost.totalTokens > 0 || message.token_usage?.output_tokens)}
				<div 
					class="msg-token-chip"
					title="Zużycie tej odpowiedzi: {formatFullTokens(tokenCost.totalTokens)} tokenów (Wejście: {formatFullTokens(tokenCost.inputTokens)}, Wyjście: {formatFullTokens(tokenCost.outputTokens)}{tokenCost.cacheReadTokens ? ', Cache: ' + formatFullTokens(tokenCost.cacheReadTokens) : ''}) • Szacunkowy koszt: {tokenCost.totalCostFormatted}"
				>
					<RamIcon size={12} class="chip-icon" />
					<span class="chip-tok">{formatCompactTokens(tokenCost.totalTokens)} tok</span>
					{#if (tokenCost.totalCost ?? 0) > 0}
						<span class="chip-cost">{tokenCost.totalCostFormatted}</span>
					{/if}
				</div>
			{/if}

			{#if message.created_at}
				<time class="message-time" datetime={message.created_at} title={message.created_at}>
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<circle cx="12" cy="12" r="10"></circle>
						<polyline points="12 6 12 12 16 14"></polyline>
					</svg>
					{formatDate(message.created_at)}
				</time>
			{/if}

			{#if hasContent || hasReasoning}
				<button class="action-btn" onclick={copyText} title="Kopiuj treść wiadomości">
					{#if copied}
						<span class="copied-indicator">✓ Skopiowano</span>
					{:else}
						<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
							<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
						</svg>
						Kopiuj
					{/if}
				</button>
			{/if}
		</div>
	</header>

	<div class="message-body">
		<!-- Chain of Thought / Reasoning Content -->
		{#if hasReasoning}
			<details class="reasoning-box">
				<summary class="reasoning-summary">
					<span class="thought-icon">🧠</span>
					<span class="thought-title">Proces myślowy / Rozumowanie (Chain of Thought)</span>
				</summary>
				<div class="reasoning-content">
					<MarkdownViewer content={message.reasoning_content || ''} />
				</div>
			</details>
		{/if}

		<!-- Main Message Markdown Content -->
		{#if hasContent}
			<div class="message-content">
				<MarkdownViewer content={message.content} />
			</div>
		{/if}

		<!-- Tool Calls Section -->
		{#if hasTools && message.tool_calls}
			<div class="tool-calls-container">
				<div class="tools-heading">
					<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
						<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
					</svg>
					<span>Wywołania narzędzi ({message.tool_calls.length})</span>
				</div>

				<div class="tools-list">
					{#each message.tool_calls as tc, idx}
						<details class="tool-call-card" open={false}>
							<summary class="tool-summary">
								<span class="tool-summary-left">
									<span class="tool-icon">🔧</span>
									<span class="tool-name">{tc.name || 'tool'}</span>
								</span>
								<span class="tool-summary-right">
									{#if tc.duration_ms}
										<span class="duration-badge">{tc.duration_ms} ms</span>
									{/if}
									{#if tc.is_error}
										<span class="status-badge error">Błąd</span>
									{:else}
										<span class="status-badge success">Sukces</span>
									{/if}
								</span>
							</summary>

							<div class="tool-details-content">
								{#if tc.input}
									<div class="tool-section">
										<div class="section-label">Parametry wejściowe (Input):</div>
										<pre class="tool-code-block"><code>{formatToolArg(tc.input)}</code></pre>
									</div>
								{/if}

								{#if tc.output !== undefined && tc.output !== null && tc.output !== ''}
									<div class="tool-section">
										<div class="section-label">Wynik wykonania (Output):</div>
										<pre class="tool-code-block output-block"><code>{formatToolArg(tc.output)}</code></pre>
									</div>
								{/if}
							</div>
						</details>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Attachments Section -->
		{#if hasAttachments && message.attachments}
			<div class="attachments-list">
				<span class="attachments-title">Załączniki:</span>
				{#each message.attachments as att}
					<span class="attachment-pill">
						📎 {typeof att === 'string' ? att : (att.name || att.file_name || JSON.stringify(att))}
					</span>
				{/each}
			</div>
		{/if}

		<!-- Sources Section -->
		{#if hasSources && message.sources}
			<div class="sources-list">
				<span class="sources-title">Źródła:</span>
				{#each message.sources as src}
					{#if typeof src === 'string'}
						<a href={src} target="_blank" rel="noopener noreferrer" class="source-link">{src}</a>
					{:else}
						<a href={src.url || '#'} target="_blank" rel="noopener noreferrer" class="source-link">
							{src.title || src.name || src.url}
						</a>
					{/if}
				{/each}
			</div>
		{/if}
	</div>
</article>

<style>
	.chat-message {
		border-radius: var(--radius-md);
		border: 1px solid var(--border-subtle);
		background: rgba(15, 23, 42, 0.45);
		transition: border-color var(--transition-quick), background var(--transition-quick);
		overflow: hidden;
	}

	.chat-message:hover {
		border-color: rgba(255, 255, 255, 0.15);
	}

	/* Role-specific styling */
	.chat-message.role-user {
		border-left: 4px solid #06b6d4;
		background: linear-gradient(180deg, rgba(6, 182, 212, 0.07) 0%, rgba(15, 23, 42, 0.5) 100%);
	}

	.chat-message.role-assistant {
		border-left: 4px solid #a855f7;
		background: linear-gradient(180deg, rgba(168, 85, 247, 0.07) 0%, rgba(15, 23, 42, 0.5) 100%);
	}

	.chat-message.role-tool {
		border-left: 4px solid #f59e0b;
		background: linear-gradient(180deg, rgba(245, 158, 11, 0.05) 0%, rgba(15, 23, 42, 0.5) 100%);
	}

	.chat-message.role-system {
		border-left: 4px solid #64748b;
		background: rgba(30, 41, 59, 0.3);
	}

	/* Header */
	.message-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.65rem 1rem;
		background: rgba(0, 0, 0, 0.15);
		border-bottom: 1px solid rgba(255, 255, 255, 0.05);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.role-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.8rem;
		font-weight: 600;
		padding: 3px 8px;
		border-radius: var(--radius-sm);
	}

	.role-user .role-badge {
		background: rgba(6, 182, 212, 0.15);
		color: #38bdf8;
		border: 1px solid rgba(6, 182, 212, 0.3);
	}

	.role-assistant .role-badge {
		background: rgba(168, 85, 247, 0.15);
		color: #c084fc;
		border: 1px solid rgba(168, 85, 247, 0.3);
	}

	:global(.role-ram-icon) {
		color: #c084fc;
		flex-shrink: 0;
	}

	.role-tool .role-badge {
		background: rgba(245, 158, 11, 0.15);
		color: #fbbf24;
		border: 1px solid rgba(245, 158, 11, 0.3);
	}

	.role-system .role-badge {
		background: rgba(100, 116, 139, 0.2);
		color: #94a3b8;
		border: 1px solid rgba(100, 116, 139, 0.3);
	}

	.step-index {
		font-size: 0.72rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.msg-token-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		background: rgba(15, 23, 42, 0.7);
		border: 1px solid rgba(168, 85, 247, 0.25);
		color: #e2e8f0;
		padding: 2px 7px;
		border-radius: 9999px;
		font-size: 0.72rem;
		font-family: var(--font-mono);
		font-weight: 500;
		cursor: default;
		transition: all var(--transition-quick);
	}

	.msg-token-chip:hover {
		border-color: rgba(168, 85, 247, 0.5);
		background: rgba(30, 41, 59, 0.85);
	}

	:global(.msg-token-chip .chip-icon) {
		color: #c084fc;
	}

	.chip-cost {
		color: #34d399;
		font-weight: 600;
		margin-left: 2px;
	}

	.message-time {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 0.75rem;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.action-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		background: transparent;
		border: 1px solid rgba(255, 255, 255, 0.1);
		color: var(--text-secondary);
		padding: 3px 8px;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.75rem;
		transition: all var(--transition-quick);
	}

	.action-btn:hover {
		background: rgba(255, 255, 255, 0.08);
		color: var(--text-primary);
		border-color: rgba(255, 255, 255, 0.2);
	}

	.copied-indicator {
		color: #10b981;
		font-weight: 500;
	}

	/* Body */
	.message-body {
		padding: 1rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
	}

	.message-content {
		color: var(--text-primary);
		line-height: 1.6;
		overflow-wrap: break-word;
	}

	/* Reasoning Box */
	.reasoning-box {
		background: rgba(30, 41, 59, 0.4);
		border: 1px dashed rgba(168, 85, 247, 0.3);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.reasoning-summary {
		padding: 8px 12px;
		cursor: pointer;
		user-select: none;
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.82rem;
		font-weight: 500;
		color: #c084fc;
		background: rgba(168, 85, 247, 0.05);
	}

	.reasoning-summary:hover {
		background: rgba(168, 85, 247, 0.1);
	}

	.reasoning-content {
		padding: 12px;
		font-size: 0.88rem;
		color: #cbd5e1;
		border-top: 1px solid rgba(168, 85, 247, 0.15);
		background: rgba(15, 23, 42, 0.4);
	}

	/* Tool Calls */
	.tool-calls-container {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-top: 4px;
	}

	.tools-heading {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #fbbf24;
	}

	.tools-list {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.tool-call-card {
		background: rgba(15, 23, 42, 0.8);
		border: 1px solid rgba(245, 158, 11, 0.2);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.tool-summary {
		padding: 7px 10px;
		cursor: pointer;
		user-select: none;
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.8rem;
	}

	.tool-summary:hover {
		background: rgba(245, 158, 11, 0.08);
	}

	.tool-summary-left {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.tool-name {
		font-family: var(--font-mono);
		font-weight: 600;
		color: #fcd34d;
	}

	.tool-summary-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.duration-badge {
		font-size: 0.7rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.status-badge {
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 3px;
		font-weight: 500;
	}

	.status-badge.success {
		background: rgba(16, 185, 129, 0.15);
		color: #34d399;
		border: 1px solid rgba(16, 185, 129, 0.3);
	}

	.status-badge.error {
		background: rgba(239, 68, 68, 0.15);
		color: #f87171;
		border: 1px solid rgba(239, 68, 68, 0.3);
	}

	.tool-details-content {
		padding: 10px;
		border-top: 1px solid rgba(245, 158, 11, 0.15);
		background: rgba(0, 0, 0, 0.3);
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.section-label {
		font-size: 0.72rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin-bottom: 4px;
	}

	.tool-code-block {
		margin: 0;
		padding: 8px 10px;
		background: rgba(0, 0, 0, 0.5);
		border-radius: 4px;
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: #e2e8f0;
		overflow-x: auto;
		max-height: 280px;
		white-space: pre-wrap;
		word-break: break-all;
	}

	.output-block {
		color: #a5f3fc;
		border-left: 2px solid #06b6d4;
	}

	/* Attachments & Sources */
	.attachments-list, .sources-list {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		margin-top: 4px;
	}

	.attachments-title, .sources-title {
		color: var(--text-muted);
		font-weight: 500;
	}

	.attachment-pill {
		background: rgba(255, 255, 255, 0.06);
		padding: 2px 8px;
		border-radius: 4px;
		color: var(--text-secondary);
		font-family: var(--font-mono);
	}

	.source-link {
		color: #38bdf8;
		text-decoration: underline;
		word-break: break-all;
	}

	.source-link:hover {
		color: #7dd3fc;
	}
</style>
