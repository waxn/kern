<script lang="ts">
	import {
		ArrowUpDown, Calendar, ChevronDown, Copy, Filter, Kanban, LayoutGrid, List, Pencil, Plus, Search,
		Settings2, Table, Trash2, ArrowUpRight
	} from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { open } from '../state/tabs.ts';
	import { ui } from '../state/ui.svelte.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { DbView, FilterGroup, ViewType } from '../types.ts';
	import BoardView from './BoardView.svelte';
	import CalendarView from './CalendarView.svelte';
	import FilterEditor from './FilterEditor.svelte';
	import GalleryView from './GalleryView.svelte';
	import ListView from './ListView.svelte';
	import Popover from './Popover.svelte';
	import PropertyEditor from './PropertyEditor.svelte';
	import { plainValue, titleOf } from './query.ts';
	import SortEditor from './SortEditor.svelte';
	import { getDb } from './state.svelte.ts';
	import TableView from './TableView.svelte';
	import ViewSettings from './ViewSettings.svelte';
	import EntryPeek from './EntryPeek.svelte';
	import { setContext } from 'svelte';

	let { dbId, viewId = null, inline = false, onviewchange }: {
		dbId: string; viewId?: string | null; inline?: boolean; onviewchange?: (id: string) => void;
	} = $props();

	// svelte-ignore state_referenced_locally
	const db = getDb(dbId);
	// svelte-ignore state_referenced_locally
	let activeId = $state<string | null>(viewId);
	let view = $derived(db.data?.views.find((v) => v.id === activeId) ?? db.data?.views[0] ?? null);
	let quick = $state('');
	let searching = $state(false);
	let pop = $state<{ kind: 'filter' | 'sort' | 'settings' | 'prop' | 'addview'; at: DOMRect; prop?: string | null } | null>(null);
	let page = $derived(ws.dbPages[dbId]);
	// Board, gallery and list items open beside the view, so you can write in them in place.
	let peeking = $state<string | null>(null);
	setContext('kern-peek', (id: string) => (peeking = id));

	let rows = $derived.by(() => {
		if (!view) return [];
		const base = db.rowsFor(view);
		const q = quick.trim().toLowerCase();
		if (!q) return base;
		return base.filter((r) =>
			titleOf(r).toLowerCase().includes(q) ||
			db.cols.some((c) => {
				const v = plainValue(r, c);
				return v !== null && String(Array.isArray(v) ? v.join(' ') : v).toLowerCase().includes(q);
			})
		);
	});

	const icons: Record<ViewType, any> = { table: Table, board: Kanban, calendar: Calendar, gallery: LayoutGrid, list: List };
	let filterCount = $derived(view?.config.filter?.rules.length ?? 0);
	let sortCount = $derived(view?.config.sorts?.length ?? 0);

	function choose(v: DbView) {
		activeId = v.id;
		onviewchange?.(v.id);
	}

	function anchor(e: MouseEvent) {
		return (e.currentTarget as HTMLElement).getBoundingClientRect();
	}

	function openFilter(e: MouseEvent) {
		if (!view) return;
		if (!view.config.filter) view.config.filter = { op: 'and', rules: [] };
		if (!view.config.filter.rules.length) {
			const c = db.cols[0];
			view.config.filter.rules.push({ prop: c.id, op: 'contains', value: '' });
		}
		pop = { kind: 'filter', at: anchor(e) };
	}

	function openSort(e: MouseEvent) {
		if (!view) return;
		if (!view.config.sorts) view.config.sorts = [];
		pop = { kind: 'sort', at: anchor(e) };
	}

	function saveFilter() {
		if (view) db.updateView(view, { filter: $state.snapshot(view.config.filter) as FilterGroup });
	}

	function saveSorts() {
		if (view) db.updateView(view, { sorts: $state.snapshot(view.config.sorts) });
	}

	function closePop() {
		if (pop?.kind === 'filter' && view?.config.filter) {
			// Drop incomplete rules so they do not linger invisibly.
			const clean = (g: FilterGroup): FilterGroup => ({
				op: g.op,
				rules: g.rules
					.map((r) => ('rules' in r ? clean(r) : r))
					.filter((r) => ('rules' in r ? r.rules.length : r.value !== '' && r.value !== undefined && r.value !== null) || ('op' in r && ['empty', 'not_empty', 'past_week', 'next_week'].includes((r as any).op)))
			});
			db.updateView(view, { filter: clean($state.snapshot(view.config.filter) as FilterGroup) });
		}
		pop = null;
	}

	async function addView(type: ViewType) {
		pop = null;
		const v = await db.addView(type);
		if (v) choose(v);
	}

	function viewMenu(e: MouseEvent, v: DbView) {
		e.preventDefault();
		ui.openMenu(e, [
			{
				label: 'Rename', icon: Pencil,
				onSelect: () => {
					const name = prompt('View name', v.name)?.trim();
					if (name) db.renameView(v, name);
				}
			},
			{ label: 'Duplicate', icon: Copy, onSelect: async () => { const c = await db.duplicateView(v); if (c) choose(c); } },
			{ separator: true },
			{ label: 'Delete view', icon: Trash2, danger: true, onSelect: async () => { if (await db.deleteView(v) && activeId === v.id) activeId = db.data!.views[0]?.id ?? null; } }
		]);
	}

	/** Create an entry honouring the view's simple "is" filters so it stays visible. */
	async function newEntry(values: Record<string, any> = {}, template?: string): Promise<string | null> {
		const v = { ...values };
		const f = view?.config.filter;
		if (f && f.op === 'and')
			for (const r of f.rules) {
				if ('rules' in r || r.prop in v) continue;
				const c = db.colMap[r.prop];
				if (!c?.def) continue;
				if ((c.type === 'select' || c.type === 'status') && r.op === 'is' && r.value) v[r.prop] = r.value;
				if ((c.type === 'multi_select' || c.type === 'relation') && r.op === 'contains' && r.value) v[r.prop] = [r.value];
				if (c.type === 'boolean' && r.op === 'is') v[r.prop] = r.value === true || r.value === 'true';
			}
		const doc = await db.addRow(v, { template });
		return doc?.id ?? null;
	}

	function newMenu(e: MouseEvent) {
		const tpls = db.data?.templates ?? [];
		ui.menuBelow(e.currentTarget as Element, [
			{ label: 'Empty entry', icon: Plus, onSelect: async () => { const id = await newEntry(); if (id) peeking = id; } },
			...(tpls.length ? [{ heading: 'Templates' }] : []),
			...tpls.map((t) => ({ label: `${t.icon ? t.icon + ' ' : ''}${t.title || 'Untitled'}`, onSelect: async () => { const id = await newEntry({}, t.id); if (id) peeking = id; } })),
			{ separator: true },
			{ label: 'New template…', icon: Copy, onSelect: () => newTemplate() }
		]);
	}

	async function newTemplate() {
		const { api } = await import('../api.ts');
		try {
			const t = await api.post<any>('/templates', { title: 'New template', template_db: dbId });
			goto(`/doc/${t.id}`);
		} catch (err) {
			ui.error(err);
		}
	}

	function addPropOfType(type: string) {
		db.addProperty({ name: type === 'status' ? 'Status' : type === 'date' ? 'Date' : 'Group', type: type as any }).then((d) => {
			if (d && view) db.updateView(view, type === 'date' ? { date_prop: d.id } : { group_by: d.id });
		});
	}
