<script lang="ts">
	import { ArrowUpRight, Cpu, Lock, Globe, Users, MemoryStick, Play, Plus, Search, Square, TriangleAlert } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import NewAppDialog from '#lib/apps/NewAppDialog.svelte';
	import { appsApi, RUNTIME_LABEL, uptime, view, type App, type Starter } from '#lib/apps/types.ts';
	import { session } from '#lib/state/session.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize } from '#lib/util.ts';

	let apps = $state<App[]>([]);
	let worker = $state(true);
	let isolated = $state(true);
	let loaded = $state(false);
	let q = $state('');
	let dialog = $state<{ start: 'ai' | 'template' | null; template?: string } | null>(null);
	let starters = $state<Starter[]>([]);

	async function load() {
		try {
			const r = await appsApi.list();
			apps = r.apps;
			worker = r.worker;
			isolated = r.isolated;
		} catch (e) {
			if (!loaded) ui.error(e);
		}
		loaded = true;
	}

	onMount(() => {
		load();
		api.get<Starter[]>('/apps/templates').then((s) => (starters = s)).catch(() => {});
		const t = setInterval(() => document.visibilityState === 'visible' && load(), 4000);
		return () => clearInterval(t);
	});

	let shown = $derived(q ? apps.filter((a) => (a.name + ' ' + a.slug + ' ' + a.description).toLowerCase().includes(q.toLowerCase())) : apps);
	let running = $derived(apps.filter((a) => a.state === 'running').length);

	async function toggle(a: App, e: MouseEvent) {
		e.stopPropagation();
		try {
			const r = await appsApi.action(a.slug, a.enabled ? 'stop' : 'start');
			apps = apps.map((x) => (x.id === r.id ? { ...x, ...r } : x));
			ui.toast(a.enabled ? `Stopping ${a.name}` : `Starting ${a.name}`);
			setTimeout(load, 1200);
		} catch (err) {
			ui.error(err);
		}
	}

	function created(a: App, kind: string) {
		dialog = null;
		goto(`/apps/${a.slug}${kind === 'ai' ? '?tab=build' : ''}`);
	}

	const ACCESS_ICON = { private: Lock, users: Users, public: Globe };
</script>

<svelte:head><title>Apps</title></svelte:head>

