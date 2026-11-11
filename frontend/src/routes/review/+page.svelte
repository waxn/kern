<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ArrowUpRight, Pause, Pencil, Undo2, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import CardFace from '#lib/learn/CardFace.svelte';
	import { counts, fmtInterval, tzo } from '#lib/learn/util.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Card, CardStats, Note } from '#lib/types.ts';

	interface Queue { card: Card | null; counts: { learning: number; review: number; new: number }; next_learning: string | null }

	let q = $state<Queue | null>(null);
	let revealed = $state(false);
	let busy = $state(false);
	let shownAt = 0;
	let done = $state(0);
	let showIntervals = $state(true);
	let scope = $derived({ deck: page.url.searchParams.get('deck'), doc: page.url.searchParams.get('doc'), tag: page.url.searchParams.get('tag') });
	let scopeLabel = $derived(
		scope.doc ? `Cards from “${ws.docs[scope.doc]?.title || 'Untitled'}”` : scope.tag ? `Cards tagged #${ws.tagMap[scope.tag]?.name ?? ''}` : scope.deck ? 'Deck' : 'All cards'
	);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function load() {
		try {
			q = await api.get<Queue>('/cards/queue' + qs({ tzo: tzo(), ...scope }));
			revealed = false;
			shownAt = performance.now();
			clearTimeout(timer);
			if (!q.card && q.next_learning) {
				// Come back automatically when the next learning card is due.
				const wait = new Date(q.next_learning).getTime() - Date.now();
				if (wait < 30 * 60_000) timer = setTimeout(load, Math.max(1000, wait + 500));
			}
		} catch (e) {
			ui.error(e);
		}
	}

	onMount(() => {
		load();
		api.get<CardStats>(`/cards/stats?tzo=${tzo()}`).then((s) => (showIntervals = s.settings.show_intervals)).catch(() => {});
		return () => {
			clearTimeout(timer);
			counts.refresh();
		};
	});

	async function rate(rating: number) {
		if (!q?.card || !revealed || busy) return;
		busy = true;
		try {
			await api.post(`/cards/${q.card.id}/review`, { rating, duration_ms: Math.round(performance.now() - shownAt) });
			done++;
			await load();
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	async function undo() {
		try {
			await api.post('/cards/undo');
			done = Math.max(0, done - 1);
			await load();
			ui.toast('Last review undone');
		} catch (e) {
			ui.error(e);
		}
	}

	async function suspend() {
		if (!q?.card) return;
		await api.post('/cards/bulk', { ids: [q.card.id], action: 'suspend' }).catch((e) => ui.error(e));
		ui.toast('Card suspended. Find it again in the card browser.');
		load();
	}

	async function edit() {
		if (!q?.card) return;
		const note = await api.get<Note>(`/notes/${q.card.note}`);
		ui.cardEditor = { note, onsaved: load };
	}

	function exit() {
		goto('/cards');
	}

	function key(e: KeyboardEvent) {
		if (ui.cardEditor || ui.confirmState || ui.searchOpen) return;
		if ((e.target as HTMLElement).closest('input, textarea, [contenteditable]')) return;
		if (e.key === 'Escape') return exit();
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') return e.preventDefault(), void undo();
		if (!q?.card) return;
		if (!revealed && (e.key === ' ' || e.key === 'Enter')) {
			e.preventDefault();
			revealed = true;
			return;
		}
		if (revealed && ['1', '2', '3', '4'].includes(e.key)) return e.preventDefault(), void rate(Number(e.key));
		if (revealed && (e.key === ' ' || e.key === 'Enter')) return e.preventDefault(), void rate(3);
		if (e.key.toLowerCase() === 'e') return e.preventDefault(), void edit();
	}

	const buttons: [number, string, string][] = [[1, 'Again', 'red'], [2, 'Hard', 'orange'], [3, 'Good', 'green'], [4, 'Easy', 'blue']];
	let remaining = $derived(q ? q.counts.learning + q.counts.review + q.counts.new : 0);
	let progress = $derived(done + remaining ? (100 * done) / (done + remaining) : 0);
</script>

<svelte:window onkeydown={key} />

<div class="review">
	<header>
		<button class="icon-btn" title="Leave review (Esc)" onclick={exit}><X size={16} /></button>
		<span class="scope">{scopeLabel}</span>
		{#if q}
			<span class="counts" title="New · Learning · Review">
				<b class="n">{q.counts.new}</b><b class="l">{q.counts.learning}</b><b class="r">{q.counts.review}</b>
			</span>
		{/if}
		<span class="grow"></span>
		<button class="icon-btn" title="Undo last review (Ctrl+Z)" disabled={!done} onclick={undo}><Undo2 size={15} /></button>
		{#if q?.card}
			<button class="icon-btn" title="Edit card (E)" onclick={edit}><Pencil size={15} /></button>
			<button class="icon-btn" title="Suspend card" onclick={suspend}><Pause size={15} /></button>
		{/if}
	</header>
	<div class="bar"><i style:width="{progress}%"></i></div>

	<main>
		{#if !q}
			<p class="faint">Loading…</p>
		{:else if !q.card}
			<div class="finished">
				<div class="big">✓</div>
				<h2>{done ? `Done for now — ${done} ${done === 1 ? 'card' : 'cards'} reviewed` : 'Nothing to review'}</h2>
				{#if q.next_learning}
					<p class="muted">Cards you are learning come back at {new Date(q.next_learning).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}. Stay here and they appear automatically.</p>
				{:else}
					<p class="muted">You are up to date. New reviews will be ready tomorrow.</p>
				{/if}
				<button class="btn primary" onclick={exit}>Back to flashcards</button>
			</div>
		{:else}
			{@const c = q.card}
			<div class="card">
				<span class="kind chip" data-c={c.state === 'new' ? 'blue' : c.state === 'review' ? 'green' : 'orange'}>{c.state === 'new' ? 'New' : c.state === 'review' ? 'Review' : 'Learning'}</span>
				<div class="side">
					<CardFace html={c.kind === 'occlusion' ? '' : c.front} image={c.image ?? ''} regions={c.regions ?? []} target={c.ordinal} reveal={revealed && c.kind === 'occlusion'} />
				</div>
				{#if revealed}
					{#if c.kind !== 'occlusion'}
						<hr />
						<div class="side answer"><CardFace html={c.back} /></div>
					{:else if c.front}
						<div class="side answer"><CardFace html={c.front} size="small" /></div>
					{/if}
				{/if}
				{#if c.document}
					<a class="src" href="/doc/{c.document}{c.block ? '#' + c.block : ''}" onclick={(e) => { e.preventDefault(); open(`/doc/${c.document}${c.block ? '#' + c.block : ''}`, e); }}>
						{c.doc_title || 'Untitled'} <ArrowUpRight size={12} />
					</a>
				{/if}
			</div>
		{/if}
	</main>

	{#if q?.card}
		<footer>
			{#if !revealed}
				<button class="btn primary reveal" onclick={() => (revealed = true)}>Show answer <kbd>Space</kbd></button>
			{:else}
				<div class="rates">
					{#each buttons as [r, label, color] (r)}
						<button class="rate" data-c={color} disabled={busy} onclick={() => rate(r)}>
							<b>{label}</b>
							{#if showIntervals}<span>{fmtInterval(q.card.intervals?.[r])}</span>{/if}
							<kbd>{r}</kbd>
						</button>
					{/each}
				</div>
			{/if}
		</footer>
	{/if}
</div>

<style>
	.review { position: fixed; inset: 0; z-index: 650; display: flex; flex-direction: column; background: var(--bg); }
	header { display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 12px; }
	.scope { color: var(--text-2); }
	.counts { display: flex; gap: 8px; font-variant-numeric: tabular-nums; }
	.counts .n { color: var(--c-blue); } .counts .l { color: var(--c-orange); } .counts .r { color: var(--c-green); }
	.grow { flex: 1; }
	.icon-btn:disabled { opacity: 0.35; }
	.bar { height: 2px; background: var(--border); }
	.bar i { display: block; height: 100%; background: var(--accent); transition: width 0.3s var(--ease); }
	main { flex: 1; overflow-y: auto; display: flex; justify-content: center; padding: 6vh 20px 20px; }
	.card { position: relative; width: min(720px, 100%); text-align: center; }
	.kind { position: absolute; top: -30px; left: 50%; transform: translateX(-50%); }
	.side { padding: 10px 0; }
	hr { border: 0; border-top: 1px solid var(--border-strong); margin: 18px auto; width: 70%; }
	.answer { animation: fade 0.18s; }
	.src { display: inline-flex; align-items: center; gap: 3px; margin-top: 28px; color: var(--text-3); font-size: 12.5px; text-decoration: none; }
	.src:hover { color: var(--accent); }
	footer { flex: none; display: flex; justify-content: center; padding: 16px 16px 26px; border-top: 1px solid var(--border); }
	.reveal { height: 40px; padding: 0 28px; font-size: 14.5px; }
	.reveal kbd { margin-left: 6px; border-color: rgba(0, 0, 0, 0.25); background: none; color: inherit; }
	.rates { display: grid; grid-template-columns: repeat(4, minmax(0, 120px)); gap: 8px; width: min(520px, 100%); }
	.rate { display: flex; flex-direction: column; align-items: center; gap: 1px; padding: 8px 6px; border-radius: var(--radius); border: 1px solid color-mix(in srgb, var(--chip) 45%, var(--border)); background: color-mix(in srgb, var(--chip) 10%, var(--surface)); }
	.rate:hover { background: color-mix(in srgb, var(--chip) 22%, var(--surface)); }
	.rate b { color: var(--chip); font-weight: 650; }
	.rate span { font-size: 12px; color: var(--text-2); }
	.rate kbd { margin-top: 3px; font-size: 10px; }
	.finished { text-align: center; max-width: 420px; margin-top: 6vh; }
	.big { width: 56px; height: 56px; margin: 0 auto 14px; display: grid; place-items: center; border-radius: 50%; background: color-mix(in srgb, var(--c-green) 20%, transparent); color: var(--c-green); font-size: 26px; }
	.finished h2 { font-size: 18px; margin: 0 0 6px; }
</style>
