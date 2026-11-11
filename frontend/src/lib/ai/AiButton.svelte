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
	.aibtn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 28px; min-width: 28px; padding: 0 6px; border-radius: var(--radius); border: 1px solid transparent; transition: background 0.15s var(--ease), transform 0.15s var(--ease), border-color 0.15s; }
	.aibtn:hover { background: color-mix(in srgb, var(--accent) 12%, transparent); border-color: color-mix(in srgb, var(--accent) 30%, transparent); }
	.aibtn:hover :global(.sparkle) { transform: rotate(45deg) scale(1.08); }
	.aibtn :global(.sparkle) { transition: transform 0.35s var(--ease); }
	.aibtn.labelled { padding: 0 10px; border-color: var(--border-strong); }
	.aibtn span { color: var(--text); }
</style>
