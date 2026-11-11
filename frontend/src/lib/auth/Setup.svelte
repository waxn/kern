<script lang="ts">
	import { ArrowLeft, ArrowRight, Check, Globe, GitBranch, KeyRound, Loader, LockKeyhole, ShieldCheck, UserPlus, Users } from '@lucide/svelte';
	import { ApiError } from '#lib/api.ts';
	import { finishSetup } from '#lib/state/session.svelte.ts';
	import AuthFrame from './AuthFrame.svelte';
	import Toggle from './Toggle.svelte';

	const steps = ['Welcome', 'Administrator', 'Access', 'Finish'];
	let step = $state(0);
	let busy = $state(false);
	let error = $state('');

	let code = $state('');
	let username = $state('');
	let email = $state('');
	let password = $state('');
	let confirm = $state('');
	let siteName = $state('Kern');
	let landing = $state(false);
	let signupMode = $state<'closed' | 'approval' | 'open'>('closed');
	let allowGit = $state(true);

	const userOk = $derived(/^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/.test(username));
	const pwOk = $derived(password.length >= 10 && password === confirm);
	const strength = $derived.by(() => {
		let n = 0;
		if (password.length >= 10) n++;
		if (password.length >= 14) n++;
		if (/[a-z]/.test(password) && /[A-Z]/.test(password)) n++;
		if (/\d/.test(password) && /[^A-Za-z0-9]/.test(password)) n++;
		return password ? Math.max(1, n) : 0;
	});

	const canNext = $derived(
		step === 0 ? code.trim().length >= 4 : step === 1 ? userOk && pwOk : step === 2 ? true : siteName.trim().length > 0
	);

	function next() {
		error = '';
		if (step < steps.length - 1) step++;
	}
	function back() {
		error = '';
		if (step > 0) step--;
	}

	async function finish() {
		if (busy) return;
		busy = true;
		error = '';
		try {
			await finishSetup({
				code: code.trim(),
				username: username.trim(),
				email: email.trim(),
				password,
				site: { site_name: siteName.trim(), landing_enabled: landing, signup_mode: signupMode, allow_git: allowGit }
			});
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Could not finish setup.';
			// Send people back to the step that holds the problem.
			if (/code/i.test(error)) step = 0;
			else if (/password|username|email/i.test(error)) step = 1;
			busy = false;
		}
	}

	const modes = [
		{ id: 'closed', icon: LockKeyhole, title: 'Invite only', text: 'Only administrators create accounts. Best for just you, or a few people you know.' },
		{ id: 'approval', icon: UserPlus, title: 'Approve each sign-up', text: 'Anyone can ask for an account; it works once an administrator approves it.' },
		{ id: 'open', icon: Users, title: 'Open sign-up', text: 'Anyone who finds this server can create an account straight away.' }
	] as const;
</script>

