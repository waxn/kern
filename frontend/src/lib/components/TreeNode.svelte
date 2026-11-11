<script module lang="ts">
	// Shared drag state for the whole tree.
	const drag = $state<{ id: string | null; over: string | null; zone: 'before' | 'after' | 'inside' | null }>({
		id: null, over: null, zone: null
	});
	export function treeDragId() {
		return drag.id;
	}
	export function endTreeDrag() {
		drag.id = drag.over = drag.zone = null;
	}
</script>

<script lang="ts">
	import { page } from '$app/state';
	import { ChevronRight, Database, Ellipsis, FileText, Plus } from '@lucide/svelte';
	import { tick } from 'svelte';
	import { slide } from 'svelte/transition';
	import { docMenu, newPage } from '#lib/actions.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Doc } from '#lib/types.ts';
	import Self from './TreeNode.svelte';

	let { doc, depth = 0, flat = false }: { doc: Doc; depth?: number; flat?: boolean } = $props();

	let kids = $derived(flat ? [] : ws.children(doc.id));
	let expanded = $derived(!!prefs.expanded[doc.id]);
	let active = $derived(page.url.pathname === `/doc/${doc.id}`);
	let renaming = $state(false);
	let draft = $state('');
	let input = $state<HTMLInputElement>();

	async function startRename() {
		draft = doc.title;
		renaming = true;
		await tick();
		input?.select();
	}

	function commitRename() {
		if (!renaming) return;
		renaming = false;
		if (draft !== doc.title) ws.updateDoc(doc.id, { title: draft }).catch(() => {});
	}

	function menu(e: MouseEvent) {
		ui.openMenu(e, docMenu(doc, { rename: startRename }));
	}

	function dragover(e: DragEvent) {
		if (flat || !drag.id || ws.isDescendant(doc.id, drag.id)) return;
		e.preventDefault();
		e.dataTransfer!.dropEffect = 'move';
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const f = (e.clientY - r.top) / r.height;
		drag.over = doc.id;
		drag.zone = f < 0.28 ? 'before' : f > 0.72 ? 'after' : 'inside';
	}

	function drop(e: DragEvent) {
		e.preventDefault();
		const id = drag.id;
		const zone = drag.zone;
		endTreeDrag();
		if (!id || !zone || ws.isDescendant(doc.id, id)) return;
		if (zone === 'inside') {
			prefs.expanded[doc.id] = true;
			ws.moveDoc(id, doc.id);
		} else {
			const siblings = ws.children(doc.parent).filter((d) => d.id !== id);
			const i = siblings.findIndex((d) => d.id === doc.id);
			ws.moveDoc(id, doc.parent, zone === 'before' ? i : i + 1);
		}
	}
</script>

<div class="node">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="row" class:active class:dragging={drag.id === doc.id}
		class:drop-before={drag.over === doc.id && drag.zone === 'before'}
		class:drop-after={drag.over === doc.id && drag.zone === 'after'}
		class:drop-inside={drag.over === doc.id && drag.zone === 'inside'}
		style:padding-left="{6 + depth * 14}px"
		draggable={!renaming && !flat}
		ondragstart={(e) => { drag.id = doc.id; e.dataTransfer!.effectAllowed = 'move'; e.dataTransfer!.setData('text/plain', doc.title); }}
		ondragend={endTreeDrag}
		ondragover={dragover}
		ondragleave={() => { if (drag.over === doc.id) drag.over = null; }}
		ondrop={drop}
		oncontextmenu={menu}>
		{#if !flat}
			<button class="chev" class:open={expanded} class:leaf={!kids.length} tabindex="-1" aria-label={expanded ? 'Collapse' : 'Expand'}
				onclick={() => (prefs.expanded[doc.id] = !expanded)}>
				<ChevronRight size={13} />
			</button>
		{/if}
		{#if renaming}
			<span class="ico">{#if doc.icon}{doc.icon}{:else}<FileText size={14} strokeWidth={1.75} />{/if}</span>
			<input class="rename" bind:this={input} bind:value={draft} onblur={commitRename}
				onkeydown={(e) => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') renaming = false; }} />
		{:else}
			<a class="link" href="/doc/{doc.id}" draggable="false" title={doc.title || 'Untitled'}
				onclick={(e) => { e.preventDefault(); open(`/doc/${doc.id}`, e); ui.mobileNav = false; }}
				onauxclick={(e) => { if (e.button === 1) { e.preventDefault(); open(`/doc/${doc.id}`, e); } }}
				ondblclick={startRename}>
				<span class="ico">{#if doc.icon}{doc.icon}{:else if doc.database}<Database size={14} strokeWidth={1.75} />{:else}<FileText size={14} strokeWidth={1.75} />{/if}</span>
				<span class="truncate" class:untitled={!doc.title}>{doc.title || 'Untitled'}</span>
			</a>
			<span class="acts">
				<button class="icon-btn sm" title="More" onclick={menu}><Ellipsis size={14} /></button>
				{#if !flat}
					<button class="icon-btn sm" title="Add sub-page" onclick={() => newPage(doc.id)}><Plus size={14} /></button>
				{/if}
			</span>
		{/if}
	</div>
	{#if expanded && kids.length}
		<div transition:slide={{ duration: 120 }}>
			{#each kids as child (child.id)}
				<Self doc={child} depth={depth + 1} />
			{/each}
		</div>
	{/if}
</div>

<style>
	.row { position: relative; display: flex; align-items: center; height: var(--row-h); padding-right: 4px; border-radius: var(--radius-sm); color: var(--text-2); }
	.row:hover { background: var(--hover); color: var(--text); }
	.row.active { background: var(--active); color: var(--text); }
	.row.dragging { opacity: 0.4; }
	.row.drop-inside { background: color-mix(in srgb, var(--accent) 18%, transparent); }
	.row.drop-before::before, .row.drop-after::after { content: ''; position: absolute; left: 8px; right: 4px; height: 2px; background: var(--accent); border-radius: 1px; }
	.row.drop-before::before { top: -1px; }
	.row.drop-after::after { bottom: -1px; }
	.chev { flex: none; width: 18px; height: 18px; display: grid; place-items: center; border-radius: 3px; color: var(--text-3); }
	.chev:hover { background: var(--active); color: var(--text); }
	.chev :global(svg) { transition: transform 0.12s var(--ease); }
	.chev.open :global(svg) { transform: rotate(90deg); }
	.chev.leaf { opacity: 0.25; }
	.link { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; height: 100%; text-decoration: none; padding-left: 2px; }
	.ico { flex: none; width: 18px; display: grid; place-items: center; font-size: 14px; line-height: 1; }
	.untitled { color: var(--text-3); }
	.acts { display: none; gap: 1px; }
	.row:hover .acts { display: flex; }
	.acts :global(.sm) { width: 20px; height: 20px; }
	.rename { flex: 1; min-width: 0; height: 22px; margin-left: 6px; padding: 0 4px; border: 1px solid var(--accent); border-radius: 3px; background: var(--bg); outline: none; }
	@media (hover: none) { .acts { display: flex; } }
</style>
