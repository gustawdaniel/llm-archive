<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { base } from '$app/paths';
	import type { Topic } from '$lib/types';

	interface Props {
		topics: Topic[];
		selectedTopicId?: string | null;
		onSelectTopic?: (topic: Topic) => void;
	}

	let { topics = [], selectedTopicId = null, onSelectTopic }: Props = $props();

	let canvas: HTMLCanvasElement;
	let container: HTMLDivElement;
	let animId: number;
	let width = $state(800);
	let height = $state(600);
	let filterQuery = $state('');

	interface Node {
		id: string;
		topic: Topic;
		x: number;
		y: number;
		vx: number;
		vy: number;
		radius: number;
		color: string;
		highlighted: boolean;
	}

	interface Edge {
		source: Node;
		target: Node;
		weight: number;
	}

	let nodes: Node[] = [];
	let edges: Edge[] = [];
	let hoveredNode: Node | null = null;
	let draggedNode: Node | null = null;
	let isDragging = false;
	let dragStartX = 0;
	let dragStartY = 0;
	let panX = $state(0);
	let panY = $state(0);
	let zoom = $state(1.0);
	let activeDetailNode = $state<Node | null>(null);

	const PALETTE = [
		'#6366f1', // Indigo
		'#a855f7', // Purple
		'#ec4899', // Pink
		'#06b6d4', // Cyan
		'#10b981', // Emerald
		'#f59e0b', // Amber
		'#3b82f6', // Blue
		'#14b8a6'  // Teal
	];

	function getTopicColor(t: Topic, idx: number): string {
		if (t.is_manual) return '#10b981'; // Green for curated
		return PALETTE[idx % PALETTE.length];
	}

	function calculateSimilarity(t1: Topic, t2: Topic): number {
		if (!t1.keywords?.length || !t2.keywords?.length) return 0;
		const set1 = new Set(t1.keywords.map(k => k.toLowerCase().trim()));
		let matches = 0;
		for (const k of t2.keywords) {
			if (set1.has(k.toLowerCase().trim())) matches++;
		}
		return matches / Math.max(1, Math.min(set1.size, t2.keywords.length));
	}

	function initGraph() {
		if (!topics || topics.length === 0) return;

		const centerX = width / 2;
		const centerY = height / 2;
		const maxCount = Math.max(...topics.map(t => t.count || 1), 1);

		nodes = topics.map((t, idx) => {
			const angle = (idx / topics.length) * 2 * Math.PI;
			const dist = 100 + Math.random() * 220;
			const radius = Math.max(14, Math.min(36, 14 + ((t.count || 0) / maxCount) * 22));

			return {
				id: t.id,
				topic: t,
				x: centerX + Math.cos(angle) * dist,
				y: centerY + Math.sin(angle) * dist,
				vx: (Math.random() - 0.5) * 1.5,
				vy: (Math.random() - 0.5) * 1.5,
				radius,
				color: getTopicColor(t, idx),
				highlighted: false
			};
		});

		edges = [];
		for (let i = 0; i < nodes.length; i++) {
			for (let j = i + 1; j < nodes.length; j++) {
				const sim = calculateSimilarity(nodes[i].topic, nodes[j].topic);
				if (sim > 0.15) {
					edges.push({
						source: nodes[i],
						target: nodes[j],
						weight: sim
					});
				}
			}
		}

		if (selectedTopicId) {
			const sel = nodes.find(n => n.id === selectedTopicId);
			if (sel) activeDetailNode = sel;
		}
	}

	function stepSimulation() {
		const kRepulse = 1800;
		const kSpring = 0.04;
		const kCenter = 0.008;
		const damping = 0.88;
		const centerX = width / 2;
		const centerY = height / 2;

		// 1. Repulsion between all node pairs
		for (let i = 0; i < nodes.length; i++) {
			for (let j = i + 1; j < nodes.length; j++) {
				const n1 = nodes[i];
				const n2 = nodes[j];
				const dx = n2.x - n1.x;
				const dy = n2.y - n1.y;
				const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 20);
				const minDist = n1.radius + n2.radius + 20;

				const force = (kRepulse * (dist < minDist ? 2.5 : 1.0)) / (dist * dist);
				const fx = (dx / dist) * force;
				const fy = (dy / dist) * force;

				n1.vx -= fx;
				n1.vy -= fy;
				n2.vx += fx;
				n2.vy += fy;
			}
		}

		// 2. Attraction along edges
		for (const edge of edges) {
			const n1 = edge.source;
			const n2 = edge.target;
			const dx = n2.x - n1.x;
			const dy = n2.y - n1.y;
			const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
			const targetDist = 120 / (edge.weight + 0.2);

			const force = (dist - targetDist) * kSpring * edge.weight;
			const fx = (dx / dist) * force;
			const fy = (dy / dist) * force;

			n1.vx += fx;
			n1.vy += fy;
			n2.vx -= fx;
			n2.vy -= fy;
		}

		// 3. Center gravity + apply velocity
		for (const n of nodes) {
			if (n === draggedNode) continue;

			n.vx += (centerX - n.x) * kCenter;
			n.vy += (centerY - n.y) * kCenter;

			n.vx *= damping;
			n.vy *= damping;

			n.x += n.vx;
			n.y += n.vy;

			// Boundary constrain
			const margin = n.radius + 10;
			n.x = Math.max(margin, Math.min(width - margin, n.x));
			n.y = Math.max(margin, Math.min(height - margin, n.y));
		}
	}

	function render() {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		ctx.clearRect(0, 0, width, height);

		ctx.save();
		ctx.translate(panX, panY);
		ctx.scale(zoom, zoom);

		const query = filterQuery.trim().toLowerCase();

		// Highlight states
		for (const n of nodes) {
			n.highlighted = query ? n.topic.name.toLowerCase().includes(query) : false;
		}

		// Draw Edges
		for (const edge of edges) {
			const isConnectedToHover = hoveredNode && (edge.source === hoveredNode || edge.target === hoveredNode);
			const isConnectedToActive = activeDetailNode && (edge.source === activeDetailNode || edge.target === activeDetailNode);
			const isDimmed = (hoveredNode || activeDetailNode) && !isConnectedToHover && !isConnectedToActive;

			ctx.beginPath();
			ctx.moveTo(edge.source.x, edge.source.y);
			ctx.lineTo(edge.target.x, edge.target.y);

			if (isConnectedToHover || isConnectedToActive) {
				ctx.strokeStyle = '#a855f7';
				ctx.lineWidth = 2.5;
				ctx.globalAlpha = 0.85;
			} else if (isDimmed) {
				ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
				ctx.lineWidth = 0.8;
				ctx.globalAlpha = 0.2;
			} else {
				ctx.strokeStyle = 'rgba(99, 102, 241, 0.25)';
				ctx.lineWidth = Math.max(1, edge.weight * 3);
				ctx.globalAlpha = 0.45;
			}
			ctx.stroke();
		}

		ctx.globalAlpha = 1.0;

		// Draw Nodes
		for (const n of nodes) {
			const isHovered = n === hoveredNode;
			const isActive = n === activeDetailNode;
			const isMatched = n.highlighted;
			const isDimmed = (hoveredNode || activeDetailNode) && !isHovered && !isActive &&
				!edges.some(e => (e.source === n && (e.target === hoveredNode || e.target === activeDetailNode)) ||
				                 (e.target === n && (e.source === hoveredNode || e.source === activeDetailNode)));

			ctx.save();
			ctx.globalAlpha = isDimmed ? 0.25 : 1.0;

			// Glow Halo
			if (isHovered || isActive || isMatched) {
				const grad = ctx.createRadialGradient(n.x, n.y, n.radius * 0.7, n.x, n.y, n.radius * 2.2);
				grad.addColorStop(0, n.color);
				grad.addColorStop(1, 'transparent');
				ctx.fillStyle = grad;
				ctx.beginPath();
				ctx.arc(n.x, n.y, n.radius * 2.2, 0, Math.PI * 2);
				ctx.fill();
			}

			// Main Node Circle
			ctx.beginPath();
			ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
			ctx.fillStyle = n.color;
			ctx.fill();

			ctx.lineWidth = isHovered || isActive ? 3 : 1.5;
			ctx.strokeStyle = isHovered || isActive ? '#ffffff' : 'rgba(255, 255, 255, 0.4)';
			ctx.stroke();

			// Count Badge inside circle
			ctx.fillStyle = '#ffffff';
			ctx.font = `600 ${Math.max(10, Math.round(n.radius * 0.55))}px Inter, sans-serif`;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			ctx.fillText((n.topic.count || 0).toString(), n.x, n.y);

			// Text Label under circle
			ctx.font = `${isHovered || isActive ? '600' : '500'} 11px Inter, sans-serif`;
			ctx.fillStyle = isHovered || isActive ? '#ffffff' : 'rgba(226, 232, 240, 0.85)';
			const maxLabelLen = 22;
			let label = n.topic.name;
			if (label.length > maxLabelLen) label = label.slice(0, maxLabelLen) + '…';

			// Background pill for label
			const textMetrics = ctx.measureText(label);
			const pillW = textMetrics.width + 10;
			const pillH = 16;
			const pillX = n.x - pillW / 2;
			const pillY = n.y + n.radius + 6;

			ctx.fillStyle = 'rgba(15, 23, 42, 0.75)';
			ctx.beginPath();
			ctx.roundRect(pillX, pillY, pillW, pillH, 4);
			ctx.fill();

			ctx.fillStyle = isHovered || isActive ? '#a5b4fc' : '#e2e8f0';
			ctx.fillText(label, n.x, pillY + pillH / 2);

			ctx.restore();
		}

		ctx.restore();
	}

	function animate() {
		stepSimulation();
		render();
		animId = requestAnimationFrame(animate);
	}

	function getNodeAt(screenX: number, screenY: number): Node | null {
		// transform screen coords to world coords
		const worldX = (screenX - panX) / zoom;
		const worldY = (screenY - panY) / zoom;

		for (let i = nodes.length - 1; i >= 0; i--) {
			const n = nodes[i];
			const dx = worldX - n.x;
			const dy = worldY - n.y;
			if (dx * dx + dy * dy <= (n.radius + 5) * (n.radius + 5)) {
				return n;
			}
		}
		return null;
	}

	function handleMouseDown(e: MouseEvent) {
		const rect = canvas.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;
		const mouseY = e.clientY - rect.top;

		const clickedNode = getNodeAt(mouseX, mouseY);
		if (clickedNode) {
			draggedNode = clickedNode;
			isDragging = true;
			activeDetailNode = clickedNode;
			if (onSelectTopic) onSelectTopic(clickedNode.topic);
		} else {
			// Start panning canvas
			isDragging = true;
			dragStartX = e.clientX - panX;
			dragStartY = e.clientY - panY;
		}
	}

	function handleMouseMove(e: MouseEvent) {
		const rect = canvas.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;
		const mouseY = e.clientY - rect.top;

		if (draggedNode && isDragging) {
			draggedNode.x = (mouseX - panX) / zoom;
			draggedNode.y = (mouseY - panY) / zoom;
			draggedNode.vx = 0;
			draggedNode.vy = 0;
		} else if (isDragging) {
			panX = e.clientX - dragStartX;
			panY = e.clientY - dragStartY;
		} else {
			hoveredNode = getNodeAt(mouseX, mouseY);
			canvas.style.cursor = hoveredNode ? 'pointer' : 'grab';
		}
	}

	function handleMouseUp() {
		isDragging = false;
		draggedNode = null;
		if (canvas) canvas.style.cursor = hoveredNode ? 'pointer' : 'default';
	}

	function handleWheel(e: WheelEvent) {
		e.preventDefault();
		const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
		const newZoom = Math.max(0.4, Math.min(2.5, zoom * zoomFactor));

		const rect = canvas.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;
		const mouseY = e.clientY - rect.top;

		panX = mouseX - (mouseX - panX) * (newZoom / zoom);
		panY = mouseY - (mouseY - panY) * (newZoom / zoom);
		zoom = newZoom;
	}

	function resetView() {
		panX = 0;
		panY = 0;
		zoom = 1.0;
		activeDetailNode = null;
	}

	onMount(() => {
		const updateSize = () => {
			if (container) {
				width = container.clientWidth;
				height = container.clientHeight || 650;
				if (canvas) {
					canvas.width = width;
					canvas.height = height;
				}
			}
		};

		updateSize();
		window.addEventListener('resize', updateSize);

		initGraph();
		animId = requestAnimationFrame(animate);

		return () => {
			window.removeEventListener('resize', updateSize);
			cancelAnimationFrame(animId);
		};
	});

	onDestroy(() => {
		if (animId) cancelAnimationFrame(animId);
	});

	$effect(() => {
		if (topics.length > 0 && nodes.length === 0) {
			initGraph();
		}
	});
