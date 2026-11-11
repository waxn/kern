<script lang="ts">
	import { ArrowDown, ArrowUp, ArrowLeft, ArrowRight, EyeOff, Filter, Maximize2, Pencil, Plus, Trash2 } from '@lucide/svelte';
	import { tick } from 'svelte';
	import PropertyField from '../components/PropertyField.svelte';
	import { PROP_ICONS } from '../propTypes.ts';
	import { open } from '../state/tabs.ts';
	import { ui } from '../state/ui.svelte.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { DbRow, DbView } from '../types.ts';
	import { opsFor, TITLE, titleOf, type Col } from './query.ts';
	import type { DbState } from './state.svelte.ts';

	let { db, view, rows, onedit, onnew }: {
		db: DbState; view: DbView; rows: DbRow[]; onedit: (id: string | null, at: DOMRect) => void; onnew: (values?: Record<string, any>) => Promise<string | null>;
	} = $props();

	let cols = $derived(db.visibleCols(view));
	let selected = $state<string[]>([]);
	let resizing = $state<string | null>(null);
	let table = $state<HTMLElement>();

	const width = (c: Col) => view.config.widths?.[c.id] ?? (c.type === 'title' ? 260 : c.type === 'boolean' ? 90 : 180);

	function startResize(e: PointerEvent, c: Col) {
		e.preventDefault();
		e.stopPropagation();
		const startX = e.clientX;
		const start = width(c);
		resizing = c.id;
		const move = (ev: PointerEvent) => {
			const widths = { ...(view.config.widths ?? {}), [c.id]: Math.max(70, Math.min(800, start + ev.clientX - startX)) };
			view.config.widths = widths;
		};
		const up = () => {
			resizing = null;
			db.updateView(view, { widths: { ...view.config.widths } });
			removeEventListener('pointermove', move);
			removeEventListener('pointerup', up);
		};
		addEventListener('pointermove', move);
		addEventListener('pointerup', up);
	}

	function sortBy(c: Col, dir: 'asc' | 'desc') {
		db.updateView(view, { sorts: [{ prop: c.id, dir }, ...(view.config.sorts ?? []).filter((s) => s.prop !== c.id)] });
	}

	function filterBy(c: Col) {
		const filter = structuredClone($state.snapshot(view.config.filter ?? { op: 'and' as const, rules: [] }));
		filter.rules.push({ prop: c.id, op: opsFor(c.type)[0][0], value: c.type === 'boolean' ? true : '' });
		db.updateView(view, { filter });
		ui.toast(`Added a filter on “${c.name}”. Set its value in Filter.`);
	}

	function headerMenu(e: MouseEvent, c: Col) {
		const el = e.currentTarget as HTMLElement;
		const props = db.data!.properties;
		const i = props.findIndex((p) => p.id === c.id);
		ui.menuBelow(el, [
			...(c.def ? [{ label: 'Edit property', icon: Pencil, onSelect: () => onedit(c.id, el.getBoundingClientRect()) }] : []),
			{ label: 'Sort ascending', icon: ArrowUp, onSelect: () => sortBy(c, 'asc') },
			{ label: 'Sort descending', icon: ArrowDown, onSelect: () => sortBy(c, 'desc') },
			{ label: 'Filter', icon: Filter, onSelect: () => filterBy(c) },
			...(c.def
				? [
						{ separator: true },
						{ label: 'Move left', icon: ArrowLeft, onSelect: () => db.moveProperty(c.id, -1), hint: i === 0 ? '—' : '' },
						{ label: 'Move right', icon: ArrowRight, onSelect: () => db.moveProperty(c.id, 1) },
						{ label: 'Hide in view', icon: EyeOff, onSelect: () => db.updateView(view, { hidden: [...(view.config.hidden ?? []), c.id] }) },
						{ separator: true },
						{ label: 'Delete property', icon: Trash2, danger: true, onSelect: () => db.deleteProperty(c.id) }
					]
				: [])
		]);
	}

	function toggleRow(id: string, e: MouseEvent) {
		if (e.shiftKey && selected.length) {
			const ids = rows.map((r) => r.id);
			const a = ids.indexOf(selected[selected.length - 1]);
			const b = ids.indexOf(id);
			const [lo, hi] = a < b ? [a, b] : [b, a];
			selected = [...new Set([...selected, ...ids.slice(lo, hi + 1)])];
		} else selected = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
	}

	async function newRow() {
		const id = await onnew();
		if (!id) return;
		await tick();
		table?.querySelector<HTMLInputElement>(`[data-row="${id}"] .title-input`)?.focus();
	}

	function titleKey(e: KeyboardEvent, row: DbRow) {
		if (e.key === 'Enter') {
			e.preventDefault();
			(e.currentTarget as HTMLInputElement).blur();
			if (rows[rows.length - 1]?.id === row.id) newRow();
			else table?.querySelector<HTMLInputElement>(`[data-row="${rows[rows.findIndex((r) => r.id === row.id) + 1]?.id}"] .title-input`)?.focus();
		}
	}

	let template = $derived(`30px ${cols.map((c) => width(c) + 'px').join(' ')} 40px`);
	let allSelected = $derived(rows.length > 0 && rows.every((r) => selected.includes(r.id)));
	$effect(() => {
		const live = new Set(rows.map((r) => r.id));
		if (selected.some((id) => !live.has(id))) selected = selected.filter((id) => live.has(id));
	});
