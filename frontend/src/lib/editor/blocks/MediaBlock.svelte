<script lang="ts">
	import { Download, Eye, EyeOff, FileText, FolderOpen, Image, Music, Paperclip, Upload, Video } from '@lucide/svelte';
	import LibraryPicker from '#lib/components/LibraryPicker.svelte';
	import { tick } from 'svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { Block } from '#lib/types.ts';
	import { fileSize } from '#lib/util.ts';
	import { getEditor } from '../context';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	let url = $state('');
	let busy = $state(false);
	let zoomed = $state(false);
	let picker = $state<HTMLInputElement>();
	let library = $state(false);

	const meta = {
		image: { icon: Image, accept: 'image/*', noun: 'image' },
		video: { icon: Video, accept: 'video/*', noun: 'video' },
		audio: { icon: Music, accept: 'audio/*', noun: 'audio file' },
		file: { icon: Paperclip, accept: '', noun: 'file' }
	} as const;
	let m = $derived(meta[block.type as keyof typeof meta]);
	let p = $derived(block.props);
	let isPdf = $derived(block.type === 'file' && (p.mime === 'application/pdf' || /\.pdf($|\?)/i.test(p.url ?? '')));

	async function upload(file: File | undefined) {
		if (!file) return;
		busy = true;
		try {
			await ed.uploadInto(block.id, file);
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	function embed() {
		const u = url.trim();
		if (!u) return;
		ed.doc.setProps(block.id, { url: u, name: u.split('/').pop()?.split('?')[0] || u });
	}

	$effect(() => {
		if (ed.fresh.id === block.id) {
			ed.fresh.id = null;
			tick().then(() => picker?.click());
		}
	});
</script>

{#if !p.url}
	<div class="setup">
		<m.icon size={16} strokeWidth={1.75} />
		<input type="file" hidden bind:this={picker} accept={m.accept} onchange={(e) => upload(e.currentTarget.files?.[0])} />
		<button class="btn" disabled={busy} onclick={() => picker?.click()}><Upload size={14} />{busy ? 'Uploading…' : `Upload ${m.noun}`}</button>
		<button class="btn ghost" onclick={() => (library = true)}><FolderOpen size={14} />Choose from files</button>
		<form onsubmit={(e) => { e.preventDefault(); embed(); }}>
			<input class="input" bind:value={url} placeholder="…or paste a link" onkeydown={(e) => e.stopPropagation()} />
		</form>
	</div>
{:else if block.type === 'image'}
	<figure>
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
		<img src={p.url} alt={p.caption || p.name || ''} loading="lazy" onclick={() => (zoomed = true)} />
		<input class="caption" value={p.caption ?? ''} placeholder="Add a caption" onkeydown={(e) => e.stopPropagation()}
			onchange={(e) => ed.doc.setProps(block.id, { caption: e.currentTarget.value })} />
	</figure>
	{#if zoomed}
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
		<div class="lightbox" onclick={() => (zoomed = false)}><img src={p.url} alt={p.caption || ''} /></div>
	{/if}
{:else if block.type === 'video'}
	<figure><!-- svelte-ignore a11y_media_has_caption --><video src={p.url} controls preload="metadata"></video></figure>
{:else if block.type === 'audio'}
	<div class="audio">
		<span class="name truncate"><Music size={14} strokeWidth={1.75} />{p.name}</span>
		<audio src={p.url} controls preload="metadata"></audio>
	</div>
{:else}
	<div class="filewrap">
		<div class="file">
			<FileText size={16} strokeWidth={1.75} />
			<a class="truncate fname" href={p.url} target="_blank" rel="noopener">{p.name || p.url}</a>
			{#if p.size}<span class="faint">{fileSize(p.size)}</span>{/if}
			{#if isPdf}
				<button class="icon-btn" title={p.preview === false ? 'Show PDF' : 'Hide PDF'} onclick={() => ed.doc.setProps(block.id, { preview: p.preview === false })}>
					{#if p.preview === false}<Eye size={14} />{:else}<EyeOff size={14} />{/if}
				</button>
			{/if}
			<a class="icon-btn" href={p.url} download={p.name} title="Download"><Download size={14} /></a>
		</div>
		{#if isPdf && p.preview !== false}
			<iframe class="pdf" src={p.url} title={p.name || 'PDF'} loading="lazy"></iframe>
		{/if}
	</div>
{/if}
{#if library}
	<LibraryPicker accept={m.accept} onclose={() => (library = false)}
		onpick={(f) => { library = false; ed.doc.setProps(block.id, { url: f.url, name: f.name, size: f.size, mime: f.mime }); }} />
{/if}

<style>
	.setup { flex: 1; display: flex; align-items: center; gap: 10px; margin: 3px 0; padding: 8px 10px; border: 1px dashed var(--border-strong); border-radius: var(--radius); color: var(--text-2); flex-wrap: wrap; }
	.setup form { flex: 1; min-width: 140px; display: flex; }
	.setup .input { flex: 1; }
	figure { flex: 1; min-width: 0; margin: 4px 0; }
	img, video { display: block; max-width: 100%; max-height: 70vh; border-radius: var(--radius); }
	figure img { cursor: zoom-in; }
	.caption { width: 100%; margin-top: 4px; border: 0; outline: 0; background: none; color: var(--text-2); font-size: 12.5px; padding: 0; }
	.caption:placeholder-shown { opacity: 0; }
	figure:hover .caption, .caption:focus { opacity: 1; }
	.audio { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; margin: 3px 0; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); }
	.audio .name { display: flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 12.5px; }
	audio { width: 100%; height: 34px; }
	.filewrap { flex: 1; min-width: 0; margin: 3px 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
	.file { display: flex; align-items: center; gap: 10px; padding: 5px 6px 5px 10px; color: var(--text); }
	.fname { flex: 1; text-decoration: none; }
	.fname:hover { color: var(--accent); }
	.pdf { display: block; width: 100%; height: min(75vh, 720px); border: 0; border-top: 1px solid var(--border); background: #fff; }
	.lightbox { position: fixed; inset: 0; z-index: 940; display: grid; place-items: center; padding: 24px; background: rgba(0, 0, 0, 0.82); cursor: zoom-out; animation: fade 0.12s; }
	.lightbox img { max-width: 100%; max-height: 100%; border-radius: 4px; }
</style>
