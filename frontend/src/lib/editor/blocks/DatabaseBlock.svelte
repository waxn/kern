<script lang="ts">
	import { Database, Plus } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import DatabaseView from '#lib/db/DatabaseView.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Block, DbPayload } from '#lib/types.ts';
	import { getEditor } from '../context.ts';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	let busy = $state(false);
	let filter = $state('');

	// Inserted as "Kanban board": create the board straight away.
	$effect(() => {
		if (block.props.preset && !block.props.database && !busy) create(block.props.preset);
	});

	async function create(preset?: string) {
		busy = true;
		try {
			const p = await api.post<DbPayload>('/databases', { parent: ed.doc.id, title: '', preset });
			await ws.load();
			ed.doc.setProps(block.id, { database: p.database.id, preset: undefined });
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	let choices = $derived(ws.databases.filter((d) => (d.title || 'Untitled').toLowerCase().includes(filter.trim().toLowerCase())).slice(0, 8));
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="dbb" data-editor-skip>
	{#if block.props.database}
		{#key block.props.database}
			<DatabaseView dbId={block.props.database} viewId={block.props.view ?? null} inline
				onviewchange={(v) => { if (v !== block.props.view) ed.doc.setProps(block.id, { view: v }); }} />
		{/key}
	{:else}
		<div class="setup">
			<Database size={16} />
			<div class="grow">
				<button class="btn primary" disabled={busy} onclick={() => create()}><Plus size={14} />New database here</button>
				{#if ws.databases.length}
					<div class="or faint">…or show a view of an existing database:</div>
					<input class="input" bind:value={filter} placeholder="Find a database…" onkeydown={(e) => e.stopPropagation()} />
					{#each choices as d (d.id)}
						<button class="menu-item" onclick={() => ed.doc.setProps(block.id, { database: d.database })}>{d.icon} {d.title || 'Untitled'}</button>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.dbb { flex: 1; min-width: 0; }
	.setup { display: flex; gap: 10px; padding: 10px; border: 1px dashed var(--border-strong); border-radius: var(--radius); color: var(--text-2); font-family: var(--font-sans); font-size: 13.5px; }
	.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
	.grow .input { width: 100%; }
	.or { font-size: 12.5px; }
</style>
