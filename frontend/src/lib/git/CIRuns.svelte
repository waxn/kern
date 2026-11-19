<script lang="ts">
	// The repository's Runs tab: the list of CI runs with a "Run" button, and one run with its jobs,
	// a live log viewer and artifacts. `runId` null shows the list.
	import { goto } from '$app/navigation';
	import { tick } from 'svelte';
	import { ArrowDown, ChevronLeft, Download, GitBranch, Package, Play, RotateCw, Square, Tag } from '@lucide/svelte';
	import { api, qs } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, fullDate, relTime } from '#lib/util.ts';
	import CIDot from './CIDot.svelte';
	import {
		artifactUrl, cleanLine, fmtDuration, isLive, runUrl, STATUS_LABEL,
		type CiLog, type CiPipeline, type CiRun, type CiRunDetail
	} from './ci.ts';
	import { short, type RepoDetail } from './types.ts';

	let { repo, runId }: { repo: RepoDetail; runId: number | null } = $props();
	const base = $derived(`/git/repos/${encodeURIComponent(repo.name)}/ci`);
	const listUrl = $derived(`/git/${encodeURIComponent(repo.name)}/runs`);

	// ---------------------------------------------------------------- list
	let runs = $state<CiRun[]>([]);
	let more = $state(false);
	let listLoaded = $state(false);
	let filter = $state('');
	let runRef = $state('');
	let pipe = $state<CiPipeline | null>(null);
	let starting = $state(false);
	let listError = $state('');

	$effect(() => {
		runRef = repo.default_branch ?? repo.branch_list[0]?.name ?? '';
	});

	// Keeps the first page fresh (every 3 s while something is queued or running, else every 15 s).
	$effect(() => {
		if (runId !== null) return;
		void filter;
		const b = base;
		let stop = false;
		let timer: ReturnType<typeof setTimeout>;
		listLoaded = false;
		const load = async () => {
			try {
				const d = await api.get<{ runs: CiRun[]; more: boolean }>(`${b}/runs` + qs({ ref: filter }));
				if (stop) return;
				listError = '';
				// Keep older pages that were loaded with "Older runs".
				const ids = new Set(d.runs.map((r) => r.id));
				const tail = runs.length > d.runs.length ? runs.filter((r) => !ids.has(r.id) && r.id < d.runs[d.runs.length - 1]?.id) : [];
				runs = [...d.runs, ...tail];
				more = tail.length ? more : d.more;
			} catch (e) {
				if (!stop) listError = e instanceof Error ? e.message : String(e);
			}
			listLoaded = true;
			if (!stop) timer = setTimeout(load, runs.some((r) => isLive(r.status)) ? 3000 : 15000);
		};
		runs = [];
		load();
		return () => {
			stop = true;
			clearTimeout(timer);
		};
	});

	async function olderRuns() {
		const d = await api.get<{ runs: CiRun[]; more: boolean }>(`${base}/runs` + qs({ ref: filter, page: Math.ceil(runs.length / 30) }));
		const have = new Set(runs.map((r) => r.id));
		runs = [...runs, ...d.runs.filter((r) => !have.has(r.id))];
		more = d.more;
	}

	// What the pipeline file of the branch picked for "Run" says.
	$effect(() => {
		const r = runRef;
		const b = base;
		pipe = null;
		if (!r) return;
		let stale = false;
		api.get<CiPipeline>(`${b}/pipeline` + qs({ ref: r })).then((d) => !stale && (pipe = d)).catch(() => {});
		return () => (stale = true);
	});

	async function startRun() {
		if (!runRef || starting) return;
		starting = true;
		try {
			const r = await api.post<CiRun>(`${base}/runs`, { ref: runRef });
			goto(runUrl(repo.name, r.id));
		} catch (e) {
			ui.error(e);
		} finally {
			starting = false;
		}
	}

	// ----------------------------------------------------------------- run
	let detail = $state<CiRunDetail | null>(null);
	let runError = $state('');
	let job = $state('');

	$effect(() => {
		const id = runId;
		const b = base;
		if (id === null) return;
		let stop = false;
		let timer: ReturnType<typeof setTimeout>;
		detail = null;
		job = '';
		runError = '';
		const load = async () => {
			try {
				const d = await api.get<CiRunDetail>(`${b}/runs/${id}`);
				if (stop) return;
				detail = d;
				if (!job || !d.jobs.some((j) => j.name === job)) {
					job = (d.jobs.find((j) => j.status === 'failed' || j.status === 'error') ?? d.jobs.find((j) => j.status === 'running') ?? d.jobs[0])?.name ?? '';
				}
			} catch (e) {
				if (!stop) runError = e instanceof Error ? e.message : String(e);
				return;
			}
			if (!stop && detail && isLive(detail.status)) timer = setTimeout(load, 1500);
		};
		load();
		return () => {
			stop = true;
			clearTimeout(timer);
		};
	});

	const MAX_LINES = 20000;
	let lines = $state<string[]>(['']);
	let hidden = $state(0);
	let logDone = $state(false);
	let follow = $state(true);
	let box = $state<HTMLElement | null>(null);

	function append(text: string) {
		const parts = text.split('\n');
		const next = lines.slice();
		next[next.length - 1] += parts[0];
		for (let i = 1; i < parts.length; i++) next.push(parts[i]);
		if (next.length > MAX_LINES) {
			hidden += next.length - MAX_LINES;
			next.splice(0, next.length - MAX_LINES);
		}
		lines = next;
	}

	// Streams the selected job's log by polling for new bytes.
	$effect(() => {
		const id = runId;
		const j = job;
		const b = base;
		if (id === null || !j) return;
		let stop = false;
		let timer: ReturnType<typeof setTimeout>;
		let offset = 0;
		lines = [''];
		hidden = 0;
		logDone = false;
		follow = true;
		const poll = async () => {
			let wait = 1000;
			try {
				const d = await api.get<CiLog>(`${b}/runs/${id}/jobs/${encodeURIComponent(j)}/log` + qs({ offset }));
				if (stop) return;
				if (d.text) append(d.text);
				offset = d.offset;
				logDone = d.done;
				if (d.offset < d.size) wait = 0;
			} catch {
				wait = 3000;
			}
			if (!stop && !logDone) timer = setTimeout(poll, wait);
		};
		poll();
		return () => {
			stop = true;
			clearTimeout(timer);
		};
	});

	$effect(() => {
		void lines;
		if (follow && box) tick().then(() => box && (box.scrollTop = box.scrollHeight));
	});

	function onScroll() {
		if (box) follow = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
	}

	async function cancel() {
		if (!detail) return;
		try {
			detail = { ...detail, ...(await api.post<CiRun>(`${base}/runs/${detail.id}/cancel`)) };
			ui.toast('Cancelling…');
		} catch (e) {
			ui.error(e);
		}
	}

	async function rerun() {
		if (!detail) return;
		try {
			const r = await api.post<CiRun>(`${base}/runs/${detail.id}/rerun`);
			goto(runUrl(repo.name, r.id));
		} catch (e) {
			ui.error(e);
		}
	}

	const refLabel = (r: CiRun) => r.branch ?? r.tag ?? r.ref;
	const how = (r: CiRun) => (r.trigger === 'push' ? `pushed by ${r.pusher}` : r.trigger === 'manual' ? `run by ${r.pusher}` : `re-run by ${r.pusher}`);
	const jobTitle = (j: { status: string; note: string; duration: number | null }) =>
		[STATUS_LABEL[j.status] ?? j.status, j.note, fmtDuration(j.duration)].filter(Boolean).join(' · ');
