<script lang="ts">
	import { ArrowUpRight, Braces } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '../api.ts';
	import { open } from '../state/tabs.ts';
	import { ui } from '../state/ui.svelte.ts';
	import type { CardKind, Deck, Note } from '../types.ts';
	import CardFace from './CardFace.svelte';
	import OcclusionEditor from './OcclusionEditor.svelte';
	import RichField from './RichField.svelte';
	import { counts } from './util.svelte.ts';

	const st = ui.cardEditor!;
	const existing = st.note;
	let kind = $state<CardKind>(existing?.kind ?? st.init?.kind ?? 'basic');
	let front = $state(existing?.front ?? st.init?.front ?? '');
	let back = $state(existing?.back ?? st.init?.back ?? '');
	let image = $state(existing?.image ?? '');
	let regions = $state(structuredClone($state.snapshot(existing?.regions ?? [])));
	let deck = $state<string>(existing?.deck ?? st.init?.deck ?? 'none');
	let decks = $state<Deck[]>([]);
	let busy = $state(false);
	let another = $state(false);
	let frontField = $state<RichField>();
	const locked = !!existing?.auto;

	onMount(() => {
		api.get<Deck[]>('/decks').then((d) => (decks = d.filter((x) => x.id !== 'none'))).catch(() => {});
	});

	const kinds: [CardKind, string, string][] = [
		['basic', 'Basic', 'Question and answer'],
		['cloze', 'Cloze', 'Hide words in a sentence'],
		['concept', 'Concept', 'Term ⇄ definition, both ways'],
		['occlusion', 'Image occlusion', 'Hide parts of an image']
	];

	async function newDeck() {
		const name = prompt('New deck name')?.trim();
		if (!name) return;
		try {
			const d = await api.post<Deck>('/decks', { name });
			decks = [...decks, d];
			deck = d.id;
		} catch (e) {
			ui.error(e);
		}
	}

	function close() {
		ui.cardEditor = null;
	}

	async function save() {
		busy = true;
		try {
			const body: Record<string, any> = { deck };
			if (!locked) Object.assign(body, { kind, front, back, image, regions: $state.snapshot(regions) });
			if (existing) await api.patch(`/notes/${existing.id}`, body);
			else await api.post('/notes', { ...body, document: st.init?.document ?? null, block: st.init?.block ?? null });
			st.onsaved?.();
			counts.refresh();
			if (another && !existing) {
				front = '';
				back = '';
				image = '';
				regions = [];
				ui.toast('Card added');
			} else close();
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	let gaps = $derived((front.match(/\{\{/g) ?? []).length);
	let previewFront = $derived(kind === 'cloze' ? front.replace(/\{\{(?:c\d+::)?(.+?)(?:::(.+?))?\}\}/, (_m, _a, h) => `<span class="cloze">[${h ?? '…'}]</span>`).replace(/\{\{(?:c\d+::)?(.+?)(?:::.+?)?\}\}/g, '$1') : front);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && close()} onkeydown={(e) => { if (e.key === 'Escape') close(); if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) save(); }}>
	<div class="dialog popover" role="dialog" aria-label="Flashcard">
		<div class="head">
			<h2>{existing ? 'Edit flashcard' : 'New flashcard'}</h2>
			{#if existing?.document}
				<a class="src" href="/doc/{existing.document}{existing.block ? '#' + existing.block : ''}"
					onclick={(e) => { e.preventDefault(); close(); open(`/doc/${existing.document}${existing.block ? '#' + existing.block : ''}`, e); }}>
					From {existing.doc_title || 'Untitled'} <ArrowUpRight size={12} />
				</a>
			{/if}
		</div>

		{#if locked}
			<p class="note">This card comes from a block written with <code>::</code>, <code>;;</code> or <code>{'{{cloze}}'}</code>. Edit its text in the page; here you can change its deck.</p>
			<div class="preview"><CardFace html={existing!.front} size="small" /><hr /><CardFace html={existing!.back || existing!.front} size="small" /></div>
		{:else}
			<div class="kinds">
				{#each kinds as [k, label, hint] (k)}
					<button class:on={kind === k} title={hint} onclick={() => (kind = k)}>{label}</button>
				{/each}
			</div>

			{#if kind === 'cloze'}
				<div class="lbl">Text <span class="faint">— wrap answers in {'{{double braces}}'}; add a hint with {'{{answer::hint}}'}</span></div>
				<RichField bind:this={frontField} bind:value={front} cloze autofocus placeholder={'The capital of France is {{Paris}}.'} minRows={3} />
				<div class="row">
					<button class="btn" onclick={() => frontField?.makeCloze()} title="Ctrl+Shift+C"><Braces size={13} />Make selection a gap</button>
					<span class="faint small">{gaps} {gaps === 1 ? 'gap' : 'gaps'} → {gaps} {gaps === 1 ? 'card' : 'cards'}</span>
				</div>
				<div class="lbl">Extra <span class="faint">(shown with the answer)</span></div>
				<RichField bind:value={back} minRows={1} />
			{:else if kind === 'occlusion'}
				<OcclusionEditor bind:image bind:regions />
				<div class="lbl">Note <span class="faint">(optional, shown below the image)</span></div>
				<RichField bind:value={front} minRows={1} />
			{:else}
				<div class="lbl">{kind === 'concept' ? 'Term' : 'Front'}</div>
				<RichField bind:value={front} autofocus placeholder={kind === 'concept' ? 'Osmosis' : 'What is the powerhouse of the cell?'} />
				<div class="lbl">{kind === 'concept' ? 'Definition' : 'Back'}</div>
				<RichField bind:value={back} placeholder={kind === 'concept' ? 'Movement of water across a membrane' : 'The mitochondrion'} />
				{#if kind === 'concept'}<p class="faint small">Makes two cards: term → definition and definition → term.</p>{/if}
			{/if}

			{#if kind !== 'occlusion' && front}
				<div class="lbl">Preview</div>
				<div class="preview"><CardFace html={previewFront} size="small" /></div>
			{/if}
		{/if}

		<div class="foot">
			<label class="deck">Deck
				<select class="input" bind:value={deck}>
					<option value="none">Default</option>
					{#each decks as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
				</select>
			</label>
			<button class="btn ghost" onclick={newDeck}>New deck…</button>
			<span class="grow"></span>
			{#if !existing}<label class="check"><input type="checkbox" bind:checked={another} />Add another</label>{/if}
			<button class="btn ghost" onclick={close}>Cancel</button>
			<button class="btn primary" disabled={busy} onclick={save}>{existing ? 'Save' : 'Add card'} <kbd>Ctrl ↵</kbd></button>
		</div>
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); animation: fade 0.12s; }
	.dialog { width: min(640px, 100%); max-height: calc(100vh - 32px); overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 8px; }
	.head { display: flex; align-items: baseline; gap: 12px; }
	h2 { margin: 0; font-size: 16px; font-weight: 650; }
	.src { display: inline-flex; align-items: center; gap: 3px; color: var(--text-3); font-size: 12.5px; text-decoration: none; }
	.src:hover { color: var(--accent); }
	.kinds { display: flex; gap: 2px; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.kinds button { flex: 1; padding: 5px 8px; border-radius: 4px; color: var(--text-2); }
	.kinds button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.lbl { margin-top: 4px; font-size: 12px; font-weight: 600; color: var(--text-2); }
	.row { display: flex; align-items: center; gap: 10px; }
	.small { font-size: 12px; }
	.preview { padding: 12px 14px; border-radius: var(--radius); background: var(--surface-2); }
	.preview hr { border: 0; border-top: 1px solid var(--border-strong); margin: 10px 0; }
	.note { margin: 0; color: var(--text-2); font-size: 13px; }
	.note code { font-family: var(--font-mono); background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
	.foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.deck { display: flex; align-items: center; gap: 6px; color: var(--text-2); }
	.grow { flex: 1; }
	.check { display: flex; align-items: center; gap: 5px; color: var(--text-2); font-size: 12.5px; }
	.check input { accent-color: var(--accent); }
	.foot kbd { margin-left: 4px; border-color: rgba(0, 0, 0, 0.25); background: transparent; color: inherit; opacity: 0.7; }
</style>
