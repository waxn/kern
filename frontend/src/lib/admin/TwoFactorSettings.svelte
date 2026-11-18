<script lang="ts">
	// Settings → Account → Two-factor sign-in (accounts/totp.py on the server).
	import { Copy, Download, KeyRound, ShieldCheck } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { loadSession, session } from '#lib/state/session.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';

	type Status = { enabled: boolean; recovery_left: number; session_verified: boolean; mail_connected: boolean };
	let status = $state<Status | null>(null);
	let step = $state<'' | 'password' | 'scan' | 'codes' | 'disable' | 'regen'>('');
	let password = $state('');
	let code = $state('');
	let setup = $state<{ secret: string; uri: string; qr_svg: string } | null>(null);
	let codes = $state<string[]>([]);
	let busy = $state(false);

	async function load() {
		try {
			status = await api.get<Status>('/auth/2fa');
		} catch (e) {
			ui.error(e);
		}
	}
	onMount(load);

	async function run(fn: () => Promise<void>) {
		busy = true;
		try {
			await fn();
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	const start = () => run(async () => {
		setup = await api.post('/auth/2fa/setup', { password });
		password = '';
		step = 'scan';
	});
	const confirm = () => run(async () => {
		const r = await api.post<{ recovery_codes: string[]; signed_out: number }>('/auth/2fa/confirm', { code });
		codes = r.recovery_codes;
		code = '';
		setup = null;
		step = 'codes';
		await load();
		loadSession();
		ui.toast(r.signed_out ? `Two-factor sign-in is on. ${r.signed_out} other session${r.signed_out === 1 ? ' was' : 's were'} signed out.` : 'Two-factor sign-in is on.');
	});
	const disable = () => run(async () => {
		await api.post('/auth/2fa/disable', { password, code });
		password = code = '';
		step = '';
		await load();
		loadSession();
		ui.toast('Two-factor sign-in is off.');
	});
	const regen = () => run(async () => {
		const r = await api.post<{ recovery_codes: string[] }>('/auth/2fa/recovery', { password });
		codes = r.recovery_codes;
		password = '';
		step = 'codes';
		await load();
	});

	function qrSrc(svg: string) {
		// As an image, so the markup can never run in the page.
		return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
	}
	async function copyCodes() {
		try {
			await navigator.clipboard.writeText(codes.join('\n'));
			ui.toast('Recovery codes copied');
		} catch {
			ui.toast('Select the codes and copy them by hand.', { kind: 'error' });
		}
	}
	function downloadCodes() {
		const name = session.site?.site_name || 'Kern';
		const blob = new Blob([`${name} recovery codes for ${session.user?.username}\nEach works once.\n\n${codes.join('\n')}\n`], { type: 'text/plain' });
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = `${name.toLowerCase().replace(/\W+/g, '-')}-recovery-codes.txt`;
		a.click();
		URL.revokeObjectURL(a.href);
	}
</script>

<div class="section-title">Two-factor sign-in</div>
<div class="group">
	{#if !status}
		<div class="item"><div><span>Loading…</span></div></div>
	{:else if step === 'codes'}
		<div class="item col">
			<div><b>Save your recovery codes</b><span>If you lose your phone, each of these signs you in once instead of a code. They won't be shown again.</span></div>
			<ol class="codes">{#each codes as c (c)}<li><code>{c}</code></li>{/each}</ol>
			<div class="row">
				<button class="btn" onclick={copyCodes}><Copy size={14} />Copy</button>
				<button class="btn" onclick={downloadCodes}><Download size={14} />Download</button>
				<button class="btn primary" onclick={() => { codes = []; step = ''; }}>I've saved them</button>
			</div>
		</div>
	{:else if status.enabled}
		<div class="item">
			<div><b class="on"><ShieldCheck size={15} /> On</b><span>Signing in needs your password and a code from your authenticator app. {status.recovery_left} recovery code{status.recovery_left === 1 ? '' : 's'} left.{#if !status.session_verified} This browser signed in before it was turned on; sign in again to open mail.{/if}</span></div>
			<div class="row">
				<button class="btn" onclick={() => (step = step === 'regen' ? '' : 'regen')}>New recovery codes</button>
				<button class="btn ghost" onclick={() => (step = step === 'disable' ? '' : 'disable')}>Turn off</button>
			</div>
		</div>
		{#if step === 'regen'}
			<form class="item" onsubmit={(e) => { e.preventDefault(); regen(); }}>
				<div><b>Your password</b><span>The old recovery codes stop working.</span></div>
				<div class="row"><input class="input wide" type="password" bind:value={password} autocomplete="current-password" required /><button class="btn primary" disabled={busy || !password}>Make new codes</button></div>
			</form>
		{:else if step === 'disable'}
			{#if status.mail_connected}
				<div class="item"><div><span>Mail needs two-factor sign-in. Disconnect your mail account in Settings → Mail first.</span></div></div>
			{:else}
				<form class="item col" onsubmit={(e) => { e.preventDefault(); disable(); }}>
					<div><b>Turn off two-factor sign-in</b><span>Your password alone will sign you in again.</span></div>
					<div class="row">
						<input class="input wide" type="password" placeholder="Password" bind:value={password} autocomplete="current-password" required />
						<input class="input code" inputmode="numeric" placeholder="Code" bind:value={code} autocomplete="one-time-code" required />
						<button class="btn" disabled={busy || !password || !code}>Turn off</button>
					</div>
				</form>
			{/if}
		{/if}
	{:else if step === 'scan' && setup}
		<form class="item col" onsubmit={(e) => { e.preventDefault(); confirm(); }}>
			<div><b>Scan this with your authenticator app</b><span>Aegis, 2FAS, Google Authenticator, 1Password, Bitwarden… Then enter the 6-digit code it shows.</span></div>
			<div class="scan">
				<img class="qr" src={qrSrc(setup.qr_svg)} alt="QR code for your authenticator app" width="168" height="168" />
				<div class="manual">
					<span>Can't scan? Enter this key:</span>
					<code class="secret">{setup.secret.replace(/(.{4})/g, '$1 ').trim()}</code>
				</div>
			</div>
			<div class="row">
				<input class="input code" inputmode="numeric" placeholder="123 456" bind:value={code} autocomplete="one-time-code" required />
				<button class="btn primary" disabled={busy || code.replace(/\s/g, '').length < 6}>Turn on</button>
				<button type="button" class="btn ghost" onclick={() => { step = ''; setup = null; }}>Cancel</button>
			</div>
		</form>
	{:else if step === 'password'}
		<form class="item" onsubmit={(e) => { e.preventDefault(); start(); }}>
			<div><b>Your password</b><span>To make sure it's you.</span></div>
			<div class="row"><input class="input wide" type="password" bind:value={password} autocomplete="current-password" required /><button class="btn primary" disabled={busy || !password}>Continue</button></div>
		</form>
	{:else}
		<div class="item">
			<div><b>Off</b><span>Add a code from an authenticator app to every sign-in. Needed to use mail.</span></div>
			<button class="btn primary" onclick={() => (step = 'password')}><KeyRound size={14} />Set up</button>
		</div>
	{/if}
</div>

<style>
	.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
	.item { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.item.col { flex-direction: column; align-items: stretch; }
	.item:first-child { border-top: 0; }
	.item > div:first-child { flex: 1; min-width: 200px; }
	.item b { display: block; font-weight: 550; }
	.item span { color: var(--text-3); font-size: 12.5px; }
	.on { display: flex !important; align-items: center; gap: 5px; color: var(--c-green); }
	.row { display: flex; gap: 6px; flex-wrap: wrap; }
	.wide { width: min(260px, 100%); }
	.code { width: 110px; letter-spacing: 0.08em; }
	.scan { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }
	.qr { background: #fff; border-radius: 8px; padding: 6px; }
	.manual { display: grid; gap: 6px; }
	.secret { font: 13px var(--font-mono); background: var(--code-bg); padding: 6px 8px; border-radius: 6px; word-break: break-all; user-select: all; }
	.codes { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px 18px; margin: 4px 0; padding-left: 22px; }
	.codes code { font: 13px var(--font-mono); user-select: all; }
</style>
