<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { open } from '#lib/state/tabs.ts';
	import type { Doc } from '#lib/types.ts';

	let { docs, sub, actions, link = true }: {
		docs: Doc[]; sub?: (d: Doc) => string; actions?: Snippet<[Doc]>; link?: boolean;
	} = $props();
</script>

<div class="list">
	{#each docs as d (d.id)}
		<div class="row">
			<svelte:element this={link ? 'a' : 'span'} class="main" href={link ? `/doc/${d.id}` : undefined}
				onclick={(e: MouseEvent) => { if (link) { e.preventDefault(); open(`/doc/${d.id}`, e); } }}>
				<span class="ico">{#if d.icon}{d.icon}{:else}<FileText size={15} strokeWidth={1.75} />{/if}</span>
				<span class="truncate" class:faint={!d.title}>{d.title || 'Untitled'}</span>
				{#if sub}<span class="sub truncate">{sub(d)}</span>{/if}
			</svelte:element>
			{#if actions}<span class="acts">{@render actions(d)}</span>{/if}
		</div>
	{/each}
</div>

<style>
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.row { display: flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 8px 0 12px; border-top: 1px solid var(--border); }
	.row:first-child { border-top: 0; }
	.row:hover { background: var(--hover); }
	.main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; height: 36px; text-decoration: none; }
	.ico { flex: none; width: 20px; display: grid; place-items: center; color: var(--text-2); }
	.sub { margin-left: auto; padding-left: 12px; color: var(--text-3); font-size: 12.5px; flex-shrink: 2; }
	.acts { flex: none; display: flex; gap: 6px; }
</style>
