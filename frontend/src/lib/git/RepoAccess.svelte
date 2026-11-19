<script lang="ts">
	import { Check, Copy, Globe, KeyRound, Lock, Plus, Trash2 } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fullDate, relTime } from '#lib/util.ts';
	import { cloneUrl, type GitToken, type RepoDetail } from './types.ts';

	let { repo, onchange }: { repo: RepoDetail; onchange: (r: RepoDetail) => void } = $props();

	let tokens = $state<GitToken[]>([]);
	let label = $state('');
	let scope = $state<'read' | 'write'>('read');
	let days = $state('');
	let busy = $state(false);
	let fresh = $state<{ token: string; scope: string; label: string } | null>(null);
	let copied = $state('');

	let publicUrl = $derived(cloneUrl(repo.name, repo.owner));
	// Ready to paste: the token is the password, the user name can be anything.
	let tokenUrl = $derived(fresh ? publicUrl.replace('://', `://token:${fresh.token}@`) : '');

	async function load() {
		try {
			tokens = await api.get<GitToken[]>(`/git/repos/${repo.name}/tokens`);
		} catch (e) {
			ui.error(e);
		}
	}
	$effect(() => {
		void repo.name;
		fresh = null;
		load();
	});

	async function setPublic(on: boolean) {
		try {
			const r = await api.patch<RepoDetail>(`/git/repos/${repo.name}`, { public: on });
			onchange(r);
			ui.toast(r.public ? 'Anyone can now clone this repository' : 'Repository is private again');
		} catch (e) {
			ui.error(e);
		}
	}

	async function create(e: Event) {
		e.preventDefault();
		if (busy || !label.trim()) return;
		busy = true;
		try {
			const t = await api.post<GitToken & { token: string }>(`/git/repos/${repo.name}/tokens`, {
				label: label.trim(), scope, expires_days: days ? Number(days) : null
			});
			fresh = { token: t.token, scope: t.scope, label: t.label };
			label = '';
			await load();
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function revoke(t: GitToken) {
		const ok = await ui.confirm({
			title: `Revoke “${t.label}”?`,
			message: 'Anything using this token stops working immediately. This cannot be undone.',
			confirmLabel: 'Revoke token', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/git/repos/${repo.name}/tokens/${t.id}`);
			tokens = tokens.filter((x) => x.id !== t.id);
		} catch (e) {
			ui.error(e);
		}
	}

	async function copy(text: string, key: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = key;
			setTimeout(() => (copied = ''), 1400);
		} catch {
			ui.toast(text);
		}
	}
</script>

{#snippet copyBox(text: string, key: string, aria: string)}
	<div class="copy">
		<input readonly value={text} onclick={(e) => e.currentTarget.select()} aria-label={aria} />
		<button class="icon-btn" title="Copy" onclick={() => copy(text, key)}>
			{#if copied === key}<Check size={14} />{:else}<Copy size={14} />{/if}
		</button>
	</div>
{/snippet}

<section class="set">
	<h3><KeyRound size={15} />Access</h3>

	<div class="row">
		<div class="txt">
			<b>{#if repo.public}<Globe size={14} /> Public{:else}<Lock size={14} /> Private{/if}</b>
			<span>
				{#if repo.public}Anyone with the link can clone and fetch without signing in. Pushing always needs credentials.{:else}Only you, and holders of an access token, can clone.{/if}
			</span>
		</div>
		<label class="switch">
			<input type="checkbox" checked={repo.public} onchange={(e) => setPublic(e.currentTarget.checked)} />
			Public
		</label>
	</div>
	{#if repo.public}
		<div class="sub"><span class="faint">Anonymous clone URL</span>{@render copyBox(publicUrl, 'public', 'Anonymous clone URL')}</div>
	{/if}

	<div class="row head"><div class="txt"><b><KeyRound size={14} /> Access tokens</b><span>Let a script, CI job or another machine use this repository only, without your password. Use the token as the password (any user name) with the owner URL.</span></div></div>

	{#if fresh}
		<div class="fresh">
			<b>Copy your token now. It will not be shown again.</b>
			{@render copyBox(fresh.token, 'token', 'Access token')}
			<span class="faint">Clone URL with this {fresh.scope} token</span>
			{@render copyBox(tokenUrl, 'url', 'Clone URL with token')}
			<button class="btn ghost" onclick={() => (fresh = null)}>Done</button>
		</div>
	{/if}

	{#if tokens.length}
		<ul class="tokens">
			{#each tokens as t (t.id)}
				<li class:expired={t.expired}>
					<div class="txt">
						<b>{t.label}</b>
						<span>
							{t.scope === 'write' ? 'Read and write' : 'Read only'} · created {relTime(t.created)} ·
							{#if t.expired}expired {fullDate(t.expires!)}{:else if t.expires}expires {fullDate(t.expires)}{:else}never expires{/if} ·
							{t.last_used ? 'last used ' + relTime(t.last_used) : 'never used'}
						</span>
					</div>
					<button class="icon-btn" title="Revoke token" onclick={() => revoke(t)}><Trash2 size={14} /></button>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="faint none">No tokens yet.</p>
	{/if}

	<form class="new" onsubmit={create}>
		<input class="input" placeholder="Label, e.g. deploy server" maxlength="60" bind:value={label} aria-label="Token label" />
		<select class="input" bind:value={scope} aria-label="Token scope">
			<option value="read">Read (clone, fetch)</option>
			<option value="write">Write (also push)</option>
		</select>
		<select class="input" bind:value={days} aria-label="Token expiry">
			<option value="">Never expires</option>
			<option value="30">30 days</option>
			<option value="90">90 days</option>
			<option value="365">1 year</option>
		</select>
		<button class="btn primary" disabled={busy || !label.trim()}><Plus size={14} />Create token</button>
	</form>
</section>

<style>
	.set { margin-bottom: 28px; }
	h3 { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 8px 0; flex-wrap: wrap; }
	.row.head { border-top: 1px solid var(--border); margin-top: 8px; padding-top: 14px; }
	.txt { flex: 1; min-width: 200px; }
	.txt b { display: flex; align-items: center; gap: 6px; font-weight: 550; }
	.txt span { display: block; color: var(--text-3); font-size: 12.5px; margin-top: 2px; }
	.switch { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
	.sub, .fresh { display: flex; flex-direction: column; gap: 4px; margin: 4px 0 8px; }
	.sub > span, .fresh > span { font-size: 12px; }
	.fresh { border: 1px solid var(--accent); border-radius: 6px; padding: 10px 12px; align-items: flex-start; }
	.fresh .copy { align-self: stretch; }
	.copy { display: flex; align-items: center; height: 30px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--bg); min-width: 0; }
	.copy input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; padding: 0 8px; font: 12px var(--font-mono); color: var(--text-2); }
	.tokens { list-style: none; margin: 4px 0 8px; padding: 0; border: 1px solid var(--border); border-radius: 6px; }
	.tokens li { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-top: 1px solid var(--border); }
	.tokens li:first-child { border-top: 0; }
	.tokens li.expired .txt b { text-decoration: line-through; color: var(--text-3); }
	.none { margin: 4px 0 8px; font-size: 13px; }
	.new { display: flex; gap: 6px; flex-wrap: wrap; }
	.new input.input { flex: 1; min-width: 160px; }
</style>
