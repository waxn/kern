<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Layers, Pencil, Plus, Search, Trash2 } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { counts, tzo } from '#lib/learn/util.svelte.ts';
	import { download, importFiles } from '#lib/data/download.ts';
	import AiButton from '#lib/ai/AiButton.svelte';
	import AiCardsDialog from '#lib/ai/AiCardsDialog.svelte';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Card, CardStats, Deck, Note } from '#lib/types.ts';
	import { relTime } from '#lib/util.ts';

	let ankiInput = $state<HTMLInputElement>();
	let aiOpen = $state(false);
	let tab = $derived(page.url.searchParams.get('tab') === 'browse' ? 'browse' : 'overview');
	let stats = $state<CardStats | null>(null);
	let decks = $state<Deck[]>([]);

	// browse
	let list = $state<Card[]>([]);
	let total = $state(0);
	let query = $state('');
	let deckFilter = $state('');
	let stateFilter = $state('');
	let selected = $state<string[]>([]);
	let loadingList = $state(false);

	async function loadOverview() {
		try {
			[stats, decks] = await Promise.all([api.get<CardStats>(`/cards/stats?tzo=${tzo()}`), api.get<Deck[]>(`/decks?tzo=${tzo()}`)]);
		} catch (e) {
			ui.error(e);
		}
	}

	let seq = 0;
	async function loadList() {
		const mine = ++seq;
		loadingList = true;
		try {
			const r = await api.get<{ total: number; cards: Card[] }>('/cards' + qs({ q: query.trim(), deck: deckFilter, state: stateFilter, limit: 300 }));
			if (mine !== seq) return;
			list = r.cards;
			total = r.total;
			selected = selected.filter((id) => r.cards.some((c) => c.id === id));
		} catch (e) {
			ui.error(e);
		} finally {
			if (mine === seq) loadingList = false;
		}
	}

	onMount(() => {
		loadOverview();
		const note = page.url.searchParams.get('note');
		if (note) api.get<Note>(`/notes/${note}`).then((n) => (ui.cardEditor = { note: n, onsaved: refresh })).catch(() => {});
	});

	$effect(() => {
		if (tab !== 'browse') return;
		void query; void deckFilter; void stateFilter;
		const t = setTimeout(loadList, 150);
		return () => clearTimeout(t);
	});

	function refresh() {
		loadOverview();
		if (tab === 'browse') loadList();
		counts.refresh();
	}

	function newCard() {
		ui.cardEditor = { init: deckFilter && deckFilter !== 'none' ? { deck: deckFilter } : {}, onsaved: refresh };
	}

	async function editCard(c: Card) {
		try {
			ui.cardEditor = { note: await api.get<Note>(`/notes/${c.note}`), onsaved: refresh };
		} catch (e) {
			ui.error(e);
		}
	}

	async function bulk(action: string, extra: Record<string, any> = {}) {
		if (!selected.length) return;
		if (action === 'delete') {
			const ok = await ui.confirm({
				title: `Delete ${selected.length} ${selected.length === 1 ? 'card' : 'cards'}?`,
				message: 'Their review history is deleted too. Cards made from page text stop until you edit that text again.',
				confirmLabel: 'Delete', danger: true
			});
			if (!ok) return;
		}
		if (action === 'reset' && !(await ui.confirm({ title: 'Reset progress?', message: 'The selected cards become new again.', confirmLabel: 'Reset', danger: true }))) return;
		await api.post('/cards/bulk', { ids: selected, action, ...extra }).catch((e) => ui.error(e));
		if (action === 'delete') selected = [];
		refresh();
	}

	async function newDeck() {
		const name = prompt('Deck name')?.trim();
		if (!name) return;
		await api.post('/decks', { name }).catch((e) => ui.error(e));
		loadOverview();
	}

	function deckMenu(e: MouseEvent, d: Deck) {
		if (d.id === 'none') return;
		ui.openMenu(e, [
			{ label: 'Rename', icon: Pencil, onSelect: async () => { const name = prompt('Deck name', d.name)?.trim(); if (name) { await api.patch(`/decks/${d.id}`, { name }).catch((err) => ui.error(err)); loadOverview(); } } },
			{ label: 'Delete deck', icon: Trash2, danger: true, onSelect: async () => {
				if (!(await ui.confirm({ title: `Delete deck “${d.name}”?`, message: 'Its cards move to the Default deck. No cards are deleted.', confirmLabel: 'Delete deck', danger: true }))) return;
				await api.del(`/decks/${d.id}`).catch((err) => ui.error(err));
				loadOverview();
			} }
		]);
	}

	let deckName = (id: string | null) => (id ? decks.find((d) => d.id === id)?.name ?? '—' : 'Default');
	const strip = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');

	// ----- charts
	let forecastMax = $derived(Math.max(1, ...(stats?.forecast ?? [0])));
	let heat = $derived.by(() => {
		const days: { date: string; n: number }[] = [];
		const end = new Date();
		const start = new Date(end);
		start.setDate(start.getDate() - 7 * 25 - end.getDay());
		for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
			days.push({ date: key, n: stats?.history[key] ?? 0 });
		}
		return days;
	});
	let heatMax = $derived(Math.max(1, ...heat.map((d) => d.n)));
	let streak = $derived.by(() => {
		let n = 0;
		for (let i = heat.length - 1; i >= 0; i--) {
			if (heat[i].n) n++;
			else if (i !== heat.length - 1) break;
		}
		return n;
	});
	let totalCards = $derived(stats ? Object.values(stats.counts).reduce((a, b) => a + b, 0) : 0);
	let studyCount = $derived(stats ? stats.due_today + stats.new_available : 0);

	const STATE_LABEL: Record<string, string> = { new: 'New', learning: 'Learning', review: 'Review', relearning: 'Relearning' };
	function dueLabel(c: Card) {
		if (c.suspended) return 'Suspended';
		if (c.state === 'new') return 'New';
		if (!c.due) return '';
		const ms = new Date(c.due).getTime() - Date.now();
		return ms <= 0 ? 'Due now' : 'Due ' + relTime(c.due);
	}
