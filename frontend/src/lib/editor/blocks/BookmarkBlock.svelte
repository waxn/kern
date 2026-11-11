<script lang="ts">
	import { Bookmark, ExternalLink } from '@lucide/svelte';
	import { tick } from 'svelte';
	import type { Block } from '#lib/types.ts';
	import { getEditor } from '../context';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	let url = $state('');
	let input = $state<HTMLInputElement>();

	let host = $derived.by(() => {
		try {
			return new URL(block.props.url).hostname.replace(/^www\./, '');
		} catch {
			return '';
		}
	});

	function save() {
		let u = url.trim();
		if (!u) return;
		if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = 'https://' + u;
		ed.doc.setProps(block.id, { url: u });
	}

	$effect(() => {
		if (ed.fresh.id === block.id) {
			ed.fresh.id = null;
			tick().then(() => input?.focus());
		}
	});
</script>

{#if block.props.url}
	<div class="bm">
		<Bookmark size={16} strokeWidth={1.75} />
		<div class="body">
			<input class="title" value={block.props.title ?? ''} placeholder={host || 'Title'}
				onkeydown={(e) => e.stopPropagation()}
				onchange={(e) => ed.doc.setProps(block.id, { title: e.currentTarget.value })} />
			<a class="url truncate" href={block.props.url} target="_blank" rel="noopener noreferrer">{block.props.url}</a>
		</div>
		<a class="icon-btn" href={block.props.url} target="_blank" rel="noopener noreferrer" title="Open link"><ExternalLink size={14} /></a>
	</div>
{:else}
	<form class="setup" onsubmit={(e) => { e.preventDefault(); save(); }}>
		<Bookmark size={15} strokeWidth={1.75} />
		<input class="input" bind:this={input} bind:value={url} placeholder="Paste a web address…" onkeydown={(e) => e.stopPropagation()} />
		<button class="btn" type="submit">Save bookmark</button>
	</form>
{/if}

<style>
	.bm, .setup { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; margin: 3px 0; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); color: var(--text-2); }
	.bm:hover { border-color: var(--border-strong); }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.title { border: 0; outline: 0; background: none; color: var(--text); font-weight: 550; padding: 0; }
	.url { font-size: 12px; color: var(--text-3); text-decoration: none; }
	.url:hover { color: var(--accent); }
	.setup .input { flex: 1; }
</style>
