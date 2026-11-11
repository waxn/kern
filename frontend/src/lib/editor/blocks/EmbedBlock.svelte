<script lang="ts" module>
	const CHAIN = Symbol('kern-embed-chain');
</script>

<script lang="ts">
	import { ArrowUpRight, FileSymlink, FileText, TextQuote, TriangleAlert } from '@lucide/svelte';
	import { getContext, setContext, tick } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Block, Suggestion } from '#lib/types.ts';
	import { getEditor } from '../context.ts';
	import { getDoc, type EditorDoc } from '../doc.svelte.ts';
	import Editor from '../Editor.svelte';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	const host = ed.doc;

	// The pages and blocks being rendered above this one, to stop circular embeds.
	const parentChain = getContext<Set<string>>(CHAIN) ?? new Set([host.id]);
	const chain = new Set(parentChain);
	setContext(CHAIN, chain);

	let kind = $derived<'doc' | 'block'>(block.props.kind === 'block' ? 'block' : 'doc');
	let target = $derived<string | null>(block.props.target ?? null);
	let sourceId = $derived<string | null>(kind === 'doc' ? target : (block.props.doc ?? null));
	let source = $state<EditorDoc | null>(null);

	let circular = $derived(
		!!target &&
			(parentChain.has(target) ||
				(kind === 'doc' && target === host.id) ||
				(kind === 'block' && sourceId === host.id && host.isInside(block.id, target)))
	);

	$effect(() => {
		if (target) chain.add(target);
		if (kind === 'doc' && target) chain.add(target);
	});

	$effect(() => {
		const id = sourceId;
		if (!id || circular) return void (source = null);
		source = getDoc(id);
	});

	// ----- setup (choosing what to embed)
	let q = $state('');
	let results = $state<Suggestion[]>([]);
	let input = $state<HTMLInputElement>();
	let seq = 0;

	$effect(() => {
		if (ed.fresh.id === block.id) {
			ed.fresh.id = null;
			tick().then(() => input?.focus());
		}
	});

	$effect(() => {
		if (target) return;
		const query = q.trim();
		const mine = ++seq;
		if (kind === 'doc') {
			const ql = query.toLowerCase();
			results = Object.values(ws.docs)
				.filter((d) => d.id !== host.id && (d.title || 'Untitled').toLowerCase().includes(ql))
				.sort((a, b) => (b.last_opened_at ?? '').localeCompare(a.last_opened_at ?? ''))
				.slice(0, 8)
				.map((d) => ({ kind: 'doc', id: d.id, title: d.title, icon: d.icon }));
		} else if (query) {
			api.get<Suggestion[]>('/suggest' + qs({ q: query, kinds: 'block', limit: 8 }))
				.then((r) => { if (mine === seq) results = r.filter((s) => s.id !== block.id); })
				.catch(() => {});
		} else results = [];
	});

	function pick(s: Suggestion) {
		if (kind === 'doc') host.setProps(block.id, { target: s.id });
		else host.setProps(block.id, { target: s.id, doc: s.doc });
	}

	let srcMeta = $derived(sourceId ? ws.docs[sourceId] : null);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="embed" data-editor-skip={!target ? '' : undefined}>
	{#if !target}
		<div class="setup">
			{#if kind === 'doc'}<FileSymlink size={15} />{:else}<TextQuote size={15} />{/if}
			<div class="grow">
				<input class="input" bind:this={input} bind:value={q} placeholder={kind === 'doc' ? 'Find a page to embed…' : 'Search for a block to embed…'}
					onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Enter' && results[0]) pick(results[0]); }} />
				{#if results.length}
					<div class="results">
						{#each results as r (r.id)}
							<button class="menu-item" onclick={() => pick(r)}>
								{#if r.icon}{r.icon}{:else}<FileText size={14} />{/if}
								<span class="truncate">{r.title || (kind === 'doc' ? 'Untitled' : '(empty block)')}</span>
								{#if r.doc_title !== undefined}<span class="hint truncate">{r.doc_title || 'Untitled'}</span>{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{:else if circular}
		<div class="warn"><TriangleAlert size={14} />This embed would show itself, so it is not displayed.</div>
	{:else if source?.status === 'missing' || (source?.status === 'ready' && source.trashed)}
		<div class="warn"><TriangleAlert size={14} />The embedded {kind === 'doc' ? 'page' : 'block'} is no longer available.</div>
	{:else if source?.status === 'ready'}
		<div class="frame" class:doc={kind === 'doc'}>
			<a class="src" href="/doc/{sourceId}{kind === 'block' ? '#' + target : ''}" title="Open the original"
				onclick={(e) => { e.preventDefault(); open(`/doc/${sourceId}${kind === 'block' ? '#' + target : ''}`, e); }}>
				{#if kind === 'doc'}<span class="big">{srcMeta?.icon ?? ''} {srcMeta?.title || 'Untitled'}</span>{:else}{srcMeta?.icon ?? ''} {srcMeta?.title || 'Untitled'}{/if}
				<ArrowUpRight size={12} />
			</a>
			<Editor doc={source} rootId={kind === 'block' ? target : null} />
		</div>
	{:else}
		<div class="faint pad">Loading…</div>
	{/if}
</div>

<style>
	.embed { flex: 1; min-width: 0; margin: 3px 0; }
	.setup { display: flex; align-items: flex-start; gap: 10px; padding: 8px 10px; border: 1px dashed var(--border-strong); border-radius: var(--radius); color: var(--text-2); }
	.setup :global(svg) { margin-top: 6px; }
	.grow { flex: 1; min-width: 0; }
	.grow .input { width: 100%; }
	.results { margin-top: 4px; }
	.frame { position: relative; padding: 4px 8px 4px 34px; border-left: 3px solid color-mix(in srgb, var(--accent) 55%, transparent); border-radius: 0 var(--radius) var(--radius) 0; background: color-mix(in srgb, var(--accent) 4%, transparent); }
	.frame.doc { padding-top: 8px; border: 1px solid var(--border); border-left: 3px solid color-mix(in srgb, var(--accent) 55%, transparent); }
	.src { display: inline-flex; align-items: center; gap: 4px; margin-left: -26px; font-size: 11.5px; color: var(--text-3); text-decoration: none; }
	.src:hover { color: var(--accent); }
	.big { font-size: 15px; font-weight: 650; color: var(--text); }
	.warn { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: var(--radius); background: var(--surface-2); color: var(--text-2); font-size: 13px; }
	.pad { padding: 6px; }
</style>
