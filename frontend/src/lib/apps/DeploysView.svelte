<script lang="ts">
	import { ChevronDown, ChevronRight, GitCommitHorizontal, RotateCcw, Rocket, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { relTime } from '#lib/util.ts';
	import LogView from './LogView.svelte';
	import { TRIGGER_LABEL, type App, type Deploy } from './types.ts';

	let { app, onchange }: { app: App; onchange: () => void } = $props();
	let deploys = $state<Deploy[]>([]);
	let openNo = $state<number | null>(null);
	let loaded = $state(false);

	async function load() {
		try {
			deploys = await api.get<Deploy[]>(`/apps/${app.slug}/deploys`);
			if (openNo === null && deploys.length && !loaded) openNo = deploys[0].number;
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}

	onMount(() => {
		load();
		const t = setInterval(() => {
			if (document.visibilityState === 'visible' && deploys.some((d) => ['queued', 'building', 'starting'].includes(d.status))) load();
		}, 2000);
		return () => clearInterval(t);
	});

	// A new deployment from elsewhere (push, the AI) shows up.
	$effect(() => {
		const latest = app.latest?.number;
		if (latest && loaded && !deploys.some((d) => d.number === latest)) {
			load().then(() => (openNo = latest));
		}
	});

	async function act(d: Deploy, action: 'rollback' | 'cancel') {
		if (action === 'rollback') {
			const ok = await ui.confirm({ title: `Go back to deployment #${d.number}?`, message: `Its files are used again as they were (commit ${d.short}). Newer pushes still deploy as usual${app.auto_deploy ? '' : ' when you deploy them'}.`, confirmLabel: 'Roll back' });
			if (!ok) return;
		}
		try {
			const r = await api.post<Deploy>(`/apps/${app.slug}/deploys/${d.number}/${action}`);
			await load();
			if (action === 'rollback') openNo = r.number;
			onchange();
		} catch (e) {
			ui.error(e);
		}
	}

	async function redeploy(sha = '') {
		try {
			await api.post(`/apps/${app.slug}/deploy`, { sha });
			await load();
			openNo = deploys[0]?.number ?? null;
			onchange();
		} catch (e) {
			ui.error(e);
		}
	}

	const DOT: Record<string, string> = { live: 'ok', old: 'off', failed: 'bad', cancelled: 'off', queued: 'busy', building: 'busy', starting: 'busy' };
	const LABEL: Record<string, string> = { live: 'Live', old: 'Replaced', failed: 'Failed', cancelled: 'Cancelled', queued: 'Queued', building: 'Building', starting: 'Starting' };
</script>

<div class="head">
	<p class="muted">
		{#if app.source === 'kern'}
			{app.auto_deploy ? `Every push to ${app.branch} deploys it.` : `Pushes to ${app.branch} don't deploy by themselves.`}
		{:else}
			Deploys {app.branch} of {app.git_url}. Use the deploy hook (Settings) to deploy on every push.
		{/if}
	</p>
	<button class="btn" onclick={() => redeploy()}><Rocket size={14} />Deploy {app.branch}</button>
</div>

{#if deploys.length}
	<div class="list">
		{#each deploys as d (d.number)}
			{@const isOpen = openNo === d.number}
			<div class="dep" class:open={isOpen}>
				<button class="row" onclick={() => (openNo = isOpen ? null : d.number)}>
					{#if isOpen}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
					<span class="dot {DOT[d.status]}"></span>
					<b class="no">#{d.number}</b>
					<span class="subj truncate" title={d.subject}>{d.rollback_of ? `Back to #${d.rollback_of}` : d.subject || 'Deployment'}</span>
					{#if d.short}<span class="sha"><GitCommitHorizontal size={12} />{d.short}</span>{/if}
					<span class="st {DOT[d.status]}">{LABEL[d.status] ?? d.status}</span>
					<span class="when faint" title={new Date(d.created).toLocaleString()}>{TRIGGER_LABEL[d.trigger] ?? d.trigger} · {relTime(d.created)}{d.seconds !== null ? ` · ${d.seconds}s` : ''}</span>
				</button>
				{#if isOpen}
					<div class="body">
						{#if d.error}<p class="error">{d.error}</p>{/if}
						<div class="acts">
							{#if d.status === 'old'}<button class="btn" onclick={() => act(d, 'rollback')}><RotateCcw size={13} />Roll back to this</button>{/if}
							{#if (d.status === 'failed' || d.status === 'old') && d.sha}<button class="btn ghost" onclick={() => redeploy(d.sha)}><Rocket size={13} />Deploy this commit again</button>{/if}
							{#if d.status === 'queued' || d.status === 'building'}<button class="btn ghost" onclick={() => act(d, 'cancel')}><X size={13} />Cancel</button>{/if}
						</div>
						<LogView kind="build" height="320px" url="/apps/{app.slug}/deploys/{d.number}/log" live={['queued', 'building', 'starting'].includes(d.status)} ondone={load} empty="Waiting for the apps service…" />
					</div>
				{/if}
			</div>
		{/each}
	</div>
{:else if loaded}
	<div class="empty"><b>No deployments yet</b>{app.source === 'kern' ? 'Push to the repository or deploy by hand.' : 'Deploy the branch to get started.'}</div>
{/if}

<style>
	.head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
	.head p { flex: 1; margin: 0; font-size: 13px; }
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.dep { border-top: 1px solid var(--border); }
	.dep:first-child { border-top: 0; }
	.row { display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 12px; text-align: left; color: var(--text-2); }
	.row:hover { background: var(--hover); }
	.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); }
	.dot.ok { background: var(--c-green); }
	.dot.bad { background: var(--danger); }
	.dot.busy { background: var(--c-yellow); animation: pulse 1.2s infinite; }
	@keyframes pulse { 50% { opacity: 0.35; } }
	.no { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
	.subj { flex: 1; color: var(--text); }
	.sha { display: inline-flex; align-items: center; gap: 3px; font: 12px var(--font-mono); color: var(--text-3); }
	.st { font-size: 12px; min-width: 64px; }
	.st.ok { color: var(--c-green); } .st.bad { color: var(--danger); } .st.busy { color: var(--c-yellow); }
	.when { font-size: 12px; white-space: nowrap; }
	.body { padding: 0 12px 12px 36px; display: flex; flex-direction: column; gap: 8px; }
	.acts { display: flex; gap: 6px; flex-wrap: wrap; }
	.acts:empty { display: none; }
	.error { margin: 0; color: var(--danger); font-size: 13px; }
	.muted { color: var(--text-2); }
	@media (max-width: 700px) { .when, .sha { display: none; } .body { padding-left: 12px; } }
</style>
