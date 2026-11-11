<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { fileSize } from '#lib/util.ts';

	interface F { id: string; url: string; name: string; mime: string; size: number }
	let { accept = '', onpick, onclose }: { accept?: string; onpick: (f: F) => void; onclose: () => void } = $props();
	let list = $state<F[]>([]);
	let q = $state('');
	let type = $derived(accept.startsWith('image') ? 'image' : accept.startsWith('video') ? 'video' : accept.startsWith('audio') ? 'audio' : '');

	onMount(load);
	async function load() {
		list = await api.get<F[]>('/library' + qs({ type, q, usage: 0 })).catch(() => []);
	}
	$effect(() => {
		void q;
		const t = setTimeout(load, 150);
		return () => clearTimeout(t);
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && onclose()} onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') onclose(); }}>
	<div class="dialog popover" role="dialog" aria-label="Choose a file">
		<div class="head"><b>Choose from your files</b><input class="input" bind:value={q} placeholder="Search files…" /></div>
		<div class="grid">
			{#each list as f (f.id)}
				<button class="item" onclick={() => onpick(f)} title={f.name}>
					{#if f.mime.startsWith('image/')}<img src={f.url} alt="" loading="lazy" />{:else}<span class="ico"><FileText size={22} /></span>{/if}
					<span class="name truncate">{f.name}</span><span class="faint sz">{fileSize(f.size)}</span>
				</button>
			{:else}<p class="faint">No files yet.</p>{/each}
		</div>
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 860; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); }
	.dialog { width: min(720px, 100%); max-height: 80vh; display: flex; flex-direction: column; padding: 14px; gap: 10px; }
	.head { display: flex; align-items: center; gap: 12px; }
	.head .input { flex: 1; }
	.grid { overflow-y: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; }
	.item { display: flex; flex-direction: column; gap: 3px; padding: 6px; border: 1px solid var(--border); border-radius: var(--radius); text-align: left; }
	.item:hover { border-color: var(--accent); }
	.item img, .ico { width: 100%; height: 86px; object-fit: cover; border-radius: 4px; background: var(--surface-2); display: grid; place-items: center; color: var(--text-3); }
	.name { font-size: 12.5px; }
	.sz { font-size: 11px; }
</style>
