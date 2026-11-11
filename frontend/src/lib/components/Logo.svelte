<script lang="ts">
	let { size = 20 }: { size?: number } = $props();
	const id = 'lg' + Math.random().toString(36).slice(2, 8);
</script>

<!-- Kern: a K drawn as a tiny knowledge graph, with the kernel glowing at its joint. -->
<svg width={size} height={size} viewBox="4 4 24 24" aria-hidden="true" class="logo">
	<defs>
		<radialGradient id={id} cx="10.5" cy="16" r="6.5" gradientUnits="userSpaceOnUse">
			<stop offset="0" style="stop-color: color-mix(in srgb, var(--accent) 55%, white)" />
			<stop offset="0.55" style="stop-color: var(--accent)" />
			<stop offset="1" style="stop-color: var(--accent); stop-opacity: 0" />
		</radialGradient>
	</defs>
	<g stroke-linecap="round" fill="none" style="stroke: var(--text)">
		<path d="M10.5 7.5v17" stroke-width="2.6" />
		<path d="M10.5 16 21.6 8.3M10.5 16 21.6 23.7" stroke-width="2.2" stroke-opacity=".7" />
	</g>
	<circle class="halo" cx="10.5" cy="16" r="6.5" fill="url(#{id})" opacity=".5" />
	<circle cx="10.5" cy="16" r="3.2" style="fill: var(--accent); stroke: var(--bg-side)" stroke-width="1.4" />
	<circle cx="22.2" cy="7.8" r="2.1" style="fill: var(--text)" />
	<circle cx="22.2" cy="24.2" r="2.1" style="fill: var(--text)" />
</svg>

<style>
	.logo { flex: none; display: block; overflow: visible; }
	.halo { transform-origin: 10.5px 16px; animation: pulse 4.5s ease-in-out infinite; }
	@keyframes pulse { 0%, 100% { opacity: 0.35; transform: scale(0.92); } 50% { opacity: 0.6; transform: scale(1.06); } }
	@media (prefers-reduced-motion: reduce) { .halo { animation: none; } }
</style>
