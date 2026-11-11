<script lang="ts">
	import { Plus } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import DocList from '#lib/components/DocList.svelte';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';

	let filter = $state('');
	let name = $state('');
	let picked = $state<string[]>([]);

	onMount(() => ws.refreshTags().catch(() => {}));

	let shown = $derived(ws.tags.filter((t) => t.name.toLowerCase().includes(filter.trim().toLowerCase())));
	let matches = $derived(
		picked.length
			? Object.values(ws.docs).filter((d) => picked.every((t) => d.tags.includes(t))).sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1))
			: []
	);

	async function create() {
		if (!name.trim()) return;
		try {
			const t = await ws.createTag(name.trim());
			name = '';
			open(`/tag/${t.id}`);
		} catch (e) {
			ui.error(e);
		}
	}
</script>

<div class="page-scroll">
	<div class="page">
		<h1>Tags</h1>
		<p class="lede">Tags group pages and blocks, and can give pages shared properties. Type <kbd>#</kbd> in a page to tag a block.</p>

		<div class="bar">
			<input class="input grow" bind:value={filter} placeholder="Filter tags…" />
			<form onsubmit={(e) => { e.preventDefault(); create(); }}>
				<input class="input" bind:value={name} placeholder="New tag name" />
				<button class="btn primary" type="submit"><Plus size={14} />Create</button>
			</form>
		</div>

		{#if shown.length}
			<div class="tags">
				{#each shown as t (t.id)}
					<div class="tag" class:on={picked.includes(t.id)}>
						<input type="checkbox" title="Filter pages by this tag" checked={picked.includes(t.id)}
							onchange={() => (picked = picked.includes(t.id) ? picked.filter((x) => x !== t.id) : [...picked, t.id])} />
						<a href="/tag/{t.id}" onclick={(e) => { e.preventDefault(); open(`/tag/${t.id}`, e); }}>
							<span class="chip" data-c={t.color || undefined}>#{t.name}</span>
						</a>
						<span class="faint n">{t.doc_count ?? 0}</span>
					</div>
				{/each}
			</div>
		{:else}
			<div class="empty"><b>{ws.tags.length ? 'No tags match' : 'No tags yet'}</b>{ws.tags.length ? 'Try a different filter.' : 'Create one above, or type # while writing.'}</div>
		{/if}

		{#if picked.length}
			<div class="section-title">Pages with {picked.length === 1 ? 'this tag' : `all ${picked.length} tags`} · {matches.length}</div>
			{#if matches.length}<DocList docs={matches} sub={(d) => ws.path(d.id).map((p) => p.title || 'Untitled').join(' / ')} />
			{:else}<div class="empty">No pages carry {picked.length === 1 ? 'this tag' : 'all of these tags'}.</div>{/if}
		{/if}
	</div>
</div>

<style>
	.bar { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
	.bar form { display: flex; gap: 6px; }
	.grow { flex: 1; min-width: 140px; }
	.tags { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 6px; }
	.tag { display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: var(--radius); }
	.tag.on { border-color: color-mix(in srgb, var(--accent) 60%, var(--border)); }
	.tag:hover { background: var(--hover); }
	.tag a { flex: 1; min-width: 0; text-decoration: none; }
	.tag input { accent-color: var(--accent); }
	.n { font-size: 12px; }
</style>
