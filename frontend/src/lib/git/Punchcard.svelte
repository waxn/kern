<script lang="ts">
	import Tip, { type TipState } from './Tip.svelte';

	/** punch[weekday 0=Mon][hour] = commits */
	let { punch }: { punch: number[][] } = $props();
	let tip = $state<TipState | null>(null);
	let max = $derived(Math.max(1, ...punch.flat()));
	const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
	const hourLabel = (h: number) => new Date(2000, 0, 1, h).toLocaleTimeString(undefined, { hour: 'numeric' });

	function show(e: MouseEvent, d: number, h: number) {
		const r = (e.currentTarget as Element).getBoundingClientRect();
		const n = punch[d][h];
		tip = { x: r.left + r.width / 2, y: r.top, title: `${n} commit${n === 1 ? '' : 's'}`, sub: `${days[d]} · ${hourLabel(h)}–${hourLabel((h + 1) % 24)}` };
	}
</script>

<div class="punch">
	{#each punch as row, d (d)}
		<span class="dl">{days[d]}</span>
		{#each row as n, h (h)}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="slot" onmouseenter={(e) => show(e, d, h)} onmouseleave={() => (tip = null)}>
				{#if n}<i style:--s={0.3 + 0.7 * Math.sqrt(n / max)}></i>{:else}<i class="z"></i>{/if}
			</div>
		{/each}
	{/each}
	<span></span>
	{#each { length: 24 } as _, h (h)}<span class="hl">{h % 6 === 0 ? hourLabel(h) : ''}</span>{/each}
</div>
<Tip {tip} />

<style>
	.punch { display: grid; grid-template-columns: 30px repeat(24, minmax(10px, 1fr)); row-gap: 2px; align-items: center; }
	.dl, .hl { font-size: 11px; color: var(--text-3); white-space: nowrap; }
	.hl { padding-top: 4px; }
	.slot { height: 18px; display: grid; place-items: center; }
	.slot i { width: calc(14px * var(--s)); height: calc(14px * var(--s)); border-radius: 50%; background: var(--accent); }
	.slot i.z { width: 3px; height: 3px; background: var(--border-strong); }
	.slot:hover i { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--text); }
</style>
