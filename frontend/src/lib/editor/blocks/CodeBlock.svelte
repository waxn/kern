<script lang="ts">
	import { Check, Copy } from '@lucide/svelte';
	import type { Block } from '#lib/types.ts';
	import { escapeHtml } from '#lib/util.ts';

	let { block }: { block: Block } = $props();
	let copied = $state(false);

	function unescape(html: string): string {
		const t = document.createElement('textarea');
		t.innerHTML = html;
		return t.value;
	}

	// Code is stored as escaped plain text; the DOM holds the raw text.
	function plain(node: HTMLElement, value: string) {
		node.textContent = unescape(value);
		return {
			update(v: string) {
				if (escapeHtml(node.innerText.replace(/\n$/, '')) !== v) node.textContent = unescape(v);
			}
		};
	}

	async function copy() {
		await navigator.clipboard?.writeText(unescape(block.html));
		copied = true;
		setTimeout(() => (copied = false), 1200);
	}
</script>

<div class="code">
	<pre data-editable data-plain contenteditable="plaintext-only" spellcheck="false" use:plain={block.html}></pre>
	<button class="icon-btn copy" contenteditable="false" title="Copy code" onclick={copy}>
		{#if copied}<Check size={14} />{:else}<Copy size={14} />{/if}
	</button>
</div>

<style>
	.code { position: relative; flex: 1; min-width: 0; margin: 4px 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
	pre { margin: 0; padding: 12px 14px; min-height: 1.5em; font: 13px/1.55 var(--font-mono); white-space: pre; overflow-x: auto; outline: none; tab-size: 2; }
	.copy { position: absolute; top: 6px; right: 6px; opacity: 0; background: var(--surface); }
	.code:hover .copy { opacity: 1; }
</style>
