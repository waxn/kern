<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '../api.ts';
	import CardFace from '../learn/CardFace.svelte';
	import { counts } from '../learn/util.svelte.ts';
	import { ui } from '../state/ui.svelte.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { Deck } from '../types.ts';
	import { escapeHtml } from '../util.ts';
	import { ai } from './ai.svelte.ts';
	import Sparkle from './Sparkle.svelte';

	interface Gen { kind: 'basic' | 'cloze' | 'concept'; front: string; back: string; keep: boolean }
	let { doc = null, onclose, onsaved }: { doc?: string | null; onclose: () => void; onsaved?: () => void } = $props();

	let prompt = $state('');
	// svelte-ignore state_referenced_locally
	let source = $state<string>(doc ?? '');
	let count = $state(10);
	let busy = $state(false);
	let cards = $state<Gen[]>([]);
	let deck = $state('none');
	let decks = $state<Deck[]>([]);

	onMount(() => {
		api.get<Deck[]>('/decks').then((d) => (decks = d.filter((x) => x.id !== 'none'))).catch(() => {});
	});

	let pages = $derived(Object.values(ws.docs).filter((d) => !d.database).sort((a, b) => (a.title || '').localeCompare(b.title || '')));

	async function generate() {
		if (!prompt.trim() && !source) return ui.toast('Describe a topic, paste text, or choose a page.');
		busy = true;
		const r = await ai.run<{ cards: Omit<Gen, 'keep'>[]; truncated: boolean }>('/ai/cards', { prompt, doc: source || null, count });
		busy = false;
		if (!r) return;
		cards = r.cards.map((c) => ({ ...c, keep: true }));
		if (r.truncated) ui.toast('The page was very long; only the first part was used.');
	}

	async function save() {
		const keep = cards.filter((c) => c.keep);
		if (!keep.length) return;
		busy = true;
		let n = 0;
		for (const c of keep) {
			try {
				await api.post('/notes', { kind: c.kind, front: escapeHtml(c.front), back: escapeHtml(c.back), deck, document: source || null });
				n++;
			} catch (e) {
				ui.error(e);
			}
		}
		busy = false;
		counts.refresh();
		ui.toast(`Added ${n} ${n === 1 ? 'card' : 'cards'}`);
		onsaved?.();
		onclose();
	}

	const preview = (c: Gen) => (c.kind === 'cloze' ? escapeHtml(c.front).replace(/\{\{(.+?)\}\}/g, '<span class="cloze shown">$1</span>') : escapeHtml(c.front));
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && !busy && onclose()} onkeydown={(e) => e.key === 'Escape' && !busy && onclose()}>
	<div class="dialog popover" role="dialog" aria-label="Generate flashcards">
		<h2><Sparkle size={18} />Generate flashcards</h2>
		{#if !cards.length}
			<textarea class="input" rows="5" bind:value={prompt} placeholder="A topic (“the Krebs cycle”), what to focus on, or paste text to learn from…"
				onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(); }}></textarea>
			<div class="row">
				<label>From page
					<select class="input" bind:value={source}>
						<option value="">No page</option>
						{#each pages as p (p.id)}<option value={p.id}>{p.icon} {p.title || 'Untitled'}</option>{/each}
					</select>
				</label>
				<label>About <input class="input num" type="number" min="1" max="50" bind:value={count} /> cards</label>
			</div>
			<p class="faint small">The prompt{source ? ' and the chosen page' : ''} are sent to {ai.config?.providers[ai.config.provider]?.label ?? 'your AI provider'}.</p>
			<div class="foot">
				<button class="btn ghost" onclick={onclose}>Cancel</button>
				<button class="btn primary" disabled={busy} onclick={generate}>{busy ? 'Thinking…' : 'Generate'}</button>
			</div>
		{:else}
			<p class="faint small">Untick any card you don't want. You can edit cards later in the card browser.</p>
			<div class="list">
				{#each cards as c, i (i)}
					<label class="card" class:off={!c.keep}>
						<input type="checkbox" bind:checked={c.keep} />
						<span class="kind faint">{c.kind}</span>
						<span class="body"><CardFace html={preview(c)} size="small" />{#if c.back}<span class="back">{c.back}</span>{/if}</span>
					</label>
				{/each}
			</div>
			<div class="foot">
				<label class="deck">Deck
					<select class="input" bind:value={deck}>
						<option value="none">Default</option>
						{#each decks as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
					</select>
				</label>
				<span class="grow"></span>
				<button class="btn ghost" disabled={busy} onclick={() => (cards = [])}>Back</button>
				<button class="btn primary" disabled={busy || !cards.some((c) => c.keep)} onclick={save}>Add {cards.filter((c) => c.keep).length} cards</button>
			</div>
		{/if}
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); animation: fade 0.12s; }
	.dialog { width: min(620px, 100%); max-height: calc(100vh - 32px); overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 10px; }
	h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 16px; }
	textarea { width: 100%; resize: vertical; font: inherit; }
	.row { display: flex; gap: 14px; flex-wrap: wrap; }
	.row label, .deck { display: flex; align-items: center; gap: 6px; color: var(--text-2); }
	.row select { max-width: 260px; }
	.num { width: 64px; }
	.small { margin: 0; font-size: 12.5px; }
	.list { display: flex; flex-direction: column; gap: 6px; }
	.card { display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer; }
	.card.off { opacity: 0.45; }
	.card input { margin-top: 3px; accent-color: var(--accent); }
	.kind { width: 56px; flex: none; font-size: 11.5px; padding-top: 2px; }
	.body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
	.back { color: var(--text-2); font-size: 13px; }
	.foot { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding-top: 10px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.grow { flex: 1; }
</style>
