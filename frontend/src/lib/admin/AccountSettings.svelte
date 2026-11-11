<script lang="ts">
	import { LogOut } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { logout, session } from '#lib/state/session.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fullDate } from '#lib/util.ts';

	let user = $derived(session.user!);
	let current = $state('');
	let next = $state('');
	let again = $state('');
	let busy = $state(false);
	let email = $state(session.user?.email ?? '');

	async function changePassword(e: Event) {
		e.preventDefault();
		if (next !== again) return ui.toast('The new passwords do not match.', { kind: 'error' });
		busy = true;
		try {
			await api.post('/auth/password', { current, new: next });
			current = next = again = '';
			ui.toast('Password changed. Other devices were signed out.');
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function saveEmail() {
		try {
			const u = await api.patch<typeof user>('/auth/profile', { email });
			if (session.site) session.site = { ...session.site, user: u };
			ui.toast('Saved.');
		} catch (err) {
			ui.error(err);
		}
	}
</script>

<p class="lede">Signed in to <b>{session.site?.site_name}</b>. Your pages and files are private to your account.</p>
<div class="group">
	<div class="item">
		<div><b>{user.username}</b><span>{user.is_admin ? 'Administrator' : 'Member'}{#if user.date_joined} · joined {fullDate(user.date_joined)}{/if}</span></div>
		<button class="btn" onclick={logout}><LogOut size={14} />Sign out</button>
	</div>
	<div class="item">
		<div><b>Email</b><span>Optional. Not used to send anything.</span></div>
		<div class="row"><input class="input wide" type="email" bind:value={email} /><button class="btn" onclick={saveEmail} disabled={email === user.email}>Save</button></div>
	</div>
</div>

<div class="section-title">Change password</div>
<form class="group" onsubmit={changePassword}>
	<div class="item"><div><b>Current password</b></div><input class="input wide" type="password" bind:value={current} autocomplete="current-password" required /></div>
	<div class="item"><div><b>New password</b><span>At least 10 characters.</span></div><input class="input wide" type="password" bind:value={next} autocomplete="new-password" required /></div>
	<div class="item"><div><b>Repeat new password</b></div><input class="input wide" type="password" bind:value={again} autocomplete="new-password" required /></div>
	<div class="item"><div><span>Changing it signs you out everywhere else.</span></div><button class="btn primary" disabled={busy || !current || !next}>Change password</button></div>
</form>

<style>
	.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
	.item { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.item:first-child { border-top: 0; }
	.item > div:first-child { flex: 1; min-width: 200px; }
	.item b { display: block; font-weight: 550; }
	.item span { color: var(--text-3); font-size: 12.5px; }
	.row { display: flex; gap: 6px; }
	.wide { width: min(300px, 100%); }
</style>
