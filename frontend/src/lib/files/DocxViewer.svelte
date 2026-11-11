<script lang="ts">
	/* Word (.docx) documents, converted to HTML in the browser with mammoth. View only. */
	import { Download } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import type { FileRef } from './kind.ts';
	import { safeHtml } from './sanitize.ts';

	let { file }: { file: FileRef } = $props();
	let html = $state('');
	let warnings = $state(0);
	let error = $state('');
	let loading = $state(true);

	onMount(async () => {
		try {
			const [{ default: mammoth }, res] = await Promise.all([import('mammoth/mammoth.browser.js'), fetch(file.url, { cache: 'no-store' })]);
			if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
			const result = await mammoth.convertToHtml({ arrayBuffer: await res.arrayBuffer() });
			warnings = result.messages.filter((m) => m.type === 'warning').length;
			// Links open in a new tab; DOMPurify already drops javascript: URLs.
			html = (await safeHtml(result.value)).replace(/<a href=/g, '<a target="_blank" rel="noopener noreferrer" href=');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
		loading = false;
	});
</script>

<div class="wrap">
	<div class="note">
		<span><b>View only.</b> Word documents are converted for reading: page layout, headers and footers, comments and tracked changes are left out, and edits cannot be saved here.{warnings ? ` (${warnings} part${warnings === 1 ? '' : 's'} could not be converted.)` : ''}</span>
		<a class="btn" href={file.url} download={file.name}><Download size={14} />Download to edit</a>
	</div>
	<div class="scroll">
		{#if loading}<p class="faint center">Converting…</p>
		{:else if error}<div class="empty center"><b>Could not open this document</b>{error}</div>
		{:else}<article class="paper">{@html html}</article>{/if}
	</div>
</div>

<style>
	.wrap { height: 100%; display: flex; flex-direction: column; min-height: 0; }
	.note { display: flex; align-items: center; gap: 12px; padding: 7px 12px; font-size: 12.5px; color: var(--text-2); border-bottom: 1px solid var(--border); background: color-mix(in srgb, var(--c-blue) 10%, var(--bg)); flex: none; }
	.note span { flex: 1; }
	.note b { color: var(--text); font-weight: 600; }
	.scroll { flex: 1; overflow: auto; padding: 28px 16px 60px; background: var(--surface-2); }
	.center { text-align: center; margin: 40px auto; max-width: 460px; }
	.paper { max-width: 800px; margin: 0 auto; padding: 56px 64px; background: #fff; color: #1d1d1b; border-radius: 4px; box-shadow: 0 2px 14px rgba(0, 0, 0, 0.18); font: 15px/1.6 var(--font-serif); overflow-wrap: anywhere; }
	.paper :global(h1), .paper :global(h2), .paper :global(h3) { font-family: var(--font-sans); line-height: 1.25; margin: 1.2em 0 0.5em; }
	.paper :global(h1) { font-size: 1.8em; }
	.paper :global(h2) { font-size: 1.4em; }
	.paper :global(:first-child) { margin-top: 0; }
	.paper :global(table) { border-collapse: collapse; margin: 1em 0; }
	.paper :global(td), .paper :global(th) { border: 1px solid #bbb; padding: 4px 8px; vertical-align: top; }
	.paper :global(img) { max-width: 100%; height: auto; }
	.paper :global(a) { color: #2f63b8; }
	@media (max-width: 700px) { .paper { padding: 28px 22px; } }
</style>
