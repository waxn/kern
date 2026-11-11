<script lang="ts">
	import { FileText, Plus } from '@lucide/svelte';
	import { getContext, tick } from 'svelte';
	import { open } from '../state/tabs.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { DbRow, DbView } from '../types.ts';
	import { titleOf } from './query.ts';
	import type { DbState } from './state.svelte.ts';
	import ValueView from './ValueView.svelte';

	let { db, view, rows, onnew }: { db: DbState; view: DbView; rows: DbRow[]; onnew: (values?: Record<string, any>) => Promise<string | null> } = $props();
	let fields = $derived(db.visibleCols(view).filter((c) => c.def).map((c) => c.def!));
	let editing = $state<string | null>(null);
	let input = $state<HTMLInputElement>();
	const peek = getContext<((id: string) => void) | undefined>('kern-peek');

	async function add() {
		const id = await onnew();
		if (!id) return;
		editing = id;
		await tick();
		input?.focus();
	}
</script>

<div class="list">
	{#each rows as row (row.id)}
		<a class="row" href="/doc/{row.id}" onclick={(e) => { e.preventDefault(); if (editing === row.id) return; if (peek && !e.ctrlKey && !e.metaKey) peek(row.id); else open(`/doc/${row.id}`, e); }}>
			<span class="ico">{#if ws.docs[row.id]?.icon || row.icon}{ws.docs[row.id]?.icon || row.icon}{:else}<FileText size={14} strokeWidth={1.75} />{/if}</span>
			{#if editing === row.id}
				<input bind:this={input} class="ti" value={titleOf(row)} placeholder="Untitled" onclick={(e) => e.stopPropagation()}
					onblur={(e) => { db.setTitle(row.id, e.currentTarget.value); editing = null; }}
					onkeydown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur(); }} />
			{:else}
				<span class="title truncate" class:faint={!titleOf(row)}>{titleOf(row) || 'Untitled'}</span>
			{/if}
			<span class="vals">{#each fields as p (p.id)}<ValueView def={p} value={row.values[p.id]} />{/each}</span>
		</a>
	{/each}
	<button class="new" onclick={add}><Plus size={14} />New</button>
</div>

<style>
	.list { display: flex; flex-direction: column; font-family: var(--font-sans); font-size: 13.5px; }
	.row { display: flex; align-items: center; gap: 8px; min-height: 34px; padding: 0 6px; border-bottom: 1px solid var(--border); text-decoration: none; }
	.row:hover { background: var(--hover); }
	.ico { flex: none; width: 20px; display: grid; place-items: center; color: var(--text-2); }
	.title { flex: 0 1 auto; min-width: 80px; font-weight: 500; }
	.ti { flex: 1; border: 0; outline: 0; background: none; font-weight: 500; }
	.vals { margin-left: auto; display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; overflow: hidden; justify-content: flex-end; min-width: 0; }
	.new { display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 8px; color: var(--text-3); }
	.new:hover { background: var(--hover); color: var(--text-2); }
</style>
