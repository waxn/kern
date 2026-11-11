<script lang="ts" module>
	import type { Component } from 'svelte';
	export interface MenuEntry {
		key: string;
		label: string;
		sub?: string;
		icon?: Component<any>;
		emoji?: string;
		group?: string;
		hint?: string;
		color?: string;
	}
</script>

<script lang="ts">
	let { items, index, rect, onchoose, onhover, empty = 'No matches' }: {
		items: MenuEntry[]; index: number; rect: DOMRect; onchoose: (i: number) => void; onhover: (i: number) => void; empty?: string;
	} = $props();

	let el = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });

	$effect(() => {
		void items.length;
		if (!el) return;
		const r = el.getBoundingClientRect();
		const below = rect.bottom + 6;
		const y = below + r.height > innerHeight - 8 ? Math.max(8, rect.top - r.height - 6) : below;
		pos = { x: Math.max(8, Math.min(rect.left, innerWidth - r.width - 8)), y };
	});

	$effect(() => {
		void index;
		el?.querySelector('.active')?.scrollIntoView({ block: 'nearest' });
	});
</script>

<div class="suggest popover" bind:this={el} style:left="{pos.x}px" style:top="{pos.y}px" role="listbox">
	{#each items as item, i (item.key)}
		{#if item.group && (i === 0 || items[i - 1].group !== item.group)}<div class="menu-heading">{item.group}</div>{/if}
		<!-- svelte-ignore a11y_mouse_events_have_key_events -->
		<button class="menu-item" class:active={i === index} role="option" aria-selected={i === index}
			onmousedown={(e) => { e.preventDefault(); onchoose(i); }} onmousemove={() => onhover(i)}>
			<span class="ico" data-c={item.color || undefined}>
				{#if item.emoji}{item.emoji}{:else if item.icon}<item.icon size={15} strokeWidth={1.75} />{/if}
			</span>
			<span class="body">
				<span class="truncate">{item.label}</span>
				{#if item.sub}<span class="sub truncate">{item.sub}</span>{/if}
			</span>
			{#if item.hint}<span class="hint">{item.hint}</span>{/if}
		</button>
	{/each}
	{#if !items.length}<div class="none">{empty}</div>{/if}
</div>

<style>
	.suggest { position: fixed; z-index: 600; width: 280px; max-height: 320px; overflow-y: auto; padding: 4px; }
	.ico { flex: none; width: 22px; height: 22px; display: grid; place-items: center; color: var(--chip, var(--text-2)); font-size: 14px; }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; line-height: 1.25; }
	.sub { font-size: 11.5px; color: var(--text-3); }
	.hint { font: 11px var(--font-mono); }
	.none { padding: 8px 10px; color: var(--text-3); }
</style>
