<script lang="ts">
	import { ArrowLeft, ArrowUpRight, Cpu, Globe, Lock, MemoryStick, Play, RefreshCw, Rocket, RotateCw, Square, TriangleAlert, Users } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError } from '#lib/api.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import BuilderView from '#lib/apps/BuilderView.svelte';
	import DeploysView from '#lib/apps/DeploysView.svelte';
	import FilesView from '#lib/apps/FilesView.svelte';
	import LogView from '#lib/apps/LogView.svelte';
	import SettingsView from '#lib/apps/SettingsView.svelte';
	import { ACCESS_LABEL, appsApi, RUNTIME_LABEL, uptime, view, type App } from '#lib/apps/types.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, relTime } from '#lib/util.ts';

	type Tab = 'preview' | 'build' | 'logs' | 'deploys' | 'files' | 'settings';
	const TABS: { k: Tab; label: string }[] = [
		{ k: 'preview', label: 'Preview' }, { k: 'build', label: 'Build with AI' }, { k: 'logs', label: 'Logs' },
		{ k: 'deploys', label: 'Deploys' }, { k: 'files', label: 'Files' }, { k: 'settings', label: 'Settings' }
	];

	let slug = $derived(page.params.slug ?? '');
	let app = $state<App | null>(null);
	let missing = $state(false);
	let busy = $state('');
	let frame = $state<HTMLIFrameElement>();
	let frameKey = $state(0);
	let tab = $derived<Tab>((TABS.some((t) => t.k === page.url.searchParams.get('tab')) ? page.url.searchParams.get('tab') : null) as Tab ?? 'preview');

	async function load() {
		try {
			const a = await appsApi.get(slug);
			const wasRunning = app?.state === 'running' && app.live?.number;
			app = a;
			missing = false;
			// A new release went live: reload the preview.
			if (wasRunning && a.live?.number !== wasRunning && tab === 'preview') frameKey++;
		} catch (e) {
			if (e instanceof ApiError && e.status === 404) missing = true;
			else if (!app) ui.error(e);
		}
	}

	let loadedSlug = '';
	$effect(() => {
		if (slug && slug !== loadedSlug) {
			loadedSlug = slug;
			app = null;
			load();
		}
	});

	onMount(() => {
		const t = setInterval(() => document.visibilityState === 'visible' && load(), 3000);
		return () => clearInterval(t);
	});

	function setTab(k: Tab) {
		const u = new URL(page.url.href);
		if (k === 'preview') u.searchParams.delete('tab');
		else u.searchParams.set('tab', k);
		goto(u.pathname + u.search, { replaceState: true });
	}

	async function act(action: 'start' | 'stop' | 'restart' | 'deploy') {
		if (!app) return;
		busy = action;
		try {
			app = await appsApi.action(app.slug, action);
			ui.toast({ start: 'Starting…', stop: 'Stopped', restart: 'Restarting…', deploy: 'Deployment queued' }[action]);
			if (action === 'deploy' && tab !== 'deploys') setTab('deploys');
			setTimeout(load, 1000);
			if (action !== 'stop') setTimeout(() => frameKey++, 2500);
		} catch (e) {
			ui.error(e);
		} finally {
			busy = '';
		}
	}

	let v = $derived(app ? view(app, app.worker !== false) : null);
	const ACCESS_ICON = { private: Lock, users: Users, public: Globe };
</script>

<svelte:head><title>{app ? `${app.name} · Apps` : 'Apps'}</title></svelte:head>

