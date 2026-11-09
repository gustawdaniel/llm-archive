<script lang="ts">
	let { size = 16, class: className = '' }: { size?: number; class?: string } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	xmlns="http://www.w3.org/2000/svg"
	class="ram-icon {className}"
	stroke="currentColor"
	stroke-width="1.8"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	<!-- PCB Module Outline with off-center alignment notch at bottom -->
	<path d="M2 7C2 5.89543 2.89543 5 4 5H20C21.1046 5 22 5.89543 22 7V17C22 17.5523 21.5523 18 21 18H14.5L13.5 16.5H10.5L9.5 18H3C2.44772 18 2 17.5523 2 17V7Z" />
	
	<!-- DRAM Memory Chips -->
	<rect x="4.5" y="8" width="3" height="5" rx="0.5" fill="currentColor" fill-opacity="0.25" stroke="currentColor" stroke-width="1.2" />
	<rect x="9" y="8" width="3" height="5" rx="0.5" fill="currentColor" fill-opacity="0.25" stroke="currentColor" stroke-width="1.2" />
	<rect x="13.5" y="8" width="3" height="5" rx="0.5" fill="currentColor" fill-opacity="0.25" stroke="currentColor" stroke-width="1.2" />
	<rect x="18" y="8" width="3" height="5" rx="0.5" fill="currentColor" fill-opacity="0.25" stroke="currentColor" stroke-width="1.2" />
	
	<!-- Gold Connector Pin Leads -->
	<line x1="3.5" y1="18" x2="3.5" y2="19.5" stroke-width="1.2" />
	<line x1="5.5" y1="18" x2="5.5" y2="19.5" stroke-width="1.2" />
	<line x1="7.5" y1="18" x2="7.5" y2="19.5" stroke-width="1.2" />
	<line x1="15.5" y1="18" x2="15.5" y2="19.5" stroke-width="1.2" />
	<line x1="17.5" y1="18" x2="17.5" y2="19.5" stroke-width="1.2" />
	<line x1="19.5" y1="18" x2="19.5" y2="19.5" stroke-width="1.2" />
</svg>

<style>
	.ram-icon {
		display: inline-block;
		vertical-align: middle;
		flex-shrink: 0;
	}
</style>
