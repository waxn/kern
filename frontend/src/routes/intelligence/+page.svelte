<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ArrowUp, MessageSquarePlus, PanelLeft, Settings, Trash2 } from '@lucide/svelte';
	import { onMount, tick } from 'svelte';
	import { api, ApiError } from '#lib/api.ts';
	import { ai } from '#lib/ai/ai.svelte.ts';
	import { renderMarkdown } from '#lib/ai/md.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { releaseDoc } from '#lib/editor/doc.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';

	interface Action { verb: string; detail: string; page?: { id: string; title: string; icon: string } }
	interface Message { role: 'user' | 'assistant'; text: string; actions?: Action[]; at?: string }
	interface ChatSummary { id: string; title: string; updated_at: string }
	interface Chat extends ChatSummary { messages: Message[] }

	let chats = $state<ChatSummary[]>([]);
	let chat = $state<Chat | null>(null);
	let draft = $state('');
	let sending = $state(false);
	let pendingText = $state('');
	let listOpen = $state(true);
	let input = $state<HTMLTextAreaElement>();
	let scroller = $state<HTMLDivElement>();

	const suggestions = [
		'What do I have due this week?',
		'Move “Essay” to Done on my Homework board',
		'Make a group for Chemistry with a calendar and a notes page',
		'Turn my most recent page into flashcards'
	];

	let current = $derived(page.url.searchParams.get('c'));
	let configured = $derived(ai.config?.configured ?? true);

	async function loadList() {
		try {
			chats = await api.get<ChatSummary[]>('/chats');
		} catch (e) {
			ui.error(e);
		}
	}

	async function openChat(id: string | null) {
		if (!id) {
			chat = null;
			return;
		}
		if (chat?.id === id) return;
		try {
			chat = await api.get<Chat>(`/chats/${id}`);
			await scrollDown();
		} catch {
			chat = null;
			goto('/intelligence', { replaceState: true });
		}
	}

	$effect(() => {
		openChat(current);
	});

	onMount(() => {
		ai.load();
		loadList();
		input?.focus();
	});

	async function scrollDown() {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
	}

	function newChat() {
		goto('/intelligence');
		chat = null;
		draft = '';
		tick().then(() => input?.focus());
	}

	async function send(text = draft) {
		text = text.trim();
		if (!text || sending) return;
		if (!(await ai.ready())) return;
		sending = true;
		pendingText = text;
		draft = '';
		await scrollDown();
		try {
			let target = chat;
			if (!target) {
				target = await api.post<Chat>('/chats', {});
				chat = target;
				goto(`/intelligence?c=${target.id}`, { replaceState: true });
			}
			const updated = await api.post<Chat>(`/chats/${target.id}/message`, { text });
			chat = updated;
			const last = updated.messages[updated.messages.length - 1];
			if (last?.actions?.length) {
				// The assistant changed the workspace: drop cached copies so pages reload fresh.
				for (const a of last.actions) if (a.page) await releaseDoc(a.page.id, false);
				ws.load().catch(() => {});
			}
			loadList();
		} catch (e) {
			draft = text;
			if (e instanceof ApiError && e.data?.setup) goto('/settings?s=ai');
			ui.error(e);
		} finally {
			sending = false;
			pendingText = '';
			await scrollDown();
			input?.focus();
		}
	}

	async function remove(c: ChatSummary, e: MouseEvent) {
		e.stopPropagation();
		const ok = await ui.confirm({
			title: `Delete “${c.title}”?`, message: 'The conversation is removed. Changes it made to your pages stay.',
			confirmLabel: 'Delete chat', danger: true
		});
		if (!ok) return;
		await api.del(`/chats/${c.id}`).catch((err) => ui.error(err));
		if (chat?.id === c.id) newChat();
		loadList();
	}

	function keydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		}
	}

	function autosize() {
		if (!input) return;
		input.style.height = 'auto';
		input.style.height = Math.min(input.scrollHeight, 220) + 'px';
	}
	$effect(() => {
		void draft;
		autosize();
	});

	const linkFor = (title: string) => {
		const d = Object.values(ws.docs).find((x) => x.title.trim().toLowerCase() === title.trim().toLowerCase());
		return d ? `/doc/${d.id}` : null;
	};

	function clickProse(e: MouseEvent) {
		const a = (e.target as HTMLElement).closest('a.ref') as HTMLAnchorElement | null;
		if (a) {
			e.preventDefault();
			open(a.getAttribute('href')!, e);
		}
	}

	function when(iso: string) {
		const d = new Date(iso);
		const today = new Date();
		return d.toDateString() === today.toDateString()
			? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
			: d.toLocaleDateString([], { month: 'short', day: 'numeric' });
	}
</script>

