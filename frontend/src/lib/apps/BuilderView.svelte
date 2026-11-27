<script lang="ts">
	// The AI builder: a conversation about one app. Each message runs in the apps service: the model
	// reads and writes the app's files, deploys, reads the logs and tries the app, then answers.
	import { ArrowUp, Check, CircleAlert, FileCode, FileMinus, Loader, RotateCcw, Rocket, Search, Square, TestTube } from '@lucide/svelte';
	import { onMount, tick } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ai } from '#lib/ai/ai.svelte.ts';
	import { renderMarkdown } from '#lib/ai/md.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { App } from './types.ts';

	interface Act { verb: string; detail: string; ok?: boolean }
	interface Turn { role: 'user' | 'assistant'; text: string; at: string; actions?: Act[]; error?: boolean }
	interface Chat { transcript: Turn[]; status: 'idle' | 'queued' | 'running'; progress: Act[]; pending: string }

	let { app, onchange }: { app: App; onchange: () => void } = $props();
	let chat = $state<Chat>({ transcript: [], status: 'idle', progress: [], pending: '' });
	let text = $state('');
	let sending = $state(false);
	let box = $state<HTMLDivElement>();
	let input = $state<HTMLTextAreaElement>();
	let timer: ReturnType<typeof setTimeout> | null = null;
	let lastLen = 0;

	let busy = $derived(chat.status !== 'idle');

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

	onMount(() => {
		ai.load();
		load().then(() => scroll(true));
		return () => timer && clearTimeout(timer);
	});

	async function scroll(force = false) {
		await tick();
		if (!box) return;
		const near = box.scrollHeight - box.scrollTop - box.clientHeight < 160;
		if (force || near) box.scrollTop = box.scrollHeight;
	}

	async function send(msg = text) {
		msg = msg.trim();
		if (!msg || busy || sending) return;
		if (!(await ai.ready())) return;
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
		} catch (e) {
			ui.error(e);
		}
	}

	function icon(verb: string) {
		if (/^(Wrote|Created|Edited)/.test(verb)) return FileCode;
		if (/^Deleted/.test(verb)) return FileMinus;
		if (/^Deploy/.test(verb)) return Rocket;
		if (/^(Tried|Requested|Called)/.test(verb)) return TestTube;
		if (/^(Read|Looked|Listed|Searched)/.test(verb)) return Search;
		return Check;
	}

	const SUGGEST = $derived(app.live
		? ['Make it look nicer on my phone', 'Add a way to export the data as CSV', 'Check the logs for errors and fix them', 'Add dark mode']
		: ['Build it', 'Keep it simple: one page, no packages']);
</script>

