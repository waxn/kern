<script lang="ts">
	// A read-only look at a linked page, opened by clicking a "link to page" text link.
	import { ArrowLeft, ArrowUpRight, FileText, TriangleAlert, X } from '@lucide/svelte';
	import { onMount, tick, untrack } from 'svelte';
	import StaticBlocks from '#lib/components/StaticBlocks.svelte';
	import { open } from '#lib/state/tabs.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Block } from '#lib/types.ts';
	import { getDoc, type EditorDoc } from './doc.svelte';

	let { id, rect, onclose }: { id: string; rect: DOMRect; onclose: () => void } = $props();

	// Links inside the peek open in the peek; Back returns to where it started.
	let trail = $state<string[]>([]);
	let current = $derived(trail[trail.length - 1] ?? id);
	let src = $state<EditorDoc>(getDoc(untrack(() => id)));
	$effect(() => {
		const want = current;
		if (want && src.id !== want) src = getDoc(want);
	});
	let meta = $derived(ws.docs[current] ?? src.meta);
	let blocks = $derived(src.status === 'ready' ? (Object.values(src.blocks) as Block[]) : []);
	let empty = $derived(src.status === 'ready' && !blocks.some((b) => b.html || b.type !== 'paragraph'));
	let crumbs = $derived(ws.path(current).map((d) => d.title || 'Untitled').join(' / '));

	let box = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0, maxH: 420 });

	function place() {
		const w = Math.min(460, innerWidth - 16);
		const below = innerHeight - rect.bottom - 16;
		const above = rect.top - 16;
		const down = below >= 260 || below >= above;
		const maxH = Math.max(180, Math.min(480, (down ? below : above) - 8));
		pos = {
			x: Math.max(8, Math.min(rect.left, innerWidth - w - 8)),
			y: down ? rect.bottom + 6 : Math.max(8, rect.top - 6 - Math.min(maxH, box?.offsetHeight ?? maxH)),
			maxH
		};
	}

	onMount(() => {
		place();
		tick().then(() => { place(); box?.focus({ preventScroll: true }); });
		const away = (e: PointerEvent) => { if (box && !box.contains(e.target as Node)) onclose(); };
		const keys = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onclose(); } };
		// Wait a tick so the click that opened the peek does not close it.
		const t = setTimeout(() => document.addEventListener('pointerdown', away, true));
		document.addEventListener('keydown', keys, true);
		addEventListener('resize', onclose);
		return () => {
			clearTimeout(t);
			document.removeEventListener('pointerdown', away, true);
			document.removeEventListener('keydown', keys, true);
			removeEventListener('resize', onclose);
		};
	});

	function openFull(e: MouseEvent) {
		const target = current; // read before closing: the props go away with the popup
		onclose();
		open(`/doc/${target}`, e);
	}

	function clickBody(e: MouseEvent) {
		const a = (e.target as HTMLElement).closest('a');
		if (!a) return;
		e.preventDefault();
		const doc = a.dataset.doc ?? (a.dataset.ref?.startsWith('doc:') ? a.dataset.ref.slice(4) : null);
		if (doc && !a.classList.contains('broken')) {
			if (doc !== current) trail = [...trail, doc];
			return;
		}
		const href = a.getAttribute('href') ?? '';
		if (a.dataset.ref && href && !a.classList.contains('broken')) {
			onclose();
			open(href, e);
		} else if (/^(https?:|mailto:)/i.test(href)) window.open(href, '_blank', 'noopener');
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="peek popover" bind:this={box} tabindex="-1" role="dialog" aria-label="Preview of {meta?.title || 'a page'}"
	style:left="{pos.x}px" style:top="{pos.y}px" style:max-height="{pos.maxH}px">
	<header>
		{#if trail.length}
			<button class="icon-btn" title="Back" onclick={() => (trail = trail.slice(0, -1))}><ArrowLeft size={14} /></button>
		{/if}
		<div class="title">
			{#if crumbs}<div class="crumbs faint truncate">{crumbs}</div>{/if}
			<div class="name truncate">
				{#if meta?.icon}<span class="ico">{meta.icon}</span>{:else}<FileText size={14} />{/if}
				{meta?.title || (src.status === 'missing' ? 'Deleted page' : 'Untitled')}
			</div>
		</div>
		{#if src.status === 'ready' && !src.trashed}
			<button class="btn open" title="Open the page (Ctrl-click: new tab)" onclick={openFull}>Open<ArrowUpRight size={13} /></button>
		{/if}
		<button class="icon-btn" title="Close (Esc)" onclick={onclose}><X size={14} /></button>
	</header>
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div class="body" onclick={clickBody}>
		{#if src.status === 'missing' || src.status === 'error'}
			<div class="note"><TriangleAlert size={14} />{src.status === 'missing' ? 'This page was deleted.' : 'This page could not be loaded.'}</div>
		{:else if src.status !== 'ready'}
			<div class="note faint">Loading…</div>
		{:else}
			{#if src.trashed}<div class="note"><TriangleAlert size={14} />This page is in the trash.</div>{/if}
			{#if empty}<div class="note faint">This page is empty.</div>{:else}<StaticBlocks {blocks} />{/if}
		{/if}
	</div>
</div>

<style>
	.peek { position: fixed; z-index: 598; width: min(460px, calc(100vw - 16px)); display: flex; flex-direction: column; overflow: hidden; outline: none; font-family: var(--font-sans); }
	header { flex: none; display: flex; align-items: center; gap: 6px; padding: 8px 8px 8px 12px; border-bottom: 1px solid var(--border); }
	.title { flex: 1; min-width: 0; }
	.crumbs { font-size: 11px; }
	.name { display: flex; align-items: center; gap: 6px; font-weight: 650; font-size: 14px; }
	.ico { font-size: 15px; }
	.open { display: inline-flex; align-items: center; gap: 3px; height: 26px; padding: 0 9px; font-size: 12.5px; }
	header :global(.icon-btn) { width: 26px; height: 26px; flex: none; }
	.body { flex: 1; min-height: 0; overflow-y: auto; padding: 8px 14px 12px; font-size: 0.92em; }
	.body :global(.sb) { font-size: 14px; }
	.note { display: flex; align-items: center; gap: 7px; padding: 6px 0; font-size: 13px; color: var(--text-2); }
</style>