</script>

<div class="dbv" class:inline>
	{#if peeking}
		{#key peeking}<EntryPeek id={peeking} onclose={() => { peeking = null; db.refresh(); }} />{/key}
	{/if}
	{#if db.status === 'loading'}
		<div class="faint pad">Loading database…</div>
	{:else if db.status === 'missing'}
		<div class="empty">This database was deleted.</div>
	{:else if db.status === 'error'}
		<div class="empty">Could not load this database. <button class="btn" onclick={() => db.load()}>Retry</button></div>
	{:else if db.data && view}
		{#if inline}
			<div class="title">
				<a href="/doc/{db.data.database.page}" onclick={(e) => { e.preventDefault(); open(`/doc/${db.data!.database.page}`, e); }}>
					{page?.icon ?? db.data.database.icon} {page?.title || db.data.database.title || 'Untitled database'}
				</a>
				<ArrowUpRight size={13} class="faint" />
			</div>
		{/if}
		<div class="bar">
			<div class="views">
				{#each db.data.views as v (v.id)}
					{@const Icon = icons[v.type]}
					<button class="vtab" class:on={v.id === view.id} onclick={() => choose(v)} oncontextmenu={(e) => viewMenu(e, v)} ondblclick={(e) => viewMenu(e, v)}>
						<Icon size={13} />{v.name}
					</button>
				{/each}
				<button class="icon-btn" title="Add view" onclick={(e) => (pop = { kind: 'addview', at: anchor(e) })}><Plus size={14} /></button>
			</div>
			<div class="tools">
				<button class="tool" class:on={filterCount > 0} onclick={openFilter}><Filter size={13} />Filter{#if filterCount} · {filterCount}{/if}</button>
				<button class="tool" class:on={sortCount > 0} onclick={openSort}><ArrowUpDown size={13} />Sort{#if sortCount} · {sortCount}{/if}</button>
				{#if searching || quick}
					<!-- svelte-ignore a11y_autofocus -->
					<input class="input search" autofocus bind:value={quick} placeholder="Search entries…" onblur={() => (searching = false)} onkeydown={(e) => { if (e.key === 'Escape') { quick = ''; searching = false; } }} />
				{:else}
					<button class="icon-btn" title="Search entries" onclick={() => (searching = true)}><Search size={14} /></button>
				{/if}
				<button class="icon-btn" title="View settings" onclick={(e) => (pop = { kind: 'settings', at: anchor(e) })}><Settings2 size={14} /></button>
				<div class="split">
					<button class="btn primary" onclick={async () => { const id = await newEntry(); if (id && view?.type !== 'table') peeking = id; }}>New</button>
					<button class="btn primary caret" title="New from template" onclick={newMenu}><ChevronDown size={13} /></button>
				</div>
			</div>
		</div>

		<div class="body">
			{#if view.type === 'table'}
				<TableView {db} {view} {rows} onnew={newEntry} onedit={(id, at) => (pop = { kind: 'prop', at, prop: id })} />
			{:else if view.type === 'board'}
				<BoardView {db} {view} {rows} onnew={newEntry} onaddprop={addPropOfType} />
			{:else if view.type === 'calendar'}
				<CalendarView {db} {view} {rows} onnew={newEntry} onaddprop={addPropOfType} />
			{:else if view.type === 'gallery'}
				<GalleryView {db} {view} {rows} onnew={newEntry} />
			{:else}
				<ListView {db} {view} {rows} onnew={newEntry} />
			{/if}
		</div>

		{#if pop}
			{#if pop.kind === 'filter' && view.config.filter}
				<Popover anchor={pop.at} onclose={closePop} width={520} align="right">
					<FilterEditor group={view.config.filter} cols={db.cols} onchange={saveFilter} />
				</Popover>
			{:else if pop.kind === 'sort' && view.config.sorts}
				<Popover anchor={pop.at} onclose={() => (pop = null)} width={400} align="right">
					<SortEditor sorts={view.config.sorts} cols={db.cols} onchange={saveSorts} />
				</Popover>
			{:else if pop.kind === 'settings'}
				<Popover anchor={pop.at} onclose={() => (pop = null)} width={330} align="right">
					<ViewSettings {db} {view} onedit={(id) => (pop = { kind: 'prop', at: pop!.at, prop: id })} onadd={() => (pop = { kind: 'prop', at: pop!.at, prop: null })} />
				</Popover>
			{:else if pop.kind === 'prop'}
				{@const def = pop.prop ? db.data.properties.find((p) => p.id === pop!.prop) : undefined}
				<Popover anchor={pop.at} onclose={() => (pop = null)} width={380}>
					<PropertyEditor {db} {def} onclose={() => (pop = null)}
						onhide={def ? () => db.updateView(view!, { hidden: [...(view!.config.hidden ?? []), def.id] }) : undefined} />
				</Popover>
			{:else if pop.kind === 'addview'}
				<Popover anchor={pop.at} onclose={() => (pop = null)} width={200}>
					{#each Object.entries(icons) as [t, Icon] (t)}
						<button class="menu-item" onclick={() => addView(t as ViewType)}><Icon size={15} />{t[0].toUpperCase() + t.slice(1)}</button>
					{/each}
				</Popover>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.dbv { font-family: var(--font-sans); font-size: 13.5px; }
	.dbv.inline { margin: 6px 0 10px; }
	.pad { padding: 12px 0; }
	.title { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; font-size: 17px; font-weight: 650; }
	.title a { text-decoration: none; }
	.title a:hover { text-decoration: underline; text-decoration-color: var(--text-3); }
	.bar { display: flex; align-items: center; gap: 8px; padding-bottom: 6px; margin-bottom: 8px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
	.views { flex: 1; min-width: 0; display: flex; align-items: center; gap: 2px; overflow-x: auto; scrollbar-width: none; }
	.vtab { display: flex; align-items: center; gap: 5px; flex: none; height: 28px; padding: 0 9px; border-radius: var(--radius); color: var(--text-3); }
	.vtab:hover { background: var(--hover); color: var(--text-2); }
	.vtab.on { color: var(--text); background: var(--active); }
	.tools { display: flex; align-items: center; gap: 4px; }
	.bar :global(.icon-btn) { width: 28px; height: 28px; }
	.split .btn { height: 28px; }
	.tool { display: flex; align-items: center; gap: 5px; height: 28px; padding: 0 8px; border-radius: var(--radius); color: var(--text-2); }
	.tool:hover { background: var(--hover); }
	.tool.on { color: var(--accent); }
	.search { width: 170px; }
	.split { display: flex; }
	.split .btn:first-child { border-radius: var(--radius) 0 0 var(--radius); }
	.caret { padding: 0 5px; border-radius: 0 var(--radius) var(--radius) 0; border-left: 1px solid rgba(0, 0, 0, 0.2) !important; }
	.body { min-height: 40px; }
</style>
