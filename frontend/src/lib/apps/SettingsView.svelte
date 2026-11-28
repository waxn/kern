<script lang="ts">
	import { Copy, Cpu, Database, Download, Eye, EyeOff, GitBranch, Globe, KeyRound, Lock, Plus, Route, SlidersHorizontal, Terminal, Trash2, TriangleAlert, Users, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';
	import type { AiConfig } from '#lib/ai/ai.svelte.ts';
	import Toggle from '#lib/auth/Toggle.svelte';
	import EmojiPicker from '#lib/components/EmojiPicker.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize } from '#lib/util.ts';
	import { appsApi, type Access, type App } from './types.ts';

	let { app, onsaved }: { app: App; onsaved: (a: App) => void } = $props();

	let name = $state('');
	let description = $state('');
	let slug = $state('');
	let publicPaths = $state<string[]>([]);
	let branch = $state('');
	let subdir = $state('');
	let gitUrl = $state('');
	let gitToken = $state('');
	let runtime = $state('');
	let buildCmd = $state('');
	let startCmd = $state('');
	let health = $state('');
	let vars = $state<{ name: string; value: string; show?: boolean }[]>([]);
	let varsOriginal = '';
	let data = $state<{ size: number; files: number } | null>(null);
	let picker = $state<{ x: number; y: number } | null>(null);
	let deleteRepo = $state(false);
	let aiCfg = $state<AiConfig | null>(null);

	function reset(a: App) {
		name = a.name;
		description = a.description;
		slug = a.slug;
		publicPaths = [...(a.public_paths ?? [])];
		branch = a.branch;
		subdir = a.subdir;
		gitUrl = a.git_url;
		gitToken = '';
		runtime = a.runtime_setting ?? '';
		buildCmd = a.build_cmd ?? '';
		startCmd = a.start_cmd ?? '';
		health = a.health_path ?? '';
	}

	onMount(async () => {
		reset(app);
		try {
			const e = await api.get<{ vars: { name: string; value: string }[] }>(`/apps/${app.slug}/env`);
			vars = e.vars;
			varsOriginal = JSON.stringify(e.vars);
			data = await api.get(`/apps/${app.slug}/data`);
			aiCfg = await api.get<AiConfig>(`/apps/${app.slug}/ai`).catch(() => null);
		} catch (err) {
			ui.error(err);
		}
	});

	async function save(patch: Record<string, unknown>, msg = 'Saved') {
		try {
			const a = await appsApi.patch(app.slug, patch);
			onsaved(a);
			reset(a);
			ui.toast(msg);
			if (a.slug !== app.slug) goto(`/apps/${a.slug}?tab=settings`, { replaceState: true });
		} catch (e) {
			ui.error(e);
		}
	}

	let generalDirty = $derived(name !== app.name || description !== app.description);
	let pathsDirty = $derived(JSON.stringify(publicPaths.filter((p) => p.trim())) !== JSON.stringify(app.public_paths ?? []));
	let sourceDirty = $derived(branch !== app.branch || subdir !== app.subdir || (app.source === 'url' && (gitUrl !== app.git_url || !!gitToken)));
	let runDirty = $derived(runtime !== (app.runtime_setting ?? '') || buildCmd !== (app.build_cmd ?? '') || startCmd !== (app.start_cmd ?? '') || health !== (app.health_path ?? ''));
	let varsDirty = $derived(JSON.stringify(vars.map(({ name, value }) => ({ name, value }))) !== varsOriginal);

	async function saveVars(restart: boolean) {
		const obj: Record<string, string> = {};
		for (const v of vars) if (v.name.trim()) obj[v.name.trim()] = v.value;
		try {
			const r = await api.put<{ vars: { name: string; value: string }[] }>(`/apps/${app.slug}/env`, { vars: obj, restart });
			vars = r.vars;
			varsOriginal = JSON.stringify(r.vars);
			ui.toast(restart ? 'Saved. Restarting…' : 'Saved. They apply from the next start.');
		} catch (e) {
			ui.error(e);
		}
	}

	async function remove() {
		const ok = await ui.confirm({
			title: `Delete ${app.name}?`,
			message: `The app stops and its data (${data ? fileSize(data.size) : 'everything in APP_DATA_DIR'}) is deleted for good.` +
				(app.source === 'kern' ? (deleteRepo ? ` The repository ${app.repo} is deleted too.` : ` The repository ${app.repo} stays.`) : ''),
			confirmLabel: 'Delete app', danger: true
		});
		if (!ok) return;
		const r = await appsApi.remove(app.slug, deleteRepo);
		if (r.ok) {
			ui.toast(`Deleted ${app.name}`);
			goto('/apps');
		} else ui.error(new Error('Could not delete the app.'));
	}

	function copy(text: string) {
		navigator.clipboard.writeText(text).then(() => ui.toast('Copied'));
	}

	const ACCESS: { v: Access; label: string; text: string; icon: typeof Lock }[] = [
		{ v: 'private', label: 'Only me', text: 'You, signed in to Kern.', icon: Lock },
		{ v: 'users', label: 'Signed-in users', text: 'Anyone with an account on this server.', icon: Users },
		{ v: 'public', label: 'Everyone', text: 'Anyone with the link, no sign-in.', icon: Globe }
	];
	let hookUrl = $derived(app.hook_path ? location.origin + app.hook_path : '');
</script>

<div class="settings">
	<section>
		<h3><SlidersHorizontal size={14} />General</h3>
		<div class="grid">
			<label class="field icon"><span>Icon</span>
				<button class="emoji" onclick={(e) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); picker = { x: r.left, y: r.bottom + 4 }; }}>{app.icon || '◇'}</button>
			</label>
			<label class="field"><span>Name</span><input class="input" bind:value={name} maxlength="80" /></label>
			<label class="field span"><span>Description</span><input class="input" bind:value={description} maxlength="300" placeholder="What is it for?" /></label>
		</div>
		{#if generalDirty}<div class="acts"><button class="btn ghost" onclick={() => reset(app)}>Cancel</button><button class="btn primary" onclick={() => save({ name, description })}>Save</button></div>{/if}
	</section>

	<section>
		<h3><Globe size={14} />Address and access</h3>
		<label class="field"><span>Address</span>
			<div class="slug"><span class="faint host">{location.host}/</span><input class="mono" bind:value={slug} maxlength="40" spellcheck="false" oninput={() => (slug = slug.toLowerCase())} /><span class="faint">/</span>
				{#if slug !== app.slug}<button class="btn primary sm" onclick={() => save({ slug }, `Moved to /${slug}/`)}>Move</button>{/if}
			</div>
			<em>Bookmarks and links to the old address stop working when you change it.</em>
		</label>
		<div class="access">
			{#each ACCESS as o (o.v)}
				<button class="opt" class:on={app.access === o.v} onclick={() => app.access !== o.v && save({ access: o.v }, `Now: ${o.label.toLowerCase()}`)}>
					<o.icon size={15} /><b>{o.label}</b><span>{o.text}</span>
				</button>
			{/each}
		</div>
		<div class="item">
			<div><b>Remove /{app.slug} from paths</b><span>The app sees <code>/api/x</code> for <code>/{app.slug}/api/x</code>. Turn off if the app handles its base path itself (it is in <code>KERN_BASE_PATH</code>).</span></div>
			<Toggle checked={app.strip_prefix} label="Remove the path prefix" onchange={(v) => save({ strip_prefix: v })} />
		</div>
	</section>

	{#if app.access !== 'public'}
		<section>
			<h3><Route size={14} />Public paths</h3>
			<p class="muted">Reachable by anyone even though the app is not public, e.g. an API your devices post to. The app checks its own token there.</p>
			{#if publicPaths.length}
				<div class="paths">
					{#each publicPaths as _, i (i)}
						<div class="pp"><span class="faint mono">/{app.slug}</span><input class="input mono" bind:value={publicPaths[i]} placeholder="/api/ingest" /><button class="icon-btn" title="Remove" onclick={() => (publicPaths = publicPaths.filter((__, j) => j !== i))}><X size={14} /></button></div>
					{/each}
				</div>
			{/if}
			<div class="acts left">
				<button class="btn ghost" onclick={() => (publicPaths = [...publicPaths, ''])}><Plus size={13} />Add a path</button>
				{#if pathsDirty}<span class="grow"></span><button class="btn primary" onclick={() => save({ public_paths: publicPaths.filter((p) => p.trim()) })}>Save paths</button>{/if}
			</div>
		</section>
	{/if}

	<section>
		<h3><GitBranch size={14} />Source</h3>
		{#if app.source === 'kern'}
			<p class="muted">Kern repository <a href="/git/{app.repo}" onclick={(e) => { e.preventDefault(); goto(`/git/${app.repo}`); }}>{app.repo}</a>. Clone it, change it, push: Kern deploys it.</p>
		{:else}
			<label class="field"><span>Repository URL</span><input class="input mono" bind:value={gitUrl} /></label>
			<label class="field"><span>Access token <em>{app.has_token ? 'a token is stored; type to replace it' : 'only for private repositories'}</em></span><input class="input mono" type="password" autocomplete="off" bind:value={gitToken} /></label>
		{/if}
		<div class="grid two">
			<label class="field"><span>Branch</span><input class="input mono" bind:value={branch} /></label>
			<label class="field"><span>Folder <em>in the repo</em></span><input class="input mono" bind:value={subdir} placeholder="(top level)" /></label>
		</div>
		{#if sourceDirty}<div class="acts"><button class="btn ghost" onclick={() => reset(app)}>Cancel</button><button class="btn primary" onclick={() => save(app.source === 'url' ? { branch, subdir, git_url: gitUrl, ...(gitToken ? { git_token: gitToken } : {}) } : { branch, subdir })}>Save</button></div>{/if}
		{#if app.source === 'kern'}
			<div class="item">
				<div><b>Deploy on push</b><span>Every push to {app.branch} (and every edit here or by the AI) goes live by itself.</span></div>
				<Toggle checked={app.auto_deploy} label="Deploy on push" onchange={(v) => save({ auto_deploy: v })} />
			</div>
		{/if}
		<div class="field">
			<span>Deploy hook <em>POST to this URL (from GitHub, a CI job, a script) to deploy the branch. Keep it secret.</em></span>
			<div class="copy"><code class="truncate">{hookUrl}</code><button class="icon-btn" title="Copy" onclick={() => copy(hookUrl)}><Copy size={13} /></button></div>
		</div>
	</section>

	<section>
		<h3><Terminal size={14} />How it runs</h3>
		<p class="muted">Empty fields come from <code>.kern/app.yml</code> in the code, or are worked out from its files.</p>
		<div class="grid two">
			<label class="field"><span>Runtime</span>
				<select class="input" bind:value={runtime}>
					<option value="">Detect ({app.live?.runtime || 'from the files'})</option>
					<option value="static">Static files</option><option value="python">Python</option><option value="node">Node.js</option><option value="command">Command</option>
				</select>
			</label>
			<label class="field"><span>Health check path <em>before traffic moves</em></span><input class="input mono" bind:value={health} placeholder="/healthz" /></label>
			<label class="field span"><span>Build command</span><input class="input mono" bind:value={buildCmd} placeholder="npm ci && npm run build" /></label>
			<label class="field span"><span>Start command <em>has to listen on $PORT</em></span><input class="input mono" bind:value={startCmd} placeholder="python app.py" /></label>
		</div>
		{#if runDirty}<div class="acts"><button class="btn ghost" onclick={() => reset(app)}>Cancel</button><button class="btn primary" onclick={() => save({ runtime, build_cmd: buildCmd, start_cmd: startCmd, health_path: health }, 'Saved. Deploy to use it.')}>Save</button></div>{/if}
	</section>

	<section>
		<h3><Cpu size={14} />Build with AI</h3>
		<div class="item">
			<div><b>Model</b><span>{aiCfg ? (aiCfg.inherited ? 'Following the workspace model' : 'Chosen for this app') : '…'}{aiCfg?.model ? ` · ${aiCfg.model}` : ''}</span></div>
			<a class="btn" href="/apps/{app.slug}?tab=build&ai=1">Choose…</a>
		</div>
		<p class="muted">Only this app's AI builder uses it. The rest of Kern keeps the workspace model from <a href="/settings?s=ai">Settings → AI</a>.</p>
	</section>

	<section>
		<h3><Database size={14} />Data</h3>
		<div class="item">
			<div><b>{data ? `${fileSize(data.size)} in ${data.files} file${data.files === 1 ? '' : 's'}` : '…'}</b><span>What the app keeps in <code>APP_DATA_DIR</code>. It survives deploys, but isn't in Kern's backups: download a copy now and then.</span></div>
			<a class="btn" href="/api/apps/{app.slug}/data?download=1" download><Download size={14} />Download</a>
		</div>
	</section>

	<section class="wide">
		<h3><KeyRound size={14} />Environment variables</h3>
		<p class="muted">Secrets and settings for the app, stored encrypted. Kern also sets <code>PORT</code>, <code>APP_DATA_DIR</code>, <code>KERN_BASE_PATH</code> and <code>KERN_APP_SECRET</code>.</p>
		<div class="vars">
			{#each vars as v, i (i)}
				<div class="var">
					<input class="input mono" bind:value={v.name} placeholder="NAME" spellcheck="false" oninput={() => (v.name = v.name.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))} />
					<input class="input mono" type={v.show ? 'text' : 'password'} bind:value={v.value} placeholder="value" autocomplete="off" />
					<button class="icon-btn" title={v.show ? 'Hide' : 'Show'} onclick={() => (v.show = !v.show)}>{#if v.show}<EyeOff size={14} />{:else}<Eye size={14} />{/if}</button>
					<button class="icon-btn" title="Remove" onclick={() => (vars = vars.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
				</div>
			{/each}
		</div>
		<div class="acts left">
			<button class="btn ghost" onclick={() => (vars = [...vars, { name: '', value: '', show: true }])}><Plus size={13} />Add a variable</button>
			{#if varsDirty}
				<span class="grow"></span>
				<button class="btn" onclick={() => saveVars(false)}>Save</button>
				<button class="btn primary" onclick={() => saveVars(true)}>Save and restart</button>
			{/if}
		</div>
	</section>

	<section class="wide danger">
		<h3><TriangleAlert size={14} />Danger zone</h3>
		<div class="item">
			<div><b>Delete this app</b><span>Stops it and deletes its data and deployments.</span>
				{#if app.source === 'kern'}<label class="check"><input type="checkbox" bind:checked={deleteRepo} />Also delete the repository {app.repo}</label>{/if}
			</div>
			<button class="btn danger" onclick={remove}><Trash2 size={14} />Delete app</button>
		</div>
	</section>
</div>

{#if picker}
	<EmojiPicker x={picker.x} y={picker.y} onclose={() => (picker = null)} onpick={(e) => { picker = null; save({ icon: e }); }} />
{/if}

<style>
	/* Masonry: CSS columns, 1 to 3 wide depending on the width the page gives us. */
	.settings { column-width: 330px; column-count: 3; column-gap: 12px; max-width: 100%; min-width: 0; }
	section { display: block; break-inside: avoid; margin: 0 0 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); min-width: 0; }
	section > * + * { margin-top: 10px; }
	section.wide { column-span: all; }
	section.danger { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); background: color-mix(in srgb, var(--danger) 5%, var(--surface)); }
	section.danger h3 { color: var(--danger); }
	section.danger h3 :global(svg) { color: var(--danger); }
	h3 { margin: 0; display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 650; }
	h3 :global(svg) { flex: none; color: var(--text-3); }
	section > h3 + * { margin-top: 8px; }
	.muted { margin: 0; color: var(--text-2); font-size: 12.5px; line-height: 1.45; overflow-wrap: anywhere; }
	section > h3 + .muted { margin-top: 6px; }
	.muted a { color: var(--accent); }
	code { font: 0.9em var(--font-mono); padding: 0 3px; border-radius: 3px; background: var(--code-bg); }
	.grid { display: grid; grid-template-columns: auto 1fr; gap: 8px 10px; align-items: end; }
	.grid.two { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
	.span { grid-column: 1 / -1; }
	.field { display: flex; flex-direction: column; gap: 3px; font-size: 12px; font-weight: 550; color: var(--text-2); min-width: 0; }
	.field em { font-style: normal; font-weight: 400; color: var(--text-3); }
	.field > em { font-size: 12px; }
	.field .input { width: 100%; }
	.emoji { width: 40px; height: 34px; border-radius: 8px; border: 1px solid var(--border-strong); font-size: 18px; background: var(--bg); }
	.emoji:hover { background: var(--hover); }
	.mono { font-family: var(--font-mono); font-size: 12.5px; }
	.slug { display: flex; align-items: center; gap: 2px; height: 30px; padding: 0 3px 0 8px; border-radius: var(--radius); border: 1px solid var(--border-strong); background: var(--bg); font-weight: 400; min-width: 0; }
	.slug:focus-within { border-color: color-mix(in srgb, var(--accent) 65%, var(--border-strong)); }
	.slug span { font: 12.5px var(--font-mono); flex: none; }
	.slug .host { flex: 0 1 auto; min-width: 0; max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.slug input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; color: var(--text); }
	.btn.sm { height: 24px; padding: 0 8px; font-size: 12px; }
	.access { display: grid; grid-template-columns: 1fr; gap: 6px; }
	.opt { display: grid; grid-template-columns: auto 1fr; gap: 0 8px; align-items: center; text-align: left; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 12px; color: var(--text-2); }
	.opt :global(svg) { grid-row: span 2; color: var(--text-3); }
	.opt b { font-size: 13px; color: var(--text); font-weight: 600; }
	.opt:hover { background: var(--hover); }
	.opt.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 7%, transparent); }
	.opt.on :global(svg) { color: var(--accent); }
	.paths { display: flex; flex-direction: column; gap: 6px; }
	.pp { display: flex; align-items: center; gap: 6px; font-weight: 400; min-width: 0; }
	.pp > .faint { flex: none; max-width: 40%; overflow: hidden; text-overflow: ellipsis; }
	.pp .input { flex: 1; min-width: 0; }
	.item { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; justify-content: space-between; }
	.item > div { flex: 1 1 200px; min-width: 0; display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; color: var(--text-2); overflow-wrap: anywhere; }
	.item b { font-size: 13px; color: var(--text); font-weight: 550; }
	.copy { display: flex; align-items: center; gap: 4px; padding: 0 3px 0 8px; height: 30px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); font-weight: 400; min-width: 0; }
	.copy code { flex: 1; background: none; color: var(--text-2); }
	.vars { display: flex; flex-direction: column; gap: 6px; }
	.vars:empty { display: none; }
	.var { display: grid; grid-template-columns: minmax(120px, 1fr) 2fr auto auto; gap: 6px; align-items: center; }
	.var .input { min-width: 0; }
	.acts { display: flex; gap: 6px; justify-content: flex-end; align-items: center; flex-wrap: wrap; }
	.acts.left { justify-content: flex-start; }
	.grow { flex: 1; }
	.check { display: flex; align-items: center; gap: 6px; margin-top: 6px; color: var(--text-2); font-size: 12.5px; }
	@media (max-width: 640px) {
		.settings { column-count: 1; column-width: auto; }
		.var { grid-template-columns: 1fr 1fr auto auto; }
	}
</style>
