<script lang="ts">
	import { ai } from './ai.svelte.ts';
	import Sparkle from './Sparkle.svelte';

	let { title = 'Ask AI', onclick, label = '' }: { title?: string; onclick: () => void; label?: string } = $props();

	async function click() {
		if (await ai.ready()) onclick();
	}
</script>

<button class="aibtn" class:labelled={!!label} {title} aria-label={title} onclick={click}>
	<Sparkle size={label ? 15 : 17} />{#if label}<span>{label}</span>{/if}
</button>

<style>
	/* Same box as the neighbouring .btn buttons, so it lines up with them. */
	.aibtn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 28px; min-width: 28px; padding: 0 6px; border-radius: var(--radius); border: 1px solid var(--border-strong); background: var(--surface); transition: background 0.15s var(--ease), border-color 0.15s var(--ease); }
	.aibtn:hover { background: color-mix(in srgb, var(--accent) 12%, var(--surface)); border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong)); }
	.aibtn :global(.sparkle) { transition: transform 0.35s var(--ease); }
	.aibtn:hover :global(.sparkle) { transform: rotate(45deg) scale(1.08); }
	.aibtn.labelled { padding: 0 10px; }
	.aibtn span { color: var(--text); }
</style>