</script>

{#if runId === null}
	<div class="bar">
		<label class="sel" title="Show runs of one branch or tag">
			<GitBranch size={13} />
			<select bind:value={filter} aria-label="Filter runs by branch or tag">
				<option value="">All branches and tags</option>
				<optgroup label="Branches">{#each repo.branch_list as b (b.name)}<option value={b.name}>{b.name}</option>{/each}</optgroup>
				{#if repo.tag_list.length}<optgroup label="Tags">{#each repo.tag_list as t (t.name)}<option value={t.name}>{t.name}</option>{/each}</optgroup>{/if}
			</select>
		</label>
		<span class="grow"></span>
		<label class="sel" title="Branch or tag to run the pipeline on">
			<Play size={13} />
			<select bind:value={runRef} aria-label="Branch or tag to run">
				<optgroup label="Branches">{#each repo.branch_list as b (b.name)}<option value={b.name}>{b.name}</option>{/each}</optgroup>
				{#if repo.tag_list.length}<optgroup label="Tags">{#each repo.tag_list as t (t.name)}<option value={t.name}>{t.name}</option>{/each}</optgroup>{/if}
			</select>
		</label>
		<button class="btn" onclick={startRun} disabled={starting || !runRef || (pipe != null && (!pipe.found || (!pipe.manual && !pipe.error)))}>
			<Play size={13} />Run
		</button>
	</div>
	{#if pipe && !pipe.found}
		<p class="hint">There is no <code>.kern/ci.yml</code> on <b>{runRef}</b>. Add one and push to start running pipelines.</p>
	{:else if pipe?.error}
		<p class="hint bad">The pipeline file on <b>{runRef}</b> has a problem: {pipe.error}</p>
	{:else if pipe && !pipe.manual}
		<p class="hint">Manual runs are turned off in the pipeline file of <b>{runRef}</b>.</p>
	{/if}

	{#if listError}
		<div class="empty"><b>Could not load runs</b>{listError}</div>
	{:else if runs.length}
		<div class="box">
			{#each runs as r (r.id)}
				<a class="run" href={runUrl(repo.name, r.id)}>
					<CIDot status={r.status} size={17} />
					<span class="main">
						<span class="subj truncate">{r.subject || short(r.sha)}</span>
						<span class="sub faint">
							#{r.id} · {how(r)}{#if r.status === 'error' && r.error} · <span class="err">{r.error}</span>{/if}
						</span>
					</span>
					<span class="chip ref">{#if r.tag}<Tag size={11} />{:else}<GitBranch size={11} />{/if}{refLabel(r)}</span>
					<code class="sha">{short(r.sha)}</code>
					<span class="faint when" title={fullDate(r.created)}>{relTime(r.created)}</span>
					<span class="faint dur">{fmtDuration(r.duration)}</span>
				</a>
			{/each}
		</div>
		{#if more}<div class="morewrap"><button class="btn" onclick={olderRuns}>Older runs</button></div>{/if}
	{:else if listLoaded}
		<div class="empty">
			<b>No runs yet</b>
			{#if filter}Nothing has run on {filter}.{:else}Add a <code>.kern/ci.yml</code> to the repository and push. See <code>docs/git-ci.md</code> for the format.{/if}
		</div>
	{/if}
{:else}
	<div class="crumb"><a href={listUrl}><ChevronLeft size={14} />All runs</a></div>
	{#if runError}
		<div class="empty"><b>Could not load this run</b>{runError}</div>
	{:else if detail}
		<div class="box rhead">
			<div class="rtop">
				<CIDot status={detail.status} size={22} />
				<div class="rtitle">
					<h2>{detail.subject || short(detail.sha)}</h2>
					<span class="faint">
						Run #{detail.id} · {STATUS_LABEL[detail.status]}{#if detail.duration != null}{' in ' + fmtDuration(detail.duration)}{/if} · {how(detail)}
						<span title={fullDate(detail.created)}>{relTime(detail.created)}</span>
					</span>
				</div>
				<span class="grow"></span>
				{#if isLive(detail.status)}
					<button class="btn ghost" onclick={cancel}><Square size={13} />Cancel</button>
				{:else}
					<button class="btn" onclick={rerun}><RotateCw size={13} />Re-run</button>
				{/if}
			</div>
			<div class="rmeta">
				<span class="chip ref">{#if detail.tag}<Tag size={11} />{:else}<GitBranch size={11} />{/if}{refLabel(detail)}</span>
				<a class="sha" href={`/git/${encodeURIComponent(repo.name)}/commit/${detail.sha}`}>{short(detail.sha)}</a>
			</div>
			{#if detail.error}<p class="errbox">{detail.error}</p>{/if}
		</div>

		{#if detail.jobs.length}
			<div class="cols">
				<div class="jobs box" role="tablist" aria-label="Jobs">
					{#each detail.jobs as j (j.name)}
						<button class="job" class:on={j.name === job} role="tab" aria-selected={j.name === job} onclick={() => (job = j.name)} title={jobTitle(j)}>
							<CIDot status={j.status} size={15} />
							<span class="truncate">{j.name}</span>
							<span class="grow"></span>
							<span class="faint dur">{fmtDuration(j.duration)}</span>
						</button>
					{/each}
				</div>
				<div class="logcol">
					{#each detail.jobs.filter((j) => j.name === job) as j (j.name)}
						{#if j.note}<p class="jnote" class:bad={j.status === 'failed' || j.status === 'error'}>{j.note}</p>{/if}
					{/each}
					<div class="logwrap">
						<div class="log" bind:this={box} onscroll={onScroll} role="log" aria-label="Log of {job}">
							{#if hidden}<div class="ln faint">… {hidden} earlier lines not shown</div>{/if}
							{#each lines as l, i (i + hidden)}
								{@const t = cleanLine(l)}
								<div class="ln" class:step={t.startsWith('##[step')} class:kern={t.startsWith('[kern-ci]')}>{t.startsWith('##[') ? t.replace(/^##\[(.*?)\]\s*/, '$1 · ') : t || ' '}</div>
							{/each}
							{#if !logDone && isLive(detail.status)}<div class="ln faint">…</div>{/if}
						</div>
						{#if !follow}
							<button class="jump icon-btn" title="Scroll to the end" onclick={() => { follow = true; if (box) box.scrollTop = box.scrollHeight; }}><ArrowDown size={15} /></button>
						{/if}
					</div>
				</div>
			</div>
		{:else if !detail.error}
			<div class="empty"><b>No jobs</b>This run has nothing to show.</div>
		{/if}

		{#if detail.artifacts.length}
			<h3 class="section-title"><Package size={14} />Artifacts</h3>
			<div class="box">
				{#each detail.artifacts as a (a.job + '/' + a.name)}
					<div class="art">
						<Download size={14} class="ic" />
						<a href={artifactUrl(repo.name, detail.id, a)} download>{a.name}</a>
						<span class="faint">{a.job}</span>
						<span class="grow"></span>
						<span class="faint">{fileSize(a.size)}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<p class="faint pad">Loading…</p>
	{/if}
{/if}

<style>
	.grow { flex: 1; }
	.bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
	.sel { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 4px 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-2); }
	.sel select { border: 0; outline: 0; background: none; color: var(--text); font: 13px var(--font-mono); max-width: 200px; }
	.hint { margin: 0 0 12px; font-size: 13px; color: var(--text-2); }
	.hint.bad, .jnote.bad { color: var(--c-red); }
	.box { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface); margin-bottom: 14px; }
	.run { display: flex; align-items: center; gap: 12px; padding: 9px 12px; border-top: 1px solid var(--border); color: var(--text); text-decoration: none; }
	.run:first-child { border-top: 0; }
	.run:hover { background: var(--hover); }
	.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
	.subj { font-weight: 550; font-size: 13.5px; }
	.run:hover .subj { color: var(--accent); }
	.sub { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.err { color: var(--c-red); }
	.chip.ref { display: inline-flex; align-items: center; gap: 4px; font: 12px var(--font-mono); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.sha { font: 12px var(--font-mono); color: var(--text-2); text-decoration: none; padding: 1px 6px; border-radius: 4px; background: var(--code-bg); white-space: nowrap; }
	a.sha:hover { color: var(--accent); }
	.when { font-size: 12px; white-space: nowrap; min-width: 70px; text-align: right; }
	.dur { font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; min-width: 52px; text-align: right; }
	.morewrap { display: flex; justify-content: center; margin-top: 4px; }
	.crumb a { display: inline-flex; align-items: center; gap: 2px; font-size: 12.5px; color: var(--text-3); text-decoration: none; margin-bottom: 8px; }
	.crumb a:hover { color: var(--text); }
	.rhead { padding: 14px 16px; }
	.rtop { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
	.rtitle { min-width: 0; }
	.rtitle h2 { margin: 0 0 2px; font-size: 16px; font-weight: 650; overflow-wrap: anywhere; }
	.rtitle .faint { font-size: 12.5px; }
	.rmeta { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
	.errbox { margin: 10px 0 0; padding: 8px 10px; border-radius: 6px; background: var(--code-bg); color: var(--c-red); font: 12.5px/1.5 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
	.cols { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 14px; align-items: start; }
	.jobs { display: flex; flex-direction: column; margin: 0; }
	.job { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-top: 1px solid var(--border); text-align: left; font-size: 13px; color: var(--text-2); }
	.job:first-child { border-top: 0; }
	.job:hover { background: var(--hover); color: var(--text); }
	.job.on { background: var(--surface-2); color: var(--text); font-weight: 550; box-shadow: inset 2px 0 0 var(--accent); }
	.jnote { margin: 0 0 6px; font-size: 12.5px; color: var(--text-2); }
	.logwrap { position: relative; }
	.log { height: min(62vh, 640px); min-height: 220px; overflow: auto; padding: 8px 0; border: 1px solid var(--border); border-radius: 8px; background: var(--code-bg); font: 12.5px/1.55 var(--font-mono); }
	.ln { white-space: pre-wrap; overflow-wrap: anywhere; padding: 0 14px; min-height: 1.55em; }
	.ln:hover { background: var(--hover); }
	.ln.step { margin-top: 8px; padding-top: 3px; padding-bottom: 3px; font-weight: 650; color: var(--c-blue); border-top: 1px solid var(--border); }
	.ln.step:first-child { margin-top: 0; border-top: 0; }
	.ln.kern { color: var(--c-orange); }
	.jump { position: absolute; right: 12px; bottom: 10px; background: var(--surface); border: 1px solid var(--border-strong); }
	.section-title { display: flex; align-items: center; gap: 6px; }
	.art { display: flex; align-items: center; gap: 9px; padding: 8px 12px; border-top: 1px solid var(--border); font-size: 13px; }
	.art:first-child { border-top: 0; }
	.art :global(.ic) { color: var(--text-3); flex: none; }
	.art a { font: 13px var(--font-mono); color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }
	.art a:hover { text-decoration: underline; }
	.pad { padding: 12px 14px; margin: 0; }
	@media (max-width: 800px) {
		.cols { grid-template-columns: 1fr; }
		.jobs { flex-direction: row; overflow-x: auto; }
		.job { border-top: 0; border-left: 1px solid var(--border); white-space: nowrap; }
		.job:first-child { border-left: 0; }
		.job.on { box-shadow: inset 0 -2px 0 var(--accent); }
		.run .sha, .run .when { display: none; }
	}
</style>
