<script lang="ts">
	import { ui } from '#lib/state/ui.svelte.ts';
	import { Check } from '@lucide/svelte';

	let el = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });

	$effect(() => {
		const m = ui.menu;
		if (!m || !el) return;
		// Keep the menu inside the viewport.
		const r = el.getBoundingClientRect();
		pos = {
			x: Math.max(8, Math.min(m.x, innerWidth - r.width - 8)),
			y: Math.max(8, Math.min(m.y, innerHeight - r.height - 8))
		};
		el.focus();
	});

	function close() {
		ui.menu = null;
	}

	function key(e: KeyboardEvent) {
		if (e.key === 'Escape') return close();
		if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
		e.preventDefault();
		const items = [...el!.querySelectorAll<HTMLElement>('button.menu-item')];
		const i = items.indexOf(document.activeElement as HTMLElement);
		items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
	}
</script>

{#if ui.menu}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" onmousedown={close} oncontextmenu={(e) => { e.preventDefault(); close(); }}></div>
	<div class="menu popover" bind:this={el} style:left="{pos.x}px" style:top="{pos.y}px" tabindex="-1" role="menu" onkeydown={key}>
		{#each ui.menu.items as item, i (i)}
			{#if item.separator}
				<div class="menu-sep"></div>
			{:else if item.heading}
				<div class="menu-heading">{item.heading}</div>
			{:else}
				<button class="menu-item" class:danger={item.danger} role="menuitem"
					onclick={() => { close(); item.onSelect?.(); }}>
					{#if item.icon}<item.icon size={15} strokeWidth={1.75} />{/if}
					<span class="truncate">{item.label}</span>
					{#if item.checked}<Check size={14} class="hint" />{:else if item.hint}<span class="hint">{item.hint}</span>{/if}
				</button>
			{/if}
		{/each}
	</div>
{/if}

<style>
	.backdrop { position: fixed; inset: 0; z-index: 900; }
	.menu { position: fixed; z-index: 901; min-width: 200px; max-width: 300px; max-height: 80vh; overflow-y: auto; padding: 4px; outline: none; }
	.menu :global(.hint) { margin-left: auto; }
</style>
