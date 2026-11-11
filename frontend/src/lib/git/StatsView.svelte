<script lang="ts">
	import { fileSize, relTime } from '#lib/util.ts';
	import Heatmap from './Heatmap.svelte';
	import MonthBars from './MonthBars.svelte';
	import Punchcard from './Punchcard.svelte';
	import Tip, { type TipState } from './Tip.svelte';
	import type { Stats } from './types.ts';

	let { stats }: { stats: Stats } = $props();
	let tip = $state<TipState | null>(null);
	let tableView = $state(false);

	const nf = new Intl.NumberFormat();
	let t = $derived(stats.totals);
	let langBytes = $derived(stats.languages.reduce((n, l) => n + l.bytes, 0) || 1);
	// Long tails fold into "Other" so the bar stays legible.
	let langs = $derived.by(() => {
		const main = stats.languages.filter((l, i) => i < 7 && l.bytes / langBytes >= 0.005);
		const rest = stats.languages.slice(main.length);
		const other = rest.reduce((a, l) => ({ ...a, files: a.files + l.files, bytes: a.bytes + l.bytes, lines: a.lines + l.lines }),
			{ name: 'Other', color: 'var(--text-3)', files: 0, bytes: 0, lines: 0 });
		return other.bytes ? [...main, other] : main;
	});
	let topCommits = $derived(Math.max(1, ...stats.contributors.map((c) => c.commits)));
	let span = $derived.by(() => {
		if (!stats.first_commit || !stats.last_commit) return '';
		const days = Math.round((+new Date(stats.last_commit) - +new Date(stats.first_commit)) / 864e5) + 1;
		return days < 60 ? `${days} day${days === 1 ? '' : 's'}` : days < 730 ? `${Math.round(days / 30.4)} months` : `${(days / 365).toFixed(1)} years`;
	});
	const pct = (n: number) => { const p = (n / langBytes) * 100; return p >= 10 ? p.toFixed(0) + '%' : p.toFixed(1) + '%'; };
	const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase() || '?';
	const hue = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };

	function showLang(e: MouseEvent, l: (typeof langs)[number]) {
		const r = (e.currentTarget as Element).getBoundingClientRect();
		tip = { x: r.left + r.width / 2, y: r.top, title: `${l.name} · ${pct(l.bytes)}`, sub: `${nf.format(l.files)} files · ${nf.format(l.lines)} lines · ${fileSize(l.bytes)}` };
	}
</script>

<div class="tiles">
	<div class="tile"><span class="k">Commits</span><b>{nf.format(t.commits)}</b><span class="faint">{span ? `over ${span}` : ''}</span></div>
	<div class="tile"><span class="k">Lines of code</span><b>{nf.format(t.lines)}</b><span class="faint">{nf.format(t.files)} files</span></div>
	<div class="tile"><span class="k">Contributors</span><b>{nf.format(t.contributors)}</b><span class="faint">{t.active_days} active day{t.active_days === 1 ? '' : 's'}</span></div>
	<div class="tile"><span class="k">Size on disk</span><b>{fileSize(t.size)}</b><span class="faint">{fileSize(t.bytes)} checked out</span></div>
	<div class="tile"><span class="k">Branches · Tags</span><b>{t.branches} · {t.tags}</b><span class="faint">{stats.last_commit ? 'last commit ' + relTime(stats.last_commit + 'T12:00:00') : ''}</span></div>
</div>

<section class="card">
	<h3>Contributions</h3>
	<Heatmap days={stats.heatmap} />
</section>

