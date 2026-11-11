<script lang="ts">
	import { ArrowRight, Loader } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { ApiError } from '#lib/api.ts';
	import { login, session, signup } from '#lib/state/session.svelte.ts';
	import AuthFrame from './AuthFrame.svelte';

	let { mode }: { mode: 'login' | 'signup' } = $props();
	let username = $state('');
	let email = $state('');
	let password = $state('');
	let confirm = $state('');
	let busy = $state(false);
	let error = $state('');
	let pending = $state(false);

	let site = $derived(session.site!);
	let canSignup = $derived(site.signup_mode !== 'closed');
	let mismatch = $derived(mode === 'signup' && confirm.length > 0 && confirm !== password);

	async function submit(e: Event) {
		e.preventDefault();
		if (busy) return;
		error = '';
		if (mode === 'signup' && password !== confirm) {
			error = 'The two passwords do not match.';
			return;
		}
		busy = true;
		try {
			if (mode === 'login') await login(username.trim(), password);
			else {
				const r = await signup(username.trim(), password, email.trim());
				if (r.pending) pending = true;
			}
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Something went wrong. Try again.';
		} finally {
			busy = false;
		}
	}

	function swap(e: MouseEvent, to: string) {
		e.preventDefault();
		error = '';
		goto(to);
	}
</script>

<AuthFrame>
	{#if pending}
		<h1>Thanks, {username}</h1>
		<p class="sub">Your account is waiting for an administrator's approval. You can sign in once it has been approved.</p>
		<a class="btn wide" href="/login" onclick={(e) => { pending = false; swap(e, '/login'); }}>Back to sign in</a>
	{:else}
		<h1>{mode === 'login' ? 'Sign in' : 'Create your account'}</h1>
		<p class="sub">
			{#if mode === 'login'}Welcome back to {site.site_name}.{:else if site.signup_mode === 'approval'}An administrator approves new accounts before you can sign in.{:else}Your own private workspace on this server.{/if}
		</p>
		<form onsubmit={submit}>
			<label>
				<span>Username</span>
				<input class="input" bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus />
			</label>
			{#if mode === 'signup'}
				<label>
					<span>Email <em>optional</em></span>
					<input class="input" type="email" bind:value={email} autocomplete="email" />
				</label>
			{/if}
			<label>
				<span>Password</span>
				<input class="input" type="password" bind:value={password} autocomplete={mode === 'login' ? 'current-password' : 'new-password'} required />
				{#if mode === 'signup'}<small>At least 10 characters. Not a common password.</small>{/if}
			</label>
			{#if mode === 'signup'}
				<label>
					<span>Repeat password</span>
					<input class="input" type="password" bind:value={confirm} autocomplete="new-password" required class:bad={mismatch} />
				</label>
			{/if}
			{#if error}<div class="err" role="alert">{error}</div>{/if}
			<button class="btn primary go" disabled={busy || !username || !password}>
				{#if busy}<Loader size={14} class="spin" />{/if}{mode === 'login' ? 'Sign in' : 'Create account'}{#if !busy}<ArrowRight size={14} />{/if}
			</button>
		</form>
		{#if mode === 'login' && canSignup}
			<p class="alt">New here? <a href="/signup" onclick={(e) => swap(e, '/signup')}>Create an account</a></p>
		{:else if mode === 'signup'}
			<p class="alt">Already have an account? <a href="/login" onclick={(e) => swap(e, '/login')}>Sign in</a></p>
		{/if}
	{/if}
</AuthFrame>

<style>
	h1 { margin: 0 0 4px; font-size: 20px; font-weight: 650; letter-spacing: -0.015em; }
	.sub { margin: 0 0 18px; color: var(--text-2); }
	form { display: flex; flex-direction: column; gap: 13px; }
	label { display: flex; flex-direction: column; gap: 5px; }
	label span { font-size: 12.5px; font-weight: 550; color: var(--text-2); }
	label em { font-style: normal; font-weight: 400; color: var(--text-3); margin-left: 4px; }
	label small { color: var(--text-3); font-size: 12px; }
	.input { height: 34px; padding: 0 10px; font-size: 14px; }
	.input.bad { border-color: var(--danger); }
	.err { padding: 8px 10px; border-radius: var(--radius); font-size: 12.5px; color: var(--danger); background: color-mix(in srgb, var(--danger) 11%, transparent); border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); }
	.go { height: 36px; justify-content: center; margin-top: 4px; font-size: 14px; }
	.wide { width: 100%; justify-content: center; height: 34px; text-decoration: none; }
	.alt { margin: 16px 0 0; text-align: center; color: var(--text-2); }
	.alt a { color: var(--accent); text-decoration: none; font-weight: 550; }
	.alt a:hover { text-decoration: underline; }
	:global(.spin) { animation: spin 0.8s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
</style>