</script>

<div class="wrap" class:resizing>
	{#if selected.length}
		<div class="selbar">
			<span>{selected.length} selected</span>
			<button class="btn ghost" onclick={() => (selected = [])}>Clear</button>
			<button class="btn ghost danger" onclick={async () => { const ids = selected; selected = []; await db.trashRows(ids); }}><Trash2 size={13} />Delete</button>
		</div>
	{/if}
	<div class="scroll" bind:this={table}>
		<div class="grid" class:wrapcells={view.config.wrap} role="table">
			<div class="tr head" role="row" style:grid-template-columns={template}>
				<div class="td sel" role="columnheader">
					<input type="checkbox" checked={allSelected} title="Select all"
						onchange={() => (selected = allSelected ? [] : rows.map((r) => r.id))} />
				</div>
				{#each cols as c (c.id)}
					{@const Icon = c.type === 'title' ? null : PROP_ICONS[c.type]}
					<div class="td th" role="columnheader">
						<button class="hbtn" onclick={(e) => headerMenu(e, c)}>
							{#if Icon}<Icon size={13} class="faint" />{:else}<span class="aa">Aa</span>{/if}
							<span class="truncate">{c.name}</span>
							{#if view.config.sorts?.[0]?.prop === c.id}<span class="faint">{view.config.sorts[0].dir === 'asc' ? '↑' : '↓'}</span>{/if}
						</button>
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div class="rz" onpointerdown={(e) => startResize(e, c)}></div>
					</div>
				{/each}
				<div class="td th add" role="columnheader">
					<button class="icon-btn" title="Add property" onclick={(e) => onedit(null, e.currentTarget.getBoundingClientRect())}><Plus size={14} /></button>
				</div>
			</div>
			{#each rows as row (row.id)}
				<div class="tr" class:on={selected.includes(row.id)} data-row={row.id} role="row" style:grid-template-columns={template}>
					<div class="td sel" role="cell"><input type="checkbox" checked={selected.includes(row.id)} onclick={(e) => toggleRow(row.id, e)} /></div>
					{#each cols as c (c.id)}
						<div class="td" role="cell">
							{#if c.type === 'title'}
								<div class="titlecell">
									{#if ws.docs[row.id]?.icon || row.icon}<span class="ico">{ws.docs[row.id]?.icon || row.icon}</span>{/if}
									<input class="title-input" value={titleOf(row)} placeholder="Untitled"
										onchange={(e) => db.setTitle(row.id, e.currentTarget.value)} onkeydown={(e) => titleKey(e, row)} />
									<a class="openbtn" href="/doc/{row.id}" title="Open as page" onclick={(e) => { e.preventDefault(); open(`/doc/${row.id}`, e); }}><Maximize2 size={11} />Open</a>
								</div>
							{:else if c.def}
								<PropertyField def={c.def} value={row.values[c.id]} compact onchange={(v) => db.setValue(row.id, c.id, v)} />
							{/if}
						</div>
					{/each}
					<div class="td add" role="cell"></div>
				</div>
			{/each}
		</div>
		<button class="newrow" onclick={newRow}><Plus size={14} />New</button>
	</div>
	<div class="count faint">{rows.length} {rows.length === 1 ? 'entry' : 'entries'}{#if TITLE && db.data && rows.length !== db.data.rows.length} · {db.data.rows.length - rows.length} hidden by filters{/if}</div>
</div>

<style>
	.wrap { position: relative; }
	.wrap.resizing { cursor: col-resize; user-select: none; }
	.scroll { overflow-x: auto; }
	.grid { display: flex; flex-direction: column; width: max-content; min-width: 100%; font-size: 13.5px; font-family: var(--font-sans); }
	.tr { display: grid; border-bottom: 1px solid var(--border); }
	.head { border-top: 1px solid var(--border); }
	.tr:hover:not(.head) { background: color-mix(in srgb, var(--hover) 60%, transparent); }
	.tr.on { background: color-mix(in srgb, var(--accent) 10%, transparent); }
	.td { display: flex; align-items: center; min-width: 0; overflow: hidden; border-right: 1px solid var(--border); padding: 2px; }
	.td > :global(*) { flex: 1; min-width: 0; }
	.td:last-child { border-right: 0; }
	.sel { justify-content: center; border-right: 0; }
	.sel > :global(input) { flex: none; }
	.sel input { accent-color: var(--accent); opacity: 0; }
	.tr:hover .sel input, .tr.on .sel input, .head .sel input:checked { opacity: 1; }
	.th { position: relative; height: 32px; overflow: visible; color: var(--text-2); font-weight: 500; }
	.hbtn { display: flex; align-items: center; gap: 6px; width: 100%; height: 28px; padding: 0 6px; border-radius: var(--radius-sm); text-align: left; }
	.hbtn:hover { background: var(--hover); color: var(--text); }
	.aa { font-size: 11px; font-weight: 600; color: var(--text-3); }
	.rz { position: absolute; top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize; z-index: 2; }
	.rz:hover { background: color-mix(in srgb, var(--accent) 50%, transparent); }
	.add { justify-content: center; }
	.add > :global(.icon-btn) { flex: none; }
	.titlecell { display: flex; align-items: center; gap: 4px; }
	.ico { flex: none; font-size: 14px; padding-left: 4px; }
	.title-input { flex: 1; min-width: 0; height: 26px; padding: 0 6px; border: 0; outline: 0; background: none; font-weight: 500; border-radius: var(--radius-sm); }
	.title-input:focus { background: var(--hover); box-shadow: inset 0 0 0 1px var(--border-strong); }
	.openbtn { display: none; align-items: center; gap: 3px; flex: none; height: 20px; padding: 0 6px; border: 1px solid var(--border-strong); border-radius: 4px; font-size: 11px; color: var(--text-2); text-decoration: none; background: var(--surface); }
	.tr:hover .openbtn { display: inline-flex; }
	.openbtn:hover { color: var(--text); }
	.wrapcells .td :global(.chips) { flex-wrap: wrap; }
	.wrapcells .td { align-items: flex-start; }
	.newrow { display: flex; align-items: center; gap: 6px; width: 100%; height: 32px; padding: 0 10px; color: var(--text-3); border-bottom: 1px solid var(--border); }
	.newrow:hover { background: var(--hover); color: var(--text-2); }
	.count { padding: 6px 4px; font-size: 12px; }
	.selbar { position: sticky; top: 0; z-index: 3; display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 8px; margin-bottom: 4px; border-radius: var(--radius); background: var(--surface-2); }
	.selbar span { flex: 1; font-weight: 550; }
	.danger { color: var(--danger); }
	@media (hover: none) { .openbtn { display: inline-flex; } .sel input { opacity: 1; } }
</style>