<div class="two">
	<section class="card">
		<h3>Commits per month</h3>
		{#if stats.months.length}<MonthBars months={stats.months} />{:else}<p class="faint">No commits yet.</p>{/if}
	</section>
	<section class="card">
		<h3>When commits happen</h3>
		<Punchcard punch={stats.punchcard} />
	</section>
</div>

<div class="two">
	<section class="card">
		<div class="h3row">
			<h3>Languages</h3>
			<button class="btn ghost sm" onclick={() => (tableView = !tableView)}>{tableView ? 'Bar' : 'Table'}</button>
		</div>
		{#if !langs.length}
			<p class="faint">No recognised source files.</p>
		{:else if tableView}
			<table class="tbl">
				<thead><tr><th>Language</th><th>Share</th><th>Files</th><th>Lines</th><th>Size</th></tr></thead>
				<tbody>
					{#each langs as l (l.name)}
						<tr><td><i class="dot" style:background={l.color}></i>{l.name}</td><td>{pct(l.bytes)}</td><td>{nf.format(l.files)}</td><td>{nf.format(l.lines)}</td><td>{fileSize(l.bytes)}</td></tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<div class="langbar">
				{#each langs as l (l.name)}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div style:flex-grow={l.bytes} style:background={l.color} onmouseenter={(e) => showLang(e, l)} onmouseleave={() => (tip = null)}></div>
				{/each}
			</div>
			<ul class="legend">
				{#each langs as l (l.name)}
					<li><i class="dot" style:background={l.color}></i><span>{l.name}</span><span class="faint">{pct(l.bytes)}</span></li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="card">
		<h3>Top contributors</h3>
		<ul class="people">
			{#each stats.contributors.slice(0, 8) as c (c.email + c.name)}
				<li>
					<span class="av" style:--h={hue(c.email || c.name)}>{initials(c.name)}</span>
					<div class="who">
						<div class="row"><b class="truncate" title={c.email}>{c.name}</b><span class="faint">{nf.format(c.commits)} commit{c.commits === 1 ? '' : 's'}</span></div>
						<div class="meter"><div style:width="{(c.commits / topCommits) * 100}%"></div></div>
						<div class="row sub"><span class="add">+{nf.format(c.additions)}</span><span class="del">−{nf.format(c.deletions)}</span><span class="faint grow">since {relTime(c.first)}</span></div>
					</div>
				</li>
			{/each}
		</ul>
	</section>
</div>
<Tip {tip} />

<style>
	.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }
	.tile { display: flex; flex-direction: column; gap: 2px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
	.tile .k { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-3); }
	.tile b { font-size: 22px; font-weight: 650; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
	.tile .faint { font-size: 12px; min-height: 1.3em; }
	.card { padding: 14px 16px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: 14px; min-width: 0; }
	h3 { margin: 0 0 12px; font-size: 13px; font-weight: 600; }
	.h3row { display: flex; align-items: baseline; justify-content: space-between; }
	.btn.sm { height: 22px; padding: 0 7px; font-size: 12px; }
	.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 14px; }
	.two .card { margin-bottom: 14px; }
	.langbar { display: flex; gap: 2px; height: 10px; border-radius: 5px; overflow: hidden; margin-bottom: 12px; }
	.langbar div { min-width: 3px; }
	.langbar div:hover { filter: brightness(1.15); }
	.legend { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px 14px; font-size: 13px; }
	.legend li { display: flex; align-items: center; gap: 6px; }
	.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; flex: none; margin-right: 6px; vertical-align: 0; }
	.legend .dot { margin-right: 0; }
	.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
	.tbl th { text-align: left; font-weight: 500; color: var(--text-3); padding: 0 6px 6px 0; }
	.tbl td { padding: 4px 6px 4px 0; border-top: 1px solid var(--border); }
	.people { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
	.people li { display: flex; gap: 10px; align-items: center; }
	.av { width: 30px; height: 30px; flex: none; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 650;
		background: color-mix(in srgb, hsl(var(--h) 55% 55%) 22%, var(--surface-2)); color: hsl(var(--h) 45% 62%); }
	.who { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
	.row { display: flex; gap: 8px; align-items: baseline; justify-content: space-between; font-size: 13px; }
	.row b { font-weight: 550; }
	.row.sub { justify-content: flex-start; font-size: 11.5px; font-variant-numeric: tabular-nums; }
	.row .grow { margin-left: auto; }
	.add { color: var(--c-green); }
	.del { color: var(--c-red); }
	.meter { height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden; }
	.meter div { height: 100%; border-radius: 2px; background: var(--accent); }
</style>
