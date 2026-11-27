<script lang="ts">
	// What the app is doing right now: its processes, deployments in flight or queued, and the AI
	// builder's current turn. Polls every 3s while the page is visible.
	import { Bot, Cpu, Hammer, ListOrdered, MemoryStick, RotateCw, TriangleAlert } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize } from '#lib/util.ts';
	import { appsApi, TRIGGER_LABEL, uptime, type App, type TaskProcess, type TasksInfo } from './types.ts';

	let { app, ontab }: { app: App; ontab?: (tab: 'deploys' | 'build' | 'logs') => void } = $props();

	let info = $state<TasksInfo | null>(null);
	let loaded = $state(false);
	let failed = $state(false);
	let now = $state(Date.now());

	let seq = 0;
	async function load() {
		const my = ++seq;
		try {
			const r = await appsApi.tasks(app.slug);
			if (my !== seq) return;
			info = r;
			failed = false;
		} catch (e) {
			if (my !== seq) return;
			if (!info) ui.error(e);
			failed = true;
		}
		loaded = true;
	}

	onMount(() => {
		load();
		const poll = setInterval(() => document.visibilityState === 'visible' && load(), 3000);
		const tick = setInterval(() => document.visibilityState === 'visible' && (now = Date.now()), 1000);
		const vis = () => {
			if (document.visibilityState === 'visible') {
				now = Date.now();
				load();
			}
		};
		document.addEventListener('visibilitychange', vis);
		return () => {
			clearInterval(poll);
			clearInterval(tick);
			document.removeEventListener('visibilitychange', vis);
		};
	});

	// The process list as a tree: children under their parent, indented.
	let tree = $derived.by(() => {
		const procs = info?.processes ?? [];
		const pids = new Set(procs.map((p) => p.pid));
		const kids = new Map<number, TaskProcess[]>();
		const roots: TaskProcess[] = [];
		for (const p of procs) {
			if (pids.has(p.ppid) && p.ppid !== p.pid) kids.set(p.ppid, [...(kids.get(p.ppid) ?? []), p]);
			else roots.push(p);
		}
		const out: { p: TaskProcess; depth: number }[] = [];
		const seen = new Set<number>();
		const walk = (p: TaskProcess, depth: number) => {
			if (seen.has(p.pid)) return;
			seen.add(p.pid);
			out.push({ p, depth });
			for (const c of kids.get(p.pid) ?? []) walk(c, depth + 1);
		};
		for (const r of roots) walk(r, 0);
		return out;
	});

	const STATE_TONE: Record<string, string> = { running: 'ok', starting: 'busy', building: 'busy', crashed: 'bad', failed: 'bad', stopped: 'off', new: 'off' };
	const DEPLOY_TONE: Record<string, string> = { queued: 'busy', building: 'busy', starting: 'busy', live: 'ok', failed: 'bad' };

	function elapsed(iso: string | null | undefined): string {
		if (!iso) return '';
		const t = Date.parse(iso);
		return Number.isNaN(t) ? '' : uptime(Math.max(0, Math.floor((now - t) / 1000)));
	}
	const pct = (n: number) => `${Math.max(0, Math.min(100, n))}%`;
</script>

