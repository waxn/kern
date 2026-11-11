<script lang="ts">
	import { Check, KeyRound, Plus, ShieldCheck, Trash2, UserX } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { session, type User } from '#lib/state/session.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, fullDate } from '#lib/util.ts';

	type Row = User & { storage_bytes: number };
	let users = $state<Row[]>([]);
	let loaded = $state(false);
	let adding = $state(false);
	let form = $state({ username: '', password: '', email: '', is_admin: false });
	let me = $derived(session.user!);
	let pending = $derived(users.filter((u) => !u.is_active && !u.last_login));

	async function load() {
		try {
			users = await api.get<Row[]>('/admin/users');
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);

	async function create(e: Event) {
		e.preventDefault();
		try {
			await api.post('/admin/users', form);
			form = { username: '', password: '', email: '', is_admin: false };
			adding = false;
			await load();
			ui.toast('Account created.');
		} catch (err) {
			ui.error(err);
		}
	}

	async function patch(u: Row, body: Record<string, unknown>) {
		try {
			await api.patch(`/admin/users/${u.id}`, body);
			await load();
		} catch (err) {
			ui.error(err);
		}
	}

	async function resetPassword(u: Row) {
		const pw = prompt(`New password for ${u.username} (at least 10 characters):`);
		if (!pw) return;
		await patch(u, { password: pw });
		ui.toast(`Password changed for ${u.username}. They were signed out everywhere.`);
	}

	async function remove(u: Row) {
		const ok = await ui.confirm({
			title: `Delete ${u.username}?`,
			message: `This permanently deletes their account and all of their pages, files, cards, bookmarks and git repositories (${fileSize(u.storage_bytes)}). It cannot be undone.`,
			confirmLabel: 'Delete account and data', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/admin/users/${u.id}`);
			await load();
		} catch (err) {
			ui.error(err);
		}
	}
</script>

<p class="lede">Each person has a separate workspace. You can add accounts, approve sign-ups and remove people here — you cannot read anyone's pages.</p>

{#if pending.length}
	<div class="notice">
		<b>{pending.length} waiting for approval</b>
		{#each pending as u (u.id)}
			<div class="prow">
				<span>{u.username}{#if u.email} <em>{u.email}</em>{/if}</span>
				<button class="btn primary" onclick={() => patch(u, { is_active: true })}><Check size={14} />Approve</button>
				<button class="btn ghost" onclick={() => remove(u)}>Decline</button>
			</div>
		{/each}
	</div>
{/if}

<div class="head">
	<div class="section-title" style="margin:0">Accounts · {users.length}</div>
	<button class="btn" onclick={() => (adding = !adding)}><Plus size={14} />Add user</button>
</div>

{#if adding}
	<form class="group add" onsubmit={create}>
		<div class="grid">
			<label><span>Username</span><input class="input" bind:value={form.username} autocapitalize="none" required /></label>
			<label><span>Email <em>optional</em></span><input class="input" type="email" bind:value={form.email} /></label>
			<label><span>Temporary password</span><input class="input" type="text" bind:value={form.password} autocomplete="off" required /></label>
			<label class="chk"><input type="checkbox" bind:checked={form.is_admin} /> Administrator</label>
		</div>
		<div class="actions"><button type="button" class="btn ghost" onclick={() => (adding = false)}>Cancel</button><button class="btn primary">Create account</button></div>
	</form>
{/if}

<div class="group">
	{#each users as u (u.id)}
		<div class="user" class:off={!u.is_active}>
			<span class="av">{u.username.slice(0, 1).toUpperCase()}</span>
			<div class="who">
				<b>{u.username}{#if u.id === me.id}<i>you</i>{/if}{#if u.is_admin}<i class="adm"><ShieldCheck size={11} />admin</i>{/if}{#if !u.is_active}<i class="dis">{u.last_login ? 'disabled' : 'pending'}</i>{/if}</b>
				<span>{u.email || 'no email'} · {fileSize(u.storage_bytes)} · {u.last_login ? 'last seen ' + fullDate(u.last_login) : 'never signed in'}</span>
			</div>
			<div class="acts">
				<button class="icon-btn" title="Set a new password" onclick={() => resetPassword(u)}><KeyRound size={14} /></button>
				{#if u.id !== me.id}
					<button class="icon-btn" title={u.is_admin ? 'Remove administrator rights' : 'Make administrator'} class:on={u.is_admin} onclick={() => patch(u, { is_admin: !u.is_admin })}><ShieldCheck size={14} /></button>
					<button class="icon-btn" title={u.is_active ? 'Disable account' : 'Enable account'} onclick={() => patch(u, { is_active: !u.is_active })}><UserX size={14} /></button>
					<button class="icon-btn danger" title="Delete account and data" onclick={() => remove(u)}><Trash2 size={14} /></button>
				{/if}
			</div>
		</div>
	{/each}
	{#if loaded && !users.length}<div class="user"><div class="who"><span>No accounts.</span></div></div>{/if}
</div>

<style>
	.head { display: flex; align-items: center; justify-content: space-between; margin: 20px 0 8px; }
	.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
	.user { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-top: 1px solid var(--border); }
	.user:first-child { border-top: 0; }
	.user.off { opacity: 0.6; }
	.av { flex: none; width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; font-weight: 650; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, var(--surface-2)); }
	.who { flex: 1; min-width: 0; }
	.who b { display: flex; align-items: center; gap: 6px; font-weight: 600; }
	.who b i { font-style: normal; font-weight: 500; font-size: 11px; padding: 0 6px; border-radius: 9px; color: var(--text-3); background: var(--surface-2); display: inline-flex; align-items: center; gap: 3px; }
	.who b i.adm { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.who b i.dis { color: var(--c-orange); background: color-mix(in srgb, var(--c-orange) 14%, transparent); }
	.who > span { display: block; color: var(--text-3); font-size: 12.5px; }
	.acts { display: flex; gap: 2px; }
	.icon-btn.danger:hover { color: var(--danger); }
	.notice { padding: 12px 14px; margin-bottom: 14px; border: 1px solid color-mix(in srgb, var(--c-orange) 45%, var(--border)); border-radius: 8px; background: color-mix(in srgb, var(--c-orange) 8%, transparent); }
	.prow { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
	.prow span { flex: 1; } .prow em { color: var(--text-3); font-style: normal; margin-left: 6px; }
	.add { padding: 14px; }
	.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; }
	@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
	label { display: flex; flex-direction: column; gap: 4px; }
	label span { font-size: 12.5px; font-weight: 550; color: var(--text-2); }
	label em { font-style: normal; font-weight: 400; color: var(--text-3); }
	label.chk { flex-direction: row; align-items: center; gap: 7px; align-self: end; height: 28px; color: var(--text-2); }
	input[type='checkbox'] { accent-color: var(--accent); }
	.actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 14px; }
</style>
