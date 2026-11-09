<script lang="ts">
	import { page } from '$app/state';
	import { base } from '$app/paths';
</script>

<header class="navbar">
	<div class="nav-container">
		<a href="{base}/" class="brand">
			<div class="logo-icon">
				<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<rect x="4" y="4" width="16" height="16" rx="2"></rect>
					<rect x="9" y="9" width="6" height="6"></rect>
					<path d="M15 2v2"></path>
					<path d="M15 20v2"></path>
					<path d="M2 15h2"></path>
					<path d="M2 9h2"></path>
					<path d="M20 15h2"></path>
					<path d="M20 9h2"></path>
					<path d="M9 2v2"></path>
					<path d="M9 20v2"></path>
				</svg>
			</div>
			<div class="brand-text">
				<span class="brand-title">Brain LLM Archive</span>
				<span class="brand-badge">Vector + FTS</span>
			</div>
		</a>

		<nav class="nav-links">
			<a href="{base}/" class="nav-link" class:active={page.url.pathname === `${base}/` || page.url.pathname === base}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<circle cx="11" cy="11" r="8"></circle>
					<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
				</svg>
				Wyszukiwarka
			</a>
			<a href="{base}/conversations" class="nav-link" class:active={page.url.pathname.startsWith(`${base}/conversations`)}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
				</svg>
				Konwersacje
			</a>
			<a href="{base}/topics" class="nav-link" class:active={page.url.pathname.startsWith(`${base}/topics`)}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<circle cx="12" cy="5" r="2.5"></circle>
					<circle cx="5" cy="19" r="2.5"></circle>
					<circle cx="19" cy="19" r="2.5"></circle>
					<line x1="10.5" y1="6.5" x2="6.5" y2="17"></line>
					<line x1="13.5" y1="6.5" x2="17.5" y2="17"></line>
				</svg>
				Tematy
			</a>
			<a href="{base}/ask" class="nav-link" class:active={page.url.pathname.startsWith(`${base}/ask`)}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path d="M12 2a8 8 0 0 0-8 8c0 3.31 2.01 6.16 4.9 7.37.38.16.6.55.6.96V20a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-1.67c0-.41.22-.8.6-.96A8.002 8.002 0 0 0 20 10a8 8 0 0 0-8-8z"></path>
					<circle cx="12" cy="10" r="1.5"></circle>
				</svg>
				Infinite Memory
				<span class="rag-pill">RAG</span>
			</a>
			<a href="{base}/stats" class="nav-link" class:active={page.url.pathname === `${base}/stats`}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<line x1="18" y1="20" x2="18" y2="10"></line>
					<line x1="12" y1="20" x2="12" y2="4"></line>
					<line x1="6" y1="20" x2="6" y2="14"></line>
				</svg>
				Dashboard
			</a>
		</nav>

		<div class="nav-meta">
			<div class="status-pill">
				<span class="pulse-dot"></span>
				<span>Online (pgvector)</span>
			</div>
		</div>
	</div>
</header>

<style>
	.navbar {
		height: 64px;
		background: rgba(9, 13, 22, 0.85);
		backdrop-filter: blur(16px);
		-webkit-backdrop-filter: blur(16px);
		border-bottom: 1px solid var(--border-subtle);
		position: sticky;
		top: 0;
		z-index: 50;
	}

	.nav-container {
		max-width: 1300px;
		margin: 0 auto;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 1.5rem;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 12px;
		text-decoration: none;
		color: var(--text-primary);
	}

	.logo-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		color: #38bdf8;
		filter: drop-shadow(0 0 10px rgba(56, 189, 248, 0.45));
		transition: transform var(--transition-quick);
	}

	.brand:hover .logo-icon {
		transform: scale(1.08);
	}

	.brand-text {
		display: flex;
		flex-direction: column;
	}

	.brand-title {
		font-size: 1.1rem;
		font-weight: 700;
		letter-spacing: -0.01em;
		background: linear-gradient(135deg, #ffffff 30%, #38bdf8 100%);
		background-clip: text;
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
	}

	.brand-badge {
		font-size: 0.68rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
	}

	.nav-links {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.nav-link {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		font-size: 0.88rem;
		font-weight: 500;
		color: var(--text-secondary);
		text-decoration: none;
		transition: all var(--transition-quick);
	}

	.nav-link:hover {
		color: var(--text-primary);
		background: rgba(255, 255, 255, 0.05);
	}

	.nav-link.active {
		color: var(--text-accent);
		background: rgba(6, 182, 212, 0.1);
		border: 1px solid rgba(6, 182, 212, 0.25);
	}

	.rag-pill {
		font-size: 0.65rem;
		font-weight: 700;
		padding: 1px 6px;
		background: rgba(139, 92, 246, 0.25);
		color: #c4b5fd;
		border: 1px solid rgba(139, 92, 246, 0.4);
		border-radius: 999px;
		margin-left: 4px;
		letter-spacing: 0.05em;
	}

	.status-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 4px 12px;
		background: rgba(16, 185, 129, 0.1);
		border: 1px solid rgba(16, 185, 129, 0.25);
		border-radius: var(--radius-pill);
		font-size: 0.75rem;
		font-family: var(--font-mono);
		color: #34d399;
	}

	.pulse-dot {
		width: 6px;
		height: 6px;
		background: #10b981;
		border-radius: 50%;
		box-shadow: 0 0 8px #10b981;
		animation: pulse 2s infinite;
	}

	@keyframes pulse {
		0% { opacity: 0.4; }
		50% { opacity: 1; }
		100% { opacity: 0.4; }
	}

	@media (max-width: 768px) {
		.brand-badge, .status-pill {
			display: none;
		}
	}
</style>
