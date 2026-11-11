<script lang="ts">
	import { goto } from '$app/navigation';
	import { CircleCheck, Clock, CornerDownLeft, FilePlus, FileText, Hash, Layers, Search, Text } from '@lucide/svelte';
	import { api, qs } from '#lib/api.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { openTab } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { SearchResult, Suggestion } from '#lib/types.ts';
	import { escapeHtml, highlight, mod, modKey } from '#lib/util.ts';

	type Kind = 'all' | 'doc' | 'block' | 'tag' | 'card' | 'task';
	interface Row {
		key: string;
		type: 'doc' | 'block' | 'tag' | 'create' | 'history' | 'card' | 'task';
		group: string;
		title: string; // safe HTML
		sub?: string; // safe HTML
		icon?: string;
		color?: string;
		href?: string;
		query?: string;
	}

	let q = $state('');
	let kind = $state<Kind>('all');
	let rows = $state<Row[]>([]);
	let counts = $state<Record<string, number>>({});
	let sel = $state(0);
	let busy = $state(false);
	let input = $state<HTMLInputElement>();
	let list = $state<HTMLElement>();
	let seq = 0;
	let timer: ReturnType<typeof setTimeout>;

	$effect(() => {
		if (ui.searchOpen) {
			q = ui.searchQuery;
			kind = 'all';
			queueMicrotask(() => input?.select());
		}
	});

	$effect(() => {
		if (!ui.searchOpen) return;
		const query = q.trim();
		const k = kind;
		clearTimeout(timer);
		if (!query) {
			rows = idleRows();
			counts = {};
			sel = 0;
			return;
		}
		timer = setTimeout(() => run(query, k), 110);
	});

	function idleRows(): Row[] {
		const out: Row[] = ws.recents.slice(0, 7).map((d) => ({
			key: 'r' + d.id, type: 'doc', group: 'Recent pages', title: escapeHtml(d.title || 'Untitled'),
			sub: escapeHtml(ws.path(d.id).map((p) => p.title || 'Untitled').join(' / ')), icon: d.icon, href: `/doc/${d.id}`
		}));
		for (const s of prefs.recentSearches.slice(0, 5))
			out.push({ key: 'h' + s, type: 'history', group: 'Recent searches', title: escapeHtml(s), query: s });
		for (const d of ws.favorites.slice(0, 6))
			out.push({ key: 'f' + d.id, type: 'doc', group: 'Favorites', title: escapeHtml(d.title || 'Untitled'), icon: d.icon, href: `/doc/${d.id}` });
		return out;
	}

	async function run(query: string, k: Kind) {
		const mine = ++seq;
		busy = true;
		try {
			const [sug, res] = await Promise.all([
				api.get<Suggestion[]>('/suggest' + qs({ q: query, kinds: 'doc,tag', limit: 6 })),
				api.get<{ results: SearchResult[]; counts: Record<string, number> }>(
					'/search' + qs({ q: query, kind: k === 'all' ? '' : k, limit: 40 })
				)
			]);
			if (mine !== seq) return;
			const out: Row[] = [];
			const seen = new Set<string>();
			const path = (p?: string[]) => escapeHtml((p ?? []).join(' / '));
			if (k === 'all' || k === 'doc') {
				for (const s of sug.filter((s) => s.kind === 'doc')) {
					seen.add(s.id);
					out.push({ key: 'd' + s.id, type: 'doc', group: 'Pages', title: markTitle(s.title || 'Untitled', query), sub: path(s.path), icon: s.icon, href: `/doc/${s.id}` });
				}
				for (const r of res.results.filter((r) => r.kind === 'doc' && !seen.has(r.id)))
					out.push({ key: 'd' + r.id, type: 'doc', group: 'Pages', title: highlight(r.title || 'Untitled'), sub: highlight(r.snippet) || path(r.path), icon: r.icon, href: `/doc/${r.id}` });
			}
			if (k === 'all' || k === 'tag')
				for (const s of sug.filter((s) => s.kind === 'tag'))
					out.push({ key: 't' + s.id, type: 'tag', group: 'Tags', title: markTitle(s.title, query), color: s.color, href: `/tag/${s.id}` });
			if (k === 'all' || k === 'block')
				for (const r of res.results.filter((r) => r.kind === 'block'))
					out.push({
						key: 'b' + r.id, type: 'block', group: 'Content', title: highlight(r.snippet),
						sub: escapeHtml([...(r.path ?? []), r.doc_title || 'Untitled'].join(' / ')), href: `/doc/${r.doc}#${r.id}`
					});
			for (const r of res.results.filter((r) => (k === 'all' || k === r.kind) && (r.kind === 'card' || r.kind === 'task')))
				out.push({
					key: r.kind[0] + r.id, type: r.kind, group: r.kind === 'card' ? 'Flashcards' : 'Tasks',
					title: highlight(r.kind === 'task' ? r.title || r.snippet : r.snippet),
					sub: r.kind === 'task' ? highlight(r.snippet) : escapeHtml(r.doc_title ?? ''),
					href: r.kind === 'card' ? `/cards?tab=browse&note=${r.id}` : `/tasks?view=open&task=${r.id}`
				});
			if (k === 'all' || k === 'doc')
				out.push({ key: 'create', type: 'create', group: 'Actions', title: `Create page “${escapeHtml(query)}”`, query });
			rows = out;
			counts = res.counts;
			sel = 0;
		} catch (e) {
			if (mine === seq) rows = [];
		} finally {
			if (mine === seq) busy = false;
		}
	}

	function markTitle(title: string, query: string): string {
		const i = title.toLowerCase().indexOf(query.toLowerCase());
		if (i < 0) return escapeHtml(title);
		return escapeHtml(title.slice(0, i)) + '<mark>' + escapeHtml(title.slice(i, i + query.length)) + '</mark>' + escapeHtml(title.slice(i + query.length));
	}

	function close() {
		ui.searchOpen = false;
	}

	async function choose(row: Row | undefined, e?: KeyboardEvent | MouseEvent) {
		if (!row) return;
		if (row.type === 'history') {
			q = row.query!;
			input?.focus();
			return;
		}
		const query = q.trim();
		if (query) prefs.recentSearches = [query, ...prefs.recentSearches.filter((s) => s !== query)].slice(0, 8);
		close();
		const newTab = !!e && mod(e);
		if (row.type === 'create') {
			try {
				const doc = await ws.createDoc({ title: row.query });
				newTab ? openTab(`/doc/${doc.id}`) : goto(`/doc/${doc.id}`);
			} catch (err) {
				ui.error(err);
			}
			return;
		}
		newTab ? openTab(row.href!) : goto(row.href!);
	}

	function key(e: KeyboardEvent) {
		if (e.key === 'Escape') close();
		else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			if (!rows.length) return;
			sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
			queueMicrotask(() => list?.querySelector('.row.active')?.scrollIntoView({ block: 'nearest' }));
		} else if (e.key === 'Enter') {
			e.preventDefault();
			choose(rows[sel], e);
		} else if (e.key === 'Tab') {
			e.preventDefault();
			const order: Kind[] = ['all', 'doc', 'block', 'tag', 'card', 'task'];
			kind = order[(order.indexOf(kind) + (e.shiftKey ? order.length - 1 : 1)) % order.length];
		}
	}

	const kinds: [Kind, string][] = [['all', 'All'], ['doc', 'Pages'], ['block', 'Content'], ['tag', 'Tags'], ['card', 'Flashcards'], ['task', 'Tasks']];