</script>

<div class="page-scroll">
	<div class="page wide">
		<div class="titlebar">
			<h1>Flashcards</h1>
			<div class="tabs">
				<button class:on={tab === 'overview'} onclick={() => goto('/cards')}>Overview</button>
				<button class:on={tab === 'browse'} onclick={() => goto('/cards?tab=browse')}>Browse</button>
			</div>
			<span class="grow"></span>
			<input type="file" hidden accept=".apkg,.csv,.zip" bind:this={ankiInput} onchange={async (e) => { const f = [...(e.currentTarget.files ?? [])]; e.currentTarget.value = ''; if (f.length && (await importFiles(f))) refresh(); }} />
			<button class="btn ghost" onclick={(e) => ui.menuBelow(e.currentTarget, [
				{ label: 'Import Anki deck (.apkg)…', onSelect: () => ankiInput?.click() },
				{ separator: true },
				{ label: 'Export all as CSV', onSelect: () => download('/export/cards?as=csv') },
				{ label: 'Export all for Anki (.apkg)', onSelect: () => download('/export/cards?as=apkg') },
				...decks.filter((d) => d.total).map((d) => ({ label: `Export “${d.name}” for Anki`, onSelect: () => download(`/export/cards?as=apkg&deck=${d.id}`) }))
			])}>Import / export</button>
			<AiButton title="Generate flashcards with AI" onclick={() => (aiOpen = true)} />
			<button class="btn" onclick={newCard}><Plus size={14} />New card</button>
			<button class="btn primary" disabled={!studyCount} onclick={() => goto('/review')}>Study now{#if studyCount} · {studyCount}{/if}</button>
		</div>

		{#if tab === 'overview'}
			<p class="lede">Write <code>Question :: Answer</code>, <code>Term ;; Definition</code> or <code>{'{{cloze}}'}</code> in any page to make cards that stay linked to your notes, or add them here.</p>
			{#if stats}
				<div class="tiles">
					<div class="tile"><span>Due today</span><b>{stats.due_today}</b>{#if stats.due_total > stats.due_today}<em>{stats.due_total - stats.due_today} over the daily limit</em>{/if}</div>
					<div class="tile"><span>New available</span><b>{stats.new_available}</b><em>{stats.counts.new} new in total</em></div>
					<div class="tile"><span>Reviewed today</span><b>{stats.reviewed_today}</b><em>{Math.round(stats.time_today_ms / 60000)} min</em></div>
					<div class="tile"><span>Recall</span><b>{stats.accuracy_30d ?? '—'}{#if stats.accuracy_30d !== null}%{/if}</b><em>last 30 days{#if stats.accuracy_today !== null} · {stats.accuracy_today}% today{/if}</em></div>
					<div class="tile"><span>Streak</span><b>{streak}</b><em>{streak === 1 ? 'day' : 'days'} in a row</em></div>
				</div>

				<div class="grid2">
					<section>
						<div class="section-title">Decks</div>
						<div class="decks">
							{#each decks as d (d.id)}
								<div class="deck" role="row" oncontextmenu={(e) => deckMenu(e, d)}>
									<Layers size={14} class="faint" />
									<span class="name truncate">{d.name}</span>
									<span class="num due" title="Due">{d.due}</span>
									<span class="num new" title="New">{d.new}</span>
									<span class="num faint" title="Total">{d.total}</span>
									<button class="btn" disabled={!d.due && !d.new} onclick={() => goto(`/review?deck=${d.id}`)}>Study</button>
								</div>
							{:else}
								<div class="empty"><b>No cards yet</b>Add one, or write <code>::</code> in a page.</div>
							{/each}
							<button class="btn ghost" onclick={newDeck}><Plus size={13} />New deck</button>
						</div>

						<div class="section-title">Study by page or tag</div>
						<div class="filters">
							<select class="input" onchange={(e) => { if (e.currentTarget.value) goto(`/review?doc=${e.currentTarget.value}`); }}>
								<option value="">A page and its sub-pages…</option>
								{#each Object.values(ws.docs).filter((d) => !d.entry_of).sort((a, b) => (a.title || '').localeCompare(b.title || '')) as d (d.id)}
									<option value={d.id}>{d.title || 'Untitled'}</option>
								{/each}
							</select>
							<select class="input" onchange={(e) => { if (e.currentTarget.value) goto(`/review?tag=${e.currentTarget.value}`); }}>
								<option value="">Pages with a tag…</option>
								{#each ws.tags as t (t.id)}<option value={t.id}>#{t.name}</option>{/each}
							</select>
						</div>
					</section>

					<section>
						<div class="section-title">Upcoming reviews · next 30 days</div>
						<div class="forecast" role="img" aria-label="Reviews due per day for the next 30 days">
							{#each stats.forecast as n, i (i)}
								<div class="col" title="{i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : `In ${i} days`}: {n}">
									<i style:height="{(n / forecastMax) * 100}%"></i>
								</div>
							{/each}
						</div>
						<div class="axis faint"><span>Today</span><span>+15d</span><span>+30d</span></div>

						<div class="section-title">Activity · last 26 weeks</div>
						<div class="heat" role="img" aria-label="Reviews per day">
							{#each heat as d (d.date)}
								<i title="{d.date}: {d.n} reviews" style:opacity={d.n ? 0.25 + 0.75 * (d.n / heatMax) : 1} class:on={d.n > 0}></i>
							{/each}
						</div>

						<div class="section-title">Cards · {totalCards}</div>
						<div class="states">
							{#each Object.entries(stats.counts) as [s, n] (s)}
								<span><i class="dot {s}"></i>{STATE_LABEL[s]} <b>{n}</b></span>
							{/each}
							{#if stats.suspended}<span><i class="dot susp"></i>Suspended <b>{stats.suspended}</b></span>{/if}
						</div>
					</section>
				</div>
			{/if}
		{:else}
			<div class="bbar">
				<div class="search"><Search size={14} class="faint" /><input bind:value={query} placeholder="Search cards…" /></div>
				<select class="input" bind:value={deckFilter}>
					<option value="">All decks</option><option value="none">Default</option>
					{#each decks.filter((d) => d.id !== 'none') as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
				</select>
				<select class="input" bind:value={stateFilter}>
					<option value="">Any state</option><option value="due">Due</option><option value="new">New</option>
					<option value="learning">Learning</option><option value="review">Review</option><option value="suspended">Suspended</option>
				</select>
				<span class="faint">{total} {total === 1 ? 'card' : 'cards'}{loadingList ? ' …' : ''}</span>
			</div>
			{#if selected.length}
				<div class="selbar">
					<b>{selected.length} selected</b>
					<button class="btn ghost" onclick={() => bulk('suspend')}>Suspend</button>
					<button class="btn ghost" onclick={() => bulk('unsuspend')}>Unsuspend</button>
					<button class="btn ghost" onclick={() => bulk('reset')}>Reset progress</button>
					<select class="input" onchange={(e) => { if (e.currentTarget.value) bulk('deck', { deck: e.currentTarget.value }); e.currentTarget.value = ''; }}>
						<option value="">Move to deck…</option><option value="none">Default</option>
						{#each decks.filter((d) => d.id !== 'none') as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
					</select>
					<span class="grow"></span>
					<button class="btn ghost danger" onclick={() => bulk('delete')}><Trash2 size={13} />Delete</button>
				</div>
			{/if}
			<div class="table">
				<div class="tr th">
					<input type="checkbox" checked={list.length > 0 && selected.length === list.length} onchange={(e) => (selected = e.currentTarget.checked ? list.map((c) => c.id) : [])} />
					<span>Card</span><span>Type</span><span>Deck</span><span>Status</span><span>Reviews</span><span>Source</span>
				</div>
				{#each list as c (c.id)}
					<div class="tr" class:susp={c.suspended} class:on={selected.includes(c.id)}>
						<input type="checkbox" checked={selected.includes(c.id)} onchange={() => (selected = selected.includes(c.id) ? selected.filter((x) => x !== c.id) : [...selected, c.id])} />
						<button class="front truncate" onclick={() => editCard(c)}>{c.kind === 'occlusion' ? `Image region ${c.ordinal + 1}` : strip(c.front) || '(empty)'}</button>
						<span class="faint">{c.kind}{c.kind === 'cloze' || c.kind === 'concept' ? ` ${c.ordinal + 1}` : ''}</span>
						<span class="truncate">{deckName(c.deck)}</span>
						<span>{dueLabel(c)}</span>
						<span class="faint">{c.reps}{#if c.lapses} · {c.lapses} lapses{/if}</span>
						{#if c.document}
							<a class="truncate" href="/doc/{c.document}" onclick={(e) => { e.preventDefault(); open(`/doc/${c.document}${c.block ? '#' + c.block : ''}`, e); }}>{c.doc_title || 'Untitled'}</a>
						{:else}<span class="faint">—</span>{/if}
					</div>
				{:else}
					<div class="empty">{query || deckFilter || stateFilter ? 'No cards match.' : 'No cards yet.'}</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

{#if aiOpen}<AiCardsDialog onclose={() => (aiOpen = false)} onsaved={refresh} />{/if}

<style>
	.wide { max-width: 1100px; }
	.titlebar { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; flex-wrap: wrap; }
	.titlebar h1 { margin: 0; }
	.tabs { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.tabs button { padding: 3px 12px; border-radius: 4px; color: var(--text-2); }
	.tabs button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.grow { flex: 1; }
	code { font-family: var(--font-mono); font-size: 0.9em; background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
	.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
	.tile { display: flex; flex-direction: column; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; }
	.tile span { font-size: 12px; color: var(--text-3); }
	.tile b { font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }
	.tile em { font-style: normal; font-size: 11.5px; color: var(--text-3); }
	.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; }
	.decks { display: flex; flex-direction: column; gap: 4px; align-items: stretch; }
	.deck { display: flex; align-items: center; gap: 10px; height: 38px; padding: 0 6px 0 10px; border: 1px solid var(--border); border-radius: var(--radius); }
	.deck .name { flex: 1; font-weight: 550; }
	.num { min-width: 28px; text-align: right; font-variant-numeric: tabular-nums; font-size: 12.5px; }
	.num.due { color: var(--c-green); } .num.new { color: var(--c-blue); }
	.decks > .btn { align-self: flex-start; }
	.filters { display: flex; flex-direction: column; gap: 6px; }
	.forecast { display: flex; align-items: flex-end; gap: 2px; height: 90px; padding-bottom: 1px; border-bottom: 1px solid var(--border-strong); }
	.col { flex: 1; height: 100%; display: flex; align-items: flex-end; }
	.col i { width: 100%; min-height: 1px; border-radius: 2px 2px 0 0; background: var(--accent); }
	.axis { display: flex; justify-content: space-between; font-size: 11px; margin-top: 3px; }
	.heat { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 11px); gap: 3px; }
	.heat i { width: 11px; height: 11px; border-radius: 2px; background: var(--surface-2); }
	.heat i.on { background: var(--c-green); }
	.states { display: flex; flex-wrap: wrap; gap: 14px; color: var(--text-2); }
	.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
	.dot.new { background: var(--c-blue); } .dot.learning, .dot.relearning { background: var(--c-orange); } .dot.review { background: var(--c-green); } .dot.susp { background: var(--text-3); }
	.bbar { display: flex; align-items: center; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
	.search { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 180px; height: 28px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); }
	.search input { flex: 1; border: 0; outline: 0; background: none; }
	.selbar { display: flex; align-items: center; gap: 6px; padding: 4px 8px; margin-bottom: 6px; border-radius: var(--radius); background: var(--surface-2); flex-wrap: wrap; }
	.danger { color: var(--danger); }
	.table { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.tr { display: grid; grid-template-columns: 24px minmax(0, 3fr) 90px minmax(0, 1fr) 120px 110px minmax(0, 1.4fr); align-items: center; gap: 10px; min-height: 34px; padding: 0 10px; border-top: 1px solid var(--border); font-size: 13px; }
	.tr:first-child { border-top: 0; }
	.tr.th { color: var(--text-3); font-size: 12px; font-weight: 500; }
	.tr:not(.th):hover { background: var(--hover); }
	.tr.on { background: color-mix(in srgb, var(--accent) 10%, transparent); }
	.tr.susp { opacity: 0.55; }
	.tr input { accent-color: var(--accent); }
	.front { text-align: left; }
	.front:hover { color: var(--accent); }
	.tr a { text-decoration: none; color: var(--text-2); }
	.tr a:hover { color: var(--accent); }
	@media (max-width: 860px) {
		.grid2 { grid-template-columns: 1fr; }
		.tr { grid-template-columns: 24px minmax(0, 1fr) 90px; }
		.tr > :nth-child(n + 4) { display: none; }
	}
</style>