<div class="builder">
	<div class="thread" bind:this={box}>
		{#if !chat.transcript.length}
			<div class="intro">
				<span class="spark"><Sparkle size={22} /></span>
				<h3>What should {app.name} do?</h3>
				<p>Describe the app or the change you want. The AI writes the code into <b>{app.repo || 'the repository'}</b>, deploys it to <code>{app.path}</code>, reads the logs and tries it until it works. Every change is a commit, so nothing is lost.</p>
				{#if ai.config && !ai.config.configured}
					<p class="warn"><CircleAlert size={14} />No AI provider is set up yet. <a href="/settings?s=ai">Choose one in Settings → AI.</a></p>
				{/if}
			</div>
		{/if}
		{#each chat.transcript as t, i (i)}
			{#if t.role === 'user'}
				<div class="msg user"><div class="bubble">{t.text}</div></div>
			{:else}
				<div class="msg bot">
					<span class="avatar"><Sparkle size={15} /></span>
					<div class="body">
						{#if t.actions?.length}
							<div class="acts">
								{#each t.actions as a, j (j)}
									{@const I = icon(a.verb)}
									<span class="act" class:bad={a.ok === false}><I size={13} /><b>{a.verb}</b><span class="truncate">{a.detail}</span></span>
								{/each}
							</div>
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
					<div class="acts">
						{#each chat.progress as a, j (j)}
							{@const I = icon(a.verb)}
							<span class="act" class:bad={a.ok === false}><I size={13} /><b>{a.verb}</b><span class="truncate">{a.detail}</span></span>
						{/each}
						<span class="act working"><Loader size={13} class="spin" />{chat.status === 'queued' ? 'Waiting for the apps service…' : chat.progress.length ? 'Working…' : 'Thinking…'}</span>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<div class="composer">
		{#if !busy && chat.transcript.length < 12}
			<div class="suggest">{#each SUGGEST as s (s)}<button class="chip" onclick={() => send(s)}>{s}</button>{/each}</div>
		{/if}
		<div class="box">
			<textarea bind:this={input} bind:value={text} rows="2" placeholder={chat.transcript.length ? 'Ask for a change…' : 'Describe the app…'}
				onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } }}></textarea>
			<div class="row">
				{#if chat.transcript.length && !busy}<button class="btn ghost sm" onclick={clear} title="Start a new conversation"><RotateCcw size={13} />New conversation</button>{/if}
				<span class="grow"></span>
				{#if busy}
					<button class="btn sm" onclick={stop}><Square size={12} />Stop</button>
				{:else}
					<button class="send" disabled={!text.trim() || sending} onclick={() => send()} title="Send (Enter)"><ArrowUp size={16} /></button>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.builder { display: flex; flex-direction: column; height: calc(100dvh - 210px); min-height: 420px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); overflow: hidden; }
	.thread { flex: 1; overflow-y: auto; padding: 20px 20px 8px; display: flex; flex-direction: column; gap: 16px; }
	.intro { max-width: 520px; margin: auto; text-align: center; color: var(--text-2); }
	.intro h3 { margin: 10px 0 6px; font-size: 17px; color: var(--text); }
	.intro p { margin: 0; font-size: 13.5px; }
	.intro code { font: 12px var(--font-mono); }
	.spark { display: inline-grid; place-items: center; width: 46px; height: 46px; border-radius: 13px; color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.warn { display: flex; align-items: center; justify-content: center; gap: 6px; margin-top: 12px !important; color: var(--c-yellow); }
	.warn a { color: var(--accent); }
	.msg { display: flex; gap: 10px; max-width: 760px; width: 100%; margin: 0 auto; }
	.msg.user { justify-content: flex-end; }
	.bubble { max-width: 80%; padding: 8px 12px; border-radius: 12px 12px 4px 12px; background: var(--surface-2); white-space: pre-wrap; overflow-wrap: anywhere; }
	.avatar { flex: none; width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
	.acts { display: flex; flex-direction: column; gap: 3px; }
	.act { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-2); min-width: 0; }
	.act :global(svg) { flex: none; color: var(--text-3); }
	.act b { font-weight: 550; color: var(--text); flex: none; }
	.act.bad b, .act.bad :global(svg) { color: var(--danger); }
	.act.working { color: var(--text-3); }
	.act :global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	.prose { font-size: 14px; line-height: 1.6; }
	.prose.err { color: var(--danger); }
	.prose :global(p) { margin: 0 0 8px; }
	.prose :global(p:last-child) { margin-bottom: 0; }
	.prose :global(pre) { padding: 10px 12px; border-radius: 8px; background: var(--code-bg); overflow-x: auto; font-size: 12.5px; }
	.composer { padding: 10px 14px 14px; border-top: 1px solid var(--border); background: var(--surface); }
	.suggest { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; max-width: 760px; margin-inline: auto; }
	.suggest .chip { cursor: pointer; }
	.suggest .chip:hover { color: var(--text); }
	.box { max-width: 760px; margin: 0 auto; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--bg); padding: 8px 8px 6px 12px; }
	.box:focus-within { border-color: color-mix(in srgb, var(--accent) 60%, var(--border-strong)); }
	textarea { width: 100%; border: 0; outline: 0; resize: none; background: none; font: inherit; font-size: 14px; max-height: 200px; field-sizing: content; min-height: 44px; }
	.row { display: flex; align-items: center; gap: 6px; }
	.grow { flex: 1; }
	.btn.sm { height: 26px; padding: 0 9px; font-size: 12.5px; }
	.send { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; background: var(--accent); color: #17130c; }
	.send:disabled { opacity: 0.35; cursor: default; }
	@media (prefers-reduced-motion: reduce) { .act :global(.spin) { animation: none; } }
	@media (max-width: 700px) { .builder { height: calc(100dvh - 190px); } .thread { padding: 14px 10px 8px; } }
</style>
