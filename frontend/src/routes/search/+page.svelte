<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Bookmark, CircleCheck, FileText, Hash, Layers, Search, Text, Trash2 } from '@lucide/svelte';
	import { api, qs } from '#lib/api.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { SearchResult } from '#lib/types.ts';
	import { escapeHtml, highlight, uid } from '#lib/util.ts';

	type Kind = '' | 'doc' | 'block' | 'tag' | 'card' | 'task';
	const kinds: [Kind, string][] = [['', 'All'], ['doc', 'Pages'], ['block', 'Content'], ['tag', 'Tags'], ['card', 'Flashcards'], ['task', 'Tasks']];

	let q = $state(page.url.searchParams.get('q') ?? '');
	let kind = $state<Kind>((page.url.searchParams.get('kind') as Kind) ?? '');
	let results = $state<SearchResult[]>([]);
	let counts = $state<Record<string, number>>({});
	let loading = $state(false);
	let limit = $state(50);
	let seq = 0;

	// Follow the URL when a saved search is opened from the sidebar.
	$effect(() => {
		const uq = page.url.searchParams.get('q') ?? '';
		const uk = (page.url.searchParams.get('kind') as Kind) ?? '';
		if (uq !== q) q = uq;
		if (uk !== kind) kind = uk;
	});

	$effect(() => {
		const query = q.trim();
		const k = kind;
		const l = limit;
		const t = setTimeout(async () => {
			const mine = ++seq;
			if (!query) return void ((results = []), (counts = {}));
			loading = true;
			try {
				const r = await api.get<{ results: SearchResult[]; counts: Record<string, number> }>('/search' + qs({ q: query, kind: k, limit: l }));
				if (mine === seq) [results, counts] = [r.results, r.counts];
			} catch (e) {
				ui.error(e);
			} finally {
				if (mine === seq) loading = false;
			}
			const u = new URL(location.href);
			u.searchParams.set('q', query);
			if (k) u.searchParams.set('kind', k);
			else u.searchParams.delete('kind');
			if (u.search !== location.search) history.replaceState(history.state, '', u);
		}, 180);
		return () => clearTimeout(t);
	});

	let saved = $derived(prefs.savedSearches ?? []);
	let current = $derived(saved.find((s) => s.q === q.trim() && (s.kind ?? '') === kind));

	function save() {
		const query = q.trim();
		if (!query) return;
		const name = prompt('Name this search', query)?.trim();
		if (!name) return;
		prefs.savedSearches = [...saved, { id: uid(), name, q: query, kind }];
		ui.toast('Saved. It now appears in the sidebar and updates as your notes change.');
	}

	function remove(id: string) {
		prefs.savedSearches = saved.filter((s) => s.id !== id);
	}

	function href(r: SearchResult): string {
		if (r.kind === 'doc') return `/doc/${r.id}`;
		if (r.kind === 'block') return `/doc/${r.doc}#${r.id}`;
		if (r.kind === 'tag') return `/tag/${r.id}`;
		if (r.kind === 'card') return `/cards?tab=browse&note=${r.id}`;
		return `/tasks?view=open&task=${r.id}`;
	}
	const icons = { doc: FileText, block: Text, tag: Hash, card: Layers, task: CircleCheck };
	let total = $derived(Object.values(counts).reduce((a, b) => a + b, 0));
</script>

