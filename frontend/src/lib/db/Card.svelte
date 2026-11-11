<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import { getContext, tick } from 'svelte';
	import { open } from '../state/tabs.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { DbRow, PropDef } from '../types.ts';
	import { titleOf } from './query.ts';
	import type { DbState } from './state.svelte.ts';
	import ValueView from './ValueView.svelte';

	let { db, row, props, cover = false, editing = false, ondone, draggable = false, ondragstart }: {
		db: DbState; row: DbRow; props: PropDef[]; cover?: boolean; editing?: boolean; ondone?: () => void;
		draggable?: boolean; ondragstart?: (e: DragEvent) => void;
	} = $props();

	let input = $state<HTMLInputElement>();
	const peek = getContext<((id: string) => void) | undefined>('kern-peek');
	let doc = $derived(ws.docs[row.id]);
	let coverUrl = $derived(doc?.cover ?? row.cover);
	let shown = $derived(props.filter((p) => {
		const v = row.values[p.id];
		return v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length) && !(p.type === 'boolean' && !v);
	}));

	$effect(() => {
		if (editing) tick().then(() => input?.focus());
	});
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="card" {draggable} {ondragstart} onclick={(e) => { if (editing) return; if (peek && !e.ctrlKey && !e.metaKey) peek(row.id); else open(`/doc/${row.id}`, e); }}>
	{#if cover}
		<div class="cover" style:background-image={coverUrl ? `url(${JSON.stringify(coverUrl)})` : undefined}>
			{#if !coverUrl}<span class="ph">{doc?.icon || row.icon || ''}</span>{/if}
		</div>
	{/if}
	<div class="body">
		<div class="title">
			{#if (doc?.icon || row.icon) && !(cover && !coverUrl)}<span>{doc?.icon || row.icon}</span>{:else if !cover}<FileText size={13} class="faint" />{/if}
			{#if editing}
				<input bind:this={input} value={titleOf(row)} placeholder="Untitled"
					onclick={(e) => e.stopPropagation()}
					onblur={(e) => { db.setTitle(row.id, e.currentTarget.value); ondone?.(); }}
					onkeydown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur(); }} />
			{:else}
				<span class="truncate" class:faint={!titleOf(row)}>{titleOf(row) || 'Untitled'}</span>
			{/if}
		</div>
		{#if shown.length}
			<div class="vals">{#each shown as p (p.id)}<span class="v"><ValueView def={p} value={row.values[p.id]} /></span>{/each}</div>
		{/if}
	</div>
</div>

<style>
	.card { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); cursor: pointer; overflow: hidden; transition: border-color 0.12s, background 0.12s; text-align: left; }
	.card:hover { border-color: var(--border-strong); background: var(--surface-2); }
	.cover { height: var(--cover-h, 120px); background: var(--surface-2) center / cover no-repeat; border-bottom: 1px solid var(--border); display: grid; place-items: center; }
	.ph { font-size: 34px; opacity: 0.85; }
	.body { padding: 7px 9px; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
	.title { display: flex; align-items: center; gap: 6px; font-weight: 550; min-width: 0; }
	.title input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font-weight: 550; padding: 0; }
	.vals { display: flex; flex-wrap: wrap; gap: 4px; }
	.v { display: inline-flex; gap: 3px; min-width: 0; max-width: 100%; }
</style>
