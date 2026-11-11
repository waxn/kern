<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import { open } from '#lib/state/tabs.ts';
	import type { BacklinkGroup } from '#lib/types.ts';

	let { groups, empty = 'Nothing links here yet.' }: { groups: BacklinkGroup[]; empty?: string } = $props();
</script>

{#each groups as g (g.doc.id)}
	<div class="group">
		<a class="doc" href="/doc/{g.doc.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${g.doc.id}`, e); }}>
			<span class="ico">{#if g.doc.icon}{g.doc.icon}{:else}<FileText size={13} strokeWidth={1.75} />{/if}</span>
			<span class="truncate">{g.doc.title || 'Untitled'}</span>
		</a>
		{#each g.items as item (item.block)}
			<a class="item" href="/doc/{g.doc.id}#{item.block}" onclick={(e) => { e.preventDefault(); open(`/doc/${g.doc.id}#${item.block}`, e); }}>
				{#if item.context}<span class="ctx truncate">{item.context}</span>{/if}
				<span class="rt">{@html item.html}</span>
			</a>
		{/each}
	</div>
{:else}
	<p class="faint none">{empty}</p>
{/each}

<style>
	.group { margin-bottom: 10px; }
	.doc { display: flex; align-items: center; gap: 6px; padding: 3px 4px; border-radius: var(--radius-sm); font-weight: 550; text-decoration: none; }
	.doc:hover { background: var(--hover); }
	.ico { flex: none; display: grid; place-items: center; width: 16px; color: var(--text-2); }
	.item { display: block; margin: 2px 0 2px 9px; padding: 4px 8px; border-left: 2px solid var(--border-strong); color: var(--text-2); text-decoration: none; font-size: 12.5px; line-height: 1.5; }
	.item:hover { background: var(--hover); border-left-color: var(--accent); color: var(--text); }
	.item :global(a) { pointer-events: none; }
	.ctx { display: block; font-size: 11.5px; color: var(--text-3); }
	.none { margin: 4px; }
</style>