<div class="page-scroll">
	<div class="page wide">
		<div class="titlebar">
			<h1>Apps</h1>
			{#if apps.length}<span class="faint">{apps.length} app{apps.length === 1 ? '' : 's'} · {running} running</span>{/if}
			<span class="grow"></span>
			{#if session.site?.apps}
				<button class="btn" onclick={() => (dialog = { start: 'ai' })}><Sparkle size={14} />Build with AI</button>
				<button class="btn primary" onclick={() => (dialog = { start: null })}><Plus size={14} />New app</button>
			{/if}
		</div>
		<p class="lede">Small programs that run on this server in the background, each at its own address, with no Kern around them.</p>

		{#if !session.site?.apps}
			<div class="empty"><b>Apps are turned off for your account</b>An administrator can turn them on in Settings → Server.</div>
		{:else}
			{#if loaded && !worker}
				<div class="banner bad">
					<TriangleAlert size={16} />
					<div><b>The apps service is not running.</b> Apps can be set up, but nothing starts until it runs: <code>docker compose up -d apps</code>.</div>
				</div>
			{:else if loaded && !isolated && apps.length}
				<div class="banner">
					<TriangleAlert size={16} />
					<div><b>Apps are not isolated here.</b> They run as the same user as Kern and can read its files. In Docker every app gets a user of its own.</div>
				</div>
			{/if}

			{#if apps.length > 6}
				<div class="search"><Search size={14} class="faint" /><input bind:value={q} placeholder="Filter apps…" /></div>
			{/if}

			{#if shown.length}
				<div class="grid">
					{#each shown as a (a.id)}
						{@const v = view(a, worker)}
						{@const AccessIcon = ACCESS_ICON[a.access]}
						<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
						<div class="card" onclick={(e) => open(`/apps/${a.slug}`, e)}>
							<div class="top">
								<span class="tile">{a.icon || '◇'}</span>
								<div class="nm">
									<a href="/apps/{a.slug}" onclick={(e) => { e.preventDefault(); e.stopPropagation(); open(`/apps/${a.slug}`, e); }}>{a.name}</a>
									<a class="path" href={a.path} target="_blank" rel="noopener" onclick={(e) => e.stopPropagation()} title="Open {a.path} in a new tab">
										{a.path}<ArrowUpRight size={12} />
									</a>
								</div>
								<span class="state {v.tone}" title={v.detail}><i></i>{v.label}</span>
							</div>
							{#if a.description}<p class="d">{a.description}</p>{/if}
							<div class="meta">
								<span title="Who can open it"><AccessIcon size={12} />{a.access === 'private' ? 'Only you' : a.access === 'users' ? 'Signed-in users' : 'Public'}</span>
								{#if a.runtime}<span>{RUNTIME_LABEL[a.runtime] ?? a.runtime}</span>{/if}
								{#if a.metrics?.running && a.metrics.pid}
									<span title="CPU"><Cpu size={12} />{a.metrics.cpu.toFixed(0)}%</span>
									<span title="Memory"><MemoryStick size={12} />{fileSize(a.metrics.rss)}</span>
									<span title="Up for">up {uptime(a.metrics.uptime)}</span>
								{/if}
								<span class="grow"></span>
								<button class="icon-btn" title={a.enabled ? 'Stop' : 'Start'} onclick={(e) => toggle(a, e)}>
									{#if a.enabled}<Square size={13} />{:else}<Play size={13} />{/if}
								</button>
							</div>
						</div>
					{/each}
				</div>
			{:else if loaded && q}
				<div class="empty"><b>No apps match</b>Try another filter.</div>
			{:else if loaded}
				<div class="start">
					<button class="hero" onclick={() => (dialog = { start: 'ai' })}>
						<span class="hi"><Sparkle size={22} /></span>
						<span><b>Describe an app and let AI build it</b><span>“Log the weights of my chickens every week, with a chart for each.” It writes the code, deploys it and checks it works.</span></span>
					</button>
					<p class="section-title">Or start from a template</p>
					<div class="tpls">
						{#each starters as s (s.key)}
							<button class="tpl" onclick={() => (dialog = { start: 'template', template: s.key })}>
								<span class="emoji">{s.icon}</span><b>{s.name}</b><span>{s.description}</span>
							</button>
						{/each}
					</div>
					<p class="faint hint">You can also deploy one of your <a href="/git" onclick={(e) => { e.preventDefault(); open('/git', e); }}>git repositories</a> or any git URL with <b>New app</b>.</p>
				</div>
			{/if}
		{/if}
	</div>
</div>

{#if dialog}
	<NewAppDialog start={dialog.start} template={dialog.template} onclose={() => (dialog = null)} oncreated={created} />
{/if}

<style>
	.wide { max-width: 1040px; }
	.titlebar { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
	.grow { flex: 1; }
	.banner { display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px; margin-bottom: 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text-2); font-size: 13px; }
	.banner :global(svg) { flex: none; margin-top: 2px; color: var(--c-yellow); }
	.banner b { color: var(--text); font-weight: 600; }
	.banner.bad { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
	.banner.bad :global(svg) { color: var(--danger); }
	.banner code { font: 12px var(--font-mono); }
	.search { display: flex; align-items: center; gap: 6px; height: 30px; padding: 0 8px; margin-bottom: 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); }
	.search input { flex: 1; border: 0; outline: 0; background: none; }
	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
	.card { display: flex; flex-direction: column; gap: 8px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); cursor: pointer; transition: border-color 0.12s, transform 0.12s var(--ease); }
	.card:hover { border-color: var(--border-strong); }
	.top { display: flex; align-items: center; gap: 10px; min-width: 0; }
	.tile { flex: none; width: 38px; height: 38px; border-radius: 10px; display: grid; place-items: center; font-size: 20px; background: var(--surface-2); }
	.nm { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.nm > a:first-child { font-size: 14.5px; font-weight: 600; color: var(--text); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.nm > a:first-child:hover { color: var(--accent); }
	.path { display: inline-flex; align-items: center; gap: 2px; width: fit-content; font: 12px var(--font-mono); color: var(--text-3); text-decoration: none; }
	.path:hover { color: var(--accent); }
	.state { flex: none; display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
	.state i { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
	.state.ok i { background: var(--c-green); box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-green) 22%, transparent); }
	.state.busy i { background: var(--c-yellow); animation: pulse 1.2s ease-in-out infinite; }
	.state.bad { color: var(--danger); }
	.state.bad i { background: var(--danger); }
	@keyframes pulse { 50% { opacity: 0.35; } }
	.d { margin: 0; font-size: 13px; color: var(--text-2); display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
	.meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--text-3); margin-top: auto; }
	.meta span { display: inline-flex; align-items: center; gap: 4px; }
	.meta .icon-btn { margin: -4px -6px -4px 0; }
	.start { display: flex; flex-direction: column; }
	.hero { display: flex; gap: 14px; align-items: center; text-align: left; padding: 18px 20px; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border)); background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, var(--surface)), var(--surface)); color: var(--text-2); font-size: 13px; transition: border-color 0.15s; }
	.hero:hover { border-color: var(--accent); }
	.hero b { display: block; font-size: 15px; color: var(--text); font-weight: 600; margin-bottom: 2px; }
	.hi { flex: none; width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); }
	.tpls { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
	.tpl { display: flex; flex-direction: column; gap: 3px; text-align: left; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
	.tpl:hover { border-color: var(--border-strong); background: var(--surface-2); }
	.tpl b { font-size: 14px; color: var(--text); font-weight: 600; }
	.tpl .emoji { font-size: 22px; margin-bottom: 4px; }
	.hint { margin: 16px 0 0; font-size: 12.5px; }
	.hint a { color: var(--accent); }
	@media (prefers-reduced-motion: reduce) { .state.busy i { animation: none; } }
	@media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
</style>
