<script lang="ts">
	import { marked } from 'marked';
	import markedKatex from 'marked-katex-extension';
	import katex from 'katex';
	import hljs from 'highlight.js';

	let { content = '' }: { content: string } = $props();

	// Configure marked with KaTeX extension for $...$ and $$...$$
	marked.use(
		markedKatex({
			throwOnError: false,
			nonStandard: true
		})
	);

	// Configure marked with syntax highlighting and code block math handling
	const renderer = new marked.Renderer();
	renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
		const cleanLang = (lang || '').trim().toLowerCase();
		if (['math', 'latex', 'katex', 'tex'].includes(cleanLang)) {
			try {
				const rendered = katex.renderToString(text, {
					displayMode: true,
					throwOnError: false
				});
				return `<div class="katex-display-block">${rendered}</div>`;
			} catch (e) {
				console.error('KaTeX block rendering error:', e);
				return `<pre><code class="hljs">${text}</code></pre>`;
			}
		}

		const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
		const highlighted = validLang !== 'plaintext'
			? hljs.highlight(text, { language: validLang }).value
			: hljs.highlightAuto(text).value;
		return `<pre><code class="hljs ${validLang}">${highlighted}</code></pre>`;
	};

	marked.setOptions({
		renderer,
		gfm: true,
		breaks: true
	});

	const renderedHtml = $derived.by(() => {
		if (!content) return '';
		try {
			return marked.parse(content) as string;
		} catch (e) {
			console.error('Failed to parse markdown:', e);
			return `<pre>${content}</pre>`;
		}
	});
</script>

<div class="markdown-container markdown-body">
	{@html renderedHtml}
</div>

<style>
	.markdown-container {
		word-break: break-word;
	}

	:global(.katex-display-block) {
		margin: 1.25rem 0;
		padding: 0.85rem 1.25rem;
		background: rgba(15, 23, 42, 0.5);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		overflow-x: auto;
		overflow-y: hidden;
		text-align: center;
	}

	:global(.katex-display) {
		margin: 0.75rem 0 !important;
		overflow-x: auto;
		overflow-y: hidden;
		padding: 0.25rem 0;
	}

	:global(.katex) {
		font-size: 1.1em;
		color: var(--text-primary);
	}

	:global(.markdown-body details) {
		background: rgba(15, 23, 42, 0.6);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		margin: 12px 0;
	}

	:global(.markdown-body summary) {
		cursor: pointer;
		font-weight: 500;
		color: var(--text-secondary);
		user-select: none;
	}

	:global(.markdown-body summary:hover) {
		color: var(--text-accent);
	}

	:global(.markdown-body table) {
		width: 100%;
		border-collapse: collapse;
		margin: 16px 0;
	}

	:global(.markdown-body th, .markdown-body td) {
		border: 1px solid var(--border-subtle);
		padding: 8px 12px;
		text-align: left;
	}

	:global(.markdown-body th) {
		background: rgba(255, 255, 255, 0.04);
		font-weight: 600;
	}

	/* Highlight.js Dark Theme */
	:global(.hljs) {
		color: #e2e8f0;
	}
	:global(.hljs-keyword), :global(.hljs-selector-tag), :global(.hljs-subst) {
		color: #f43f5e;
	}
	:global(.hljs-string), :global(.hljs-title), :global(.hljs-section), :global(.hljs-attribute), :global(.hljs-literal), :global(.hljs-template-tag), :global(.hljs-template-variable), :global(.hljs-type), :global(.hljs-addition) {
		color: #10b981;
	}
	:global(.hljs-comment), :global(.hljs-quote), :global(.hljs-deletion), :global(.hljs-meta) {
		color: #64748b;
		font-style: italic;
	}
	:global(.hljs-number), :global(.hljs-regexp), :global(.hljs-link) {
		color: #f59e0b;
	}
	:global(.hljs-variable), :global(.hljs-symbol), :global(.hljs-bullet) {
		color: #38bdf8;
	}
	:global(.hljs-built_in), :global(.hljs-class) {
		color: #a855f7;
	}
</style>
