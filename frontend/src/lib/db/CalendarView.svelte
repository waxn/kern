<script lang="ts">
	import { ChevronLeft, ChevronRight, Plus } from '@lucide/svelte';
	import { open } from '../state/tabs.ts';
	import type { DbRow, DbView } from '../types.ts';
	import { titleOf, todayStr } from './query.ts';
	import type { DbState } from './state.svelte.ts';

	let { db, view, rows, onnew, onaddprop }: {
		db: DbState; view: DbView; rows: DbRow[]; onnew: (values?: Record<string, any>) => Promise<string | null>; onaddprop: (type: string) => void;
	} = $props();

	let dateProp = $derived.by(() => {
		const props = db.data?.properties ?? [];
		const ok = (t: string) => t === 'date' || t === 'created_time' || t === 'last_edited_time';
		return props.find((p) => p.id === view.config.date_prop && ok(p.type)) ?? props.find((p) => p.type === 'date') ?? props.find((p) => ok(p.type));
	});
	let editable = $derived(dateProp?.type === 'date');
	let mode = $derived(view.config.calendar_mode ?? 'month');
	let cursor = $state(new Date());
	let dragId = $state<string | null>(null);
	let over = $state<string | null>(null);

	const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	const weekStart = 1; // Monday

	let days = $derived.by(() => {
		const c = new Date(cursor.getFullYear(), cursor.getMonth(), mode === 'month' ? 1 : cursor.getDate());
		const start = new Date(c);
		start.setDate(start.getDate() - ((start.getDay() - weekStart + 7) % 7));
		const n = mode === 'month' ? 42 : 7;
		return Array.from({ length: n }, (_, i) => {
			const d = new Date(start);
			d.setDate(start.getDate() + i);
			return d;
		});
	});

	let byDay = $derived.by(() => {
		const map: Record<string, DbRow[]> = {};
		if (!dateProp) return map;
		for (const r of rows) {
			const v = r.values[dateProp.id];
			if (typeof v !== 'string' || !v) continue;
			const key = dateProp.type === 'date' ? v.slice(0, 10) : iso(new Date(v));
			(map[key] ??= []).push(r);
		}
		return map;
	});
	let undated = $derived(dateProp ? rows.filter((r) => !r.values[dateProp.id]).length : 0);

	function shift(n: number) {
		const d = new Date(cursor);
		if (mode === 'month') d.setMonth(d.getMonth() + n, 1);
		else d.setDate(d.getDate() + 7 * n);
		cursor = d;
	}

	let label = $derived(
		mode === 'month'
			? cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
			: `${days[0].toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${days[6].toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`
	);
	const weekdays = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(undefined, { weekday: 'short' }));

	function drop(e: DragEvent, day: string) {
		e.preventDefault();
		const id = dragId;
		dragId = over = null;
		if (id && dateProp && editable) db.setValue(id, dateProp.id, day);
	}
</script>

{#if !dateProp}
	<div class="empty">
		<b>Calendar views place entries by a date property</b>
		This database has none yet.
		<div style="margin-top:10px"><button class="btn" onclick={() => onaddprop('date')}>Add a Date property</button></div>
	</div>
{:else}
	<div class="cal">
		<div class="bar">
			<b class="label">{label}</b>
			<span class="faint small">by {dateProp.name}{#if undated} · {undated} without a date{/if}</span>
			<span class="grow"></span>
			<div class="seg">
				<button class:on={mode === 'month'} onclick={() => db.updateView(view, { calendar_mode: 'month' })}>Month</button>
				<button class:on={mode === 'week'} onclick={() => db.updateView(view, { calendar_mode: 'week' })}>Week</button>
			</div>
			<button class="icon-btn" title="Previous" onclick={() => shift(-1)}><ChevronLeft size={15} /></button>
			<button class="btn ghost" onclick={() => (cursor = new Date())}>Today</button>
			<button class="icon-btn" title="Next" onclick={() => shift(1)}><ChevronRight size={15} /></button>
		</div>
		<div class="grid" class:week={mode === 'week'}>
			{#each weekdays as w (w)}<div class="wd">{w}</div>{/each}
			{#each days as d (iso(d))}
				{@const key = iso(d)}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="day" class:other={mode === 'month' && d.getMonth() !== cursor.getMonth()} class:today={key === todayStr()} class:over={over === key}
					ondragover={(e) => { if (dragId && editable) { e.preventDefault(); over = key; } }}
					ondragleave={() => { if (over === key) over = null; }}
					ondrop={(e) => drop(e, key)}>
					<div class="dhead">
						{#if editable}<button class="icon-btn add" title="New entry on this day" onclick={() => onnew({ [dateProp.id]: key })}><Plus size={12} /></button>{/if}
						<span class="num">{d.getDate() === 1 && mode === 'month' ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : d.getDate()}</span>
					</div>
					{#each byDay[key] ?? [] as r (r.id)}
						<a class="ev" href="/doc/{r.id}" draggable={editable}
							ondragstart={(e) => { dragId = r.id; e.dataTransfer!.effectAllowed = 'move'; }}
							onclick={(e) => { e.preventDefault(); open(`/doc/${r.id}`, e); }}>
							{r.icon ? r.icon + ' ' : ''}{titleOf(r) || 'Untitled'}
						</a>
					{/each}
				</div>
			{/each}
		</div>
	</div>
{/if}

<svelte:window ondragend={() => { dragId = over = null; }} />

<style>
	.cal { font-family: var(--font-sans); font-size: 13px; }
	.bar { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
	.label { font-size: 15px; font-weight: 600; }
	.small { font-size: 12px; }
	.grow { flex: 1; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 2px 9px; border-radius: 4px; color: var(--text-2); font-size: 12.5px; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); border-top: 1px solid var(--border); border-left: 1px solid var(--border); }
	.wd { padding: 4px 6px; font-size: 11.5px; color: var(--text-3); border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); }
	.day { min-height: 104px; padding: 3px; display: flex; flex-direction: column; gap: 2px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); min-width: 0; }
	.week .day { min-height: 320px; }
	.day.other { background: color-mix(in srgb, var(--surface-2) 45%, transparent); }
	.day.other .num { color: var(--text-3); }
	.day.over { background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.dhead { display: flex; align-items: center; justify-content: flex-end; gap: 2px; height: 22px; }
	.num { padding: 0 5px; font-size: 12px; color: var(--text-2); border-radius: 10px; line-height: 20px; }
	.today .num { background: var(--accent); color: #17130c; font-weight: 650; }
	.add { width: 20px; height: 20px; opacity: 0; margin-right: auto; }
	.day:hover .add { opacity: 1; }
	.ev { display: block; padding: 2px 6px; border-radius: 4px; background: var(--surface); border: 1px solid var(--border); text-decoration: none; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.ev:hover { border-color: var(--border-strong); background: var(--surface-2); }
	@media (max-width: 760px) { .day { min-height: 70px; } .ev { font-size: 11px; padding: 1px 3px; } }
</style>