<AuthFrame wide home={false}>
	<ol class="steps" aria-label="Setup progress">
		{#each steps as s, i (s)}
			<li class:done={i < step} class:on={i === step}>
				<span>{#if i < step}<Check size={12} strokeWidth={3} />{:else}{i + 1}{/if}</span>{s}
			</li>
		{/each}
	</ol>

	{#if step === 0}
		<h1>Let's set up your server</h1>
		<p class="sub">This takes a minute. You will create the administrator account and decide who can use this server.</p>
		<label>
			<span><KeyRound size={13} /> Setup code</span>
			<input class="input mono" bind:value={code} placeholder="XXXXXXXX" autocomplete="off" spellcheck="false" autocapitalize="characters" maxlength="40" autofocus onkeydown={(e) => e.key === 'Enter' && canNext && next()} />
			<small>Proves you control this server. Find it with <code>docker compose logs backend</code> — it is printed in a box near the start.</small>
		</label>
	{:else if step === 1}
		<h1>Create the administrator</h1>
		<p class="sub">The administrator manages users and server settings. You can add more administrators later.</p>
		<div class="grid">
			<label>
				<span>Username</span>
				<input class="input" bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" autofocus />
				<small class:bad={username && !userOk}>3–32 letters, digits, dots, dashes or underscores.</small>
			</label>
			<label>
				<span>Email <em>optional</em></span>
				<input class="input" type="email" bind:value={email} autocomplete="email" />
			</label>
			<label>
				<span>Password</span>
				<input class="input" type="password" bind:value={password} autocomplete="new-password" />
				<div class="meter" data-s={strength}><i></i><i></i><i></i><i></i></div>
				<small>At least 10 characters. A few random words work well.</small>
			</label>
			<label>
				<span>Repeat password</span>
				<input class="input" type="password" bind:value={confirm} autocomplete="new-password" class:badline={confirm && confirm !== password} />
			</label>
		</div>
	{:else if step === 2}
		<h1>Who can get in?</h1>
		<p class="sub">Every person gets a completely separate, private workspace. Nobody can see anyone else's pages or files.</p>
		<div class="section">Sign-ups</div>
		<div class="choices">
			{#each modes as m (m.id)}
				<button type="button" class="choice" class:on={signupMode === m.id} onclick={() => (signupMode = m.id)}>
					<m.icon size={16} />
					<span><b>{m.title}</b><small>{m.text}</small></span>
					<i class="radio"></i>
				</button>
			{/each}
		</div>
		<div class="section">Front page</div>
		<div class="row">
			<Globe size={16} />
			<span><b>Show a public landing page</b><small>Visitors who are not signed in see a page that introduces Kern, with sign-in and sign-up buttons. Off: they go straight to the sign-in form.</small></span>
			<Toggle bind:checked={landing} label="Show a public landing page" />
		</div>
	{:else}
		<h1>Almost done</h1>
		<p class="sub">A few last details. You can change everything here later under Settings → Server.</p>
		<label>
			<span>Server name</span>
			<input class="input" bind:value={siteName} maxlength="60" autofocus />
			<small>Shown on the sign-in page and the landing page.</small>
		</label>
		<div class="row">
			<GitBranch size={16} />
			<span><b>Git hosting</b><small>Let people host git repositories here and push to them over HTTP.</small></span>
			<Toggle bind:checked={allowGit} label="Git hosting" />
		</div>
		<div class="summary">
			<div class="section">Summary</div>
			<dl>
				<dt>Administrator</dt><dd>{username}</dd>
				<dt>Sign-ups</dt><dd>{modes.find((m) => m.id === signupMode)?.title}</dd>
				<dt>Landing page</dt><dd>{landing ? 'Shown to visitors' : 'Off'}</dd>
			</dl>
			<p class="note"><ShieldCheck size={14} /> Passwords are stored hashed. After setup the setup code stops working.</p>
		</div>
	{/if}

	{#if error}<div class="err" role="alert">{error}</div>{/if}

	<div class="nav">
		{#if step > 0}<button class="btn ghost" onclick={back} disabled={busy}><ArrowLeft size={14} />Back</button>{:else}<span></span>{/if}
		{#if step < steps.length - 1}
			<button class="btn primary" onclick={next} disabled={!canNext}>Continue<ArrowRight size={14} /></button>
		{:else}
			<button class="btn primary" onclick={finish} disabled={!canNext || busy}>
				{#if busy}<Loader size={14} class="spin" />{/if}Create server
			</button>
		{/if}
	</div>
</AuthFrame>

<style>
	.steps { list-style: none; margin: 0 0 22px; padding: 0; display: flex; gap: 4px; }
	.steps li { flex: 1; display: flex; align-items: center; gap: 7px; padding-top: 9px; border-top: 2px solid var(--border); font-size: 12px; color: var(--text-3); white-space: nowrap; }
	.steps li span { display: grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; font-size: 10.5px; font-weight: 650; background: var(--surface-2); color: var(--text-3); }
	.steps li.on { border-top-color: var(--accent); color: var(--text); }
	.steps li.on span { background: var(--accent); color: #17130c; }
	.steps li.done { border-top-color: color-mix(in srgb, var(--accent) 50%, var(--border)); color: var(--text-2); }
	.steps li.done span { background: color-mix(in srgb, var(--accent) 25%, var(--surface-2)); color: var(--accent); }
	@media (max-width: 480px) { .steps li { font-size: 0; gap: 0; } .steps li span { font-size: 10.5px; } }
	h1 { margin: 0 0 4px; font-size: 20px; font-weight: 650; letter-spacing: -0.015em; }
	.sub { margin: 0 0 18px; color: var(--text-2); }
	label { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }
	label > span { display: flex; align-items: center; gap: 5px; font-size: 12.5px; font-weight: 550; color: var(--text-2); }
	label em { font-style: normal; font-weight: 400; color: var(--text-3); }
	label small, .row small, .choice small { color: var(--text-3); font-size: 12px; line-height: 1.4; }
	small.bad { color: var(--danger); }
	code { font-family: var(--font-mono); font-size: 0.92em; background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
	.input { height: 34px; padding: 0 10px; font-size: 14px; }
	.input.mono { font-family: var(--font-mono); letter-spacing: 0.14em; text-transform: uppercase; font-size: 16px; height: 40px; }
	.input.badline { border-color: var(--danger); }
	.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
	@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
	.meter { display: flex; gap: 3px; margin-top: 2px; }
	.meter i { flex: 1; height: 3px; border-radius: 2px; background: var(--border-strong); }
	.meter[data-s='1'] i:nth-child(-n + 1) { background: var(--danger); }
	.meter[data-s='2'] i:nth-child(-n + 2) { background: var(--c-orange); }
	.meter[data-s='3'] i:nth-child(-n + 3) { background: var(--c-yellow); }
	.meter[data-s='4'] i { background: var(--c-green); }
	.section { margin: 14px 0 7px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); }
	.choices { display: flex; flex-direction: column; gap: 6px; }
	.choice { display: flex; align-items: flex-start; gap: 11px; padding: 10px 12px; text-align: left; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--bg); color: var(--text-2); transition: border-color 0.12s, background 0.12s; }
	.choice:hover { background: var(--surface-2); }
	.choice.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg)); color: var(--text); }
	.choice > :global(svg) { margin-top: 2px; flex: none; }
	.choice span, .row span { flex: 1; display: flex; flex-direction: column; gap: 2px; }
	.choice b, .row b { font-weight: 600; color: var(--text); }
	.radio { flex: none; width: 15px; height: 15px; margin-top: 3px; border-radius: 50%; border: 1.5px solid var(--border-strong); }
	.choice.on .radio { border: 4.5px solid var(--accent); }
	.row { display: flex; align-items: flex-start; gap: 11px; padding: 11px 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--bg); color: var(--text-2); margin-bottom: 4px; }
	.row > :global(svg) { margin-top: 2px; flex: none; }
	.summary dl { display: grid; grid-template-columns: auto 1fr; gap: 5px 16px; margin: 0; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); }
	.summary dt { color: var(--text-3); }
	.summary dd { margin: 0; color: var(--text); font-weight: 550; }
	.note { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; font-size: 12px; color: var(--text-3); }
	.err { margin-top: 6px; padding: 8px 10px; border-radius: var(--radius); font-size: 12.5px; color: var(--danger); background: color-mix(in srgb, var(--danger) 11%, transparent); border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent); }
	.nav { display: flex; justify-content: space-between; align-items: center; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }
	.nav .btn { height: 32px; padding: 0 14px; }
	:global(.spin) { animation: spin 0.8s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
</style>