{#if !loaded}
	<p class="faint">Loading…</p>
{:else if !info}
	<div class="empty"><b>Can't read the tasks</b>The server did not answer. It tries again every few seconds.</div>
{:else}
	{#if !info.worker_up}
		<div class="banner bad"><TriangleAlert size={15} /><span><b>The apps service is not running</b>, so nothing below is live. Start it with <code>docker compose up -d apps</code>.</span></div>
	{:else if failed}
		<div class="banner"><TriangleAlert size={15} /><span>Lost contact with the server; showing the last known state.</span></div>
	{/if}

	<div class="cards">
		<section class="card wide">
			<header>
				<Cpu size={15} /><h3>Processes</h3>
				<span class="st {STATE_TONE[info.state] ?? 'off'}"><i></i>{info.state}</span>
				<span class="grow"></span>
				<button class="link" onclick={() => ontab?.('logs')}>Logs</button>
			</header>
			{#if info.process}
				<div class="stats">
					<div><span class="faint">PID</span><b class="mono">{info.process.pid}</b></div>
					<div><span class="faint">Up</span><b>{uptime(info.process.uptime_s)}</b></div>
					<div><span class="faint"><RotateCw size={11} />Restarts</span><b class:warn={info.process.restarts > 0}>{info.process.restarts}</b></div>
					<div>
						<span class="faint"><Cpu size={11} />CPU</span><b>{info.process.cpu.toFixed(1)}%</b>
						<div class="bar"><i style:width={pct(info.process.cpu)}></i></div>
					</div>
					<div><span class="faint"><MemoryStick size={11} />Memory</span><b>{fileSize(info.process.mem_bytes)}</b></div>
				</div>
			{:else}
				<p class="none">{info.state === 'running' || info.state === 'starting' ? 'Waiting for the process…' : 'Not running.'}</p>
			{/if}
			{#if tree.length}
				<div class="procs">
					<div class="prow head faint"><span>Command</span><span class="r">PID</span><span class="r">CPU</span><span class="r">Memory</span><span class="r">Age</span></div>
					{#each tree as { p, depth } (p.pid)}
						<div class="prow">
							<span class="cmd mono truncate" style:padding-left="{depth * 14}px" title={p.cmd}>{#if depth}<i class="elbow">└</i>{/if}{p.cmd}</span>
							<span class="r mono">{p.pid}</span>
							<span class="r">{p.cpu.toFixed(1)}%</span>
							<span class="r">{fileSize(p.mem_bytes)}</span>
							<span class="r">{uptime(p.age_s)}</span>
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<section class="card">
			<header>
				<Hammer size={15} /><h3>Deployments</h3>
				<span class="grow"></span>
				<button class="link" onclick={() => ontab?.('deploys')}>All deploys</button>
			</header>
			{#if info.deploy}
				<div class="job">
					<span class="dot {DEPLOY_TONE[info.deploy.status] ?? 'off'}"></span>
					<div class="jb">
						<div><b>#{info.deploy.number}</b> <span class="st {DEPLOY_TONE[info.deploy.status] ?? 'off'}">{info.deploy.status}</span></div>
						<div class="faint truncate" title={info.deploy.subject}>{info.deploy.subject || 'Deployment'}</div>
					</div>
					{#if info.deploy.started}<span class="faint nowrap">{elapsed(info.deploy.started)}</span>{/if}
				</div>
			{:else}
				<p class="none">Nothing is deploying.</p>
			{/if}
			{#if info.queued.length}
				<div class="queue">
					<div class="qh faint"><ListOrdered size={12} />Queued ({info.queued.length})</div>
					{#each info.queued as q (q.number)}
						<div class="job small">
							<span class="dot busy"></span>
							<b>#{q.number}</b>
							<span class="faint">{TRIGGER_LABEL[q.trigger] ?? q.trigger}</span>
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<section class="card">
			<header>
				<Bot size={15} /><h3>AI builder</h3>
				<span class="grow"></span>
				<button class="link" onclick={() => ontab?.('build')}>Open</button>
			</header>
			{#if info.builder}
				<div class="job">
					<span class="dot busy"></span>
					<div class="jb">
						<div><b>{info.builder.status}</b></div>
						{#if info.builder.step}<div class="faint step">{info.builder.step}</div>{/if}
					</div>
				</div>
			{:else}
				<p class="none">Idle. Ask it for a change in the Build with AI tab.</p>
			{/if}
		</section>
	</div>
{/if}

<style>
	.cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
	.card { min-width: 0; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: hidden; }
	.card.wide { grid-column: 1 / -1; }
	.card header { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
	.card header :global(svg) { color: var(--text-3); flex: none; }
	.card h3 { margin: 0; font-size: 13px; font-weight: 600; }
	.grow { flex: 1; }
	.link { font-size: 12.5px; color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
	.mono { font-family: var(--font-mono); }
	.nowrap { white-space: nowrap; }
	.st { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-2); text-transform: capitalize; }
	.st i { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
	.st.ok { color: var(--c-green); } .st.ok i { background: var(--c-green); }
	.st.bad { color: var(--danger); } .st.bad i { background: var(--danger); }
	.st.busy { color: var(--c-yellow); } .st.busy i { background: var(--c-yellow); animation: pulse 1.2s infinite; }
	.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; padding: 12px; }
	.stats > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
	.stats span { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; }
	.stats b { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
	.stats b.warn { color: var(--c-yellow); }
	.bar { height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden; margin-top: 3px; }
	.bar i { display: block; height: 100%; background: var(--accent); transition: width 0.4s; }
	.procs { border-top: 1px solid var(--border); overflow-x: auto; font-size: 12.5px; }
	.prow { display: grid; grid-template-columns: minmax(180px, 1fr) 64px 60px 80px 70px; gap: 10px; align-items: center; padding: 4px 12px; min-width: 520px; }
	.prow:not(.head):hover { background: var(--hover); }
	.prow.head { font-size: 11.5px; padding-top: 6px; }
	.r { text-align: right; font-variant-numeric: tabular-nums; }
	.cmd { display: block; font-size: 12px; color: var(--text); }
	.elbow { font-style: normal; color: var(--text-3); margin-right: 4px; }
	.job { display: flex; align-items: center; gap: 10px; padding: 12px; font-size: 13px; }
	.job.small { padding: 4px 12px; font-size: 12.5px; }
	.jb { flex: 1; min-width: 0; }
	.step { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; }
	.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); }
	.dot.ok { background: var(--c-green); } .dot.bad { background: var(--danger); }
	.dot.busy { background: var(--c-yellow); animation: pulse 1.2s infinite; }
	@keyframes pulse { 50% { opacity: 0.35; } }
	.queue { border-top: 1px solid var(--border); padding-bottom: 6px; }
	.qh { display: flex; align-items: center; gap: 5px; padding: 8px 12px 2px; font-size: 11.5px; }
	.none { margin: 0; padding: 14px 12px; color: var(--text-3); font-size: 13px; }
	.banner { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 12px; padding: 9px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); font-size: 13px; color: var(--text-2); }
	.banner.bad { border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
	.banner :global(svg) { flex: none; margin-top: 2px; color: var(--c-yellow); }
	.banner.bad :global(svg) { color: var(--danger); }
	.banner b { color: var(--text); }
	.banner code { font: 12px var(--font-mono); }
	@media (max-width: 700px) { .cards { grid-template-columns: 1fr; } }
	@media (prefers-reduced-motion: reduce) { .st.busy i, .dot.busy { animation: none; } }
</style>
