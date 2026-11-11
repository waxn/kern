<script lang="ts">
	import Tip, { type TipState } from './Tip.svelte';

	let { days }: { days: [string, number][] } = $props();
	let tip = $state<TipState | null>(null);

	const parse = (d: string) => new Date(d + 'T12:00:00');
	// Columns are weeks (Sunday first), rows are weekdays.
	let weeks = $derived.by(() => {
		const out: ([string, number] | null)[][] = [];
		let col: ([string, number] | null)[] = [];
		for (const d of days) {
			const wd = parse(d[0]).getDay();
			if (wd === 0 && col.length) { out.push(col); col = []; }
			while (col.length < wd) col.push(null);
			col.push(d);
		}
		if (col.length) out.push(col);
		return out;
	});
	let max = $derived(Math.max(1, ...days.map((d) => d[1])));
	let total = $derived(days.reduce((n, d) => n + d[1], 0));
	// Sequential scale: one hue (the accent), four steps up from an empty cell.
	const level = (n: number) => (n === 0 ? 0 : Math.min(4, Math.ceil((n / max) * 4)));
	let months = $derived.by(() => {
		const out: { i: number; label: string }[] = [];
		let last = -1;
		weeks.forEach((w, i) => {
			const first = w.find(Boolean);
			if (!first) return;
			const m = parse(first[0]).getMonth();
			if (m !== last && parse(first[0]).getDate() <= 7) {
				out.push({ i, label: parse(first[0]).toLocaleDateString(undefined, { month: 'short' }) });
			}
			last = m;
		});
		return out;
	});

	function show(e: MouseEvent, d: [string, number]) {
		const r = (e.currentTarget as Element).getBoundingClientRect();
		tip = {
			x: r.left + r.width / 2, y: r.top,
			title: `${d[1] || 'No'} commit${d[1] === 1 ? '' : 's'}`,
			sub: parse(d[0]).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
		};
	}
</script>

<div class="heat">
	<div class="scroll">
		<div class="grid" style:--weeks={weeks.length}>
			<div class="months">
				{#each months as m (m.i)}<span style:grid-column={m.i + 2}>{m.label}</span>{/each}
			</div>
			<div class="wd"><span></span><span>Mon</span><span></span><span>Wed</span><span></span><span>Fri</span><span></span></div>
			{#each weeks as w, wi (wi)}
				<div class="col">
					{#each { length: 7 } as _, r (r)}
						{@const d = w[r]}
						{#if d}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div class="cell l{level(d[1])}" onmouseenter={(e) => show(e, d)} onmouseleave={() => (tip = null)}
								aria-label="{d[1]} commits on {d[0]}"></div>
						{:else}<div class="cell none"></div>{/if}
					{/each}
				</div>
			{/each}
		</div>
	</div>
	<div class="foot">
		<span class="faint">{total} commit{total === 1 ? '' : 's'} in the last year</span>
		<span class="grow"></span>
		<span class="faint">Less</span>
		{#each [0, 1, 2, 3, 4] as l (l)}<i class="cell l{l}"></i>{/each}
		<span class="faint">More</span>
	</div>
</div>
<Tip {tip} />

<style>
	.scroll { overflow-x: auto; padding-bottom: 4px; }
	.grid { display: grid; grid-template-columns: 26px repeat(var(--weeks), 11px); grid-template-rows: 16px auto; column-gap: 3px; width: max-content; }
	.months { grid-column: 1 / -1; display: grid; grid-template-columns: subgrid; font-size: 11px; color: var(--text-3); }
	.months span { white-space: nowrap; }
	.wd, .col { display: grid; grid-template-rows: repeat(7, 11px); row-gap: 3px; }
	.wd { font-size: 10px; color: var(--text-3); line-height: 11px; }
	.cell { width: 11px; height: 11px; border-radius: 2.5px; background: var(--surface-2); outline: 1px solid color-mix(in srgb, var(--text) 4%, transparent); outline-offset: -1px; }
	.cell.none { background: none; outline: 0; }
	.cell.l1 { background: color-mix(in srgb, var(--accent) 30%, var(--surface-2)); }
	.cell.l2 { background: color-mix(in srgb, var(--accent) 55%, var(--surface-2)); }
	.cell.l3 { background: color-mix(in srgb, var(--accent) 78%, var(--surface-2)); }
	.cell.l4 { background: var(--accent); }
	.col .cell:hover { outline: 1.5px solid var(--text); outline-offset: 0; }
	.foot { display: flex; align-items: center; gap: 3px; margin-top: 8px; font-size: 11.5px; }
	.foot .faint:last-child { margin-left: 3px; }
	.foot .grow + .faint { margin-right: 3px; }
	.grow { flex: 1; }
	i.cell { display: inline-block; }
</style>
