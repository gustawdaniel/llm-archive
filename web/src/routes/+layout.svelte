<script lang="ts">
	import '../app.css';
	import 'katex/dist/katex.min.css';
	import Navbar from '$lib/components/Navbar.svelte';

	let { children } = $props();
</script>

<div class="app-layout">
	<Navbar />
	<main class="main-content">
		{@render children()}
	</main>
	<footer class="footer">
		<div class="footer-container">
			<span>Brain Infrastructure • LLM Archive • pgvector</span>
			<span>Syncthing Obsidian Vault: <code>doc/llm-archive/</code></span>
		</div>
	</footer>
</div>

<style>
	.app-layout {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	.main-content {
		flex: 1;
		max-width: 1300px;
		width: 100%;
		margin: 0 auto;
		padding: 2rem 1.5rem 4rem;
	}

	.footer {
		border-top: 1px solid var(--border-subtle);
		background: rgba(9, 13, 22, 0.9);
		padding: 1.25rem 1.5rem;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.footer-container {
		max-width: 1300px;
		margin: 0 auto;
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	code {
		font-family: var(--font-mono);
		color: var(--text-accent);
	}
</style>
