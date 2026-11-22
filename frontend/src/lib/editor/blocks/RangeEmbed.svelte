<script lang="ts">
	// Blocks copied on one page and pasted on another: a live view of the originals, editable in
	// place. If the original page (or all of the blocks) goes away, the last saved copy is shown.
	import { ArrowUpRight, Repeat, TriangleAlert, Unlink } from '@lucide/svelte';
	import { getContext, setContext } from 'svelte';
	import LostNode from '#lib/components/LostNode.svelte';
	import StaticBlocks from '#lib/components/StaticBlocks.svelte';
	import { open } from '#lib/state/tabs.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Block } from '#lib/types.ts';
	import { snapshotOf, stripTasks, treesToBlocks } from '../clip';
	import { EMBED_CHAIN, getEditor } from '../context';
	import { getDoc, type BlockTree, type EditorDoc } from '../doc.svelte';
	import Editor from '../Editor.svelte';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	const host = ed.doc;

	const parentChain = getContext<Set<string>>(EMBED_CHAIN) ?? new Set([host.id]);
	const chain = new Set(parentChain);
	setContext(EMBED_CHAIN, chain);

	let sourceId = $derived<string | null>(typeof block.props.doc === 'string' ? block.props.doc : null);
	let targets = $derived<string[]>(Array.isArray(block.props.targets) ? block.props.targets : []);
	let snapshot = $derived<BlockTree[] | null>(Array.isArray(block.props.snapshot) && block.props.snapshot.length ? block.props.snapshot : null);
	let source = $state<EditorDoc | null>(null);

	// Showing a block inside itself (directly or through other embeds) would never end.
	let circular = $derived(
		targets.some((t) => parentChain.has(t)) || (sourceId === host.id && targets.some((t) => host.isInside(block.id, t)))
	);

	$effect(() => {
		for (const t of targets) chain.add(t);
	});

	$effect(() => {
		const id = sourceId;
		if (!id || circular) return void (source = null);
		const src = getDoc(id);
		// Blocks still selected on the original page (where they were just copied) are not selected here.
		if (src.selected.length && !frame?.contains(document.activeElement)) src.selected = [];
		source = src;
	});

	let usable = $derived(source?.status === 'ready' && !source.trashed);
	/** The originals still there, outermost first, in page order. */
	let live = $derived(usable && source ? source.topLevel(targets) : []);
	let meta = $derived(sourceId ? (ws.docs[sourceId] ?? source?.meta ?? null) : null);
	let title = $derived(meta?.title || 'Untitled');
	let view = $derived<'circular' | 'loading' | 'live' | 'offline' | 'trashed' | 'gone' | 'emptied'>(
		circular ? 'circular'
		: !sourceId ? 'gone'
		: !source || source.status === 'loading' ? 'loading'
		: source.status === 'error' ? 'offline'
		: source.status === 'missing' ? 'gone'
		: source.trashed ? 'trashed'
		: live.length ? 'live' : 'emptied'
	);

	// ----- new blocks written inside the embed (Enter at the end) stay part of it
	let known: Set<string> | null = null;
	let frame = $state<HTMLElement>();

	function focusIn() {
		if (!known && source && usable) known = new Set(Object.keys(source.blocks));
	}

	function focusOut(e: FocusEvent) {
		if (frame?.contains(e.relatedTarget as Node | null)) return;
		known = null;
		saveCopy();
	}

	$effect(() => {
		const src = source;
		const ids = live;
		if (!src || !known || !ids.length) return;
		const have = new Set(ids);
		const add: string[] = [];
		for (const id of ids) {
			const list = src.children(src.blocks[id]?.parent ?? null);
			const at = list.indexOf(id);
			for (const step of [1, -1])
				for (let i = at + step; i >= 0 && i < list.length && !have.has(list[i]) && !known.has(list[i]); i += step) {
					have.add(list[i]);
					add.push(list[i]);
				}
		}
		if (add.length) host.setPropsQuietly(block.id, { targets: [...targets, ...add] });
	});

	/** Keep the offline copy current after editing through the embed. */
	function saveCopy() {
		if (!source || !live.length) return;
		const snap = snapshotOf(source.exportTrees(live));
		if (JSON.stringify(snap) !== JSON.stringify(block.props.snapshot ?? null)) host.setPropsQuietly(block.id, { snapshot: snap });
	}

	/** Replace the embed with ordinary blocks: the originals as they are now, or the saved copy. */
	function keepCopy() {
		const trees = stripTasks(live.length && source ? source.exportTrees(live) : (snapshot ?? []));
		host.run(() => {
			const { parent, index } = host.loc(block.id);
			const ids = trees.length ? host.insertTrees(trees, parent, index + 1) : [];
			host.remove([block.id]);
			if (ids.length) host.select(ids);
		});
	}

	function openSource(e: MouseEvent) {
		e.preventDefault();
		if (sourceId) open(`/doc/${sourceId}${live[0] ? '#' + live[0] : ''}`, e);
	}

	let snapBlocks = $derived(snapshot ? treesToBlocks(snapshot) : []);
