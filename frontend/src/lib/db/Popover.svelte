<script lang="ts">
	import type { Snippet } from 'svelte';

	let { anchor, onclose, children, width = 300, align = 'left' }: {
		anchor: DOMRect; onclose: () => void; children: Snippet; width?: number; align?: 'left' | 'right';
	} = $props();

	let el = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });

	$effect(() => {
		if (!el) return;
		const r = el.getBoundingClientRect();
		const x = align === 'right' ? anchor.right - r.width : anchor.left;
		const below = anchor.bottom + 4;
		pos = {
			x: Math.max(8, Math.min(x, innerWidth - r.width - 8)),
			y: below + r.height > innerHeight - 8 ? Math.max(8, anchor.top - r.height - 4) : below
		};
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="backdrop" onmousedown={onclose}></div>
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="pop popover" bind:this={el} style:left="{pos.x}px" style:top="{pos.y}px" style:width="{width}px"
	onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') onclose(); }}>
	{@render children()}
</div>

<style>
	.backdrop { position: fixed; inset: 0; z-index: 500; }
	.pop { position: fixed; z-index: 501; max-height: min(560px, calc(100vh - 16px)); overflow-y: auto; padding: 8px; }
</style>
