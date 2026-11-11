<script lang="ts">
	import { Plus } from '@lucide/svelte';
	import type { DbRow, DbView } from '../types.ts';
	import Card from './Card.svelte';
	import type { DbState } from './state.svelte.ts';

	let { db, view, rows, onnew }: { db: DbState; view: DbView; rows: DbRow[]; onnew: (values?: Record<string, any>) => Promise<string | null> } = $props();
	let fields = $derived(db.visibleCols(view).filter((c) => c.def).map((c) => c.def!));
	let size = $derived(view.config.card_size ?? 'medium');
	let editing = $state<string | null>(null);
	const widths = { small: 180, medium: 240, large: 320 };
	const covers = { small: 90, medium: 130, large: 180 };
</script>

<div class="gallery" style:--min="{widths[size]}px" style:--cover-h="{covers[size]}px">
	{#each rows as row (row.id)}
		<Card {db} {row} props={fields} cover={view.config.cover !== 'none'} editing={editing === row.id} ondone={() => (editing = null)} />
	{/each}
	<button class="new" onclick={async () => { const id = await onnew(); if (id) editing = id; }}><Plus size={15} />New</button>
</div>

<style>
	.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(var(--min), 1fr)); gap: 10px; font-family: var(--font-sans); font-size: 13.5px; }
	.new { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 80px; border: 1px dashed var(--border-strong); border-radius: var(--radius); color: var(--text-3); }
	.new:hover { background: var(--hover); color: var(--text-2); }
</style>
