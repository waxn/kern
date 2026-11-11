<script lang="ts">
	import { Download, X } from '@lucide/svelte';

	let { file, onclose }: { file: { url: string; name: string; mime: string }; onclose: () => void } = $props();
	let kind = $derived(file.mime.startsWith('image/') ? 'image' : file.mime.startsWith('video/') ? 'video' : file.mime.startsWith('audio/') ? 'audio' : file.mime === 'application/pdf' ? 'pdf' : file.mime.startsWith('text/') ? 'text' : 'other');
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onclick={(e) => e.target === e.currentTarget && onclose()}>
	<div class="bar">
		<span class="truncate">{file.name}</span>
		<a class="icon-btn" href={file.url} download={file.name} title="Download"><Download size={15} /></a>
		<button class="icon-btn" title="Close (Esc)" onclick={onclose}><X size={16} /></button>
	</div>
	<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
	<div class="stage" onclick={(e) => e.target === e.currentTarget && onclose()}>
		{#if kind === 'image'}<img src={file.url} alt={file.name} />
		{:else if kind === 'video'}<!-- svelte-ignore a11y_media_has_caption --><video src={file.url} controls autoplay></video>
		{:else if kind === 'audio'}<audio src={file.url} controls autoplay></audio>
		{:else if kind === 'pdf' || kind === 'text'}<iframe src={file.url} title={file.name}></iframe>
		{:else}<div class="none"><p>No preview for this file type.</p><a class="btn primary" href={file.url} download={file.name}><Download size={14} />Download</a></div>{/if}
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 940; display: flex; flex-direction: column; background: rgba(0, 0, 0, 0.85); animation: fade 0.12s; }
	.bar { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 12px; color: #eee; }
	.bar span { flex: 1; }
	.bar :global(.icon-btn) { color: #ddd; }
	.stage { flex: 1; min-height: 0; display: grid; place-items: center; padding: 0 20px 20px; }
	img, video { max-width: 100%; max-height: 100%; border-radius: 4px; }
	iframe { width: min(1000px, 100%); height: 100%; border: 0; border-radius: 4px; background: #fff; }
	audio { width: min(520px, 100%); }
	.none { text-align: center; color: #ddd; }
</style>
