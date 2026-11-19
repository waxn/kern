<script lang="ts">
	import { Check, Copy } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { activeCloneUrl, gitSsh, loadSshInfo, setCloneMode } from './sshConfig.svelte.ts';
	import { cloneUrl } from './types.ts';

	// Public repositories show the owner-qualified URL, which works anonymously; private ones keep
	// the classic URL, which always asks you to sign in as the owner.
	let { name, compact = false, owner = '', isPublic = false }: { name: string; compact?: boolean; owner?: string; isPublic?: boolean } = $props();
	onMount(() => loadSshInfo());
	let ssh = $derived(!!gitSsh.info?.enabled);
	let useSsh = $derived(ssh && gitSsh.mode === 'ssh');
	let url = $derived(activeCloneUrl(name, cloneUrl(name, isPublic ? owner : undefined)));
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
	{#if ssh}
		<span class="tags" role="group" aria-label="Clone protocol">
			<button class:on={!useSsh} onclick={(e) => { e.stopPropagation(); setCloneMode('http'); }}>HTTP</button>
			<button class:on={useSsh} onclick={(e) => { e.stopPropagation(); setCloneMode('ssh'); }}>SSH</button>
		</span>
	{:else}
		<span class="tag">HTTP</span>
	{/if}
	<input readonly value={url} onclick={(e) => { e.stopPropagation(); e.currentTarget.select(); }} aria-label="Clone URL" />
	<button class="icon-btn" title="Copy clone URL" onclick={copy}>
		{#if copied}<Check size={14} />{:else}<Copy size={14} />{/if}
	</button>
</div>

<style>
	.clone { display: flex; align-items: center; height: 30px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--bg); min-width: 0; }
	.clone.compact { height: 26px; }
	.tag { padding: 0 8px; align-self: stretch; display: grid; place-items: center; font-size: 10.5px; font-weight: 650; letter-spacing: 0.04em; color: var(--text-3); border-right: 1px solid var(--border); }
	.tags { display: flex; align-self: stretch; border-right: 1px solid var(--border); }
	.tags button { padding: 0 7px; font-size: 10.5px; font-weight: 650; letter-spacing: 0.04em; color: var(--text-3); }
	.tags button.on { color: var(--text); background: var(--active); }
	input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; padding: 0 8px; font: 12px var(--font-mono); color: var(--text-2); }
	.icon-btn { margin-right: 2px; }
</style>
