<script lang="ts">
	// The AI builder: a conversation about one app. Each message runs in the apps service: the model
	// reads and writes the app's files, deploys, reads the logs and tries the app, then answers.
	import {
		ArrowDown, ArrowUp, Check, ChevronDown, ChevronRight, CircleAlert, Cpu, Database, FileMinus, FilePen, FileSearch, Loader,
		RotateCcw, Rocket, ScrollText, Settings, Square, TestTube, X
	} from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ai, type AiConfig } from '#lib/ai/ai.svelte.ts';
	import { renderMarkdown } from '#lib/ai/md.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { App } from './types.ts';

	interface Act { verb: string; detail: string; ok?: boolean }
	interface Turn { role: 'user' | 'assistant'; text: string; at: string; actions?: Act[]; error?: boolean }
	interface Chat { transcript: Turn[]; status: 'idle' | 'queued' | 'running'; progress: Act[]; pending: string }

	// Steps of one kind that follow each other are shown as one card ("Edited 3 files").
	type Kind = 'look' | 'edit' | 'delete' | 'deploy' | 'logs' | 'request' | 'settings' | 'save' | 'db' | 'proc' | 'other';
	interface Group { kind: Kind; items: Act[]; bad: boolean }

	let { app, onchange }: { app: App; onchange: () => void } = $props();
	let chat = $state<Chat>({ transcript: [], status: 'idle', progress: [], pending: '' });
	let text = $state('');
	let sending = $state(false);
	let box = $state<HTMLDivElement>();
	let input = $state<HTMLTextAreaElement>();
	let atBottom = $state(true);
	let open = $state<Record<string, boolean>>({});
	let timer: ReturnType<typeof setTimeout> | null = null;
	let lastLen = 0;

	let busy = $derived(chat.status !== 'idle');
	let empty = $derived(!chat.transcript.length && !busy);
	let liveGroups = $derived(group(chat.progress));

	// ---- loading and polling ----

	async function load() {
		timer = null;
		try {
			const c = await api.get<Chat>(`/apps/${app.slug}/builder`);
			const grew = c.transcript.length !== chat.transcript.length || c.progress.length !== chat.progress.length;
			const finished = chat.status !== 'idle' && c.status === 'idle';
			chat = c;
			if (grew) scroll();
			if (finished) onchange();
			else if (c.progress.length !== lastLen) onchange();
			lastLen = c.progress.length;
		} catch {
			/* retry */
		}
		timer = setTimeout(load, busy ? 1200 : 5000);
	}

	let appAi = $state<AiConfig | null>(null);
	let aiPanel = $state(false);
	let aiScope = $state<'inherit' | 'app'>('inherit');
	let aiForm = $state({ provider: '', model: '', base_url: '', api_key: '' });
	let aiSaving = $state(false);

	const MODEL_HINTS: Record<string, string[]> = {
		anthropic: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1'],
		openai: [], gemini: [], openrouter: [], ollama: ['llama3.3', 'qwen3', 'mistral'], custom: []
	};

	let aiReady = $derived((appAi ?? ai.config)?.configured ?? false);
	let aiMissing = $derived(!!(appAi ?? ai.config) && !aiReady);
	// The model in effect: the app's own choice, else the workspace one (public_config returns the effective one).
	let aiModel = $derived(appAi?.model || ai.config?.model || '');
	let aiLabel = $derived(aiModel ? `Model: ${aiModel}` : 'Model');

	type ProviderInfo = { label: string; base_url: string; model: string; needs_key: boolean };
	let aiProviders = $derived((ai.config?.providers ?? appAi?.providers ?? {}) as Record<string, ProviderInfo>);

	function fillAiForm(c: AiConfig) {
		aiScope = c.inherited ? 'inherit' : 'app';
		aiForm = { provider: c.provider, model: c.model, base_url: c.base_url, api_key: '' };
	}

	async function loadAppAi() {
		try {
			const c = await api.get<AiConfig>(`/apps/${app.slug}/ai`);
			appAi = c;
			if (!aiPanel) fillAiForm(c);
		} catch {
			/* the workspace settings still apply */
		}
	}

	function openAi() {
		if (appAi) fillAiForm(appAi);
		aiPanel = !aiPanel;
	}

	function pickProvider(p: string) {
		const info = aiProviders[p];
		aiForm = {
			...aiForm, provider: p,
			model: p === aiForm.provider ? aiForm.model : (info?.model ?? ''),
			base_url: p === aiForm.provider ? aiForm.base_url : (info?.base_url ?? '')
		};
	}

	async function saveAppAi() {
		aiSaving = true;
		try {
			const body: Record<string, unknown> = aiScope === 'inherit'
				? { inherit: true }
				: { provider: aiForm.provider, model: aiForm.model, base_url: aiForm.base_url };
			if (aiScope === 'app' && aiForm.api_key.trim()) body.api_key = aiForm.api_key.trim();
			const c = await api.put<AiConfig>(`/apps/${app.slug}/ai`, body);
			appAi = c;
			fillAiForm(c);
			aiPanel = false;
			ui.toast(aiScope === 'inherit' ? 'This app follows the workspace AI settings.' : 'Saved. Only Build with AI uses this model.');
		} catch (e) {
			ui.error(e);
		} finally {
			aiSaving = false;
		}
	}

	async function canBuild(): Promise<boolean> {
		if (!appAi) await loadAppAi();
		if (appAi?.configured) return true;
		if (!appAi) {
			if (!ai.config) await ai.load();
			if (ai.config?.configured) return true;
		}
		ui.toast('Set up an AI provider first.');
		goto('/settings?s=ai');
		return false;
	}

	onMount(() => {
		ai.load();
		loadAppAi().then(() => {
			if (page.url.searchParams.get('ai') === '1') {
				openAi();
				const u = new URL(page.url.href);
				u.searchParams.delete('ai');
				goto(u.pathname + u.search, { replaceState: true });
			}
			return load().then(() => scroll(true));
		});
		return () => timer && clearTimeout(timer);
	});

	function onscroll() {
		if (box) atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
	}

	async function scroll(force = false) {
		await tick();
		if (!box) return;
		const near = box.scrollHeight - box.scrollTop - box.clientHeight < 160;
		if (force || near) {
			box.scrollTop = box.scrollHeight;
			atBottom = true;
		}
	}

	function jump() {
		if (!box) return;
		const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
		box.scrollTo({ top: box.scrollHeight, behavior: calm ? 'auto' : 'smooth' });
	}

	// ---- actions ----

	async function send(msg = text) {
		msg = msg.trim();
		if (!msg || busy || sending) return;
		if (!(await canBuild())) return;
		sending = true;
		try {
			chat = await api.post<Chat>(`/apps/${app.slug}/builder`, { message: msg });
			text = '';
			scroll(true);
			if (timer) clearTimeout(timer);
			timer = setTimeout(load, 800);
		} catch (e) {
			ui.error(e);
		} finally {
			sending = false;
		}
	}

	async function stop() {
		try {
			chat = await api.post<Chat>(`/apps/${app.slug}/builder/stop`);
			ui.toast('Stopping after the current step…');
		} catch (e) {
			ui.error(e);
		}
	}

	async function clear() {
		if (!(await ui.confirm({ title: 'Start a new conversation?', message: 'The AI forgets this conversation. The app and its code stay as they are.', confirmLabel: 'Start over' }))) return;
		try {
			chat = await api.del<Chat>(`/apps/${app.slug}/builder`);
			open = {};
		} catch (e) {
			ui.error(e);
		}
	}

	// ---- composer ----

	function fit() {
		if (!input) return;
		input.style.height = 'auto';
		input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
	}

	$effect(() => {
		text;
		input;
		fit();
	});

	// A chip fills the composer; a trailing "…" is selected so typing replaces it.
	async function fill(s: string) {
		const have = text.trim();
		text = have ? `${have}\n${s}` : s;
		await tick();
		if (!input) return;
		input.focus();
		const end = input.value.length;
		input.setSelectionRange(s.endsWith('…') ? end - 1 : end, end);
	}

	function keydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		}
	}

	const CHIPS = $derived.by(() => {
		const failing = app.state === 'failed' || app.state === 'crashed' || app.latest?.status === 'failed';
		if (!app.live && !app.latest) return ['Build a one-page app that …', 'Keep it simple: one page, no packages', 'Add a database table for …', 'Make it work on mobile', 'Add a dark theme'];
		const list = ['Add a settings page', 'Make it work on mobile', 'Add a dark theme', 'Fix the last error', 'Add a database table for …', 'Export the data as CSV'];
		return failing ? ['Fix the last error', ...list.filter((s) => s !== 'Fix the last error')] : list;
	});

	const CAN = [
		{ icon: FilePen, title: 'Reads and edits the code', body: 'Looks at the files, then writes or changes them. Every change is a commit.' },
		{ icon: Rocket, title: 'Deploys it', body: 'Builds and starts a new version and reads the build output.' },
		{ icon: ScrollText, title: 'Checks the logs', body: 'Reads what the app prints and fixes what breaks.' },
		{ icon: TestTube, title: 'Tries the app', body: 'Sends it requests like a visitor would, to see that it works.' },
		{ icon: Database, title: 'Inspects its data', body: 'Runs read-only queries on the app\'s database to see what it stored.' },
		{ icon: Cpu, title: 'Watches its processes', body: 'Checks what the app is running, and how much CPU and memory it uses.' },
		{ icon: Settings, title: 'Tunes its settings', body: 'Description, icon and public paths. Access and secrets stay yours.' }
	];

	// ---- status ----

	let status = $derived.by(() => {
		if (chat.status === 'queued') return { tone: 'busy', label: 'Waiting for the apps service', sub: '' };
		if (chat.status === 'running') {
			const n = chat.progress.length;
			const last = chat.progress[n - 1];
			return { tone: 'busy', label: n ? `Working · ${n} step${n === 1 ? '' : 's'}` : 'Thinking', sub: last ? `${last.verb} ${last.detail}`.trim() : '' };
		}
		const latest = app.latest;
		if (latest?.status === 'failed' && (!app.live || latest.number > app.live.number)) return { tone: 'bad', label: `Deploy #${latest.number} failed`, sub: '' };
		if (app.live) return { tone: 'ok', label: `Deployed #${app.live.number}`, sub: 'Idle' };
		return { tone: 'idle', label: 'Idle', sub: 'Nothing deployed yet' };
	});

	// ---- step cards ----

	function kindOf(verb: string): Kind {
		if (/^(Wrote|Created|Edited)/.test(verb)) return 'edit';
		if (/^Deleted/.test(verb)) return 'delete';
		if (/^Deploy/.test(verb)) return 'deploy';
		if (/^(Tried|Requested|Called)/.test(verb)) return 'request';
		if (/database|\bsql\b|\btables?\b/i.test(verb)) return 'db';
		if (/process|restart/i.test(verb)) return 'proc';
		if (/logs?\b/i.test(verb)) return 'logs';
		if (/^(Read|Looked|Listed|Searched)/.test(verb)) return 'look';
		if (/^Changed settings/.test(verb)) return 'settings';
		if (/^(Saved|Could not save)/.test(verb)) return 'save';
		return 'other';
	}

	function group(acts: Act[] | undefined): Group[] {
		const out: Group[] = [];
		for (const a of acts ?? []) {
			const kind = kindOf(a.verb);
			const g = out[out.length - 1];
			// Each deploy is its own card: it has its own result.
			if (g && g.kind === kind && kind !== 'deploy') {
				g.items.push(a);
				g.bad ||= a.ok === false;
			} else out.push({ kind, items: [a], bad: a.ok === false });
		}
		return out;
	}

	function title(g: Group): { t: string; sub: string; plain: boolean } {
		const one = g.items.length === 1;
		const a = g.items[0];
		const n = (word: string, c: number) => `${c} ${word}${c === 1 ? '' : 's'}`;
		switch (g.kind) {
			case 'edit': {
				const files = new Set(g.items.map((i) => i.detail)).size;
				const v = g.items.every((i) => i.verb === 'Created') ? 'Created' : g.items.every((i) => i.verb === 'Wrote') ? 'Wrote' : 'Edited';
				return files === 1 ? { t: v, sub: a.detail, plain: true } : { t: `${v} ${n('file', files)}`, sub: '', plain: false };
			}
			case 'delete':
				return one ? { t: 'Deleted', sub: a.detail, plain: true } : { t: `Deleted ${n('file', g.items.length)}`, sub: '', plain: false };
			case 'look': {
				const reads = g.items.filter((i) => i.verb === 'Read');
				if (reads.length === 1 && g.items.length === 1) return { t: 'Read', sub: reads[0].detail, plain: true };
				if (reads.length) return { t: `Read ${n('file', new Set(reads.map((i) => i.detail)).size)}`, sub: '', plain: false };
				return { t: 'Looked at the files', sub: one ? a.detail : '', plain: one };
			}
			case 'logs':
				return { t: one ? 'Read the logs' : `Read the logs ×${g.items.length}`, sub: '', plain: true };
			case 'request':
				return one ? { t: 'Tried', sub: a.detail.replace(/^Tried\s*/, ''), plain: false } : { t: `Tried ${n('request', g.items.length)}`, sub: '', plain: false };
			case 'deploy':
				return { t: a.verb, sub: a.detail, plain: !a.detail || a.detail.length < 60 };
			default:
				return one ? { t: a.verb, sub: a.detail, plain: !a.detail || a.detail.length < 60 } : { t: `${g.items[0].verb} ×${g.items.length}`, sub: '', plain: false };
		}
	}

	const ICONS = { look: FileSearch, edit: FilePen, delete: FileMinus, deploy: Rocket, logs: ScrollText, request: TestTube, settings: Settings, save: Check, db: Database, proc: Cpu, other: Check };

	function isOpen(key: string, dflt: boolean) {
		return open[key] ?? dflt;
	}

	function toggle(key: string, dflt: boolean) {
		open[key] = !isOpen(key, dflt);
	}

	// A finished turn with many cards folds into one line; the live turn always shows its cards.
	const FOLD = 3;
	function summary(gs: Group[]) {
		return gs.map((g) => title(g)).map((x) => (x.sub && x.plain ? `${x.t} ${x.sub}` : x.t)).join(' · ');
	}
