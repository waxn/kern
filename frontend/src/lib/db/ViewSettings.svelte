<script lang="ts">
	import { ArrowDown, ArrowUp, Calendar, Eye, EyeOff, Kanban, LayoutGrid, List, Pencil, Plus, Table } from '@lucide/svelte';
	import { PROP_ICONS } from '../propTypes.ts';
	import type { DbView, ViewType } from '../types.ts';
	import type { DbState } from './state.svelte.ts';

	let { db, view, onedit, onadd }: { db: DbState; view: DbView; onedit: (id: string) => void; onadd: () => void } = $props();

	const layouts: [ViewType, string, any][] = [
		['table', 'Table', Table], ['board', 'Board', Kanban], ['calendar', 'Calendar', Calendar],
		['gallery', 'Gallery', LayoutGrid], ['list', 'List', List]
	];

	let fields = $derived(db.data?.properties ?? []);
	let hidden = $derived(new Set(view.config.hidden ?? []));
	let groupable = $derived(fields.filter((p) => p.type === 'select' || p.type === 'status'));
	let dateProps = $derived(fields.filter((p) => p.type === 'date' || p.type === 'created_time' || p.type === 'last_edited_time'));

	function toggle(id: string) {
		const next = new Set(hidden);
		next.has(id) ? next.delete(id) : next.add(id);
		db.updateView(view, { hidden: [...next] });
	}

	async function setLayout(t: ViewType) {
		view.type = t;
		const { api } = await import('../api.ts');
		await api.patch(`/views/${view.id}`, { type: t });
	}
</script>

<div class="vs">
	<div class="sub">Layout</div>
	<div class="layouts">
		{#each layouts as [t, label, Icon] (t)}
			<button class:on={view.type === t} onclick={() => setLayout(t)}><Icon size={16} strokeWidth={1.75} />{label}</button>
		{/each}
	</div>

	{#if view.type === 'board'}
		<label class="field"><span>Group by</span>
			<select class="input" value={view.config.group_by ?? groupable[0]?.id ?? ''} onchange={(e) => db.updateView(view, { group_by: e.currentTarget.value })}>
				{#each groupable as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
				{#if !groupable.length}<option value="">No select or status property</option>{/if}
			</select>
		</label>
		<label class="check"><input type="checkbox" checked={!!view.config.hide_empty_groups} onchange={(e) => db.updateView(view, { hide_empty_groups: e.currentTarget.checked })} /> Hide empty groups</label>
	{:else if view.type === 'calendar'}
		<label class="field"><span>Show by</span>
			<select class="input" value={view.config.date_prop ?? dateProps[0]?.id ?? ''} onchange={(e) => db.updateView(view, { date_prop: e.currentTarget.value })}>
				{#each dateProps as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
				{#if !dateProps.length}<option value="">No date property</option>{/if}
			</select>
		</label>
	{:else if view.type === 'gallery'}
		<label class="field"><span>Card size</span>
			<select class="input" value={view.config.card_size ?? 'medium'} onchange={(e) => db.updateView(view, { card_size: e.currentTarget.value as any })}>
				<option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option>
			</select>
		</label>
		<label class="field"><span>Card preview</span>
			<select class="input" value={view.config.cover ?? 'page'} onchange={(e) => db.updateView(view, { cover: e.currentTarget.value as any })}>
				<option value="page">Page cover</option><option value="none">None</option>
			</select>
		</label>
	{:else if view.type === 'table'}
		<label class="check"><input type="checkbox" checked={!!view.config.wrap} onchange={(e) => db.updateView(view, { wrap: e.currentTarget.checked })} /> Wrap cell contents</label>
	{/if}

	<div class="sub">Properties</div>
	<div class="props">
		<div class="prop"><span class="ico">Aa</span><span class="grow">Name</span><span class="faint small">Always shown</span></div>
		{#each fields as p, i (p.id)}
			{@const Icon = PROP_ICONS[p.type]}
			<div class="prop">
				<span class="ico"><Icon size={13} /></span>
				<span class="grow truncate" class:faint={hidden.has(p.id)}>{p.name}</span>
				<button class="icon-btn" title="Move up" disabled={i === 0} onclick={() => db.moveProperty(p.id, -1)}><ArrowUp size={12} /></button>
				<button class="icon-btn" title="Move down" disabled={i === fields.length - 1} onclick={() => db.moveProperty(p.id, 1)}><ArrowDown size={12} /></button>
				<button class="icon-btn" title="Edit property" onclick={() => onedit(p.id)}><Pencil size={12} /></button>
				<button class="icon-btn" title={hidden.has(p.id) ? 'Show in this view' : 'Hide in this view'} onclick={() => toggle(p.id)}>
					{#if hidden.has(p.id)}<EyeOff size={13} />{:else}<Eye size={13} />{/if}
				</button>
			</div>
		{/each}
	</div>
	<button class="btn ghost" onclick={onadd}><Plus size={13} />New property</button>
</div>

<style>
	.vs { display: flex; flex-direction: column; gap: 8px; }
	.sub { font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); margin-top: 2px; }
	.layouts { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; }
	.layouts button { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 7px 2px; border: 1px solid var(--border); border-radius: var(--radius); font-size: 11.5px; color: var(--text-2); }
	.layouts button:hover { background: var(--hover); }
	.layouts button.on { border-color: var(--accent); color: var(--text); background: color-mix(in srgb, var(--accent) 10%, transparent); }
	.field { display: flex; align-items: center; gap: 8px; }
	.field span { width: 86px; color: var(--text-3); font-size: 12.5px; }
	.field .input { flex: 1; }
	.check { display: flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 12.5px; }
	.check input { accent-color: var(--accent); }
	.props { display: flex; flex-direction: column; }
	.prop { display: flex; align-items: center; gap: 4px; height: 28px; padding: 0 4px; border-radius: var(--radius-sm); }
	.prop:hover { background: var(--hover); }
	.prop .icon-btn { width: 22px; height: 22px; }
	.prop .icon-btn:disabled { opacity: 0.3; }
	.ico { width: 20px; display: grid; place-items: center; color: var(--text-3); font-size: 11px; font-weight: 600; }
	.grow { flex: 1; min-width: 0; }
	.small { font-size: 11.5px; }
</style>