<div class="wrap">
	{#if listOpen}
		<aside class="chats">
			<div class="chats-head">
				<span class="faint">Chats</span>
				<button class="icon-btn" title="New chat" onclick={newChat}><MessageSquarePlus size={15} /></button>
			</div>
			<div class="chat-list">
				{#each chats as c (c.id)}
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<div class="chat-row" class:active={chat?.id === c.id} onclick={() => goto(`/intelligence?c=${c.id}`)}>
						<span class="truncate">{c.title}</span>
						<span class="when faint">{when(c.updated_at)}</span>
						<button class="icon-btn del" title="Delete chat" onclick={(e) => remove(c, e)}><Trash2 size={13} /></button>
					</div>
				{:else}
					<p class="faint none">Your conversations show up here.</p>
				{/each}
			</div>
		</aside>
	{/if}

	<section class="main">
		<header class="bar">
			<button class="icon-btn" title={listOpen ? 'Hide chats' : 'Show chats'} onclick={() => (listOpen = !listOpen)}><PanelLeft size={15} /></button>
			<span class="title truncate">{chat?.title || 'Intelligence'}</span>
			{#if chat}
				<button class="btn ghost" onclick={newChat}><MessageSquarePlus size={14} />New chat</button>
			{/if}
		</header>

		<div class="scroll" bind:this={scroller}>
			{#if !chat && !sending}
				<div class="hello">
					<div class="mark"><Sparkle size={44} /></div>
					<h1>Intelligence</h1>
					<p class="muted">Ask about your notes, or have it change them: write and reorganise pages, move cards on a board, add calendar events, plan tasks, make flashcards.</p>
					{#if !configured}
						<a class="btn primary" href="/settings?s=ai"><Settings size={14} />Set up an AI provider</a>
					{:else}
						<div class="ideas">
							{#each suggestions as s (s)}
								<button class="idea" onclick={() => send(s)}>{s}</button>
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				<div class="thread">
					{#each chat?.messages ?? [] as m, i (i)}
						{#if m.role === 'user'}
							<div class="msg user"><div class="bubble">{m.text}</div></div>
						{:else}
							<div class="msg bot">
								<span class="avatar"><Sparkle size={16} /></span>
								<div class="body">
									{#if m.actions?.length}
										<div class="actions">
											{#each m.actions as a, j (j)}
												{#if a.page}
													<a class="act" href="/doc/{a.page.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${a.page!.id}`, e); }}>
														<b>{a.verb}</b>
														<span class="truncate">{a.page.icon ? a.page.icon + ' ' : ''}{a.page.title}</span>
														{#if a.detail}<span class="faint truncate">· {a.detail}</span>{/if}
													</a>
												{:else}
													<span class="act"><b>{a.verb}</b><span class="truncate">{a.detail}</span></span>
												{/if}
											{/each}
										</div>
									{/if}
									<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
									<div class="prose rt" onclick={clickProse}>{@html renderMarkdown(m.text, linkFor)}</div>
								</div>
							</div>
						{/if}
					{/each}
					{#if sending}
						<div class="msg user"><div class="bubble">{pendingText}</div></div>
						<div class="msg bot">
							<span class="avatar spin"><Sparkle size={16} /></span>
							<div class="body"><span class="thinking">Working on it…</span></div>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<div class="composer-wrap">
			<div class="composer">
				<textarea
					bind:this={input}
					bind:value={draft}
					rows="1"
					placeholder={chat ? 'Reply…' : 'Ask Intelligence to find or change anything…'}
					onkeydown={keydown}
				></textarea>
				<button class="send" title="Send (Enter)" disabled={!draft.trim() || sending} onclick={() => send()}>
					<ArrowUp size={16} strokeWidth={2.25} />
				</button>
			</div>
			<p class="note faint">Changes are reversible: edited pages keep version history and deleted pages go to the trash.</p>
		</div>
	</section>
</div>

<style>
	.wrap { display: flex; height: 100%; min-height: 0; }
	.chats { width: 240px; flex: none; display: flex; flex-direction: column; border-right: 1px solid var(--border); background: color-mix(in srgb, var(--bg-side) 60%, var(--bg)); }
	.chats-head { display: flex; align-items: center; justify-content: space-between; height: 40px; padding: 0 8px 0 14px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
	.chat-list { flex: 1; overflow-y: auto; padding: 0 6px 12px; }
	.chat-row { display: flex; align-items: center; gap: 6px; height: 32px; padding: 0 4px 0 10px; border-radius: var(--radius-sm); color: var(--text-2); cursor: pointer; }
	.chat-row:hover { background: var(--hover); color: var(--text); }
	.chat-row.active { background: var(--active); color: var(--text); }
	.chat-row .truncate { flex: 1; }
	.when { font-size: 11.5px; }
	.del { width: 22px; height: 22px; display: none; }
	.chat-row:hover .del { display: inline-grid; }
	.chat-row:hover .when { display: none; }
	.none { padding: 8px 10px; font-size: 13px; }

	.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.bar { display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 12px 0 8px; border-bottom: 1px solid var(--border); }
	.bar .title { flex: 1; font-weight: 550; }
	.scroll { flex: 1; overflow-y: auto; }

	.hello { max-width: 620px; margin: 0 auto; padding: 12vh 24px 24px; text-align: center; }
	.mark { display: inline-grid; place-items: center; width: 76px; height: 76px; border-radius: 22px; margin-bottom: 14px;
		background: radial-gradient(circle at 50% 40%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%); }
	.mark :global(.sparkle) { animation: breathe 4s var(--ease) infinite; }
	@keyframes breathe { 50% { transform: rotate(45deg) scale(1.06); } }
	.hello h1 { font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 6px; }
	.hello p { margin: 0 auto 24px; max-width: 480px; line-height: 1.55; }
	.ideas { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; text-align: left; }
	.idea { padding: 10px 12px; border: 1px solid var(--border-strong); border-radius: 10px; background: var(--surface); color: var(--text-2); line-height: 1.4; transition: border-color .15s var(--ease), color .15s var(--ease), background .15s var(--ease); }
	.idea:hover { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong)); background: color-mix(in srgb, var(--accent) 6%, var(--surface)); }

	.thread { max-width: 760px; margin: 0 auto; padding: 24px 24px 12px; display: flex; flex-direction: column; gap: 18px; }
	.msg.user { display: flex; justify-content: flex-end; }
	.bubble { max-width: 80%; padding: 8px 13px; border-radius: 14px 14px 4px 14px; background: var(--surface-2); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5; }
	.msg.bot { display: flex; gap: 12px; align-items: flex-start; }
	.avatar { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--border-strong); background: var(--surface); }
	.avatar.spin :global(.sparkle) { animation: spin 1.6s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	.body { flex: 1; min-width: 0; padding-top: 3px; }
	.thinking { color: var(--text-3); background: linear-gradient(90deg, var(--text-3), var(--text), var(--text-3)); background-size: 200% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; animation: shimmer 1.8s linear infinite; }
	@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
	.actions { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
	.act { display: flex; align-items: center; gap: 6px; max-width: 100%; width: fit-content; padding: 4px 10px; border-radius: 8px; font-size: 12.5px; text-decoration: none; color: var(--text-2);
		border: 1px solid color-mix(in srgb, var(--accent) 25%, var(--border)); background: color-mix(in srgb, var(--accent) 6%, transparent); }
	a.act:hover { color: var(--text); border-color: color-mix(in srgb, var(--accent) 50%, var(--border)); }
	.act b { font-weight: 600; color: var(--accent); white-space: nowrap; }
	.prose { line-height: 1.6; }
	.prose :global(p) { margin: 0 0 8px; }
	.prose :global(p:last-child) { margin-bottom: 0; }
	.prose :global(ul), .prose :global(ol) { margin: 0 0 8px; padding-left: 22px; }
	.prose :global(h4) { margin: 10px 0 4px; font-size: 14.5px; }
	.prose :global(pre) { margin: 0 0 8px; padding: 10px 12px; border-radius: 8px; background: var(--code-bg); overflow-x: auto; font: 12.5px/1.5 var(--font-mono); }
	.prose :global(pre code) { background: none; padding: 0; color: inherit; }

	.composer-wrap { padding: 8px 24px 14px; }
	.composer { max-width: 760px; margin: 0 auto; display: flex; align-items: flex-end; gap: 8px; padding: 8px 8px 8px 14px; border: 1px solid var(--border-strong); border-radius: 14px; background: var(--surface); transition: border-color .15s var(--ease), box-shadow .15s var(--ease); }
	.composer:focus-within { border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent); }
	textarea { flex: 1; resize: none; border: 0; outline: none; background: none; color: var(--text); font: inherit; line-height: 1.5; padding: 4px 0; max-height: 220px; }
	.send { flex: none; display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--accent); color: #17130c; transition: filter .12s, opacity .12s; }
	.send:hover:not(:disabled) { filter: brightness(1.08); }
	.send:disabled { opacity: 0.35; cursor: default; }
	.note { max-width: 760px; margin: 6px auto 0; font-size: 11.5px; text-align: center; }

	@media (max-width: 720px) {
		.chats { display: none; }
		.ideas { grid-template-columns: 1fr; }
		.thread, .composer-wrap { padding-left: 14px; padding-right: 14px; }
	}
</style>
