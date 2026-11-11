<script lang="ts">
	import { download } from '#lib/data/download.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';

	let { id, onclose }: { id: string; onclose: () => void } = $props();
	let doc = $derived(ws.docs[id]);
	let children = $state(false);
	let hasChildren = $derived(Object.values(ws.docs).some((d) => d.parent === id));

	const formats: [string, string, string][] = [
		['md', 'Markdown', 'Plain text, opens anywhere. Sub-pages and attachments come as a zip.'],
		['html', 'HTML', 'A styled, standalone web page.'],
		['pdf', 'PDF', 'Opens a print view; choose “Save as PDF”.'],
		['json', 'Kern JSON', 'Everything, including properties and databases; can be imported back.'],
		['opml', 'OPML', 'The outline, for other outliners.']
	];

	function go(fmt: string) {
		if (fmt === 'pdf') {
			window.open(`/api/export/document/${id}?as=print`, '_blank');
		} else download(`/export/document/${id}?as=${fmt}${children ? '&children=1' : ''}`);
		onclose();
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && onclose()} onkeydown={(e) => e.key === 'Escape' && onclose()}>
	<div class="dialog popover" role="dialog" aria-label="Export">
		<h2>Export “{doc?.title || 'Untitled'}”</h2>
		{#each formats as [f, label, hint] (f)}
			<button class="fmt" onclick={() => go(f)}><b>{label}</b><span>{hint}</span></button>
		{/each}
		{#if doc?.database}
			<button class="fmt" onclick={() => { download(`/export/database/${doc.database}?as=csv`); onclose(); }}><b>CSV</b><span>The database's entries and properties, for spreadsheets.</span></button>
		{/if}
		{#if hasChildren}
			<label class="check"><input type="checkbox" bind:checked={children} /> Include sub-pages</label>
		{/if}
		<div class="foot"><button class="btn ghost" onclick={onclose}>Cancel</button></div>
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); }
	.dialog { width: min(440px, 100%); padding: 16px; display: flex; flex-direction: column; gap: 4px; }
	h2 { margin: 0 0 8px; font-size: 15px; }
	.fmt { display: flex; flex-direction: column; align-items: flex-start; padding: 8px 10px; border-radius: var(--radius); text-align: left; }
	.fmt:hover { background: var(--hover); }
	.fmt span { font-size: 12px; color: var(--text-3); }
	.check { display: flex; align-items: center; gap: 6px; margin: 8px 10px 0; color: var(--text-2); }
	.check input { accent-color: var(--accent); }
	.foot { display: flex; justify-content: flex-end; margin-top: 8px; }
</style>
