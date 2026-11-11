<script lang="ts">
	import { X } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { blockEl, htmlToText } from '#lib/editor/dom.ts';
	import type { EditorDoc } from '#lib/editor/doc.svelte.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { BacklinkGroup } from '#lib/types.ts';
	import { fullDate } from '#lib/util.ts';
	import { open } from '#lib/state/tabs.ts';
	import BacklinkList from './BacklinkList.svelte';

	let { doc, onhistory }: { doc: EditorDoc; onhistory?: () => void } = $props();
	let meta = $derived(ws.docs[doc.id]);
	let backlinks = $state<BacklinkGroup[]>([]);
	let blockRefs = $state<BacklinkGroup[]>([]);
	let loaded = $state(false);

	async function loadBacklinks() {
		try {
			backlinks = await api.get<BacklinkGroup[]>(`/documents/${doc.id}/backlinks`);
		} catch {
			/* keep previous */
		}
		loaded = true;
	}

	$effect(() => {
		void doc.id;
		loadBacklinks();
		const onFocus = () => loadBacklinks();
		addEventListener('focus', onFocus);
		return () => removeEventListener('focus', onFocus);
	});

	$effect(() => {
		const id = doc.inspectBlock;
		void doc.savedSeq;
		if (!id) return void (blockRefs = []);
		api.get<BacklinkGroup[]>(`/blocks/${id}/backlinks`).then((r) => (blockRefs = r)).catch(() => {});
	});

	/** Pages sharing tags with this one, linked from it, or its siblings. */
	let related = $derived.by(() => {
		if (!meta) return [];
		const mine = new Set(meta.tags);
		const linked = new Set(Object.keys(doc.refs).filter((k) => k.startsWith('doc:')).map((k) => k.slice(4)));
		const out: { id: string; title: string; icon: string; why: string; score: number }[] = [];
		for (const d of Object.values(ws.docs)) {
			if (d.id === meta.id || d.database) continue;
			const shared = d.tags.filter((t) => mine.has(t)).length;
			const links = linked.has(d.id);
			const back = backlinks.some((g) => g.doc.id === d.id);
			const score = shared * 2 + (links ? 3 : 0) + (back ? 3 : 0);
			if (!score) continue;
			const why = [links && 'linked', back && 'links here', shared && `${shared} shared ${shared === 1 ? 'tag' : 'tags'}`].filter(Boolean).join(' · ');
			out.push({ id: d.id, title: d.title, icon: d.icon, why, score });
		}
		return out.sort((a, b) => b.score - a.score).slice(0, 8);
	});

	let ordered = $derived.by(() => {
		const out: string[] = [];
		const walk = (key: string) => {
			for (const id of doc.kids[key] ?? []) {
				out.push(id);
				walk(id);
			}
		};
		walk('root');
		return out;
	});

	let outline = $derived(
		ordered
			.map((id) => doc.blocks[id])
			.filter((b) => b && (b.type === 'h1' || b.type === 'h2' || b.type === 'h3') && b.html)
			.map((b) => ({ id: b.id, level: Number(b.type[1]), text: htmlToText(b.html) }))
	);

	let words = $derived.by(() => {
		let n = 0;
		for (const id of ordered) {
			const t = htmlToText(doc.blocks[id]?.html ?? '').trim();
			if (t) n += t.split(/\s+/).length;
		}
		return n;
	});

	function jump(id: string) {
		// Reveal the heading if an ancestor is collapsed.
		let p = doc.blocks[id]?.parent;
		while (p) {
			if (doc.blocks[p].collapsed) doc.toggleCollapsed(p, false);
			p = doc.blocks[p].parent;
		}
		requestAnimationFrame(() => {
			const el = blockEl(id);
			el?.scrollIntoView({ block: 'start', behavior: 'smooth' });
			el?.classList.add('flash');
			setTimeout(() => el?.classList.remove('flash'), 1600);
		});
	}
</script>

