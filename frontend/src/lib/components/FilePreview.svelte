<script lang="ts">
	/* Opens a file in the right viewer: images full-bleed; PDFs, text/Markdown/code and Word
	   documents in a themed sheet; audio and video hand off to the app-wide player. */
	import { Download, FileText, X } from '@lucide/svelte';
	import DocxViewer from '#lib/files/DocxViewer.svelte';
	import PdfViewer from '#lib/files/PdfViewer.svelte';
	import TextEditor from '#lib/files/TextEditor.svelte';
	import { fileKind, type FileRef } from '#lib/files/kind.ts';
	import { player } from '#lib/files/player.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize } from '#lib/util.ts';

	let { file, onclose, onchange }: { file: FileRef; onclose: () => void; onchange?: () => void } = $props();
	let kind = $derived(fileKind(file));
	let dirty = $state(false);
	let sheet = $derived(['pdf', 'markdown', 'text', 'docx', 'office'].includes(kind));

	// Media plays in the persistent player instead of this overlay.
	$effect(() => {
		if (kind === 'audio' || kind === 'video') {
			player.open(file);
			onclose();
		}
	});

	async function close() {
		if (dirty && !(await ui.confirm({ title: 'Discard unsaved changes?', message: `Your edits to “${file.name}” have not been saved.`, confirmLabel: 'Discard', danger: true }))) return;
		onclose();
	}
	function keydown(e: KeyboardEvent) {
		// Let the viewer inside handle Escape first (closing its own popovers); it marks the event.
		if (e.key === 'Escape') setTimeout(() => !e.defaultPrevented && !ui.confirmState && close());
	}
</script>

<svelte:window onkeydown={keydown} />

{#if kind !== 'audio' && kind !== 'video'}
	<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
	<div class="overlay" class:sheet onclick={(e) => e.target === e.currentTarget && close()}>
		{#if sheet}
			<div class="panel" role="dialog" aria-label={file.name}>
				<div class="head">
					<FileText size={15} class="faint" />
					<span class="truncate name">{file.name}</span>
					{#if file.size}<span class="faint size">{fileSize(file.size)}</span>{/if}
					<span class="grow"></span>
					<a class="icon-btn" href={file.url} download={file.name} title="Download"><Download size={15} /></a>
					<button class="icon-btn" title="Close (Esc)" onclick={close}><X size={16} /></button>
				</div>
				<div class="body">
					{#if kind === 'pdf'}<PdfViewer {file} onsaved={onchange} />
					{:else if kind === 'markdown' || kind === 'text'}<TextEditor {file} bind:dirty onsaved={onchange} />
					{:else if kind === 'docx'}<DocxViewer {file} />
					{:else}
						<div class="none">
							<b>This document can't be shown here</b>
							<p class="faint">Kern can view PDF, Word (.docx), Markdown, text and code files. Other office formats (spreadsheets, presentations, older .doc files) can only be downloaded and opened in another app.</p>
							<a class="btn primary" href={file.url} download={file.name}><Download size={14} />Download</a>
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<div class="bar">
				<span class="truncate">{file.name}</span>
				<a class="icon-btn" href={file.url} download={file.name} title="Download"><Download size={15} /></a>
				<button class="icon-btn" title="Close (Esc)" onclick={close}><X size={16} /></button>
			</div>
			<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
			<div class="stage" onclick={(e) => e.target === e.currentTarget && close()}>
				{#if kind === 'image'}<img src={file.url} alt={file.name} />
				{:else}<div class="none dark"><p>No preview for this file type.</p><a class="btn primary" href={file.url} download={file.name}><Download size={14} />Download</a></div>{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.overlay { position: fixed; inset: 0; z-index: 940; display: flex; flex-direction: column; background: rgba(0, 0, 0, 0.85); animation: fade 0.12s; }
	.overlay.sheet { background: rgba(0, 0, 0, 0.55); padding: 18px; }
	.panel { flex: 1; min-height: 0; display: flex; flex-direction: column; max-width: 1400px; width: 100%; margin: 0 auto; background: var(--bg); color: var(--text); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow); animation: pop 0.14s var(--ease); }
	.head { display: flex; align-items: center; gap: 8px; height: 42px; padding: 0 8px 0 14px; border-bottom: 1px solid var(--border); flex: none; }
	.name { font-weight: 550; }
	.size { font-size: 12px; white-space: nowrap; }
	.grow { flex: 1; }
	.body { flex: 1; min-height: 0; position: relative; }
	.bar { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 12px; color: #eee; }
	.bar span { flex: 1; }
	.bar :global(.icon-btn) { color: #ddd; }
	.stage { flex: 1; min-height: 0; display: grid; place-items: center; padding: 0 20px 20px; }
	img { max-width: 100%; max-height: 100%; border-radius: 4px; }
	.none { max-width: 460px; margin: 60px auto; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 8px; }
	.none.dark { color: #ddd; }
	@media (max-width: 700px) { .overlay.sheet { padding: 0; } .panel { border-radius: 0; } }
</style>
