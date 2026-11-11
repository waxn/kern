<script lang="ts">
	import { Maximize2, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '../api.ts';
	import DocMeta from '../components/DocMeta.svelte';
	import { getDoc } from '../editor/doc.svelte.ts';
	import Editor from '../editor/Editor.svelte';
	import { open } from '../state/tabs.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import { debounce } from '../util.ts';

	let { id, onclose }: { id: string; onclose: () => void } = $props();

	// svelte-ignore state_referenced_locally
	const doc = getDoc(id);
	let title = $state('');
	let titleInput = $state<HTMLTextAreaElement>();

	onMount(() => {
		title = ws.docs[id]?.title ?? '';
		if (!title) setTimeout(() => titleInput?.focus(), 50);
		return () => {
			save.cancel();
			if (title !== (ws.docs[id]?.title ?? '')) commit();
			doc.flush();
		};
	});

	function commit() {
		if (ws.docs[id]) ws.docs[id].title = title;
		api.patch(`/documents/${id}`, { title }).catch(() => {});
	}
	const save = debounce(commit, 400);

	function startBody() {
		const first = doc.children(null)[0];
		doc.focus(first ?? doc.append('paragraph'), 'start');
	}
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape' && !(e.target as HTMLElement)?.closest('[contenteditable], input, textarea')) onclose(); }} />

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="scrim" onclick={onclose}></div>
<aside class="peek" aria-label="Card">
	<header>
		<span class="faint">{ws.docs[id]?.entry_of ? ws.dbPages[ws.docs[id].entry_of!]?.title || 'Database' : ''}</span>
		<span class="grow"></span>
		<button class="icon-btn" title="Open as full page" onclick={(e) => { onclose(); open(`/doc/${id}`, e); }}><Maximize2 size={14} /></button>
		<button class="icon-btn" title="Close (Esc)" onclick={onclose}><X size={15} /></button>
	</header>
	<div class="body">
		{#if doc.status === 'ready'}
			<textarea class="title" rows="1" bind:this={titleInput} bind:value={title} placeholder="Untitled"
				oninput={() => save()} onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); startBody(); } }}></textarea>
			<DocMeta {doc} />
			<Editor {doc} />
		{:else if doc.status === 'loading'}
			<p class="faint">Loading…</p>
		{:else}
			<p class="faint">This card could not be loaded.</p>
		{/if}
	</div>
</aside>

<style>
	.scrim { position: fixed; inset: 0; z-index: 620; background: rgba(0, 0, 0, 0.25); animation: fade 0.12s; }
	.peek { position: fixed; z-index: 621; top: 0; right: 0; bottom: 0; width: min(640px, 100vw); display: flex; flex-direction: column; background: var(--bg); border-left: 1px solid var(--border); box-shadow: var(--shadow); animation: slide 0.16s var(--ease); }
	@keyframes slide { from { transform: translateX(24px); opacity: 0; } }
	header { flex: none; display: flex; align-items: center; gap: 4px; height: 42px; padding: 0 10px 0 20px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
	.grow { flex: 1; }
	.body { flex: 1; overflow-y: auto; padding: 20px 40px 40px 56px; }
	.title { width: 100%; border: 0; outline: 0; resize: none; background: none; padding: 0; margin-bottom: 6px; font: 700 26px/1.25 var(--font-editor); letter-spacing: -0.02em; field-sizing: content; }
	.title::placeholder { color: var(--text-3); }
	@media (max-width: 760px) { .body { padding: 16px 16px 40px 30px; } }
</style>