</script>

<svelte:window onresize={fit} />

{#snippet cards(gs: Group[], prefix: string, live: boolean)}
	<div class="cards">
		{#each gs as g, gi (gi)}
			{@const key = `${prefix}:${gi}`}
			{@const ti = title(g)}
			{@const I = ICONS[g.kind]}
			{@const last = live && gi === gs.length - 1}
			{@const fold = !(ti.plain && g.items.length === 1) && (g.items.length > 1 || !!g.items[0].detail)}
			{@const shown = fold && isOpen(key, last)}
			{@const good = g.kind === 'deploy' && g.items[0].ok === true}
			{@const pending = g.kind === 'deploy' && g.items[0].ok === undefined && live}
			<div class="card" class:bad={g.bad} class:good class:open={shown}>
				{#if fold}
					<button class="head" aria-expanded={shown} onclick={() => toggle(key, last)}>
						{#if pending}<Loader size={13} class="spin" />{:else}<I size={13} />{/if}
						<b>{ti.t}</b>
						{#if ti.sub}<span class="sub truncate">{ti.sub}</span>{/if}
						{#if g.items.length > 1}<span class="count">{g.items.length}</span>{/if}
						<ChevronRight size={13} class="chev" />
					</button>
				{:else}
					<div class="head static" title={ti.sub ? `${ti.t} ${ti.sub}` : ti.t}>
						{#if pending}<Loader size={13} class="spin" />{:else}<I size={13} />{/if}<b>{ti.t}</b>{#if ti.sub}<span class="sub truncate">{ti.sub}</span>{/if}
					</div>
				{/if}
				{#if shown}
					<ul class="detail">
						{#each g.items as a, ai (ai)}
							<li class:bad={a.ok === false}>{#if g.items.length > 1 || g.kind === 'edit' || g.kind === 'look'}<b>{a.verb}</b>{/if}<span>{a.detail}</span></li>
						{/each}
					</ul>
				{/if}
			</div>
		{/each}
	</div>
{/snippet}

<div class="builder">
	<div class="bar" aria-live="polite">
		<span class="dot {status.tone}"></span>
		<span class="state">{status.label}</span>
		{#if status.sub}<span class="stateSub truncate">{status.sub}</span>{/if}
		<span class="grow"></span>
		<button class="btn ghost sm aiBtn" onclick={openAi} title="Choose the model Build with AI uses for this app">
			<Cpu size={13} /><span class="lbl truncate">{aiLabel}</span><ChevronDown size={12} />
		</button>
		{#if chat.transcript.length && !busy}
			<button class="btn ghost sm" onclick={clear} title="Start a new conversation"><RotateCcw size={13} /><span class="lbl">New conversation</span></button>
		{/if}
	</div>

	{#if aiPanel}
		<div class="aiPanel">
			<div class="aiHead">
				<Cpu size={14} />
				<b>AI for Build with AI</b>
				<span class="grow"></span>
				<button class="icon-btn" title="Close" onclick={() => (aiPanel = false)}><X size={14} /></button>
			</div>
			<div class="aiScope">
				<button class="scope" class:on={aiScope === 'inherit'} onclick={() => (aiScope = 'inherit')}>Use the workspace model</button>
				<button class="scope" class:on={aiScope === 'app'} onclick={() => (aiScope = 'app')}>Choose a model for this app</button>
			</div>
			{#if aiScope === 'app'}
				<div class="providers">
					{#each Object.entries(aiProviders) as [k, p] (k)}
						<button class="prov" class:on={aiForm.provider === k} onclick={() => pickProvider(k)}>{p.label}</button>
					{/each}
				</div>
				{#if aiForm.provider}
					{@const info = aiProviders[aiForm.provider]}
					<div class="aiGrid">
						<label class="field span"><span>Model</span>
							<input class="input mono" list="app-ai-models" bind:value={aiForm.model} placeholder="model name" />
							<datalist id="app-ai-models">{#each MODEL_HINTS[aiForm.provider] ?? [] as m (m)}<option value={m}></option>{/each}</datalist>
						</label>
						{#if aiForm.provider !== 'anthropic'}
							<label class="field span"><span>Base URL</span>
								<input class="input mono" bind:value={aiForm.base_url} placeholder="https://…/v1" />
							</label>
						{/if}
						{#if info?.needs_key || aiForm.provider === 'custom' || aiForm.provider === 'ollama'}
							<label class="field span"><span>API key <em>{appAi?.own_key ? 'saved for this app; leave empty to keep it' : 'empty uses the workspace key'}</em></span>
								<input class="input mono" type="password" autocomplete="off" bind:value={aiForm.api_key} placeholder={appAi?.own_key ? '••••••••' : info?.needs_key ? 'API key' : 'optional'} />
							</label>
						{/if}
					</div>
				{/if}
			{:else}
				<p class="aiNote">{aiReady ? `Uses the workspace model${aiModel ? ` (${aiModel})` : ''}. Choose “Choose a model for this app” to use a different one.` : 'The workspace has no AI model yet.'} <a href="/settings?s=ai">Open AI settings</a></p>
			{/if}
			<div class="aiActs">
				<span class="aiHint">Only Build with AI uses this; the rest of Kern keeps the workspace model.</span>
				<span class="grow"></span>
				<button class="btn ghost" onclick={() => { if (appAi) fillAiForm(appAi); aiPanel = false; }}>Cancel</button>
				<button class="btn primary" disabled={aiSaving || (aiScope === 'app' && !aiForm.provider)} onclick={saveAppAi}>{aiSaving ? 'Saving…' : 'Save'}</button>
			</div>
		</div>
	{/if}

	<div class="stage">
		<div class="thread" role="log" aria-label="Conversation" bind:this={box} {onscroll}>
			{#if empty}
				<div class="intro">
					<span class="spark"><Sparkle size={22} /></span>
					<h3>What should {app.name} do?</h3>
					<p>Describe the app or the change you want. The AI writes the code into <b>{app.repo || 'the repository'}</b> and deploys it to <code>{app.path}</code>. Nothing is lost: every change is a commit.</p>
					<ul class="can">
						{#each CAN as c (c.title)}
							{@const I = c.icon}
							<li><span class="ci"><I size={15} /></span><span><b>{c.title}</b>{c.body}</span></li>
						{/each}
					</ul>
					{#if aiMissing}
						{#if appAi && !appAi.inherited}
							<p class="warn"><CircleAlert size={14} />This app's AI model is not fully set up. <button class="linkish" onclick={openAi}>Finish its setup.</button></p>
						{:else}
							<p class="warn"><CircleAlert size={14} />No AI provider is set up yet. <a href="/settings?s=ai">Choose one in Settings → AI.</a></p>
						{/if}
					{:else if aiReady}
						<p class="using">Builds with <b>{aiModel}</b> · <button class="linkish" onclick={openAi}>Change model</button></p>
					{/if}
				</div>
			{/if}
			{#each chat.transcript as t, i (i)}
				{#if t.role === 'user'}
					<div class="msg user"><div class="bubble">{t.text}</div></div>
				{:else}
					{@const gs = group(t.actions)}
					<div class="msg bot">
						<span class="avatar"><Sparkle size={15} /></span>
						<div class="body">
							{#if gs.length > FOLD}
								{@const sk = `t${i}`}
								{@const bad = gs.some((g) => g.bad)}
								<div class="fold" class:bad>
									<button class="foldhead" aria-expanded={isOpen(sk, false)} onclick={() => toggle(sk, false)}>
										<ChevronRight size={13} class="chev {isOpen(sk, false) ? 'on' : ''}" />
										<b>{t.actions?.length} steps</b>
										<span class="sub truncate">{summary(gs)}</span>
									</button>
									{#if isOpen(sk, false)}{@render cards(gs, `t${i}`, false)}{/if}
								</div>
							{:else if gs.length}
								{@render cards(gs, `t${i}`, false)}
							{/if}
							<div class="prose rt" class:err={t.error}>{@html renderMarkdown(t.text)}</div>
						</div>
					</div>
				{/if}
			{/each}
			{#if busy}
				<div class="msg bot">
					<span class="avatar"><Sparkle size={15} /></span>
					<div class="body">
						{#if liveGroups.length}{@render cards(liveGroups, 'live', true)}{/if}
						<div class="working"><Loader size={13} class="spin" />{chat.status === 'queued' ? 'Waiting for the apps service…' : chat.progress.length ? 'Working…' : 'Thinking…'}</div>
					</div>
				</div>
			{/if}
		</div>
		{#if !atBottom && (chat.transcript.length || busy)}
			<button class="jump" onclick={jump}><ArrowDown size={14} />Jump to latest</button>
		{/if}
	</div>

	<div class="composer">
		{#if !busy}
			<div class="suggest" aria-label="Quick prompts">{#each CHIPS as s (s)}<button class="qchip" onclick={() => fill(s)}>{s}</button>{/each}</div>
		{/if}
		<div class="box">
			<textarea bind:this={input} bind:value={text} rows="1" aria-label="Message to the AI builder"
				placeholder={busy ? 'The AI is working. You can write your next message…' : chat.transcript.length ? 'Ask for a change…' : 'Describe the app…'}
				onkeydown={keydown}></textarea>
			<div class="row">
				<span class="hint">Enter to send · Shift+Enter for a new line</span>
				<span class="grow"></span>
				{#if busy}
					<button class="stop" onclick={stop} title="Ends the turn after the current step"><Square size={11} fill="currentColor" />Stop</button>
				{:else}
					<button class="send" disabled={!text.trim() || sending} onclick={() => send()} title="Send (Enter)" aria-label="Send"><ArrowUp size={16} /></button>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.builder { display: flex; flex-direction: column; height: calc(100dvh - 210px); min-height: 420px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); overflow: hidden; }

	/* status header */
	.bar { flex: none; display: flex; align-items: center; gap: 8px; min-height: 36px; padding: 4px 10px 4px 14px; border-bottom: 1px solid var(--border); background: var(--surface); font-size: 12.5px; min-width: 0; }
	.state { font-weight: 550; flex: none; }
	.stateSub { color: var(--text-3); min-width: 0; }
	.dot { flex: none; width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); }
	.dot.ok { background: var(--c-green); }
	.dot.bad { background: var(--danger); }
	.dot.busy { background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
	@keyframes pulse { 50% { opacity: 0.35; } }
	.grow { flex: 1; }
	.btn.sm { height: 26px; padding: 0 9px; font-size: 12.5px; }
	.aiBtn { max-width: 210px; }
	.aiBtn .lbl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	/* per-app AI settings */
	.aiPanel { flex: none; padding: 10px 14px; border-bottom: 1px solid var(--border); background: var(--surface); display: flex; flex-direction: column; gap: 10px; }
	.aiHead { display: flex; align-items: center; gap: 7px; font-size: 13px; }
	.aiHead :global(svg) { color: var(--accent); }
	.aiScope { display: flex; gap: 6px; }
	.scope { height: 28px; padding: 0 12px; border-radius: 14px; border: 1px solid var(--border-strong); background: var(--bg); color: var(--text-2); font-size: 12.5px; }
	.scope:hover { background: var(--hover); }
	.scope.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); color: var(--text); }
	.providers { display: flex; flex-wrap: wrap; gap: 6px; }
	.prov { height: 26px; padding: 0 10px; border-radius: 13px; border: 1px solid var(--border); background: var(--bg); color: var(--text-2); font-size: 12px; }
	.prov:hover { background: var(--hover); }
	.prov.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 9%, transparent); color: var(--text); }
	.aiGrid { display: grid; grid-template-columns: 1fr; gap: 8px; max-width: 640px; }
	.aiGrid .span { grid-column: 1 / -1; }
	.aiGrid .field { display: flex; flex-direction: column; gap: 3px; font-size: 12px; font-weight: 550; color: var(--text-2); }
	.aiGrid .field em { font-style: normal; font-weight: 400; color: var(--text-3); }
	.aiGrid .input { width: 100%; }
	.aiNote { margin: 0; font-size: 12.5px; color: var(--text-2); }
	.aiNote a { color: var(--accent); }
	.aiActs { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.aiHint { font-size: 11.5px; color: var(--text-3); }

	/* conversation */
	.stage { position: relative; flex: 1; min-height: 0; }
	.thread { height: 100%; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; padding: 18px 20px 10px; display: flex; flex-direction: column; gap: 16px; }
	.jump { position: absolute; left: 50%; bottom: 10px; transform: translateX(-50%); display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 12px; border-radius: 14px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); font-size: 12.5px; box-shadow: var(--shadow); animation: fade 0.15s var(--ease); }
	.jump:hover { background: var(--surface-2); }

	.intro { max-width: 560px; margin: auto; text-align: center; color: var(--text-2); }
	.intro h3 { margin: 10px 0 6px; font-size: 17px; color: var(--text); }
	.intro p { margin: 0; font-size: 13.5px; overflow-wrap: anywhere; }
	.intro code { font: 12px var(--font-mono); }
	.spark { display: inline-grid; place-items: center; width: 46px; height: 46px; border-radius: 13px; color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.can { list-style: none; margin: 16px 0 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; text-align: left; }
	.can li { display: flex; gap: 9px; padding: 9px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); font-size: 12.5px; line-height: 1.4; color: var(--text-2); min-width: 0; }
	.can li:last-child:nth-child(odd) { grid-column: 1 / -1; }
	.can b { display: block; color: var(--text); font-weight: 550; margin-bottom: 1px; }
	.ci { flex: none; display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
	.warn { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px; margin-top: 14px !important; color: var(--c-yellow); }
	.warn a { color: var(--accent); }
	.using { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; margin-top: 14px !important; color: var(--text-3); font-size: 12.5px; }
	.using b { color: var(--text-2); font-weight: 600; }
	.linkish { padding: 0; border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; }
	.linkish:hover { text-decoration: underline; }

	.msg { display: flex; gap: 10px; max-width: 780px; width: 100%; margin: 0 auto; min-width: 0; }
	.msg.user { justify-content: flex-end; }
	.bubble { max-width: 82%; padding: 8px 12px; border-radius: 12px 12px 4px 12px; background: var(--surface-2); white-space: pre-wrap; overflow-wrap: anywhere; }
	.avatar { flex: none; width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }

	/* step cards */
	.cards { display: flex; flex-direction: column; gap: 4px; }
	.card { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); font-size: 12.5px; color: var(--text-2); min-width: 0; overflow: hidden; }
	.card.bad { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
	.head { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 28px; padding: 4px 9px; text-align: left; min-width: 0; color: inherit; }
	button.head:hover { background: var(--hover); }
	.head :global(svg) { flex: none; color: var(--text-3); }
	.head b { font-weight: 550; color: var(--text); flex: none; max-width: 100%; }
	.head .sub { min-width: 0; color: var(--text-3); font-family: var(--font-mono); font-size: 12px; }
	.head .count { flex: none; margin-left: auto; min-width: 18px; padding: 0 5px; border-radius: 9px; background: var(--surface-2); color: var(--text-2); font-size: 11.5px; text-align: center; }
	.head :global(.chev) { flex: none; margin-left: auto; transition: transform 0.12s var(--ease); }
	.head .count + :global(.chev) { margin-left: 0; }
	.card.open .head :global(.chev) { transform: rotate(90deg); }
	.card.bad .head b, .card.bad .head :global(svg:first-child) { color: var(--danger); }
	.card.good .head :global(svg:first-child) { color: var(--c-green); }
	.detail { list-style: none; margin: 0; padding: 2px 9px 8px 29px; display: flex; flex-direction: column; gap: 2px; border-top: 1px solid var(--border); padding-top: 6px; }
	.detail li { display: flex; gap: 6px; min-width: 0; font-family: var(--font-mono); font-size: 12px; overflow-wrap: anywhere; }
	.detail li b { flex: none; font-family: var(--font-sans); font-weight: 550; color: var(--text-2); }
	.detail li.bad { color: var(--danger); }
	.fold { display: flex; flex-direction: column; gap: 4px; }
	.foldhead { display: flex; align-items: center; gap: 7px; min-height: 26px; padding: 2px 4px; border-radius: 6px; font-size: 12.5px; color: var(--text-2); min-width: 0; text-align: left; }
	.foldhead:hover { background: var(--hover); }
	.foldhead b { flex: none; font-weight: 550; color: var(--text); }
	.foldhead .sub { min-width: 0; color: var(--text-3); }
	.foldhead :global(svg) { flex: none; color: var(--text-3); transition: transform 0.12s var(--ease); }
	.foldhead :global(svg.on) { transform: rotate(90deg); }
	.fold.bad .foldhead b { color: var(--danger); }
	.working { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-3); }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }

	.prose { font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; min-width: 0; }
	.prose.err { color: var(--danger); }
	.prose :global(p) { margin: 0 0 8px; }
	.prose :global(p:last-child) { margin-bottom: 0; }
	.prose :global(pre) { padding: 10px 12px; border-radius: 8px; background: var(--code-bg); overflow-x: auto; font-size: 12.5px; }
	.prose :global(table) { display: block; max-width: 100%; overflow-x: auto; }
	.prose :global(img) { max-width: 100%; height: auto; }

	/* composer: always at the bottom, the thread scrolls above it */
	.composer { flex: none; padding: 8px 14px max(12px, env(safe-area-inset-bottom)); border-top: 1px solid var(--border); background: var(--surface); }
	.suggest { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 auto 8px; max-width: 780px; }
	.qchip { height: 24px; padding: 0 10px; border-radius: 12px; border: 1px solid var(--border-strong); background: var(--bg); color: var(--text-2); font-size: 12.5px; white-space: nowrap; transition: background 0.12s var(--ease), color 0.12s var(--ease); }
	.qchip:hover { background: var(--surface-2); color: var(--text); }
	.box { max-width: 780px; margin: 0 auto; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--bg); padding: 8px 8px 6px 12px; }
	.box:focus-within { border-color: color-mix(in srgb, var(--accent) 60%, var(--border-strong)); }
	textarea { display: block; width: 100%; box-sizing: border-box; border: 0; outline: 0; resize: none; background: none; font: inherit; font-size: 14px; line-height: 1.5; padding: 2px 0; min-height: 26px; max-height: 200px; overflow-y: auto; color: var(--text); }
	.row { display: flex; align-items: center; gap: 6px; min-height: 30px; }
	.hint { font-size: 11.5px; color: var(--text-3); }
	.send { flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: #17130c; }
	.send:disabled { opacity: 0.35; cursor: default; }
	.stop { flex: none; display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 14px; border-radius: 15px; border: 1px solid var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger); font-weight: 550; font-size: 13px; }
	.stop:hover { background: color-mix(in srgb, var(--danger) 22%, transparent); }

	@media (prefers-reduced-motion: reduce) { :global(.spin), .dot.busy { animation: none; } .jump { animation: none; } }
	@media (hover: none) { .hint { display: none; } }
	@media (max-width: 640px) {
		.builder { height: calc(100dvh - 190px); border-radius: 8px; }
		.bar { padding-left: 12px; }
		.lbl { display: none; }
		.thread { padding: 12px 10px 8px; gap: 14px; }
		.avatar { display: none; }
		.bubble { max-width: 90%; }
		.can { grid-template-columns: 1fr; }
		.composer { padding: 6px 10px max(10px, env(safe-area-inset-bottom)); }
		.suggest { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin-inline: -10px; padding-inline: 10px; max-width: none; }
		.suggest::-webkit-scrollbar { display: none; }
		.qchip { flex: none; height: 28px; }
		textarea { font-size: 16px; }
		.hint { display: none; }
	}
</style>
