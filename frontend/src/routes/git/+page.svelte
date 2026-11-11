<script lang="ts">
	import { GitBranch, GitCommitHorizontal, HardDrive, KeyRound, Plus, Search, Trash2, Upload } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import CloneBox from '#lib/git/CloneBox.svelte';
	import { cloneUrl, type Repo } from '#lib/git/types.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, relTime } from '#lib/util.ts';

	let repos = $state<Repo[]>([]);
	let loaded = $state(false);
	let q = $state('');
	let creating = $state(false);
	let name = $state('');
	let description = $state('');
	let busy = $state(false);
	let nameInput = $state<HTMLInputElement>();
	let showAuth = $state(false);
	let auth = $state<{ mode: 'off' | 'push' | 'all'; has_password: boolean }>({ mode: 'off', has_password: false });
	let password = $state('');

	const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
	let nameError = $derived(
		!name ? '' : !NAME_RE.test(name) ? 'Letters, digits, “.”, “-” and “_” only; start with a letter or digit.'
			: /\.git$/i.test(name) ? 'Leave off the “.git” — it is added to the clone URL.'
			: name.includes('..') ? 'No “..” please.'
			: repos.some((r) => r.name === name) ? 'A repository with that name already exists.' : ''
	);

	async function load() {
		try {
			[repos, auth] = await Promise.all([api.get<Repo[]>('/git/repos'), api.get<typeof auth>('/git/config')]);
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);

	let shown = $derived(q ? repos.filter((r) => (r.name + ' ' + r.description).toLowerCase().includes(q.toLowerCase())) : repos);
	let totalSize = $derived(repos.reduce((n, r) => n + r.size, 0));

	function startCreate() {
		creating = true;
		name = '';
		description = '';
		queueMicrotask(() => nameInput?.focus());
	}

	async function create(e: SubmitEvent) {
		e.preventDefault();
		if (!name || nameError || busy) return;
		busy = true;
		try {
			const r = await api.post<Repo>('/git/repos', { name, description });
			creating = false;
			open(`/git/${r.name}`);
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function remove(r: Repo, e: MouseEvent) {
		e.stopPropagation();
		const ok = await ui.confirm({
			title: `Delete “${r.name}”?`,
			message: `This permanently deletes the repository and all of its history (${fileSize(r.size)}). Clones elsewhere are not affected. This cannot be undone.`,
			confirmLabel: 'Delete repository', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/git/repos/${r.name}`);
			repos = repos.filter((x) => x.name !== r.name);
			ui.toast(`Deleted ${r.name}`);
		} catch (err) {
			ui.error(err);
		}
	}

	async function saveAuth(mode: typeof auth.mode) {
		try {
			auth = await api.put<typeof auth>('/git/config', { mode, password: password || undefined });
			password = '';
			ui.toast(mode === 'off' ? 'Git access is open (localhost only)' : 'Git password saved');
		} catch (err) {
			ui.error(err);
		}
	}
</script>

<div class="page-scroll">
	<div class="page wide">
		<div class="titlebar">
			<h1>Git</h1>
			{#if repos.length}<span class="faint">{repos.length} repositor{repos.length === 1 ? 'y' : 'ies'} · {fileSize(totalSize)}</span>{/if}
			<span class="grow"></span>
			<button class="btn ghost" class:on={showAuth} onclick={() => (showAuth = !showAuth)} title="Password for git clients">
				<KeyRound size={14} />{auth.mode === 'off' ? 'Access' : auth.mode === 'push' ? 'Push protected' : 'Protected'}
			</button>
			<button class="btn primary" onclick={startCreate}><Plus size={14} />New repository</button>
		</div>
		<p class="lede">Host your own git repositories. Clone, push and pull over HTTP from any git client.</p>

		{#if showAuth}
			<div class="panel">
				<div class="ptext">
					<b>Git client access</b>
					<span class="muted">Kern listens on localhost only, so by default anyone on this machine can clone and push. Set a password to require it for pushes, or for everything. Git asks for a username — any name works.</span>
				</div>
				<div class="prow">
					<div class="seg">
						{#each [['off', 'Open'], ['push', 'Password to push'], ['all', 'Password for all']] as [m, label] (m)}
							<button class:on={auth.mode === m} onclick={() => saveAuth(m as typeof auth.mode)} disabled={m !== 'off' && !auth.has_password && !password}>{label}</button>
						{/each}
					</div>
					<input class="input" type="password" autocomplete="new-password" placeholder={auth.has_password ? 'Change password…' : 'Set a password…'} bind:value={password} />
					<button class="btn" disabled={password.length < 6} onclick={() => saveAuth(auth.mode === 'off' ? 'push' : auth.mode)}>Save</button>
				</div>
			</div>
		{/if}

		{#if creating}
			<form class="panel create" onsubmit={create}>
				<label>
					<span>Name</span>
					<input class="input mono" bind:this={nameInput} bind:value={name} placeholder="my-project" maxlength="64" spellcheck="false" autocomplete="off" />
				</label>
				<label class="desc">
					<span>Description <em class="faint">optional</em></span>
					<input class="input" bind:value={description} placeholder="What is it?" maxlength="500" />
				</label>
				<div class="actions">
					<button type="button" class="btn ghost" onclick={() => (creating = false)}>Cancel</button>
					<button class="btn primary" disabled={!name || !!nameError || busy}>Create</button>
				</div>
				<p class="hint" class:err={!!nameError}>
					{#if nameError}{nameError}{:else if name}Clone URL: <code>{cloneUrl(name)}</code>{:else}&nbsp;{/if}
				</p>
			</form>
		{/if}

		{#if repos.length > 6}
			<div class="search"><Search size={14} class="faint" /><input bind:value={q} placeholder="Filter repositories…" /></div>
		{/if}

		{#if shown.length}
			<div class="list">
				{#each shown as r (r.name)}
					<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
					<div class="repo" onclick={(e) => open(`/git/${r.name}`, e)}>
						<div class="main">
							<div class="nm">
								<a href="/git/{r.name}" onclick={(e) => { e.preventDefault(); e.stopPropagation(); open(`/git/${r.name}`, e); }}>{r.name}</a>
								{#if r.empty}<span class="chip">empty</span>{/if}
							</div>
							{#if r.description}<p class="d">{r.description}</p>{/if}
							<div class="meta">
								{#if r.last_commit}
									<span title={r.last_commit.subject}><GitCommitHorizontal size={13} />{r.last_commit.subject.length > 60 ? r.last_commit.subject.slice(0, 60) + '…' : r.last_commit.subject}</span>
								{/if}
								{#if r.default_branch}<span><GitBranch size={13} />{r.default_branch}{r.branches > 1 ? ` +${r.branches - 1}` : ''}</span>{/if}
								<span><HardDrive size={13} />{fileSize(r.size)}</span>
								<span><Upload size={13} />{r.last_push ? 'pushed ' + relTime(r.last_push) : 'never pushed'}</span>
							</div>
						</div>
						<div class="side">
							<CloneBox name={r.name} compact />
							<button class="icon-btn" title="Delete repository" onclick={(e) => remove(r, e)}><Trash2 size={14} /></button>
						</div>
					</div>
				{/each}
			</div>
		{:else if loaded}
			<div class="empty">
				{#if q}<b>No repositories match</b>Try another filter.{:else}
					<b>No repositories yet</b>Create one, then push an existing project to it.
					<div><button class="btn primary first" onclick={startCreate}><Plus size={14} />New repository</button></div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.wide { max-width: 1000px; }
	.titlebar { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
	.grow { flex: 1; }
	.btn.on { background: var(--active); color: var(--text); }
	.panel { padding: 14px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: 14px; }
	.ptext { display: flex; flex-direction: column; gap: 2px; margin-bottom: 10px; font-size: 13px; }
	.prow { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
	.prow .input { width: 200px; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 3px 9px; border-radius: 4px; color: var(--text-2); font-size: 12.5px; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.seg button:disabled { opacity: 0.45; }
	.create { display: grid; grid-template-columns: minmax(160px, 1fr) minmax(200px, 2fr) auto; gap: 10px 12px; align-items: end; }
	.create label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 550; color: var(--text-2); }
	.create em { font-style: normal; font-weight: 400; }
	.mono { font-family: var(--font-mono); }
	.actions { display: flex; gap: 6px; }
	.hint { grid-column: 1 / -1; margin: 0; font-size: 12px; color: var(--text-3); }
	.hint.err { color: var(--danger); }
	.hint code { font: 11.5px var(--font-mono); color: var(--text-2); }
	.search { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px; margin-bottom: 10px; border: 1px solid var(--border-strong); border-radius: var(--radius); }
	.search input { flex: 1; border: 0; outline: 0; background: none; }
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.repo { display: flex; gap: 16px; align-items: center; padding: 14px 16px; border-top: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
	.repo:first-child { border-top: 0; }
	.repo:hover { background: var(--hover); }
	.main { flex: 1; min-width: 0; }
	.nm { display: flex; align-items: center; gap: 8px; }
	.nm a { font-size: 15px; font-weight: 600; color: var(--text); text-decoration: none; }
	.nm a:hover { color: var(--accent); }
	.d { margin: 2px 0 0; color: var(--text-2); font-size: 13px; }
	.meta { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; font-size: 12px; color: var(--text-3); }
	.meta span { display: inline-flex; align-items: center; gap: 4px; min-width: 0; }
	.side { display: flex; align-items: center; gap: 4px; width: 330px; flex: none; }
	.side :global(.clone) { flex: 1; }
	.first { margin-top: 12px; }
	@media (max-width: 760px) {
		.repo { flex-direction: column; align-items: stretch; }
		.side { width: auto; }
		.create { grid-template-columns: 1fr; }
	}
</style>