<div class="page-scroll">
	<div class="page">
		<div class="titlebar">
			<h1>Search</h1>
			<span class="grow"></span>
			{#if current}
				<button class="btn ghost" onclick={() => remove(current.id)}><Trash2 size={14} />Remove saved search</button>
			{:else if q.trim()}
				<button class="btn" onclick={save}><Bookmark size={14} />Save search</button>
			{/if}
		</div>
		<div class="bar">
			<Search size={16} class="faint" />
			<!-- svelte-ignore a11y_autofocus -->
			<input bind:value={q} placeholder="Search everything…" autofocus spellcheck="false" />
			{#if loading}<span class="faint">…</span>{/if}
		</div>
		<div class="kinds">
			{#each kinds as [k, label] (k)}
				<button class:on={kind === k} onclick={() => (kind = k)}>{label}{#if k && counts[k]} <span>{counts[k]}</span>{:else if !k && total} <span>{total}</span>{/if}</button>
			{/each}
		</div>

		{#if !q.trim()}
			{#if saved.length}
				<div class="section-title">Saved searches</div>
				<div class="saved">
					{#each saved as s (s.id)}
						<a href="/search?q={encodeURIComponent(s.q)}{s.kind ? '&kind=' + s.kind : ''}" onclick={(e) => { e.preventDefault(); goto(`/search?q=${encodeURIComponent(s.q)}${s.kind ? '&kind=' + s.kind : ''}`); }}>
							<Bookmark size={13} />{s.name}<span class="faint">“{s.q}”</span>
						</a>
					{/each}
				</div>
			{:else}
				<div class="empty"><b>Search pages, content, tags, flashcards and tasks</b>Save a search to keep it in the sidebar as a live view.</div>
			{/if}
		{:else}
			<div class="results">
				{#each results as r (r.kind + r.id)}
					{@const Icon = icons[r.kind]}
					<a class="row" href={href(r)} onclick={(e) => { e.preventDefault(); open(href(r), e); }}>
						<span class="ico">{#if r.icon && r.kind === 'doc'}{r.icon}{:else}<Icon size={15} strokeWidth={1.75} />{/if}</span>
						<span class="body">
							<span class="title">{@html r.kind === 'block' || r.kind === 'card' ? highlight(r.snippet) : highlight(r.title || r.snippet || 'Untitled')}</span>
							{#if r.kind === 'doc' && r.snippet}<span class="sub">{@html highlight(r.snippet)}</span>{/if}
							{#if r.doc}<span class="where">{escapeHtml([...(r.path ?? []), r.doc_title || 'Untitled'].join(' / '))}</span>{/if}
						</span>
						<span class="kind faint">{kinds.find((k) => k[0] === r.kind)?.[1]}</span>
					</a>
				{:else}
					{#if !loading}<div class="empty">No matches for “{q}”.</div>{/if}
				{/each}
			</div>
			{#if results.length >= limit}<button class="btn ghost more" onclick={() => (limit += 50)}>Show more</button>{/if}
		{/if}
	</div>
</div>

<style>
	.titlebar { display: flex; align-items: center; gap: 10px; }
	.grow { flex: 1; }
	.bar { display: flex; align-items: center; gap: 10px; height: 42px; padding: 0 12px; margin-top: 8px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); }
	.bar input { flex: 1; border: 0; outline: 0; background: none; font-size: 15px; }
	.kinds { display: flex; gap: 2px; margin: 10px 0; flex-wrap: wrap; }
	.kinds button { padding: 3px 10px; border-radius: 12px; color: var(--text-2); }
	.kinds button:hover { background: var(--hover); }
	.kinds button.on { background: var(--active); color: var(--text); }
	.kinds span { color: var(--text-3); }
	.saved { display: flex; flex-direction: column; }
	.saved a { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: var(--radius); text-decoration: none; }
	.saved a:hover { background: var(--hover); }
	.results { border-top: 1px solid var(--border); }
	.row { display: flex; gap: 10px; padding: 8px 6px; border-bottom: 1px solid var(--border); text-decoration: none; }
	.row:hover { background: var(--hover); }
	.ico { flex: none; width: 20px; display: grid; place-items: center; color: var(--text-2); }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
	.title { overflow-wrap: anywhere; }
	.sub { font-size: 12.5px; color: var(--text-2); }
	.where { font-size: 12px; color: var(--text-3); }
	.kind { flex: none; font-size: 12px; }
	.more { margin-top: 10px; }
</style>
