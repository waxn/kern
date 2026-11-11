<script lang="ts">
	import { ArrowDown, ArrowUp, Plus, Trash2 } from '@lucide/svelte';
	import type { ViewConfig } from '../types.ts';
	import type { Col } from './query.ts';

	let { sorts, cols, onchange }: { sorts: NonNullable<ViewConfig['sorts']>; cols: Col[]; onchange: () => void } = $props();

	function add() {
		const used = new Set(sorts.map((s) => s.prop));
		const c = cols.find((c) => !used.has(c.id)) ?? cols[0];
		sorts.push({ prop: c.id, dir: 'asc' });
		onchange();
	}

	function move(i: number, d: number) {
		const j = i + d;
		if (j < 0 || j >= sorts.length) return;
		[sorts[i], sorts[j]] = [sorts[j], sorts[i]];
		onchange();
	}
</script>

<div class="sorts">
	{#each sorts as s, i (i)}
		<div class="row">
			<select class="input" bind:value={s.prop} onchange={onchange}>
				{#each cols as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
			</select>
			<select class="input dir" bind:value={s.dir} onchange={onchange}><option value="asc">Ascending</option><option value="desc">Descending</option></select>
			<button class="icon-btn" title="Higher priority" onclick={() => move(i, -1)}><ArrowUp size={13} /></button>
			<button class="icon-btn" title="Lower priority" onclick={() => move(i, 1)}><ArrowDown size={13} /></button>
			<button class="icon-btn" title="Remove sort" onclick={() => { sorts.splice(i, 1); onchange(); }}><Trash2 size={13} /></button>
		</div>
	{:else}
		<p class="faint none">No sorts. Entries keep the order they were added in.</p>
	{/each}
	<button class="btn ghost" onclick={add}><Plus size={13} />Add sort</button>
</div>

<style>
	.sorts { display: flex; flex-direction: column; gap: 5px; align-items: flex-start; }
	.row { display: flex; gap: 4px; width: 100%; }
	.row .input { flex: 1; min-width: 0; }
	.dir { flex: none !important; width: 112px; }
	.none { margin: 2px 4px 4px; font-size: 12.5px; }
</style>
