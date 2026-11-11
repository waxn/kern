<script lang="ts">
	import katex from 'katex';
	import { tick } from 'svelte';
	import type { Block } from '#lib/types.ts';
	import { getEditor } from '../context';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	let editing = $state(false);
	let draft = $state('');
	let area = $state<HTMLTextAreaElement>();

	let rendered = $derived.by(() => {
		try {
			return katex.renderToString(editing ? draft : (block.props.tex ?? ''), { displayMode: true, throwOnError: false });
		} catch {
			return '';
		}
	});

	async function edit() {
		draft = block.props.tex ?? '';
		editing = true;
		await tick();
		area?.focus();
	}

	function save() {
		if (!editing) return;
		editing = false;
		if (draft !== (block.props.tex ?? '')) ed.doc.setProps(block.id, { tex: draft });
	}

	$effect(() => {
		if (ed.fresh.id === block.id) {
			ed.fresh.id = null;
			edit();
		}
	});
</script>

<div class="eq" class:editing>
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="view" onclick={edit} title="Click to edit">
		{#if (editing ? draft : block.props.tex)?.trim()}{@html rendered}{:else}<span class="faint">Empty equation — click to write LaTeX</span>{/if}
	</div>
	{#if editing}
		<textarea class="input" bind:this={area} bind:value={draft} rows="2" spellcheck="false" placeholder="e = mc^2"
			onblur={save}
			onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape' || (e.key === 'Enter' && (e.ctrlKey || e.metaKey))) { e.preventDefault(); save(); } }}></textarea>
	{/if}
</div>

<style>
	.eq { flex: 1; min-width: 0; margin: 2px 0; border-radius: var(--radius); }
	.view { padding: 10px 12px; text-align: center; border-radius: var(--radius); cursor: pointer; overflow-x: auto; }
	.view:hover, .editing .view { background: var(--hover); }
	textarea { width: 100%; margin-top: 4px; font: 13px var(--font-mono); }
</style>