<div class="page-scroll">
	<div class="page wide">
		<a class="back" href="/apps" onclick={(e) => { e.preventDefault(); open('/apps', e); }}><ArrowLeft size={14} />Apps</a>
		{#if missing}
			<div class="empty"><b>No app at /{slug}</b>It may have been deleted or moved to another address.</div>
		{:else if app && v}
			{@const AccessIcon = ACCESS_ICON[app.access]}
			<header>
				<span class="tile">{app.icon || '◇'}</span>
				<div class="title">
					<div class="nm">
						<h1>{app.name}</h1>
						<span class="state {v.tone}" title={v.detail}><i></i>{v.label}</span>
					</div>
					<div class="sub">
						<a class="path" href={app.path} target="_blank" rel="noopener">{location.host}{app.path}<ArrowUpRight size={12} /></a>
						<span title="Who can open it"><AccessIcon size={12} />{ACCESS_LABEL[app.access]}</span>
						{#if app.runtime}<span>{RUNTIME_LABEL[app.runtime] ?? app.runtime}</span>{/if}
						{#if app.metrics?.running && app.metrics.pid}
							<span title="CPU"><Cpu size={12} />{app.metrics.cpu.toFixed(1)}%</span>
							<span title="Memory"><MemoryStick size={12} />{fileSize(app.metrics.rss)}</span>
							<span>up {uptime(app.metrics.uptime)}</span>
						{/if}
						{#if app.live}<span title={app.live.subject}>live: #{app.live.number} · {app.live.short} · {relTime(app.live.finished)}</span>{/if}
					</div>
				</div>
				<div class="actions">
					{#if app.enabled}
						<button class="btn ghost" disabled={!!busy} onclick={() => act('restart')} title="Restart"><RotateCw size={14} /><span class="hide-sm">Restart</span></button>
						<button class="btn ghost" disabled={!!busy} onclick={() => act('stop')}><Square size={13} /><span class="hide-sm">Stop</span></button>
					{:else}
						<button class="btn" disabled={!!busy} onclick={() => act('start')}><Play size={13} />Start</button>
					{/if}
					<button class="btn ghost" disabled={!!busy} onclick={() => act('deploy')} title="Build and deploy the newest commit of {app.branch}"><Rocket size={14} /><span class="hide-sm">Deploy</span></button>
					<a class="btn primary" href={app.path} target="_blank" rel="noopener"><ArrowUpRight size={14} />Open</a>
				</div>
			</header>

			{#if app.worker === false}
				<div class="banner bad"><TriangleAlert size={15} /><span><b>The apps service is not running</b>, so this app can't start. Start it with <code>docker compose up -d apps</code>.</span></div>
			{:else if (v.tone === 'bad' || app.state === 'failed') && v.detail}
				<div class="banner bad"><TriangleAlert size={15} /><span>{v.detail} <button class="link" onclick={() => setTab(app?.state === 'failed' ? 'deploys' : 'logs')}>{app.state === 'failed' ? 'See the build log' : 'See the log'}</button>{#if app.repo} · <button class="link" onclick={() => { setTab('build'); }}>ask the AI to fix it</button>{/if}</span></div>
			{/if}

			<div class="tabs" role="tablist">
				{#each TABS as t (t.k)}
					<button role="tab" aria-selected={tab === t.k} class:on={tab === t.k} onclick={() => setTab(t.k)}>
						{#if t.k === 'build'}<Sparkle size={13} />{/if}{t.label}
					</button>
				{/each}
			</div>

			<div class="pane">
				{#if tab === 'preview'}
					{#if app.state === 'running' || app.metrics?.running}
						<div class="preview">
							<div class="pbar">
								<button class="icon-btn" title="Reload" onclick={() => frameKey++}><RefreshCw size={13} /></button>
								<span class="url mono truncate">{location.host}{app.path}</span>
								<a class="icon-btn" href={app.path} target="_blank" rel="noopener" title="Open in a new tab"><ArrowUpRight size={14} /></a>
							</div>
							{#key frameKey}
								<iframe bind:this={frame} src={app.path} title="{app.name} preview"></iframe>
							{/key}
						</div>
					{:else}
						<div class="empty big">
							{#if v.tone === 'busy'}
								<b>{v.label}…</b>The preview shows up when it's running. <button class="link" onclick={() => setTab('deploys')}>Watch the build</button>
							{:else if !app.live && !app.latest}
								<b>Nothing deployed yet</b>
								{#if app.repo}Describe the app to the AI, or push code to <code>{app.repo}</code>.
									<div><button class="btn primary first" onclick={() => setTab('build')}><Sparkle size={14} />Build with AI</button></div>
								{:else}Deploy the branch to start.{/if}
							{:else if !app.enabled}
								<b>Stopped</b>Start it to see it here.<div><button class="btn primary first" onclick={() => act('start')}><Play size={13} />Start</button></div>
							{:else}
								<b>{v.label}</b>{v.detail}
							{/if}
						</div>
					{/if}
				{:else if tab === 'build'}
					<BuilderView {app} onchange={load} />
				{:else if tab === 'logs'}
					<LogView url="/apps/{app.slug}/logs" height="calc(100dvh - 230px)" empty="No output yet. What the app prints shows up here." />
				{:else if tab === 'deploys'}
					<DeploysView {app} onchange={load} />
				{:else if tab === 'files'}
					<FilesView {app} onchange={load} />
				{:else}
					<SettingsView {app} onsaved={(a) => (app = { ...app!, ...a })} />
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.wide { max-width: 1180px; padding-top: 20px; }
	.back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-3); text-decoration: none; font-size: 12.5px; margin-bottom: 12px; }
	.back:hover { color: var(--text); }
	header { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
	.tile { flex: none; width: 48px; height: 48px; border-radius: 13px; display: grid; place-items: center; font-size: 26px; background: var(--surface-2); }
	.title { flex: 1; min-width: 240px; }
	.nm { display: flex; align-items: center; gap: 12px; }
	.nm h1 { margin: 0; }
	.sub { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 3px; font-size: 12.5px; color: var(--text-3); }
	.sub span, .sub a { display: inline-flex; align-items: center; gap: 4px; }
	.path { font-family: var(--font-mono); color: var(--text-2); text-decoration: none; }
	.path:hover { color: var(--accent); }
	.state { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px; border-radius: 11px; font-size: 12px; background: var(--surface-2); color: var(--text-2); }
	.state i { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
	.state.ok { color: var(--c-green); background: color-mix(in srgb, var(--c-green) 13%, transparent); }
	.state.ok i { background: var(--c-green); }
	.state.busy { color: var(--c-yellow); background: color-mix(in srgb, var(--c-yellow) 13%, transparent); }
	.state.busy i { background: var(--c-yellow); animation: pulse 1.2s infinite; }
	.state.bad { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
	.state.bad i { background: var(--danger); }
	@keyframes pulse { 50% { opacity: 0.35; } }
	.actions { display: flex; gap: 6px; align-items: center; }
	.banner { display: flex; gap: 8px; align-items: flex-start; margin-top: 14px; padding: 9px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); font-size: 13px; color: var(--text-2); }
	.banner.bad { border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
	.banner :global(svg) { flex: none; margin-top: 2px; color: var(--danger); }
	.banner b { color: var(--text); }
	.banner code { font: 12px var(--font-mono); }
	.link { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
	.tabs { display: flex; gap: 2px; margin: 18px 0 14px; border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none; }
	.tabs button { display: inline-flex; align-items: center; gap: 5px; padding: 8px 12px; margin-bottom: -1px; border-bottom: 2px solid transparent; color: var(--text-2); white-space: nowrap; font-weight: 500; }
	.tabs button:hover { color: var(--text); }
	.tabs button.on { color: var(--text); border-bottom-color: var(--accent); }
	.tabs button :global(svg) { color: var(--accent); }
	.preview { display: flex; flex-direction: column; height: calc(100dvh - 230px); min-height: 420px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }
	.pbar { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-bottom: 1px solid var(--border); }
	.url { flex: 1; font-size: 12px; color: var(--text-3); text-align: center; }
	.mono { font-family: var(--font-mono); }
	iframe { flex: 1; width: 100%; border: 0; background: var(--bg); }
	.empty.big { padding: 60px 20px; }
	.empty code { font: 12px var(--font-mono); }
	.first { margin-top: 14px; }
	@media (max-width: 700px) {
		.hide-sm { display: none; }
		.actions { width: 100%; }
		.actions .primary { margin-left: auto; }
	}
	@media (prefers-reduced-motion: reduce) { .state.busy i { animation: none; } }
</style>
