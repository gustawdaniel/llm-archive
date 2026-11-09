<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { getStats } from '$lib/api';
	import type { ArchiveStats } from '$lib/types';
	import PlatformBadge from '$lib/components/PlatformBadge.svelte';

	let stats = $state<ArchiveStats | null>(null);
	let isLoading = $state(true);

	async function loadStats() {
		isLoading = true;
		try {
			stats = await getStats();
		} catch (e) {
			console.error('Failed to load stats:', e);
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		loadStats();
	});

	function formatDate(iso?: string): string {
		if (!iso) return 'Teraz';
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
	<title>Dashboard & Statystyki | Brain LLM Archive</title>
</svelte:head>

<div class="stats-page">
	<div class="page-header">
		<h1 class="page-title">Dashboard & Statystyki Archiwum</h1>
		<p class="page-subtitle">Metryki bazy wiedzy, stan synchronizacji w czasie rzeczywistym i podgląd źródeł.</p>
	</div>

	{#if isLoading}
		<div class="loading-state glass-card">
			<div class="spinner-large"></div>
			<p>Pobieranie statystyk z bazy wiedzy...</p>
		</div>
	{:else if stats}
		<!-- Key KPI Cards -->
		<div class="kpi-grid">
			<div class="kpi-card glass-card">
				<div class="kpi-icon cyan">💬</div>
				<div class="kpi-info">
					<span class="kpi-label">Konwersacje</span>
					<span class="kpi-value">{(stats.total_conversations ?? 0).toLocaleString()}</span>
				</div>
			</div>

			<div class="kpi-card glass-card">
				<div class="kpi-icon emerald">📨</div>
				<div class="kpi-info">
					<span class="kpi-label">Wiadomości</span>
					<span class="kpi-value">{(stats.total_messages ?? 0).toLocaleString()}</span>
				</div>
			</div>

			<div class="kpi-card glass-card">
				<div class="kpi-icon violet">🧩</div>
				<div class="kpi-info">
					<span class="kpi-label">Wektorowe Chunki</span>
					<span class="kpi-value">{(stats.total_chunks ?? 0).toLocaleString()}</span>
				</div>
			</div>

			<div class="kpi-card glass-card">
				<div class="kpi-icon amber">⚡</div>
				<div class="kpi-info">
					<span class="kpi-label">Śr. wiadomości / sesję</span>
					<span class="kpi-value">
						{stats.total_conversations ? (((stats.total_messages || 0) / stats.total_conversations)).toFixed(1) : 0}
					</span>
				</div>
			</div>
		</div>

		<!-- Grafana In-Depth Analytics Banner -->
		<div class="grafana-banner glass-card">
			<div class="grafana-banner-content">
				<div class="grafana-badge">
					<span class="pulsing-dot-blue"></span>
					ZAAWANSOWANA ANALITYKA HISTORII & TRENDÓW
				</div>
				<h2 class="grafana-title">Wykresy Popularności w Czasie & Rozkład Wiadomości</h2>
				<p class="grafana-desc">
					Osobny dedykowany dashboard w Grafanie do pogłębionych analiz historycznych: przesunięcia używanych narzędzi (ChatGPT &rarr; DeepSeek &rarr; Gemini / Claude Code / Antigravity), trendy miesięczne i tygodniowe oraz dokładna dystrybucja długości konwersacji.
				</p>
			</div>
			<div class="grafana-actions">
				<a href="http://grafana/d/brain-llm-analytics" target="_blank" rel="noreferrer" class="grafana-btn">
					<span>Otwórz Dashboard w Grafanie</span>
					<span class="external-icon">&nearr;</span>
				</a>
			</div>
		</div>

		<!-- Real-Time Sync & Live Sessions -->
		<div class="section-container glass-card">
			<div class="section-header">
				<div>
					<h2 class="section-title">Synchronizacja w Czasie Rzeczywistym & Urządzenia</h2>
					<p class="section-desc">Stan demonów nasłuchujących na stacjach roboczych i podział zaimportowanych sesji.</p>
				</div>
				<span class="sync-status-badge live">
					<span class="pulsing-dot-green"></span>
					Aktywna synchronizacja (ROG Daemon)
				</span>
			</div>

			<!-- Devices / Sources Grid -->
			<div class="sync-grid">
				{#each (stats.devices || []) as d}
					<div class="sync-device-card">
						<div class="device-icon">
							{#if d.device === 'rog'}💻{:else if d.device === 'mac'}🍎{:else}🖥️{/if}
						</div>
						<div class="device-info">
							<div class="device-name">{d.device === 'rog' ? 'ASUS ROG (Linux)' : d.device === 'mac' ? 'MacBook (macOS)' : d.device}</div>
							<div class="device-meta">
								<span class="device-count font-mono">{d.conversations.toLocaleString()} sesji</span>
								<span class="device-sync">Ostatnia: {formatDate(d.last_sync)}</span>
							</div>
						</div>
					</div>
				{/each}
			</div>

			<!-- Recent Live Sessions Table -->
			{#if stats.recent_syncs && stats.recent_syncs.length > 0}
				<div class="recent-syncs-wrapper">
					<h3 class="subsection-title">Ostatnio Zsynchronizowane Sesje (Live Activity)</h3>
					<div class="table-wrapper">
						<table class="stats-table">
							<thead>
								<tr>
									<th>Platforma</th>
									<th>Tytuł Sesji / Pierwszy Prompt</th>
									<th>Katalog Roboczy</th>
									<th>Urządzenie</th>
									<th class="align-right">Wiadomości</th>
									<th class="align-right">Zsynchronizowano</th>
								</tr>
							</thead>
							<tbody>
								{#each stats.recent_syncs as s}
									<tr>
										<td>
											<PlatformBadge platform={s.platform} />
										</td>
										<td>
											<a href="{base}/conversations/{s.id}" class="conv-link">
												{s.title || 'Sesja bez tytułu'}
											</a>
										</td>
										<td class="font-mono text-muted text-small">
											{s.project_path || '—'}
										</td>
										<td>
											<span class="device-pill {s.device || 'unknown'}">{s.device || '—'}</span>
										</td>
										<td class="align-right font-mono">
											<span class="badge-count">{s.message_count}</span>
										</td>
										<td class="align-right text-muted font-mono text-small">
											{formatDate(s.last_ingested_at || s.updated_at)}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		</div>

		<!-- Platform Breakdown -->
		<div class="section-container glass-card">
			<h2 class="section-title">Podział według Platform</h2>

			<div class="table-wrapper">
				<table class="stats-table">
					<thead>
						<tr>
							<th>Platforma</th>
							<th class="align-right">Konwersacje</th>
							<th class="align-right">Wiadomości</th>
							<th class="align-right">Chunki HNSW</th>
							<th class="align-right">Udział</th>
						</tr>
					</thead>
					<tbody>
						{#each (stats.platforms || []) as p}
							{@const pct = stats.total_conversations ? (((p.conversations || 0) / stats.total_conversations) * 100).toFixed(1) : '0'}
							<tr>
								<td>
									<PlatformBadge platform={p.platform} />
								</td>
								<td class="align-right font-mono">{(p.conversations || 0).toLocaleString()}</td>
								<td class="align-right font-mono">{(p.messages || 0).toLocaleString()}</td>
								<td class="align-right font-mono">{(p.chunks || 0).toLocaleString()}</td>
								<td class="align-right">
									<div class="share-wrapper">
										<div class="share-bar-bg">
											<div class="share-bar-fill" style="width: {pct}%;"></div>
										</div>
										<span class="share-text font-mono">{pct}%</span>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Infrastructure Info -->
		<div class="infra-grid">
			<div class="infra-card glass-card">
				<h3>Baza Danych & Indeks</h3>
				<ul class="infra-list">
					<li><strong>Silnik:</strong> PostgreSQL 16.15 na Incus (kontener <code>brain-db</code>)</li>
					<li><strong>Indeks:</strong> HNSW (<code>vector_cosine_ops</code>, 1024-dim)</li>
					<li><strong>FTS:</strong> <code>pg_trgm</code> + słownik polski i angielski</li>
					<li><strong>Backup:</strong> brak (do zrobienia: backup poza hostem)</li>
				</ul>
			</div>

			<div class="infra-card glass-card">
				<h3>Wektoryzacja & Synchronizacja</h3>
				<ul class="infra-list">
					<li><strong>Model embeddingów:</strong> <code>bge-m3</code> via lokalną Ollama</li>
					<li><strong>Obsługa plików:</strong> Markdown z YAML frontmatter</li>
					<li><strong>Obsidian Vault:</strong> <code>doc/llm-archive/</code> (Syncthing)</li>
					<li><strong>Agenci w tle:</strong> Demon obserwator na macOS i Linuxie (ROG)</li>
				</ul>
			</div>
		</div>
	{/if}
</div>

<style>
	.stats-page {
		display: flex;
		flex-direction: column;
		gap: 2rem;
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

	.kpi-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 1.25rem;
	}

	.kpi-card {
		padding: 1.25rem;
		display: flex;
		align-items: center;
		gap: 1.25rem;
	}

	.kpi-icon {
		font-size: 2rem;
		width: 54px;
		height: 54px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-md);
		background: rgba(255, 255, 255, 0.05);
	}

	.kpi-icon.cyan { background: rgba(6, 182, 212, 0.12); }
	.kpi-icon.emerald { background: rgba(16, 185, 129, 0.12); }
	.kpi-icon.violet { background: rgba(139, 92, 246, 0.12); }
	.kpi-icon.amber { background: rgba(245, 158, 11, 0.12); }

	.kpi-info {
		display: flex;
		flex-direction: column;
	}

	.kpi-label {
		font-size: 0.82rem;
		color: var(--text-muted);
	}

	.kpi-value {
		font-size: 1.6rem;
		font-weight: 700;
		color: #ffffff;
		font-family: var(--font-mono);
	}

	/* Grafana Banner */
	.grafana-banner {
		padding: 1.5rem 1.75rem;
		background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
		border: 1px solid rgba(56, 189, 248, 0.25);
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 2rem;
		flex-wrap: wrap;
	}

	.grafana-banner-content {
		max-width: 780px;
	}

	.grafana-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #38bdf8;
		background: rgba(56, 189, 248, 0.1);
		padding: 3px 8px;
		border-radius: 4px;
		margin-bottom: 0.6rem;
	}

	.pulsing-dot-blue {
		width: 7px;
		height: 7px;
		background-color: #38bdf8;
		border-radius: 50%;
		box-shadow: 0 0 8px #38bdf8;
		animation: pulse-blue 2s infinite;
	}

	@keyframes pulse-blue {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.4; transform: scale(0.85); }
	}

	.pulsing-dot-green {
		width: 7px;
		height: 7px;
		background-color: #10b981;
		border-radius: 50%;
		box-shadow: 0 0 8px #10b981;
		animation: pulse-green 1.8s infinite;
	}

	@keyframes pulse-green {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.3; }
	}

	.grafana-title {
		font-size: 1.25rem;
		font-weight: 700;
		color: #ffffff;
		margin-bottom: 0.35rem;
	}

	.grafana-desc {
		font-size: 0.88rem;
		color: var(--text-secondary);
		line-height: 1.45;
	}

	.grafana-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
		color: #ffffff;
		padding: 10px 18px;
		border-radius: var(--radius-md);
		font-weight: 600;
		font-size: 0.9rem;
		text-decoration: none;
		box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);
		transition: all 0.2s ease;
		white-space: nowrap;
	}

	.grafana-btn:hover {
		background: linear-gradient(135deg, #0369a1 0%, #075985 100%);
		transform: translateY(-1px);
		box-shadow: 0 6px 18px rgba(2, 132, 199, 0.45);
	}

	.external-icon {
		font-size: 1.1rem;
		line-height: 1;
	}

	/* Section containers */
	.section-container {
		padding: 1.5rem;
	}

	.section-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		margin-bottom: 1.25rem;
		flex-wrap: wrap;
		gap: 1rem;
	}

	.section-title {
		font-size: 1.2rem;
		font-weight: 600;
		color: #ffffff;
	}

	.section-desc {
		font-size: 0.85rem;
		color: var(--text-muted);
		margin-top: 0.2rem;
	}

	.subsection-title {
		font-size: 1rem;
		font-weight: 600;
		color: #e2e8f0;
		margin: 1.5rem 0 0.85rem 0;
	}

	.sync-status-badge {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border-radius: var(--radius-pill);
		font-size: 0.8rem;
		font-weight: 600;
	}

	.sync-status-badge.live {
		background: rgba(16, 185, 129, 0.12);
		color: #34d399;
		border: 1px solid rgba(16, 185, 129, 0.25);
	}

	.sync-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: 1rem;
		margin-bottom: 1.25rem;
	}

	.sync-device-card {
		background: rgba(255, 255, 255, 0.03);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		padding: 1rem;
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.device-icon {
		font-size: 1.8rem;
		width: 44px;
		height: 44px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(255, 255, 255, 0.05);
		border-radius: var(--radius-md);
	}

	.device-info {
		display: flex;
		flex-direction: column;
	}

	.device-name {
		font-weight: 600;
		color: #ffffff;
		font-size: 0.95rem;
	}

	.device-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-top: 4px;
	}

	.device-count {
		font-size: 0.85rem;
		color: #38bdf8;
	}

	.device-sync {
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.device-pill {
		display: inline-block;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		padding: 2px 7px;
		border-radius: 4px;
		font-family: var(--font-mono);
	}

	.device-pill.rog {
		background: rgba(16, 185, 129, 0.15);
		color: #34d399;
		border: 1px solid rgba(16, 185, 129, 0.3);
	}

	.device-pill.mac {
		background: rgba(168, 85, 247, 0.15);
		color: #c084fc;
		border: 1px solid rgba(168, 85, 247, 0.3);
	}

	.device-pill.unknown, .device-pill.server-brain-db {
		background: rgba(148, 163, 184, 0.15);
		color: #cbd5e1;
		border: 1px solid rgba(148, 163, 184, 0.3);
	}

	.badge-count {
		display: inline-block;
		background: rgba(255, 255, 255, 0.08);
		padding: 2px 8px;
		border-radius: var(--radius-pill);
		font-size: 0.85rem;
		color: #e2e8f0;
	}

	.conv-link {
		color: #f1f5f9;
		text-decoration: none;
		font-weight: 500;
		transition: color 0.15s ease;
	}

	.conv-link:hover {
		color: #38bdf8;
		text-decoration: underline;
	}

	.text-muted {
		color: var(--text-muted);
	}

	.text-small {
		font-size: 0.82rem;
	}

	.table-wrapper {
		overflow-x: auto;
	}

	.stats-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
	}

	.stats-table th, .stats-table td {
		padding: 12px 16px;
		border-bottom: 1px solid var(--border-subtle);
	}

	.stats-table th {
		color: var(--text-muted);
		font-weight: 600;
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.align-right {
		text-align: right;
	}

	.font-mono {
		font-family: var(--font-mono);
	}

	.share-wrapper {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		width: 120px;
	}

	.share-bar-bg {
		flex: 1;
		height: 6px;
		background: rgba(255, 255, 255, 0.08);
		border-radius: var(--radius-pill);
		overflow: hidden;
	}

	.share-bar-fill {
		height: 100%;
		background: linear-gradient(90deg, #06b6d4, #38bdf8);
		border-radius: var(--radius-pill);
	}

	.share-text {
		font-size: 0.78rem;
		color: var(--text-secondary);
		width: 38px;
	}

	.infra-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
		gap: 1.25rem;
	}

	.infra-card {
		padding: 1.5rem;
	}

	.infra-card h3 {
		font-size: 1.1rem;
		font-weight: 600;
		margin-bottom: 1rem;
		color: #ffffff;
	}

	.infra-list {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		font-size: 0.88rem;
		color: var(--text-secondary);
	}

	.infra-list code {
		font-family: var(--font-mono);
		color: var(--text-accent);
		background: rgba(255, 255, 255, 0.06);
		padding: 2px 6px;
		border-radius: 4px;
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
</style>
