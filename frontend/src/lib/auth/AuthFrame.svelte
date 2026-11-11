<script lang="ts">
	import type { Snippet } from 'svelte';
	import Logo from '#lib/components/Logo.svelte';
	import { session } from '#lib/state/session.svelte.ts';

	let { children, wide = false, home = true }: { children: Snippet; wide?: boolean; home?: boolean } = $props();
	let name = $derived(session.site?.site_name ?? 'Kern');
	let toLanding = $derived(home && session.site?.landing_enabled && !session.site.needs_setup);
</script>

<div class="frame">
	<div class="dots" aria-hidden="true"></div>
	<main class:wide>
		<a class="brand" href={toLanding ? '/' : undefined} aria-label={name}>
			<Logo size={26} /><span>{name}</span>
		</a>
		<div class="card">{@render children()}</div>
		<p class="foot">Self-hosted · your notes stay on your own server</p>
	</main>
</div>

<style>
	.frame { position: relative; height: 100dvh; overflow-y: auto; display: grid; place-items: center; padding: 28px 16px; background: var(--bg-side); }
	.dots { position: absolute; inset: 0; pointer-events: none; background-image: radial-gradient(color-mix(in srgb, var(--text) 13%, transparent) 1px, transparent 1px); background-size: 22px 22px; mask-image: radial-gradient(ellipse at center, #000 20%, transparent 75%); }
	main { position: relative; width: min(392px, 100%); display: flex; flex-direction: column; gap: 18px; }
	main.wide { width: min(560px, 100%); }
	.brand { display: flex; align-items: center; justify-content: center; gap: 9px; font-size: 18px; font-weight: 650; letter-spacing: -0.015em; text-decoration: none; color: var(--text); }
	.card { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 12px; padding: 26px 26px 24px; box-shadow: 0 1px 0 color-mix(in srgb, var(--text) 5%, transparent), 0 18px 48px -24px rgba(0, 0, 0, 0.5); }
	.foot { margin: 0; text-align: center; font-size: 12px; color: var(--text-3); }
	@media (max-width: 480px) { .card { padding: 20px 16px; } }
</style>
