<script lang="ts">
	let { size = 16 }: { size?: number } = $props();
	const id = 'sp' + Math.random().toString(36).slice(2, 8);
</script>

<!-- A four-pointed star with concave sides, in the app's warm accent. -->
<svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" class="sparkle">
	<defs>
		<linearGradient id={id} x1="3" y1="3" x2="21" y2="21" gradientUnits="userSpaceOnUse">
			<stop offset="0" style="stop-color: var(--accent)" />
			<stop offset="0.55" style="stop-color: color-mix(in srgb, var(--accent) 55%, var(--c-pink))" />
			<stop offset="1" style="stop-color: var(--c-purple)" />
		</linearGradient>
	</defs>
	<path fill="url(#{id})" d="M12 1.5c.5 5.6 4.9 10 10.5 10.5-5.6.5-10 4.9-10.5 10.5C11.5 16.9 7.1 12.5 1.5 12 7.1 11.5 11.5 7.1 12 1.5Z" />
</svg>

<style>
	.sparkle { flex: none; display: block; }
</style>
