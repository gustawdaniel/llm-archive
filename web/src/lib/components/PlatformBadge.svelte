<script lang="ts">
	let { platform }: { platform: string } = $props();

	const platformMap: Record<string, { label: string; color: string; bg: string; border: string }> = {
		antigravity: {
			label: 'Antigravity',
			color: '#06b6d4',
			bg: 'rgba(6, 182, 212, 0.12)',
			border: 'rgba(6, 182, 212, 0.35)'
		},
		claude_code: {
			label: 'Claude Code',
			color: '#f59e0b',
			bg: 'rgba(245, 158, 11, 0.12)',
			border: 'rgba(245, 158, 11, 0.35)'
		},
		claude_web: {
			label: 'Claude Web',
			color: '#fbbf24',
			bg: 'rgba(251, 191, 36, 0.12)',
			border: 'rgba(251, 191, 36, 0.35)'
		},
		chatgpt: {
			label: 'ChatGPT',
			color: '#10b981',
			bg: 'rgba(16, 185, 129, 0.12)',
			border: 'rgba(16, 185, 129, 0.35)'
		},
		deepseek: {
			label: 'DeepSeek',
			color: '#3b82f6',
			bg: 'rgba(59, 130, 246, 0.12)',
			border: 'rgba(59, 130, 246, 0.35)'
		},
		gemini: {
			label: 'Gemini',
			color: '#a855f7',
			bg: 'rgba(168, 85, 247, 0.12)',
			border: 'rgba(168, 85, 247, 0.35)'
		},
		grok: {
			label: 'Grok',
			color: '#e2e8f0',
			bg: 'rgba(226, 232, 240, 0.12)',
			border: 'rgba(226, 232, 240, 0.35)'
		},
		cline: {
			label: 'Cline',
			color: '#38bdf8',
			bg: 'rgba(56, 189, 248, 0.12)',
			border: 'rgba(56, 189, 248, 0.35)'
		},
		opencode: {
			label: 'OpenCode',
			color: '#10b981',
			bg: 'rgba(16, 185, 129, 0.12)',
			border: 'rgba(16, 185, 129, 0.35)'
		},
		aider: {
			label: 'Aider',
			color: '#ec4899',
			bg: 'rgba(236, 72, 153, 0.12)',
			border: 'rgba(236, 72, 153, 0.35)'
		},
		codex: {
			label: 'Codex',
			color: '#e5e7eb',
			bg: 'rgba(229, 231, 235, 0.10)',
			border: 'rgba(229, 231, 235, 0.35)'
		},
		omp: {
			label: 'Oh My Pi',
			color: '#f97316',
			bg: 'rgba(249, 115, 22, 0.12)',
			border: 'rgba(249, 115, 22, 0.35)'
		},
		zed: {
			label: 'Zed',
			color: '#06b6d4',
			bg: 'rgba(6, 182, 212, 0.12)',
			border: 'rgba(6, 182, 212, 0.35)'
		},
		hermes: {
			label: 'Hermes',
			color: '#8b5cf6',
			bg: 'rgba(139, 92, 246, 0.12)',
			border: 'rgba(139, 92, 246, 0.35)'
		}
	};

	const info = $derived(platformMap[platform.toLowerCase()] || {
		label: platform.toUpperCase(),
		color: '#94a3b8',
		bg: 'rgba(148, 163, 184, 0.12)',
		border: 'rgba(148, 163, 184, 0.35)'
	});
</script>

<span
	class="platform-badge"
	style="color: {info.color}; background: {info.bg}; border-color: {info.border};"
>
	<span class="dot" style="background: {info.color};"></span>
	{info.label}
</span>

<style>
	.platform-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 2px 10px;
		font-size: 0.75rem;
		font-weight: 600;
		font-family: var(--font-mono);
		border-radius: var(--radius-pill);
		border: 1px solid;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}

	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		display: inline-block;
		box-shadow: 0 0 8px currentColor;
	}
</style>
