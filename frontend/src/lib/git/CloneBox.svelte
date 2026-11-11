<script lang="ts">
	import { Check, Copy } from '@lucide/svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { cloneUrl } from './types.ts';

	let { name, compact = false }: { name: string; compact?: boolean } = $props();
	let url = $derived(cloneUrl(name));
	let copied = $state(false);

	async function copy(e: MouseEvent) {
		e.stopPropagation();
		e.preventDefault();
		try {
			await navigator.clipboard.writeText(url);
			copied = true;
			setTimeout(() => (copied = false), 1400);
		} catch {
			ui.toast(url);
		}
	}
</script>

<div class="clone" class:compact>
	<span class="tag">HTTP</span>
	<input readonly value={url} onclick={(e) => { e.stopPropagation(); e.currentTarget.select(); }} aria-label="Clone URL" />
	<button class="icon-btn" title="Copy clone URL" onclick={copy}>
		{#if copied}<Check size={14} />{:else}<Copy size={14} />{/if}
	</button>
</div>

<style>
	.clone { display: flex; align-items: center; height: 30px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--bg); min-width: 0; }
	.clone.compact { height: 26px; }
	.tag { padding: 0 8px; align-self: stretch; display: grid; place-items: center; font-size: 10.5px; font-weight: 650; letter-spacing: 0.04em; color: var(--text-3); border-right: 1px solid var(--border); }
	input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; padding: 0 8px; font: 12px var(--font-mono); color: var(--text-2); }
	.icon-btn { margin-right: 2px; }
</style>
