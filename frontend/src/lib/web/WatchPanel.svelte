<script lang="ts">
	import { Eye, RefreshCw, TrendingDown, TrendingUp } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fullDate, relTime } from '#lib/util.ts';
	import { INTERVALS, MODE_LABEL, MODES, changeText, priceDirection, type Monitor } from './types.ts';

	interface Updated { monitor: Monitor; versions: number }
	let { id, monitor, onupdate }: { id: string; monitor: Monitor; onupdate: (d: Updated) => void } = $props();

	let busy = $state(false);

	async function patch(body: Record<string, unknown>) {
		busy = true;
		try {
			onupdate(await api.patch<Updated>(`/web/${id}`, body));
		} catch (e) {
			ui.error(e);
		}
		busy = false;
	}

	async function checkNow() {
		busy = true;
		const before = monitor.unseen;
		try {
			const d = await api.post<Updated>(`/web/${id}/check`);
			onupdate(d);
			if (d.monitor.error) ui.toast(d.monitor.error, { kind: 'error' });
			else ui.toast(d.monitor.unseen > before ? changeText(d.monitor.last_change) || 'Found a change' : 'No changes since the last check');
		} catch (e) {
			ui.error(e);
		}
		busy = false;
	}

	let lc = $derived(monitor.last_change);
	let dir = $derived(priceDirection(lc));
	let prices = $derived(monitor.price_history.map((p) => p.amount));
	let low = $derived(prices.length > 1 ? monitor.price_history.reduce((a, b) => (b.amount < a.amount ? b : a)) : null);
	let high = $derived(prices.length > 1 ? monitor.price_history.reduce((a, b) => (b.amount > a.amount ? b : a)) : null);
</script>

<div class="box watch" class:on={monitor.enabled}>
	<label class="toggle">
		<input type="checkbox" checked={monitor.enabled} disabled={busy} onchange={(e) => patch({ monitor_enabled: e.currentTarget.checked })} />
		<Eye size={14} /><b>Watch for changes</b>
		{#if busy}<RefreshCw size={12} class="spin faint" />{/if}
	</label>

	{#if monitor.enabled}
		<div class="row">
			<select value={monitor.mode} disabled={busy} aria-label="What to watch" onchange={(e) => patch({ monitor_mode: e.currentTarget.value })}>
				{#each MODES as [v, label] (v)}<option value={v}>{label}</option>{/each}
			</select>
			<select value={monitor.interval} disabled={busy} aria-label="How often" onchange={(e) => patch({ monitor_interval: +e.currentTarget.value })}>
				{#each INTERVALS as [v, label] (v)}<option value={v}>{label}</option>{/each}
				{#if !INTERVALS.some(([v]) => v === monitor.interval)}<option value={monitor.interval}>Every {monitor.interval} min</option>{/if}
			</select>
		</div>
		<label class="check">
			<input type="checkbox" checked={monitor.archive} onchange={(e) => patch({ monitor_archive: e.currentTarget.checked })} />
			Save a snapshot to history on every change
		</label>

		<div class="faint small">
			{#if monitor.resolved_mode}Watching {MODE_LABEL[monitor.resolved_mode]}{monitor.mode === 'auto' ? ' (picked automatically)' : ''}{/if}
			{#if monitor.last_checked_at} · checked <span title={fullDate(monitor.last_checked_at)}>{relTime(monitor.last_checked_at)}</span>{/if}
			{#if monitor.next_check_at} · next <span title={fullDate(monitor.next_check_at)}>{relTime(monitor.next_check_at)}</span>{/if}
		</div>
		{#if monitor.feed_url}<div class="faint small truncate" title={monitor.feed_url}>Feed: {monitor.feed_url.replace(/^https?:\/\/(www\.)?/, '')}</div>{/if}
		{#if monitor.error}<div class="warn small">{monitor.error}</div>{/if}

		{#if monitor.resolved_mode === 'price' && monitor.price}
			<div class="price">
				<b>{monitor.price.display}</b>
				{#if dir === 'down'}<span class="down"><TrendingDown size={14} />was {lc?.type === 'price' ? lc.old.display : ''}</span>
				{:else if dir === 'up'}<span class="up"><TrendingUp size={14} />was {lc?.type === 'price' ? lc.old.display : ''}</span>{/if}
			</div>
			{#if low && high && low.amount !== high.amount}
				<div class="faint small">Lowest {low.display} ({relTime(low.at)}) · highest {high.display} ({relTime(high.at)})</div>
			{/if}
			{#if monitor.price.source === 'text'}<div class="faint small">Read from the page's text; the site gives no product data.</div>{/if}
		{/if}

		{#if lc}
			<div class="change" class:fresh={monitor.unseen > 0}>
				<div class="small"><b>{changeText(lc)}</b> <span class="faint">· {relTime(lc.at)}</span></div>
				{#if lc.type === 'posts'}
					<ul>{#each lc.added.slice(0, 6) as p, i (i)}<li>{#if p.url}<a href={p.url} target="_blank" rel="noopener noreferrer">{p.title || p.url}</a>{:else}{p.title}{/if}</li>{/each}</ul>
				{:else if lc.type === 'content' && lc.snippets.length}
					<ul class="snips">{#each lc.snippets as s, i (i)}<li>{s}</li>{/each}</ul>
				{/if}
			</div>
		{/if}

		{#if monitor.resolved_mode === 'posts' && monitor.latest.length && !(lc?.type === 'posts')}
			<div class="small faint">Latest on the page</div>
			<ul class="latest">{#each monitor.latest.slice(0, 5) as p, i (i)}<li>{#if p.url}<a href={p.url} target="_blank" rel="noopener noreferrer">{p.title || p.url}</a>{:else}{p.title}{/if}</li>{/each}</ul>
		{/if}

		<div class="row"><button class="btn" disabled={busy} onclick={checkNow}><RefreshCw size={13} />Check now</button></div>
	{:else}
		<p class="faint small">Kern fetches the page on a schedule and flags new posts, price changes or edits, saving each version to the history.</p>
	{/if}
</div>

<style>
	.box { display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
	.watch.on { border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }
	.toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13.5px; color: var(--text); }
	.check { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
	.row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
	select { border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 4px 6px; font: inherit; font-size: 13px; background: var(--surface); color: var(--text); flex: 1; min-width: 0; }
	.small { font-size: 12.5px; }
	p { margin: 0; }
	.warn { padding: 6px 8px; border-radius: 6px; background: color-mix(in srgb, var(--c-orange, #d9822b) 15%, transparent); }
	.price { display: flex; align-items: baseline; gap: 10px; }
	.price b { font-size: 20px; font-variant-numeric: tabular-nums; }
	.price span { display: inline-flex; align-items: center; gap: 3px; font-size: 12.5px; }
	.down { color: var(--c-green, #2e8b57); }
	.up { color: var(--c-red, #c0392b); }
	.change { padding: 8px; border-radius: 6px; background: var(--surface); border: 1px solid var(--border); }
	.change.fresh { border-color: var(--accent); }
	ul { margin: 4px 0 0; padding-left: 18px; font-size: 13px; display: flex; flex-direction: column; gap: 2px; }
	.snips li { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
	a { color: var(--text); text-decoration: underline; text-decoration-color: var(--border-strong); }
	a:hover { text-decoration-color: currentColor; }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
</style>
