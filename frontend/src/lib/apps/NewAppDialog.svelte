<script lang="ts">
	import { ArrowLeft, FolderGit2, Globe, LayoutTemplate } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, ApiError } from '#lib/api.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { debounce } from '#lib/util.ts';
	import type { App, Starter } from './types.ts';

	type Kind = 'ai' | 'template' | 'repo' | 'url';
	let { onclose, oncreated, start = null, template: preset = '' }: {
		onclose: () => void; oncreated: (a: App, kind: Kind) => void; start?: Kind | null; template?: string;
	} = $props();

	let kind = $state<Kind | null>(null);
	let starters = $state<Starter[]>([]);
	let repos = $state<{ name: string; default_branch: string | null; description: string }[]>([]);
	let template = $state('');
	let name = $state('');
	let slug = $state('');
	let slugTouched = $state(false);
	let slugProblem = $state('');
	let prompt = $state('');
	let repo = $state('');
	let branch = $state('');
	let subdir = $state('');
	let gitUrl = $state('');
	let gitToken = $state('');
	let busy = $state(false);
	let error = $state('');
	let nameInput = $state<HTMLInputElement>();
	let nameTouched = $state(false);

	onMount(async () => {
		kind = start;
		template = preset;
		try {
			starters = await api.get<Starter[]>('/apps/templates');
			if (!template && starters.length) template = starters[0].key;
		} catch (e) {
			ui.error(e);
		}
		try {
			repos = await api.get<typeof repos>('/git/repos');
		} catch {
			/* git may be off */
		}
	});

	const IDEAS = [
		'Log the weights of my chickens each week and chart them',
		'A dashboard my devices send their Claude usage to, with daily totals',
		'A shared grocery list',
		'Track when I last watered each plant'
	];

	function suggest(n: string) {
		return n.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
	}

	$effect(() => {
		if (!slugTouched) slug = suggest(name);
	});

	const check = debounce(async (s: string) => {
		if (!s) { slugProblem = ''; return; }
		try {
			const r = await api.get<{ ok: boolean; problem: string }>(`/apps/check-slug?slug=${encodeURIComponent(s)}`);
			if (s === slug) slugProblem = r.problem;
		} catch {
			/* offline */
		}
	}, 250);
	$effect(() => check(slug));

	function pick(k: Kind) {
		kind = k;
		error = '';
		if (k === 'template') {
			const s = starters.find((x) => x.key === template);
			if (s && !name) name = s.name;
		}
		queueMicrotask(() => nameInput?.focus());
	}

	function pickTemplate(s: Starter) {
		const prev = starters.find((x) => x.key === template);
		template = s.key;
		if (!name || name === prev?.name) name = s.name;
	}

	$effect(() => {
		// For an AI app, a name from the first words of the idea until one is typed.
		if (kind === 'ai' && !nameTouched && prompt) {
			const words = prompt.replace(/^(an?|the|make|build|create)\s+/i, '').split(/\s+/).slice(0, 4).join(' ');
			name = words.charAt(0).toUpperCase() + words.slice(1).replace(/[.,;:!?]+$/, '');
		}
	});

	let ready = $derived(
		!!name.trim() && !!slug && !slugProblem && !busy &&
			(kind === 'ai' ? !!prompt.trim() : kind === 'template' ? !!template : kind === 'repo' ? !!repo : kind === 'url' ? /^https?:\/\//.test(gitUrl) : false)
	);

	async function create(e: Event) {
		e.preventDefault();
		if (!ready || !kind) return;
		busy = true;
		error = '';
		try {
			const body: Record<string, unknown> = { kind, name: name.trim(), slug };
			if (kind === 'ai') body.prompt = prompt.trim();
			if (kind === 'template') body.template = template;
			if (kind === 'repo') Object.assign(body, { repo, branch: branch.trim(), subdir: subdir.trim() });
			if (kind === 'url') Object.assign(body, { git_url: gitUrl.trim(), git_token: gitToken.trim(), branch: branch.trim(), subdir: subdir.trim() });
			const a = await api.post<App>('/apps', body);
			oncreated(a, kind);
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Could not create the app.';
		} finally {
			busy = false;
		}
	}

	const CHOICES: { k: Kind; title: string; text: string }[] = [
		{ k: 'ai', title: 'Build it with AI', text: 'Describe the app. The AI writes it, deploys it and fixes what breaks.' },
		{ k: 'template', title: 'Start from a template', text: 'A small working app to change: a tracker, a collector, a page, a server.' },
		{ k: 'repo', title: 'From a Kern repository', text: 'Deploy one of your repositories, and again on every push.' },
		{ k: 'url', title: 'From a git URL', text: 'GitHub, Gitea, GitLab… Deploy by hand or with a deploy hook.' }
	];
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && !busy && onclose()} onkeydown={(e) => e.key === 'Escape' && !busy && onclose()}>
	<div class="dialog popover" role="dialog" aria-label="New app">
		{#if !kind}
			<h2>New app</h2>
			<p class="sub">Apps run on this server in the background, each at its own address.</p>
			<div class="choices">
				{#each CHOICES as c (c.k)}
					<button class="choice" class:ai={c.k === 'ai'} onclick={() => pick(c.k)} disabled={c.k === 'repo' && !repos.length} title={c.k === 'repo' && !repos.length ? 'You have no repositories yet' : ''}>
						<span class="ci">
							{#if c.k === 'ai'}<Sparkle size={18} />{:else if c.k === 'template'}<LayoutTemplate size={18} />{:else if c.k === 'repo'}<FolderGit2 size={18} />{:else}<Globe size={18} />{/if}
						</span>
						<span class="ct"><b>{c.title}</b><span>{c.text}</span></span>
					</button>
				{/each}
			</div>
		{:else}
			<form onsubmit={create}>
				<h2>
					<button type="button" class="icon-btn" title="Back" onclick={() => (kind = null)}><ArrowLeft size={16} /></button>
					{CHOICES.find((c) => c.k === kind)?.title}
				</h2>

				{#if kind === 'ai'}
					<label class="field">
						<span>What should it do?</span>
						<!-- svelte-ignore a11y_autofocus -->
						<textarea class="input" rows="4" autofocus bind:value={prompt} maxlength="20000"
							placeholder="A page where I enter the weight of each of my chickens every Sunday, with a chart per chicken…"
							onkeydown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) create(e); }}></textarea>
					</label>
					<div class="ideas">{#each IDEAS as i (i)}<button type="button" class="chip" onclick={() => (prompt = i)}>{i}</button>{/each}</div>
				{:else if kind === 'template'}
					<div class="starters">
						{#each starters as s (s.key)}
							<button type="button" class="starter" class:on={template === s.key} onclick={() => pickTemplate(s)}>
								<span class="emoji">{s.icon}</span>
								<span><b>{s.name}</b><span>{s.description}</span></span>
							</button>
						{/each}
					</div>
				{:else if kind === 'repo'}
					<div class="row2">
						<label class="field"><span>Repository</span>
							<select class="input" bind:value={repo} onchange={() => { const r = repos.find((x) => x.name === repo); branch = r?.default_branch ?? ''; if (!name) name = repo; }}>
								<option value="" disabled>Choose…</option>
								{#each repos as r (r.name)}<option value={r.name}>{r.name}</option>{/each}
							</select>
						</label>
						<label class="field"><span>Branch</span><input class="input mono" bind:value={branch} placeholder="main" /></label>
					</div>
					<label class="field"><span>Folder <em>optional, when the app is not at the top of the repository</em></span><input class="input mono" bind:value={subdir} placeholder="apps/tracker" /></label>
				{:else}
					<label class="field"><span>Repository URL</span><input class="input mono" bind:value={gitUrl} placeholder="https://github.com/you/app.git" spellcheck="false" /></label>
					<div class="row2">
						<label class="field"><span>Branch</span><input class="input mono" bind:value={branch} placeholder="main" /></label>
						<label class="field"><span>Folder <em>optional</em></span><input class="input mono" bind:value={subdir} placeholder="" /></label>
					</div>
					<label class="field"><span>Access token <em>only for private repositories; stored encrypted</em></span><input class="input mono" type="password" autocomplete="off" bind:value={gitToken} /></label>
				{/if}

				<div class="row2">
					<label class="field"><span>Name</span><input class="input" bind:this={nameInput} bind:value={name} maxlength="80" oninput={() => (nameTouched = true)} placeholder="Chicken weights" /></label>
					<label class="field"><span>Address</span>
						<div class="slug" class:err={!!slugProblem}>
							<span class="faint">{location.host}/</span>
							<input class="mono" bind:value={slug} maxlength="40" spellcheck="false" autocomplete="off" oninput={() => { slugTouched = true; slug = slug.toLowerCase(); }} />
						</div>
					</label>
				</div>
				{#if slugProblem}<p class="err">{slugProblem}</p>{/if}
				{#if error}<p class="err">{error}</p>{/if}
				<div class="foot">
					<span class="faint small">{kind === 'ai' ? 'Uses the AI provider from Settings → AI.' : 'Only you can open it until you change who can.'}</span>
					<button type="button" class="btn ghost" onclick={onclose}>Cancel</button>
					<button class="btn primary" disabled={!ready}>{busy ? 'Creating…' : kind === 'ai' ? 'Start building' : 'Create app'}</button>
				</div>
			</form>
		{/if}
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); animation: fade 0.12s; }
	.dialog { width: min(600px, 100%); max-height: calc(100dvh - 32px); overflow-y: auto; padding: 20px; }
	form { display: flex; flex-direction: column; gap: 12px; }
	h2 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 16px; font-weight: 650; }
	h2 .icon-btn { margin-left: -6px; }
	.sub { margin: 4px 0 14px; color: var(--text-2); }
	.choices { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
	.choice { display: flex; gap: 12px; text-align: left; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); transition: border-color 0.12s, background 0.12s; }
	.choice:hover:not(:disabled) { border-color: var(--border-strong); background: var(--hover); }
	.choice:disabled { opacity: 0.45; cursor: default; }
	.choice.ai { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); background: color-mix(in srgb, var(--accent) 6%, var(--bg)); }
	.ci { flex: none; width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; background: var(--surface-2); color: var(--text-2); }
	.choice.ai .ci { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.ct { display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; color: var(--text-2); }
	.ct b { font-size: 13.5px; color: var(--text); font-weight: 600; }
	.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 550; color: var(--text-2); min-width: 0; }
	.field em { font-style: normal; font-weight: 400; color: var(--text-3); }
	.field .input { width: 100%; }
	textarea.input { font: inherit; resize: vertical; }
	.mono { font-family: var(--font-mono); font-size: 12.5px; }
	.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
	.ideas { display: flex; flex-wrap: wrap; gap: 6px; margin-top: -4px; }
	.ideas .chip { cursor: pointer; }
	.ideas .chip:hover { color: var(--text); }
	.starters { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
	.starter { display: flex; gap: 10px; text-align: left; padding: 11px 12px; border: 1px solid var(--border); border-radius: 9px; font-size: 12px; color: var(--text-2); line-height: 1.4; }
	.starter b { display: block; font-size: 13.5px; color: var(--text); font-weight: 600; margin-bottom: 1px; }
	.starter:hover { background: var(--hover); }
	.starter.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 7%, transparent); }
	.emoji { font-size: 20px; line-height: 1.2; }
	.slug { display: flex; align-items: center; height: 28px; padding: 0 8px; border-radius: var(--radius); border: 1px solid var(--border-strong); background: var(--bg); font-weight: 400; min-width: 0; }
	.slug:focus-within { border-color: color-mix(in srgb, var(--accent) 65%, var(--border-strong)); }
	.slug.err { border-color: var(--danger); }
	.slug span { font-family: var(--font-mono); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 55%; }
	.slug input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--text); }
	.err { margin: -4px 0 0; color: var(--danger); font-size: 12.5px; }
	.foot { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
	.foot .small { flex: 1; font-size: 12px; }
	@media (max-width: 600px) {
		.choices, .starters, .row2 { grid-template-columns: 1fr; }
		.foot .small { display: none; }
	}
</style>
