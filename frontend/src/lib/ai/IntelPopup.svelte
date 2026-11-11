<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ArrowUp, Globe, Maximize2, MessageSquarePlus, Settings, X } from '@lucide/svelte';
	import { onMount, tick } from 'svelte';
	import { api, ApiError } from '../api.ts';
	import { shortcut } from '../state/prefs.svelte.ts';
	import { modKey } from '../util.ts';
	import { ui } from '../state/ui.svelte.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import { ai } from './ai.svelte.ts';
	import { sendChat, type Chat } from './chat.ts';
	import ChatThread from './ChatThread.svelte';
	import Sparkle from './Sparkle.svelte';

	const pretty = (c: string) => c.replace('Mod', modKey).replace(/\+/g, ' ');
	let chat = $state<Chat | null>(null);
	let draft = $state('');
	let sending = $state(false);
	let pendingText = $state('');
	let input = $state<HTMLTextAreaElement>();
	let scroller = $state<HTMLDivElement>();

	// The page the popup is about: the document open in the current tab, if any.
	let pageId = $derived(page.url.pathname.match(/^\/doc\/([^/]+)/)?.[1] ?? null);
	let doc = $derived(pageId ? ws.docs[pageId] : undefined);
	let scopeKey = $derived(`kern:intel-chat:${pageId ?? 'all'}`);
	let configured = $derived(ai.config?.configured ?? true);
	let web = $derived(!!ai.config?.web_search);

	const pageIdeas = [
		{ label: 'Quiz me', text: 'Quiz me on this page.' },
		{ label: 'Summarize', text: 'Summarize this page in a few bullet points.' },
		{ label: 'Explain simply', text: 'Explain the hardest idea on this page in simpler terms, with an example.' },
		{ label: 'Find more online', text: 'Find more information about the main topic of this page on the web, with sources.', web: true },
		{ label: 'Make flashcards', text: 'Make flashcards from the key facts on this page and add them to it.' },
		{ label: 'Tidy up', text: 'Reorganise this page with clear headings and bullets, without losing anything.' }
	];
	const globalIdeas = [
		{ label: 'Due this week', text: 'What do I have due this week?' },
		{ label: 'Find in my notes', text: 'Search my notes for ' },
		{ label: 'New group', text: 'Make a group for ' },
		{ label: 'Plan my day', text: 'Look at my tasks and suggest a plan for today.' }
	];
	let ideas = $derived(pageId ? pageIdeas : globalIdeas);

	const remembered = (key: string) => {
		try {
			return localStorage.getItem(key);
		} catch {
			return null;
		}
	};
	const remember = (key: string, id: string | null) => {
		try {
			if (id) localStorage.setItem(key, id);
			else localStorage.removeItem(key);
		} catch {
			/* private mode */
		}
	};

	// Each page keeps its own conversation; switching page switches the chat.
	let loadedKey = '';
	$effect(() => {
		const key = scopeKey;
		if (key === loadedKey) return;
		loadedKey = key;
		chat = null;
		const id = remembered(key);
		if (id)
			api.get<Chat>(`/chats/${id}`).then((c) => {
				if (loadedKey === key) {
					chat = c;
					scrollDown(false);
				}
			}).catch(() => remember(key, null));
	});

	onMount(() => {
		ai.load();
		input?.focus();
	});

	async function scrollDown(smooth = true) {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
	}

	async function send(text = draft) {
		text = text.trim();
		if (!text || sending) return;
		if (!(await ai.ready())) return;
		const key = scopeKey;
		sending = true;
		pendingText = text;
		draft = '';
		scrollDown();
		try {
			const updated = await sendChat(chat, text, pageId, (c) => remember(key, c.id));
			if (loadedKey === key) chat = updated;
		} catch (e) {
			draft = text;
			if (e instanceof ApiError && e.data?.setup) goto('/settings?s=ai');
			ui.error(e);
		} finally {
			sending = false;
			pendingText = '';
			scrollDown();
			input?.focus();
		}
	}

	function pick(idea: { text: string }) {
		if (idea.text.endsWith(' ')) {
			draft = idea.text;
			input?.focus();
		} else send(idea.text);
	}

	function fresh() {
		remember(scopeKey, null);
		chat = null;
		draft = '';
		input?.focus();
	}

	function expand() {
		ai.popupOpen = false;
		goto(chat ? `/intelligence?c=${chat.id}` : '/intelligence');
	}

	function keydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			ai.popupOpen = false;
		}
	}

	$effect(() => {
		void draft;
		if (!input) return;
		input.style.height = 'auto';
		input.style.height = Math.min(input.scrollHeight, 160) + 'px';
	});
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="intel popover" role="dialog" aria-label="Intelligence" tabindex="-1"
	onkeydown={(e) => { if (e.key === 'Escape') ai.popupOpen = false; }}>
	<header>
		<span class="brand"><Sparkle size={15} />Intelligence</span>
		<span class="scope truncate" title={pageId ? 'Answers are about this page' : 'Answers use your whole workspace'}>
			{#if doc}{doc.icon ? doc.icon + ' ' : ''}{doc.title || 'Untitled'}{:else}Workspace{/if}
		</span>
		<button class="icon-btn" title="New chat" onclick={fresh}><MessageSquarePlus size={14} /></button>
		<button class="icon-btn" title="Open full page" onclick={expand}><Maximize2 size={14} /></button>
		<button class="icon-btn" title="Close (Esc)" onclick={() => (ai.popupOpen = false)}><X size={15} /></button>
	</header>

	<div class="scroll" bind:this={scroller}>
		{#if chat?.messages.length || sending}
			<ChatThread messages={chat?.messages ?? []} {sending} {pendingText} compact />
		{:else}
			<div class="hello">
				<p class="muted">{pageId ? 'Ask about this page, have it edit it, quiz you, or look things up.' : 'Ask about your notes or have it change them.'}</p>
				{#if !configured}
					<a class="btn primary" href="/settings?s=ai" onclick={() => (ai.popupOpen = false)}><Settings size={14} />Set up an AI provider</a>
				{:else}
					<div class="ideas">
						{#each ideas as idea (idea.label)}
							<button class="idea" disabled={'web' in idea && !web} title={'web' in idea && !web ? 'Web search needs Claude as the provider (Settings → AI)' : idea.text}
								onclick={() => pick(idea)}>
								{#if 'web' in idea}<Globe size={12} />{/if}{idea.label}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="composer">
		<textarea bind:this={input} bind:value={draft} rows="1" onkeydown={keydown}
			placeholder={pageId ? 'Ask about this page, or tell it what to change…' : 'Ask Intelligence…'}></textarea>
		<button class="send" title="Send (Enter)" disabled={!draft.trim() || sending} onclick={() => send()}><ArrowUp size={15} strokeWidth={2.25} /></button>
	</div>
	<p class="foot faint">
		{ai.config && !web ? 'No web search with this provider (needs Claude) · ' : ''}{pretty(shortcut('intelligence'))} to toggle
	</p>
</div>

<style>
	.intel { position: fixed; right: 20px; bottom: 20px; z-index: 900; width: 420px; height: min(600px, calc(100vh - 80px)); display: flex; flex-direction: column; border-radius: 14px; overflow: hidden; }
	header { flex: none; display: flex; align-items: center; gap: 4px; height: 42px; padding: 0 6px 0 12px; border-bottom: 1px solid var(--border); }
	.brand { display: flex; align-items: center; gap: 6px; font-weight: 600; white-space: nowrap; }
	.scope { flex: 1; margin: 0 4px; padding: 1px 8px; border-radius: 9px; font-size: 12px; color: var(--text-2); background: var(--hover); width: fit-content; max-width: max-content; }
	header :global(.icon-btn) { width: 26px; height: 26px; }
	header .icon-btn:first-of-type { margin-left: auto; }
	.scroll { flex: 1; overflow-y: auto; padding: 14px; }
	.hello p { margin: 4px 0 14px; line-height: 1.5; }
	.ideas { display: flex; flex-wrap: wrap; gap: 6px; }
	.idea { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 11px; border-radius: 14px; border: 1px solid var(--border-strong); color: var(--text-2); font-size: 12.5px; transition: border-color .15s var(--ease), color .15s var(--ease); }
	.idea:hover:not(:disabled) { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong)); }
	.idea:disabled { opacity: 0.45; cursor: default; }
	.composer { flex: none; display: flex; align-items: flex-end; gap: 6px; margin: 0 10px; padding: 6px 6px 6px 12px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--bg); }
	.composer:focus-within { border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong)); }
	textarea { flex: 1; resize: none; border: 0; outline: none; background: none; color: var(--text); font: inherit; font-size: 13.5px; line-height: 1.5; padding: 3px 0; max-height: 160px; }
	.send { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; background: var(--accent); color: #17130c; }
	.send:disabled { opacity: 0.35; cursor: default; }
	.foot { flex: none; margin: 6px 12px 8px; font-size: 11px; text-align: center; }
	@media (max-width: 560px) {
		.intel { right: 8px; left: 8px; bottom: 8px; width: auto; height: calc(100vh - 70px); }
	}
</style>
