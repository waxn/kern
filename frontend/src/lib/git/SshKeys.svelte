<script lang="ts">
	// Account SSH keys (all your repositories), or one repository's deploy keys when `repo` is set.
	import { KeyRound, Plus, Trash2 } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { relTime } from '#lib/util.ts';
	import { gitSsh, loadSshInfo } from './sshConfig.svelte.ts';

	interface Key { id: number; title: string; type: string; fingerprint: string; repo: string | null; read_only: boolean; created: string; last_used: string | null }

	let { repo = null }: { repo?: string | null } = $props();
	let base = $derived(repo ? `/git/repos/${repo}/deploy-keys` : '/git/ssh-keys');
	let keys = $state<Key[]>([]);
	let loaded = $state(false);
	let title = $state('');
	let key = $state('');
	let readOnly = $state(true);
	let busy = $state(false);

	async function load() {
		try {
			keys = await api.get<Key[]>(base);
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(() => {
		load();
		loadSshInfo();
	});

	async function add(e: SubmitEvent) {
		e.preventDefault();
		if (busy || !key.trim()) return;
		busy = true;
		try {
			const k = await api.post<Key>(base, { title: title.trim() || 'My key', key: key.trim(), ...(repo ? { read_only: readOnly } : {}) });
			keys = [...keys, k];
			title = key = '';
			ui.toast(`Added ${k.title} (${k.fingerprint})`);
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function remove(k: Key) {
		const ok = await ui.confirm({
			title: `Remove “${k.title}”?`,
			message: 'Clients using this key can no longer sign in.',
			confirmLabel: 'Remove key', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`${base}/${k.id}`);
			keys = keys.filter((x) => x.id !== k.id);
		} catch (err) {
			ui.error(err);
		}
	}
</script>

<section class="set">
	<h3><KeyRound size={15} />{repo ? 'Deploy keys' : 'SSH keys'}</h3>
	<p class="muted">
		{#if repo}A deploy key gives a server or CI job access to this repository only, read-only or with push.
		{:else}Clone and push over SSH without a password. A key here reaches all of your repositories.{/if}
		{#if gitSsh.info && !gitSsh.info.enabled}<b>The SSH service is not running on this server.</b>{/if}
		{#if !repo && gitSsh.info?.fingerprint}Server host key: <code>{gitSsh.info.fingerprint}</code>{/if}
	</p>
	{#if keys.length}
		<div class="box">
			{#each keys as k (k.id)}
				<div class="row">
					<div class="info">
						<b>{k.title}</b>{#if repo}<span class="chip">{k.read_only ? 'read-only' : 'read/write'}</span>{/if}
						<code class="fp">{k.fingerprint}</code>
						<span class="faint">{k.type.replace('ssh-', '')} · added {relTime(k.created)} · {k.last_used ? 'used ' + relTime(k.last_used) : 'never used'}</span>
					</div>
					<button class="icon-btn" title="Remove key" onclick={() => remove(k)}><Trash2 size={14} /></button>
				</div>
			{/each}
		</div>
	{:else if loaded}
		<p class="faint none">No keys yet.</p>
	{/if}
	<form class="add" onsubmit={add}>
		<input class="input" placeholder="Title, e.g. Work laptop" bind:value={title} maxlength="80" aria-label="Key title" />
		<textarea class="input mono" rows="3" placeholder="ssh-ed25519 AAAA… (contents of your .pub file)" bind:value={key} spellcheck="false" aria-label="Public key"></textarea>
		<div class="line">
			{#if repo}<label class="chk"><input type="checkbox" bind:checked={readOnly} />Read-only (cannot push)</label>{:else}<span></span>{/if}
			<button class="btn" disabled={!key.trim() || busy}><Plus size={13} />Add key</button>
		</div>
	</form>
</section>

<style>
	.set { margin-bottom: 28px; }
	.set :global(h3) { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.muted { margin: 0 0 10px; font-size: 13px; }
	.box { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; }
	.row { display: flex; align-items: center; gap: 12px; padding: 8px 10px; }
	.row + .row { border-top: 1px solid var(--border); }
	.info { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; font-size: 13px; }
	.fp { font-size: 11.5px; color: var(--text-2); overflow-wrap: anywhere; }
	.info .faint { font-size: 12px; flex-basis: 100%; }
	.none { font-size: 13px; margin: 0 0 10px; }
	.add { display: flex; flex-direction: column; gap: 8px; max-width: 560px; }
	.mono { font: 12px var(--font-mono); resize: vertical; }
	.line { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
	.chk { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--text-2); }
</style>
