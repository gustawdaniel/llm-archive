<script lang="ts">
	let {
		open = $bindable(false),
		platform,
		externalId,
		device,
		projectPath
	}: {
		open: boolean;
		platform: string;
		externalId: string;
		device?: string;
		projectPath?: string;
	} = $props();

	const host = $derived(device || '<host>');

	// Where the raw session files actually live on disk, per platform's own
	// on-disk layout (see docs/network_and_sync.md § 3).
	const filesPath = $derived(
		platform === 'antigravity'
			? `~/.gemini/antigravity-ide/brain/${externalId}/`
			: platform === 'cline'
			? `~/.cline/data/sessions/${externalId}/`
			: platform === 'opencode'
			? `~/.local/share/opencode/opencode.db`
			: platform === 'aider'
			? `${projectPath || '~'}/.aider.chat.history.md`
			: platform === 'omp'
			? `~/.omp/agent/sessions/*/*${externalId}*.jsonl`
			: platform === 'codex'
			? `~/.codex/sessions/*/*/*/rollout-*${externalId}.jsonl`
			: platform === 'zed'
			? `~/.local/share/zed/threads/threads.db`
			: platform === 'hermes'
			? `~/.hermes/state.db`
			: `~/.claude/projects/*/${externalId}.jsonl`
	);

	const listCommand = $derived(
		platform === 'antigravity'
			? `ssh ${host} "ls -la ${filesPath}.system_generated/logs/"`
			: platform === 'cline'
			? `ssh ${host} "ls -la '${filesPath}'"`
			: platform === 'opencode'
			? `ssh ${host} "sqlite3 ~/.local/share/opencode/opencode.db \"SELECT id, title, model FROM session WHERE id = '${externalId}';\""`
			: platform === 'aider'
			? `ssh ${host} "tail -n 50 '${filesPath}'"`
			: platform === 'omp'
			? `ssh ${host} "ls -la ~/.omp/agent/sessions/*/*${externalId}*.jsonl"`
			: platform === 'codex'
			? `ssh ${host} "ls -la ~/.codex/sessions/*/*/*/rollout-*${externalId}.jsonl"`
			: platform === 'zed'
			? `ssh ${host} "sqlite3 ~/.local/share/zed/threads/threads.db \"SELECT id, summary, updated_at FROM threads WHERE id = '${externalId}';\""`
			: platform === 'hermes'
			? `ssh ${host} "sqlite3 ~/.hermes/state.db \"SELECT id, title, model FROM sessions WHERE id = '${externalId}';\""`
			: `ssh ${host} "find ~/.claude/projects -name '${externalId}.jsonl'"`
	);

	const openProjectCommand = $derived(
		projectPath ? `ssh ${host} "cd ${projectPath} && $SHELL"` : null
	);

	let copiedCmd = $state<string | null>(null);
	async function copy(cmd: string) {
		try {
			await navigator.clipboard.writeText(cmd);
			copiedCmd = cmd;
			setTimeout(() => { if (copiedCmd === cmd) copiedCmd = null; }, 1500);
		} catch (err) {
			console.error('Copy failed:', err);
		}
	}

	function close() {
		open = false;
	}
</script>

{#if open}
	<div class="modal-backdrop" onclick={close} onkeydown={(e) => e.key === 'Escape' && close()} role="presentation">
		<div class="modal-card glass-card" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" tabindex="-1">
			<div class="modal-header">
				<h2>Dostęp lokalny</h2>
				<button class="close-btn" onclick={close} aria-label="Zamknij">✕</button>
			</div>

			<p class="modal-hint">
				{platform === 'antigravity' ? 'Antigravity' : platform === 'cline' ? 'Cline' : 'Claude Code'} nie ma web UI ani linku do
				konwersacji — ta sesja istnieje wyłącznie jako pliki na dysku maszyny, na której została
				uruchomiona.
			</p>

			<div class="field">
				<span class="field-label">Host</span>
				<code class="field-value">{host}</code>
			</div>

			{#if projectPath}
				<div class="field">
					<span class="field-label">Katalog projektu (gdzie był otwarty czat)</span>
					<code class="field-value">{projectPath}</code>
				</div>
			{/if}

			<div class="field">
				<span class="field-label">Pliki sesji na dysku</span>
				<code class="field-value">{filesPath}</code>
			</div>

			<div class="command-block">
				<span class="field-label">Podejrzyj pliki sesji</span>
				<div class="command-row">
					<code>{listCommand}</code>
					<button class="copy-icon-btn" onclick={() => copy(listCommand)} aria-label="Kopiuj komendę">
						{copiedCmd === listCommand ? '✓' : '⧉'}
					</button>
				</div>
			</div>

			{#if openProjectCommand}
				<div class="command-block">
					<span class="field-label">Otwórz projekt w tym samym miejscu</span>
					<div class="command-row">
						<code>{openProjectCommand}</code>
						<button class="copy-icon-btn" onclick={() => copy(openProjectCommand)} aria-label="Kopiuj komendę">
							{copiedCmd === openProjectCommand ? '✓' : '⧉'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		backdrop-filter: blur(2px);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: 1rem;
	}

	.modal-card {
		max-width: 560px;
		width: 100%;
		padding: 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}

	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.modal-header h2 {
		font-size: 1.1rem;
		font-weight: 700;
		color: #fff;
	}

	.close-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 1rem;
		padding: 4px 8px;
	}
	.close-btn:hover {
		color: var(--text-primary);
	}

	.modal-hint {
		font-size: 0.85rem;
		color: var(--text-secondary);
		line-height: 1.5;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.field-label {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		color: var(--text-muted);
	}

	.field-value {
		font-family: var(--font-mono);
		font-size: 0.85rem;
		color: var(--text-primary);
		background: rgba(255, 255, 255, 0.05);
		padding: 4px 8px;
		border-radius: 4px;
		word-break: break-all;
	}

	.command-block {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.command-row {
		display: flex;
		align-items: center;
		gap: 6px;
		background: rgba(0, 0, 0, 0.35);
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: var(--radius-sm);
		padding: 8px 10px;
	}

	.command-row code {
		flex: 1;
		font-family: var(--font-mono);
		font-size: 0.8rem;
		color: #38bdf8;
		word-break: break-all;
	}

	.copy-icon-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.9rem;
		flex-shrink: 0;
	}
	.copy-icon-btn:hover {
		color: var(--text-primary);
	}
</style>
