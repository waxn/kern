<script lang="ts">
	import Tip, { type TipState } from './Tip.svelte';

	let { months }: { months: [string, number][] } = $props();
	let tip = $state<TipState | null>(null);
	let hover = $state<string | null>(null);
	let max = $derived(Math.max(1, ...months.map((m) => m[1])));
	// A "nice" top for the single gridline.
	let top = $derived.by(() => {
		const p = 10 ** Math.floor(Math.log10(max));
		return [1, 2, 2.5, 5, 10].map((s) => s * p).find((v) => v >= max) ?? max;
	});
	const label = (m: string, opts: Intl.DateTimeFormatOptions) => new Date(m + '-15T12:00:00').toLocaleDateString(undefined, opts);
	let ticks = $derived.by(() => {
		const step = Math.max(1, Math.ceil(months.length / 8));
		return months.map((m, i) => (i % step === 0 || i === months.length - 1 ? i : -1)).filter((i) => i >= 0);
	});

	function show(e: MouseEvent, m: [string, number]) {
		const r = (e.currentTarget as Element).getBoundingClientRect();
		hover = m[0];
		tip = { x: r.left + r.width / 2, y: r.top + 8, title: `${m[1]} commit${m[1] === 1 ? '' : 's'}`, sub: label(m[0], { month: 'long', year: 'numeric' }) };
	}
</script>

<div class="chart">
	<div class="y"><span>{top}</span><span>0</span></div>
	<div class="plot">
		<div class="grid"></div>
		<div class="bars" style:--n={months.length}>
			{#each months as m (m[0])}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="hit" class:dim={hover && hover !== m[0]} onmouseenter={(e) => show(e, m)} onmouseleave={() => { tip = null; hover = null; }}>
					<div class="bar" style:height="{(m[1] / top) * 100}%"></div>
				</div>
			{/each}
		</div>
		<div class="x" style:--n={months.length}>
			{#each ticks as i (i)}
				<span style:grid-column={i + 1}>{label(months[i][0], months.length > 14 ? { month: 'short', year: '2-digit' } : { month: 'short' })}</span>
			{/each}
		</div>
	</div>
</div>
<Tip {tip} />

<style>
	.chart { display: flex; gap: 8px; height: 168px; }
	.y { display: flex; flex-direction: column; justify-content: space-between; padding-bottom: 20px; font-size: 11px; color: var(--text-3); text-align: right; min-width: 18px; margin-top: -6px; }
	.plot { flex: 1; min-width: 0; position: relative; display: flex; flex-direction: column; }
	.grid { position: absolute; left: 0; right: 0; top: 0; bottom: 20px; border-top: 1px dashed var(--border); border-bottom: 1px solid var(--border-strong); pointer-events: none; }
	.bars { flex: 1; display: grid; grid-template-columns: repeat(var(--n), 1fr); column-gap: 2px; align-items: end; }
	.hit { height: 100%; display: flex; align-items: flex-end; justify-content: center; cursor: default; }
	.bar { width: min(100%, 22px); min-height: 0; background: var(--accent); border-radius: 4px 4px 0 0; transition: opacity 0.12s; }
	.hit.dim .bar { opacity: 0.45; }
	.x { height: 20px; display: grid; grid-template-columns: repeat(var(--n), 1fr); column-gap: 2px; font-size: 11px; color: var(--text-3); padding-top: 5px; }
	.x span { white-space: nowrap; justify-self: center; }
</style>