</script>

<div class="range" class:live={view === 'live'}>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="head" data-editor-skip>
		<Repeat size={12} />
		{#if sourceId && view !== 'gone'}
			<a class="src truncate" href="/doc/{sourceId}" title="Open the original" onclick={openSource}>{meta?.icon ? meta.icon + ' ' : ''}{title}</a>
		{:else}
			<span class="src truncate">{meta?.title ? title : 'Deleted page'}</span>
		{/if}
		<span class="tag">{view === 'live' ? 'Live' : view === 'loading' ? '' : 'Saved copy'}</span>
		<span class="grow"></span>
		{#if view === 'live'}
			<button class="act" title="Unlink: keep these blocks here as an ordinary copy" onclick={keepCopy}><Unlink size={13} /><span>Keep a copy</span></button>
			<a class="act icon" href="/doc/{sourceId}" title="Open the original" onclick={openSource}><ArrowUpRight size={14} /></a>
		{/if}
	</div>

	{#if view === 'live' && source}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="body" bind:this={frame} onfocusin={focusIn} onfocusout={focusOut}>
			<Editor doc={source} rootIds={live} />
		</div>
	{:else if view === 'loading'}
		<div class="body faint pad">Loading…</div>
	{:else if view === 'circular'}
		<div class="note"><TriangleAlert size={14} />These blocks would show themselves here, so they are not displayed.</div>
	{:else}
		<div class="lost">
			<div class="art" aria-hidden="true"><LostNode /></div>
			<div class="why">
				<b>{view === 'trashed' ? `“${title}” is in the trash.` : view === 'offline' ? 'The original could not be loaded.' : view === 'emptied' ? `These blocks were removed from “${title}”.` : 'The original page was deleted.'}</b>
				<span class="faint">{snapshot ? 'Showing the last saved copy. Keep it to make it part of this page.' : 'There is no saved copy to show.'}</span>
				<div class="btns">
					{#if snapshot && view !== 'offline'}<button class="btn" onclick={keepCopy}>Keep the copy</button>{/if}
					<button class="btn ghost" onclick={() => host.remove([block.id])}>Remove</button>
				</div>
			</div>
		</div>
		{#if snapBlocks.length}<div class="body snap"><StaticBlocks blocks={snapBlocks} /></div>{/if}
	{/if}
</div>

<style>
	.range { flex: 1; min-width: 0; margin: 4px 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
	.range.live { border-color: color-mix(in srgb, var(--accent) 28%, var(--border)); }
	.head { display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 4px 0 10px; border-bottom: 1px solid var(--border); background: var(--surface-2); color: var(--text-3); font-family: var(--font-sans); font-size: 12px; user-select: none; }
	.head :global(svg) { flex: none; }
	.src { min-width: 0; color: var(--text-2); text-decoration: none; font-weight: 550; }
	a.src:hover { color: var(--accent); }
	.tag { flex: none; font-size: 10.5px; letter-spacing: 0.02em; text-transform: uppercase; color: var(--text-3); }
	.live .tag { color: color-mix(in srgb, var(--accent) 80%, var(--text-3)); }
	.grow { flex: 1; }
	.act { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 6px; border-radius: 5px; color: var(--text-3); font-size: 12px; text-decoration: none; opacity: 0; transition: opacity .12s var(--ease); }
	.act.icon { padding: 0 4px; }
	.range:hover .act, .range:focus-within .act, .range:not(.live) .act { opacity: 1; }
	.act:hover { background: var(--hover); color: var(--text); }
	.body { padding: 4px 10px 4px 30px; }
	.body.snap { opacity: 0.75; border-top: 1px dashed var(--border); padding: 6px 14px; }
	.pad { padding: 8px 12px; font-size: 13px; }
	.note { display: flex; align-items: center; gap: 8px; padding: 8px 12px; color: var(--text-2); font-size: 13px; }
	.lost { display: flex; align-items: center; gap: 12px; padding: 10px 12px; font-family: var(--font-sans); }
	.art { position: relative; flex: none; width: 76px; height: 60px; border-radius: 8px; overflow: hidden; background: var(--bg); }
	.why { display: flex; flex-direction: column; gap: 3px; min-width: 0; font-size: 13px; }
	.btns { display: flex; gap: 6px; margin-top: 5px; }
	.btns .btn { height: 26px; padding: 0 10px; font-size: 12.5px; }
	@media (max-width: 560px) { .act span { display: none; } .body { padding-left: 22px; } }
</style>