</script>

{#if ui.searchOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
	<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && close()}>
		<div class="palette popover" role="dialog" aria-label="Search">
			<div class="bar">
				<Search size={16} class="faint" />
				<input bind:this={input} bind:value={q} placeholder="Search pages, content and tags…" onkeydown={key} spellcheck="false" />
				{#if busy}<span class="faint">…</span>{/if}
			</div>
			{#if q.trim()}
				<div class="kinds">
					{#each kinds as [k, label] (k)}
						<button class:on={kind === k} onclick={() => { kind = k; input?.focus(); }}>
							{label}{#if k !== 'all' && counts[k]}<span>{counts[k]}</span>{/if}
						</button>
					{/each}
				</div>
			{/if}
			<div class="list" bind:this={list}>
				{#each rows as row, i (row.key)}
					{#if i === 0 || rows[i - 1].group !== row.group}<div class="menu-heading">{row.group}</div>{/if}
					<!-- svelte-ignore a11y_mouse_events_have_key_events -->
					<button class="row" class:active={i === sel} onmousemove={() => (sel = i)} onclick={(e) => choose(row, e)}>
						<span class="ico" data-c={row.color || undefined}>
							{#if row.icon}{row.icon}
							{:else if row.type === 'doc'}<FileText size={15} strokeWidth={1.75} />
							{:else if row.type === 'tag'}<Hash size={15} strokeWidth={1.75} />
							{:else if row.type === 'block'}<Text size={15} strokeWidth={1.75} />
							{:else if row.type === 'create'}<FilePlus size={15} strokeWidth={1.75} />
							{:else if row.type === 'card'}<Layers size={15} strokeWidth={1.75} />
							{:else if row.type === 'task'}<CircleCheck size={15} strokeWidth={1.75} />
							{:else}<Clock size={15} strokeWidth={1.75} />{/if}
						</span>
						<span class="body">
							<span class="title truncate">{@html row.title}</span>
							{#if row.sub}<span class="sub truncate">{@html row.sub}</span>{/if}
						</span>
						{#if i === sel}<CornerDownLeft size={13} class="faint" />{/if}
					</button>
				{/each}
				{#if !rows.length}
					<div class="none">{q.trim() ? (busy ? 'Searching…' : 'No results.') : 'Type to search your workspace.'}</div>
				{/if}
			</div>
			<div class="foot">
				<span><kbd>↑</kbd> <kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span>
				<span><kbd>{modKey} ↵</kbd> new tab</span><span><kbd>Tab</kbd> filter</span>
				{#if q.trim()}<button class="all" onclick={() => { close(); goto(`/search?q=${encodeURIComponent(q.trim())}${kind !== 'all' ? '&kind=' + kind : ''}`); }}>All results and save search →</button>{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay { position: fixed; inset: 0; z-index: 800; display: flex; justify-content: center; align-items: flex-start; padding-top: 12vh; background: rgba(0, 0, 0, 0.4); animation: fade 0.1s; }
	.palette { width: min(640px, calc(100vw - 24px)); display: flex; flex-direction: column; max-height: 70vh; overflow: hidden; }
	.bar { display: flex; align-items: center; gap: 10px; padding: 0 14px; height: 46px; border-bottom: 1px solid var(--border); }
	.bar input { flex: 1; border: 0; outline: 0; background: none; font-size: 15px; }
	.kinds { display: flex; gap: 2px; padding: 6px 8px 0; }
	.kinds button { display: flex; gap: 6px; padding: 3px 9px; border-radius: 12px; color: var(--text-2); font-size: 12.5px; }
	.kinds button:hover { background: var(--hover); }
	.kinds button.on { background: var(--active); color: var(--text); }
	.kinds span { color: var(--text-3); }
	.list { flex: 1; overflow-y: auto; padding: 4px 6px 6px; }
	.row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 5px 8px; border-radius: var(--radius-sm); text-align: left; }
	.row.active { background: var(--hover); }
	.ico { flex: none; width: 20px; display: grid; place-items: center; font-size: 15px; color: var(--chip, var(--text-2)); }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.sub { font-size: 12px; color: var(--text-3); }
	.none { padding: 22px; text-align: center; color: var(--text-3); }
	.all { margin-left: auto; color: var(--accent); font-size: 12px; }
	.foot { display: flex; gap: 14px; padding: 7px 14px; border-top: 1px solid var(--border); color: var(--text-3); font-size: 12px; }
	@media (max-width: 760px) { .overlay { padding-top: 8px; } .foot { display: none; } }
</style>