</script>

<div class="kg-wrapper" bind:this={container}>
	<!-- Graph Controls Bar -->
	<div class="kg-controls glass-panel">
		<div class="kg-search-wrap">
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
				<circle cx="11" cy="11" r="8"></circle>
				<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
			</svg>
			<input
				type="text"
				placeholder="Szukaj tematu na grafie..."
				bind:value={filterQuery}
			/>
			{#if filterQuery}
				<button class="clear-btn" onclick={() => (filterQuery = '')}>✕</button>
			{/if}
		</div>

		<div class="kg-actions">
			<button class="tool-btn" title="Przybliż" onclick={() => (zoom = Math.min(2.5, zoom * 1.2))}>+</button>
			<button class="tool-btn" title="Oddal" onclick={() => (zoom = Math.max(0.4, zoom * 0.8))}>−</button>
			<button class="tool-btn reset" title="Resetuj widok" onclick={resetView}>Reset</button>
		</div>

		<div class="kg-legend">
			<span class="legend-item"><span class="dot manual"></span> Ręczny</span>
			<span class="legend-item"><span class="dot auto"></span> Auto (HDBSCAN)</span>
			<span class="legend-meta font-mono">{nodes.length} węzłów &bull; {edges.length} relacji</span>
		</div>
	</div>

	<!-- Canvas Rendering -->
	<canvas
		bind:this={canvas}
		class="kg-canvas"
		onmousedown={handleMouseDown}
		onmousemove={handleMouseMove}
		onmouseup={handleMouseUp}
		onwheel={handleWheel}
	></canvas>

	<!-- Interactive Node Detail Drawer -->
	{#if activeDetailNode}
		<div class="kg-detail-card glass-panel">
			<button class="detail-close" onclick={() => (activeDetailNode = null)}>✕</button>
			<div class="detail-badge" style="background: {activeDetailNode.color}22; border-color: {activeDetailNode.color}; color: {activeDetailNode.color}">
				{activeDetailNode.topic.is_manual ? 'Ręczny Temat' : 'Klaster Semantyczny'}
			</div>
			<h3 class="detail-title">{activeDetailNode.topic.name}</h3>
			<p class="detail-desc">{activeDetailNode.topic.description || 'Brak opisu dla tego klastra.'}</p>

			<div class="detail-stats">
				<span class="stat-pill"><strong>{activeDetailNode.topic.count || 0}</strong> powiązanych konwersacji</span>
			</div>

			{#if activeDetailNode.topic.keywords?.length}
				<div class="detail-keywords">
					{#each activeDetailNode.topic.keywords as kw}
						<span class="kw-tag">{kw}</span>
					{/each}
				</div>
			{/if}

			<a href="{base}/topics/{activeDetailNode.topic.id}" class="detail-link-btn">
				<span>Eksploruj wątki tematu</span>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
					<line x1="5" y1="12" x2="19" y2="12"></line>
					<polyline points="12 5 19 12 12 19"></polyline>
				</svg>
			</a>
		</div>
	{/if}
</div>

<style>
	.kg-wrapper {
		position: relative;
		width: 100%;
		height: 680px;
		background: #090d16;
		border: 1px solid rgba(99, 102, 241, 0.2);
		border-radius: 16px;
		overflow: hidden;
		box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.6);
	}

	.kg-canvas {
		width: 100%;
		height: 100%;
		display: block;
		cursor: default;
	}

	.kg-controls {
		position: absolute;
		top: 1rem;
		left: 1rem;
		right: 1rem;
		z-index: 10;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.65rem 1rem;
		background: rgba(15, 23, 42, 0.82);
		backdrop-filter: blur(12px);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 12px;
	}

	.kg-search-wrap {
		position: relative;
		display: flex;
		align-items: center;
		flex: 1;
		max-width: 320px;
	}

	.kg-search-wrap svg {
		position: absolute;
		left: 0.75rem;
		color: #94a3b8;
		pointer-events: none;
	}

	.kg-search-wrap input {
		width: 100%;
		padding: 0.45rem 2rem 0.45rem 2.2rem;
		background: rgba(0, 0, 0, 0.35);
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 8px;
		color: #ffffff;
		font-size: 0.85rem;
		outline: none;
	}

	.kg-search-wrap input:focus {
		border-color: #6366f1;
	}

	.clear-btn {
		position: absolute;
		right: 0.5rem;
		background: none;
		border: none;
		color: #94a3b8;
		cursor: pointer;
		font-size: 0.8rem;
	}

	.kg-actions {
		display: flex;
		gap: 0.4rem;
	}

	.tool-btn {
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.15);
		color: #ffffff;
		padding: 0.35rem 0.65rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.tool-btn:hover {
		background: rgba(99, 102, 241, 0.3);
		border-color: #6366f1;
	}

	.tool-btn.reset {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.kg-legend {
		display: flex;
		align-items: center;
		gap: 0.85rem;
		font-size: 0.78rem;
		color: #94a3b8;
	}

	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}

	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.dot.manual {
		background: #10b981;
	}

	.dot.auto {
		background: #6366f1;
	}

	.kg-detail-card {
		position: absolute;
		bottom: 1.25rem;
		right: 1.25rem;
		width: 320px;
		max-width: calc(100% - 2.5rem);
		padding: 1.25rem;
		background: rgba(15, 23, 42, 0.92);
		backdrop-filter: blur(16px);
		border: 1px solid rgba(99, 102, 241, 0.3);
		border-radius: 14px;
		box-shadow: 0 15px 35px rgba(0, 0, 0, 0.6);
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		z-index: 10;
		animation: slide-up 0.2s ease-out;
	}

	@keyframes slide-up {
		from { opacity: 0; transform: translateY(10px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.detail-close {
		position: absolute;
		top: 0.75rem;
		right: 0.75rem;
		background: none;
		border: none;
		color: #94a3b8;
		font-size: 0.9rem;
		cursor: pointer;
	}

	.detail-close:hover {
		color: #ffffff;
	}

	.detail-badge {
		align-self: flex-start;
		font-size: 0.72rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.2rem 0.5rem;
		border-radius: 6px;
		border: 1px solid;
	}

	.detail-title {
		font-size: 1.15rem;
		font-weight: 700;
		color: #ffffff;
		margin: 0;
	}

	.detail-desc {
		font-size: 0.82rem;
		color: #94a3b8;
		line-height: 1.45;
		margin: 0;
		display: -webkit-box;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.detail-stats {
		font-size: 0.8rem;
		color: #e2e8f0;
	}

	.stat-pill {
		display: inline-block;
		background: rgba(255, 255, 255, 0.05);
		padding: 0.25rem 0.5rem;
		border-radius: 6px;
	}

	.detail-keywords {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}

	.kw-tag {
		font-size: 0.72rem;
		background: rgba(99, 102, 241, 0.15);
		color: #a5b4fc;
		border: 1px solid rgba(99, 102, 241, 0.3);
		padding: 0.15rem 0.45rem;
		border-radius: 4px;
	}

	.detail-link-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		background: linear-gradient(135deg, #6366f1, #8b5cf6);
		color: #ffffff;
		font-size: 0.82rem;
		font-weight: 600;
		text-decoration: none;
		padding: 0.55rem 1rem;
		border-radius: 8px;
		transition: opacity 0.15s ease;
		margin-top: 0.25rem;
	}

	.detail-link-btn:hover {
		opacity: 0.9;
	}
</style>
