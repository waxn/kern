<script lang="ts">
	import { Bookmark, Globe, Mail, ShieldCheck, X } from '@lucide/svelte';
	import { open } from '../state/tabs.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import { SCOPE_LABELS, type ChatMessage, type ChatPending, type ChatScope, type PermissionAnswer } from './chat.ts';
	import { renderMarkdown } from './md.ts';
	import Sparkle from './Sparkle.svelte';

	let { messages, sending = false, pendingText = '', compact = false, pending = null, granted = [], answering = null, onanswer, onrevoke }: {
		messages: ChatMessage[]; sending?: boolean; pendingText?: string; compact?: boolean;
		/** A permission request the assistant is waiting on. */
		pending?: ChatPending | null; granted?: ChatScope[]; answering?: PermissionAnswer | null;
		onanswer?: (a: PermissionAnswer) => void; onrevoke?: (s: ChatScope) => void;
	} = $props();

	let mailAsk = $derived(!!pending?.scopes.includes('mail.read'));
	let askTitle = $derived(
		!pending ? '' : pending.scopes.length > 1 ? 'Intelligence is asking for permission'
		: mailAsk ? 'Intelligence wants to read your email' : 'Intelligence wants to change your bookmarks'
	);

	const linkFor = (title: string) => {
		const t = title.trim().toLowerCase();
		const d = Object.values(ws.docs).find((x) => x.title.trim().toLowerCase() === t);
		return d ? `/doc/${d.id}` : null;
	};

	function clickProse(e: MouseEvent) {
		const a = (e.target as HTMLElement).closest('a.ref') as HTMLAnchorElement | null;
		if (a) {
			e.preventDefault();
			open(a.getAttribute('href')!, e);
		}
	}

	const host = (url: string) => {
		try {
			return new URL(url).hostname.replace(/^www\./, '');
		} catch {
			return url;
		}
	};
</script>

<div class="thread" class:compact>
	{#each messages as m, i (i)}
		{#if m.role === 'user'}
			<div class="msg user"><div class="bubble">{m.text}</div></div>
		{:else}
			<div class="msg bot">
				<span class="avatar"><Sparkle size={compact ? 14 : 16} /></span>
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
					{#if m.sources?.length}
						<div class="sources">
							<Globe size={12} class="faint" />
							{#each m.sources as s (s.url)}
								<a class="src" href={s.url} target="_blank" rel="noopener noreferrer" title={s.title}>{host(s.url)}</a>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	{/each}
	{#if pending && !sending}
		<div class="msg bot">
			<span class="avatar"><Sparkle size={compact ? 14 : 16} /></span>
			<div class="body">
				<div class="ask" role="group" aria-label="Permission request">
					<div class="ask-head"><ShieldCheck size={15} />{askTitle}</div>
					<ul>
						{#each pending.asks as a, i (i)}
							<li>{#if a.scope === 'mail.read'}<Mail size={13} />{:else}<Bookmark size={13} />{/if}<span>{a.detail}</span></li>
						{/each}
					</ul>
					{#if mailAsk}<p class="ask-note">Read only: it cannot send, change or delete email, and web search is turned off for the rest of this chat.</p>{/if}
					{#if answering}
						<span class="thinking">{answering === 'deny' ? 'Telling it no…' : 'Working on it…'}</span>
					{:else}
						<div class="ask-btns">
							<button class="btn primary" onclick={() => onanswer?.('once')}>Allow once</button>
							<button class="btn" onclick={() => onanswer?.('chat')} title="Don't ask again in this conversation">Allow in this chat</button>
							<button class="btn ghost" onclick={() => onanswer?.('deny')}>Don't allow</button>
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
	{#if granted.length && onrevoke}
		<div class="grants">
			<ShieldCheck size={12} />Allowed in this chat:
			{#each granted as g (g)}
				<button class="grant" title="Ask me again next time" onclick={() => onrevoke?.(g)}>{SCOPE_LABELS[g] ?? g}<X size={11} /></button>
			{/each}
		</div>
	{/if}
	{#if sending}
		<div class="msg user"><div class="bubble">{pendingText}</div></div>
		<div class="msg bot">
			<span class="avatar spin"><Sparkle size={compact ? 14 : 16} /></span>
			<div class="body"><span class="thinking">Working on it…</span></div>
		</div>
	{/if}
</div>

<style>
	.thread { display: flex; flex-direction: column; gap: 18px; }
	.thread.compact { gap: 14px; font-size: 13.5px; }
	.msg.user { display: flex; justify-content: flex-end; }
	.bubble { max-width: 85%; padding: 8px 13px; border-radius: 14px 14px 4px 14px; background: var(--surface-2); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5; }
	.compact .bubble { padding: 6px 11px; }
	.msg.bot { display: flex; gap: 12px; align-items: flex-start; }
	.compact .msg.bot { gap: 9px; }
	.avatar { flex: none; display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; border: 1px solid var(--border-strong); background: var(--surface); }
	.compact .avatar { width: 24px; height: 24px; border-radius: 7px; }
	.avatar.spin :global(.sparkle) { animation: spin 1.6s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	.body { flex: 1; min-width: 0; padding-top: 3px; }
	.thinking { background: linear-gradient(90deg, var(--text-3), var(--text), var(--text-3)); background-size: 200% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; animation: shimmer 1.8s linear infinite; }
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
	.ask { padding: 10px 12px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--accent) 40%, var(--border)); background: color-mix(in srgb, var(--accent) 6%, var(--surface)); }
	.ask-head { display: flex; align-items: center; gap: 7px; font-weight: 600; }
	.ask-head :global(svg) { color: var(--accent); flex: none; }
	.ask ul { margin: 8px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
	.ask li { display: flex; align-items: flex-start; gap: 7px; color: var(--text-2); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }
	.ask li :global(svg) { flex: none; margin-top: 3px; }
	.ask-note { margin: 8px 0 0; font-size: 12px; color: var(--text-3); line-height: 1.45; }
	.ask-btns { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
	.ask-btns .btn { height: 28px; padding: 0 11px; font-size: 12.5px; }
	.ask .thinking { display: inline-block; margin-top: 10px; }
	.grants { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: -6px; font-size: 11.5px; color: var(--text-3); }
	.grant { display: inline-flex; align-items: center; gap: 3px; padding: 1px 6px 1px 8px; border-radius: 9px; background: var(--hover); color: var(--text-2); font-size: 11.5px; }
	.grant:hover { background: var(--active); color: var(--text); }
	.sources { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 8px; }
	.src { padding: 1px 7px; border-radius: 9px; font-size: 11.5px; color: var(--text-2); text-decoration: none; background: var(--hover); }
	.src:hover { color: var(--text); background: var(--active); }
</style>
