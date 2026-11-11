<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount, tick } from 'svelte';
	import StaticBlocks from '../components/StaticBlocks.svelte';
	import type { BlockTree } from '../editor/doc.svelte.ts';
	import { textToTrees } from '../editor/paste.ts';
	import type { Block } from '../types.ts';
	import { uid } from '../util.ts';
	import { ai } from './ai.svelte.ts';
	import Sparkle from './Sparkle.svelte';

	let { docId, selection = '', rect, onclose, oninsert }: {
		docId: string; selection?: string; rect: DOMRect; onclose: () => void;
		oninsert: (trees: BlockTree[], replace: boolean) => void;
	} = $props();

	let prompt = $state('');
	let busy = $state(false);
	let result = $state<string | null>(null);
	let lastPrompt = '';
	let input = $state<HTMLInputElement>();
	let el = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });
	let sel = $state(0);

	const actions = $derived([
		...(selection ? [['Improve writing', 'Rewrite the current block so it reads more clearly. Keep the meaning.'], ['Expand on this', 'Expand the current block into a few well-structured paragraphs or bullets.']] : []),
		['Continue writing', 'Continue writing the page from where it ends, in the same style.'],
		['Summarize this page', 'Summarize this page in a few bullet points.'],
		['Make flashcards from this page', 'Write flashcards for the key facts on this page. Put each card on its own line as "Question :: Answer". No headings, no numbering.'],
		['Outline', 'Write an outline for this topic as nested bullets.'],
		['Brainstorm ideas', 'Brainstorm a list of ideas related to this page.'],
		['Action items', 'List the action items in this page as "- [ ] " to-dos.']
	] as [string, string][]);

	onMount(async () => {
		await ai.load();
		await tick();
		input?.focus();
	});

	$effect(() => {
		void result;
		void busy;
		if (!el) return;
		const r = el.getBoundingClientRect();
		const below = rect.bottom + 6;
		pos = {
			x: Math.max(8, Math.min(rect.left, innerWidth - r.width - 8)),
			y: below + r.height > innerHeight - 8 ? Math.max(8, rect.top - r.height - 6) : below
		};
	});

	async function run(p: string) {
		if (!p.trim() || busy) return;
		lastPrompt = p;
		busy = true;
		result = null;
		const r = await ai.run<{ markdown: string }>('/ai/write', { prompt: p, doc: docId, selection });
		busy = false;
		if (r) result = r.markdown;
		await tick();
		input?.focus(); // it was disabled while waiting, which drops focus
	}

	let trees = $derived(result ? textToTrees(result) : []);
	let preview = $derived.by(() => {
		const out: Block[] = [];
		const add = (t: BlockTree, parent: string | null, i: number) => {
			const id = uid();
			out.push({ id, parent, position: i, type: t.type, html: t.html, props: t.props, collapsed: false });
			t.children.forEach((c, j) => add(c, id, j));
		};
		trees.forEach((t, i) => add(t, null, i));
		return out;
	});

	let filtered = $derived(prompt.trim() ? actions.filter(([l]) => l.toLowerCase().includes(prompt.toLowerCase())) : actions);

	function key(e: KeyboardEvent) {
		e.stopPropagation();
		if (e.key === 'Escape') return onclose();
		if (result !== null) {
			if (e.key === 'Enter') { e.preventDefault(); oninsert(trees, false); }
			return;
		}
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			const n = filtered.length;
			if (n) sel = (sel + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			// A typed request wins unless it is just filtering the quick actions.
			if (filtered.length && (!prompt.trim() || filtered.length < actions.length)) run(filtered[sel]?.[1] ?? prompt);
			else run(prompt);
		}
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="backdrop" onmousedown={() => !busy && onclose()}></div>
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="aip popover" bind:this={el} style:left="{pos.x}px" style:top="{pos.y}px" onkeydown={key} data-editor-skip>
	{#if ai.config && !ai.config.configured}
		<div class="setup">
			<Sparkle size={18} />
			<span>The AI assistant isn't set up yet.</span>
			<button class="btn primary" onclick={() => { onclose(); goto('/settings?s=ai'); }}>Set up AI</button>
		</div>
	{:else}
		<div class="bar">
			<Sparkle size={16} />
			<input bind:this={input} bind:value={prompt} placeholder={result !== null ? 'Ask for changes…' : 'Ask AI to write, summarize, brainstorm…'}
				disabled={busy} oninput={() => (sel = 0)}
				onkeydown={(e) => { if (result !== null && e.key === 'Enter' && prompt.trim()) { e.preventDefault(); e.stopPropagation(); run(`${lastPrompt}\n\nThen revise it: ${prompt}`); prompt = ''; } }} />
			{#if busy}<span class="dots" aria-label="Thinking"><i></i><i></i><i></i></span>{/if}
		</div>
		{#if result !== null}
			<div class="result"><StaticBlocks blocks={preview} /></div>
			<div class="acts">
				<button class="btn primary" onclick={() => oninsert(trees, false)}>Insert <kbd>↵</kbd></button>
				{#if selection}<button class="btn" onclick={() => oninsert(trees, true)}>Replace block</button>{/if}
				<button class="btn ghost" onclick={() => run(lastPrompt)}>Try again</button>
				<span class="grow"></span>
				<button class="btn ghost" onclick={onclose}>Discard</button>
			</div>
		{:else if !busy}
			<div class="list">
				{#each filtered as [label, p], i (label)}
					<!-- svelte-ignore a11y_mouse_events_have_key_events -->
					<button class="menu-item" class:active={i === sel} onmousemove={() => (sel = i)} onclick={() => run(p)}>{label}</button>
				{/each}
				{#if prompt.trim()}<button class="menu-item ask" onclick={() => run(prompt)}>Ask: “{prompt.trim()}”</button>{/if}
			</div>
			<div class="foot faint">Uses {ai.config?.model || 'your model'} · this page is sent as context</div>
		{/if}
	{/if}
</div>

<style>
	.backdrop { position: fixed; inset: 0; z-index: 597; }
	.aip { position: fixed; z-index: 598; width: min(520px, calc(100vw - 16px)); padding: 6px; display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: 13.5px; }
	.bar { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 8px; border-radius: var(--radius); background: color-mix(in srgb, var(--accent) 7%, var(--bg)); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 35%, var(--border)); }
	.bar input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font-size: 14px; }
	.list { max-height: 260px; overflow-y: auto; }
	.ask { color: var(--accent); }
	.result { max-height: 46vh; overflow-y: auto; padding: 8px 10px; border-radius: var(--radius); background: var(--bg); border: 1px solid var(--border); }
	.acts { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.acts kbd { margin-left: 4px; border-color: rgba(0, 0, 0, 0.25); background: none; color: inherit; }
	.grow { flex: 1; }
	.foot { padding: 2px 6px; font-size: 11.5px; }
	.setup { display: flex; align-items: center; gap: 10px; padding: 6px 8px; }
	.setup span { flex: 1; }
	.dots { display: flex; gap: 3px; }
	.dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); animation: blink 1s infinite ease-in-out; }
	.dots i:nth-child(2) { animation-delay: 0.15s; }
	.dots i:nth-child(3) { animation-delay: 0.3s; }
	@keyframes blink { 0%, 80%, 100% { opacity: 0.2; } 40% { opacity: 1; } }
</style>
