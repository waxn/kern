<script lang="ts">
	// Push mirrors: after every push, copy branches and tags to another remote (e.g. GitHub).
	import { onDestroy, onMount } from 'svelte';
	import { Check, CircleAlert, Pencil, Plus, RefreshCw, Trash2, UploadCloud } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import Toggle from '#lib/auth/Toggle.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fullDate, relTime } from '#lib/util.ts';
	import type { GitMirror, RepoDetail } from './types.ts';

	let { repo }: { repo: RepoDetail } = $props();

	let mirrors = $state<GitMirror[]>([]);
	let loaded = $state(false);
	let editing = $state<number | 'new' | null>(null);
	let busy = $state(false);
	let form = $state({ url: '', username: '', secret: '', clear_secret: false, only_protected: false, branch_filter: '', enabled: true });
	let timer: ReturnType<typeof setTimeout> | undefined;

	const base = $derived(`/git/repos/${repo.name}/mirrors`);

	async function load() {
		try {
			mirrors = (await api.get<{ mirrors: GitMirror[] }>(base)).mirrors;
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
		clearTimeout(timer);
		if (mirrors.some((m) => m.syncing)) timer = setTimeout(load, 1500);
	}
	onMount(load);
	onDestroy(() => clearTimeout(timer));

	function open(m: GitMirror | null) {
		editing = m ? m.id : 'new';
		form = m
			? { url: m.url, username: m.username, secret: '', clear_secret: false, only_protected: m.only_protected, branch_filter: m.branch_filter, enabled: m.enabled }
			: { url: '', username: '', secret: '', clear_secret: false, only_protected: false, branch_filter: '', enabled: true };
	}

	async function save(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		try {
			const body: Record<string, unknown> = { ...form };
			if (!form.secret) delete body.secret;
			if (editing === 'new') await api.post(base, body);
			else await api.patch(`${base}/${editing}`, body);
			editing = null;
			await load();
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function toggle(m: GitMirror, enabled: boolean) {
		try {
			await api.patch(`${base}/${m.id}`, { enabled });
		} catch (e) {
			ui.error(e);
		}
		await load();
	}

	async function sync(m: GitMirror) {
		try {
			await api.post(`${base}/${m.id}/sync`);
			ui.toast('Sync started');
		} catch (e) {
			ui.error(e);
		}
		await load();
	}

	async function remove(m: GitMirror) {
		if (!(await ui.confirm({ title: 'Remove this mirror?', message: `${m.url} stays as it is; Kern just stops pushing to it.`, confirmLabel: 'Remove', danger: true }))) return;
		try {
			await api.del(`${base}/${m.id}`);
		} catch (e) {
			ui.error(e);
		}
		await load();
	}
</script>

<section class="set">
	<h3><UploadCloud size={15} />Push mirrors</h3>
	<p class="muted">After every push, copy this repository's branches and tags to another remote, such as GitHub, so its CI can run there too. Branches and tags deleted here are deleted there. The token is stored encrypted and never shown again.</p>

	{#if loaded && mirrors.length}
		<div class="box">
			{#each mirrors as m (m.id)}
				<div class="item">
					<div class="top">
						<code class="url" title={m.url}>{m.url}</code>
						<span class="grow"></span>
						<button class="btn" disabled={!m.enabled || m.syncing} onclick={() => sync(m)}><RefreshCw size={13} class={m.syncing ? 'spin' : ''} />{m.syncing ? 'Syncing…' : 'Sync now'}</button>
						<Toggle checked={m.enabled} label="Mirror enabled" onchange={(v) => toggle(m, v)} />
						<button class="icon-btn" title="Edit" onclick={() => open(m)}><Pencil size={14} /></button>
						<button class="icon-btn" title="Remove" onclick={() => remove(m)}><Trash2 size={14} /></button>
					</div>
					<div class="status">
						{#if m.last_error}
							<span class="bad"><CircleAlert size={13} />Last attempt {relTime(m.last_attempt)} failed</span>
						{:else if m.last_success}
							<span class="good" title={fullDate(m.last_success)}><Check size={13} />Synced {relTime(m.last_success)}</span>
						{:else}
							<span class="muted">Not synced yet</span>
						{/if}
						{#if m.last_success && m.last_error}<span class="muted" title={fullDate(m.last_success)}>· last success {relTime(m.last_success)}</span>{/if}
						{#if m.only_protected}<span class="muted">· protected branches only</span>{/if}
						{#if m.branch_filter}<span class="muted">· branches: {m.branch_filter}</span>{/if}
					</div>
					{#if m.last_error}<pre class="err">{m.last_error}</pre>{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if editing !== null}
		<form class="form" onsubmit={save}>
			<label>Remote URL<input class="input" type="url" placeholder="https://github.com/you/repo.git" bind:value={form.url} required autocomplete="off" /></label>
			<div class="two">
				<label>Username<input class="input" bind:value={form.username} placeholder="your GitHub username" autocomplete="off" /></label>
				<label>Token or password<input class="input" type="password" bind:value={form.secret} autocomplete="new-password"
					placeholder={editing !== 'new' && mirrors.find((m) => m.id === editing)?.has_secret ? 'unchanged' : 'personal access token'} /></label>
			</div>
			{#if editing !== 'new' && mirrors.find((m) => m.id === editing)?.has_secret}
				<label class="chk"><input type="checkbox" bind:checked={form.clear_secret} />Remove the stored token</label>
			{/if}
			<label class="chk"><input type="checkbox" bind:checked={form.only_protected} />Only push protected branches (tags always)</label>
			<label>Only these branches <span class="muted">(optional, space separated, <code>*</code> allowed)</span><input class="input" bind:value={form.branch_filter} placeholder="main release/*" /></label>
			<div class="actions">
				<button class="btn primary" disabled={busy || !form.url.trim()}>{editing === 'new' ? 'Add mirror' : 'Save'}</button>
				<button type="button" class="btn ghost" onclick={() => (editing = null)}>Cancel</button>
			</div>
		</form>
	{:else}
		<button class="btn" onclick={() => open(null)}><Plus size={13} />Add mirror</button>
	{/if}
</section>

<style>
	.set { margin-bottom: 28px; }
	.set :global(h3) { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.set :global(.muted) { margin: 0; font-size: 13px; color: var(--text-3); }
	p.muted { margin-bottom: 10px; }
	.box { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; }
	.item { padding: 8px 10px; }
	.item + .item { border-top: 1px solid var(--border); }
	.top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.url { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; min-width: 0; }
	.grow { flex: 1; }
	.status { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12.5px; margin-top: 4px; }
	.status > span { display: inline-flex; align-items: center; gap: 4px; }
	.good { color: var(--text-2); }
	.bad { color: var(--danger); }
	.err { margin: 6px 0 0; padding: 6px 8px; border-radius: var(--radius); background: var(--code-bg); font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 140px; overflow: auto; }
	.form { display: flex; flex-direction: column; gap: 10px; max-width: 520px; }
	.form label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
	.form label.chk { flex-direction: row; align-items: center; gap: 6px; }
	.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
	.actions { display: flex; gap: 8px; }
	@media (max-width: 560px) { .two { grid-template-columns: 1fr; } }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
</style>