<aside class="panel">
	<div class="head">
		<span>Page details</span>
		<button class="icon-btn" title="Close panel" onclick={() => (prefs.panelOpen = false)}><X size={15} /></button>
	</div>
	<div class="body">
		{#if doc.inspectBlock}
			<div class="sec">
				<h3>References to block <button class="icon-btn sm" title="Close" onclick={() => (doc.inspectBlock = null)}><X size={12} /></button></h3>
				<p class="quote truncate">{htmlToText(doc.blocks[doc.inspectBlock]?.html ?? '') || 'Block'}</p>
				<BacklinkList groups={blockRefs} empty="No references to this block." />
			</div>
		{/if}

		<div class="sec">
			<h3>Outline</h3>
			{#each outline as h (h.id)}
				<button class="toc truncate" style:padding-left="{6 + (h.level - 1) * 12}px" onclick={() => jump(h.id)}>{h.text}</button>
			{:else}
				<p class="faint none">Headings appear here.</p>
			{/each}
		</div>

		<div class="sec">
			<h3>Backlinks {#if backlinks.length}<span class="count">{backlinks.reduce((n, g) => n + g.items.length, 0)}</span>{/if}</h3>
			{#if loaded}<BacklinkList groups={backlinks} />{/if}
		</div>

		{#if related.length}
			<div class="sec">
				<h3>Related</h3>
				{#each related as r (r.id)}
					<a class="toc rel" href="/doc/{r.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${r.id}`, e); }}>
						<span class="truncate">{r.icon} {r.title || 'Untitled'}</span><span class="faint why">{r.why}</span>
					</a>
				{/each}
			</div>
		{/if}

		{#if meta?.entry_of && ws.dbPages[meta.entry_of]}
			{@const db = ws.dbPages[meta.entry_of]}
			<div class="sec">
				<h3>Database</h3>
				<a class="toc" href="/doc/{db.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${db.id}`, e); }}>{db.icon} {db.title || 'Untitled'} · {ws.entries(meta.entry_of).length} entries</a>
			</div>
		{/if}

		<div class="sec">
			<h3>Info</h3>
			<dl>
				<dt>Created</dt><dd>{fullDate(meta?.created_at)}</dd>
				<dt>Edited</dt><dd>{fullDate(meta?.updated_at)}</dd>
				<dt>Words</dt><dd>{words.toLocaleString()}</dd>
				<dt>Blocks</dt><dd>{ordered.length.toLocaleString()}</dd>
			</dl>
			{#if onhistory}<button class="btn ghost hist" onclick={onhistory}>Version history…</button>{/if}
		</div>
	</div>
</aside>

<style>
	.panel { flex: none; width: 300px; display: flex; flex-direction: column; border-left: 1px solid var(--border); background: var(--bg-side); }
	.head { flex: none; display: flex; align-items: center; justify-content: space-between; height: 38px; padding: 0 8px 0 14px; border-bottom: 1px solid var(--border); font-weight: 600; }
	.body { flex: 1; overflow-y: auto; padding: 4px 10px 24px; }
	.sec { padding: 10px 0; border-bottom: 1px solid var(--border); }
	.sec:last-child { border-bottom: 0; }
	h3 { display: flex; align-items: center; gap: 6px; margin: 0 4px 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); }
	h3 .sm { margin-left: auto; width: 18px; height: 18px; }
	.count { padding: 0 5px; border-radius: 8px; background: var(--active); color: var(--text-2); letter-spacing: 0; }
	.toc { display: block; width: 100%; padding: 3px 6px; border-radius: var(--radius-sm); text-align: left; color: var(--text-2); }
	.toc:hover { background: var(--hover); color: var(--text); }
	a.toc { text-decoration: none; }
	.rel { display: flex; gap: 6px; }
	.rel .truncate { flex: 1; }
	.why { font-size: 11px; white-space: nowrap; }
	.none { margin: 4px; }
	.quote { margin: 0 4px 8px; padding-left: 8px; border-left: 2px solid var(--accent); color: var(--text-2); }
	dl { display: grid; grid-template-columns: 74px 1fr; gap: 4px 8px; margin: 0 4px; font-size: 12.5px; }
	dt { color: var(--text-3); }
	dd { margin: 0; color: var(--text-2); }
	.hist { margin-top: 8px; }
	@media (max-width: 1000px) {
		.panel { position: absolute; z-index: 50; right: 0; top: 0; bottom: 0; width: min(320px, 92vw); box-shadow: var(--shadow); }
	}
</style>
