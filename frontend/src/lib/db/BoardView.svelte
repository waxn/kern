<script lang="ts">
	import { ChevronRight, Plus } from '@lucide/svelte';
	import type { DbRow, DbView, PropOption } from '../types.ts';
	import Card from './Card.svelte';
	import type { DbState } from './state.svelte.ts';

	let { db, view, rows, onnew, onaddprop }: {
		db: DbState; view: DbView; rows: DbRow[]; onnew: (values?: Record<string, any>) => Promise<string | null>; onaddprop: (type: string) => void;
	} = $props();

	let groupProp = $derived.by(() => {
		const props = db.data?.properties ?? [];
		return props.find((p) => p.id === view.config.group_by && (p.type === 'select' || p.type === 'status')) ??
			props.find((p) => p.type === 'status' || p.type === 'select');
	});
	let cardProps = $derived(db.visibleCols(view).filter((c) => c.def && c.def.id !== groupProp?.id).map((c) => c.def!));
	let editing = $state<string | null>(null);
	let dragId = $state<string | null>(null);
	let over = $state<string | null>(null);

	interface Group { key: string; option: PropOption | null; rows: DbRow[] }
	let groups = $derived.by((): Group[] => {
		const p = groupProp;
		if (!p) return [];
		const out: Group[] = [{ key: '__none', option: null, rows: [] }, ...p.options.map((o) => ({ key: o.id, option: o, rows: [] as DbRow[] }))];
		const map = new Map(out.map((g) => [g.key, g]));
		for (const r of rows) (map.get(r.values[p.id]) ?? map.get('__none')!).rows.push(r);
		return out.filter((g) => g.rows.length || (!view.config.hide_empty_groups && g.key !== '__none'));
	});
	let collapsed = $derived(new Set(view.config.collapsed ?? []));

	function toggleGroup(key: string) {
		const next = new Set(collapsed);
		next.has(key) ? next.delete(key) : next.add(key);
		db.updateView(view, { collapsed: [...next] });
	}

	function drop(e: DragEvent, key: string) {
		e.preventDefault();
		const id = dragId;
		dragId = over = null;
		if (!id || !groupProp) return;
		const value = key === '__none' ? null : key;
		const row = db.row(id);
		if (row && row.values[groupProp.id] !== value) db.setValue(id, groupProp.id, value);
	}

	async function add(key: string) {
		if (!groupProp) return;
		const id = await onnew(key === '__none' ? {} : { [groupProp.id]: key });
		if (id) editing = id;
	}
</script>

{#if !groupProp}
	<div class="empty">
		<b>Board views group entries by a select or status property</b>
		This database has none yet.
		<div style="margin-top:10px; display:flex; gap:6px; justify-content:center">
			<button class="btn" onclick={() => onaddprop('status')}>Add a Status property</button>
			<button class="btn" onclick={() => onaddprop('select')}>Add a Select property</button>
		</div>
	</div>
{:else}
	<div class="board">
		{#each groups as g (g.key)}
			{#if collapsed.has(g.key)}
				<button class="col folded" onclick={() => toggleGroup(g.key)} title="Expand">
					<ChevronRight size={13} />
					<span class="chip vert" data-c={g.option?.color}>{g.option?.name ?? `No ${groupProp.name}`}</span>
					<span class="faint">{g.rows.length}</span>
				</button>
			{:else}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="col" class:over={over === g.key}
					ondragover={(e) => { if (dragId) { e.preventDefault(); over = g.key; } }}
					ondragleave={(e) => { if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) over = null; }}
					ondrop={(e) => drop(e, g.key)}>
					<div class="colhead">
						<button class="icon-btn fold" title="Collapse" onclick={() => toggleGroup(g.key)}><ChevronRight size={13} /></button>
						{#if g.option}<span class="chip" data-c={g.option.color}>{g.option.name}</span>{:else}<span class="faint">No {groupProp.name}</span>{/if}
						<span class="faint n">{g.rows.length}</span>
						<button class="icon-btn" title="New entry" onclick={() => add(g.key)}><Plus size={13} /></button>
					</div>
					<div class="cards">
						{#each g.rows as row (row.id)}
							<div class:dragging={dragId === row.id}>
								<Card {db} {row} props={cardProps} editing={editing === row.id} ondone={() => (editing = null)} draggable
									ondragstart={(e) => { dragId = row.id; e.dataTransfer!.effectAllowed = 'move'; e.dataTransfer!.setData('text/plain', row.title); }} />
							</div>
						{/each}
						<button class="addcard" onclick={() => add(g.key)}><Plus size={13} />New</button>
					</div>
				</div>
			{/if}
		{/each}
	</div>
{/if}

<svelte:window ondragend={() => { dragId = over = null; }} />

<style>
	.board { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 10px; align-items: flex-start; font-family: var(--font-sans); font-size: 13.5px; }
	.col { flex: none; width: 260px; display: flex; flex-direction: column; gap: 6px; padding: 6px; border-radius: 8px; background: color-mix(in srgb, var(--surface-2) 60%, transparent); transition: background 0.12s; }
	.col.over { background: color-mix(in srgb, var(--accent) 12%, transparent); }
	.col.folded { width: 42px; align-items: center; gap: 8px; padding: 8px 0; cursor: pointer; }
	.vert { writing-mode: vertical-rl; height: auto; padding: 7px 0; }
	.colhead { display: flex; align-items: center; gap: 6px; height: 28px; }
	.colhead .n { flex: 1; font-size: 12px; }
	.fold :global(svg) { transform: rotate(90deg); }
	.cards { display: flex; flex-direction: column; gap: 6px; min-height: 24px; }
	.dragging { opacity: 0.4; }
	.addcard { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px; border-radius: var(--radius); color: var(--text-3); }
	.addcard:hover { background: var(--hover); color: var(--text-2); }
</style>
