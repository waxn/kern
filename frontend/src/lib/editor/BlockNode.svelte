<script lang="ts">
	import { Check, ChevronRight, GripVertical, Layers, Plus, Repeat } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';
	import { fmtDue, localDate, PRIORITY_COLOR } from '#lib/learn/util.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { Card, Note } from '#lib/types.ts';
	import EmojiPicker from '#lib/components/EmojiPicker.svelte';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { MEDIA_TYPES, PLACEHOLDERS, TEXT_TYPES } from './blockTypes';
	import BookmarkBlock from './blocks/BookmarkBlock.svelte';
	import CodeBlock from './blocks/CodeBlock.svelte';
	import DatabaseBlock from './blocks/DatabaseBlock.svelte';
	import EmbedBlock from './blocks/EmbedBlock.svelte';
	import EquationBlock from './blocks/EquationBlock.svelte';
	import MediaBlock from './blocks/MediaBlock.svelte';
	import TableBlock from './blocks/TableBlock.svelte';
	import { getEditor } from './context';
	import { readHtml, renderMath } from './dom';
	import Self from './BlockNode.svelte';

	let { id, index }: { id: string; index: number } = $props();
	const ed = getEditor();
	const doc = ed.doc;

	let b = $derived(doc.blocks[id]);
	let kids = $derived(doc.kids[id] ?? []);
	let selected = $derived(doc.selected.includes(id));
	let refCount = $derived(doc.blockBacklinks[id] ?? 0);
	let cardCount = $derived(doc.blockCards[id] ?? 0);
	let task = $derived(b?.type === 'todo' && b.props.task ? doc.blockTasks[id] : undefined);

	async function openCards() {
		try {
			const r = await api.get<{ cards: Card[] }>(`/cards?block=${id}`);
			if (!r.cards.length) return;
			ui.cardEditor = { note: await api.get<Note>(`/notes/${r.cards[0].note}`) };
		} catch (e) {
			ui.error(e);
		}
	}
	let picker = $state<{ x: number; y: number } | null>(null);

	let number = $derived.by(() => {
		if (b?.type !== 'numbered') return 0;
		const list = doc.children(b.parent);
		let n = 1;
		for (let i = index - 1; i >= 0 && doc.blocks[list[i]]?.type === 'numbered'; i--) n++;
		return n;
	});

	// Keeps the DOM in step with stored HTML without disturbing the caret while typing.
	function content(node: HTMLElement, value: string) {
		const set = (v: string) => {
			node.innerHTML = v;
			renderMath(node);
		};
		set(value);
		return {
			update(v: string) {
				if (readHtml(node) !== v) set(v);
			}
		};
	}

	function addBelow() {
		const nid = doc.run(() => (kids.length && !b.collapsed ? doc.insert(doc.make('paragraph'), id, 0) : doc.insertAfter(id, 'paragraph')));
		doc.focus(nid, 'start');
	}
</script>

{#if b}
	<div class="block t-{b.type}" class:selected class:checked={b.type === 'todo' && b.props.checked} data-block-id={id}>
		<div class="row">
			<div class="gutter" contenteditable="false">
				<button class="g" title="Add block below" tabindex="-1" onclick={addBelow}><Plus size={14} /></button>
				<button class="g grip" title="Drag to move · click for menu" tabindex="-1" draggable="true"
					ondragstart={(e) => ed.startDrag(id, e)} onclick={(e) => ed.blockMenu(e.currentTarget, id)}>
					<GripVertical size={14} />
				</button>
			</div>
			{#if kids.length && b.type !== 'toggle' && b.type !== 'synced'}
				<button class="fold" class:open={!b.collapsed} contenteditable="false" tabindex="-1"
					title={b.collapsed ? 'Expand' : 'Collapse'} onclick={() => doc.toggleCollapsed(id)}>
					<ChevronRight size={12} />
				</button>
			{/if}

			{#if b.type === 'bullet'}
				<span class="marker" contenteditable="false"><span class="dot"></span></span>
			{:else if b.type === 'numbered'}
				<span class="marker num" contenteditable="false">{number}.</span>
			{:else if b.type === 'todo'}
				<span class="marker" contenteditable="false">
					<button class="box" role="checkbox" aria-checked={!!b.props.checked} tabindex="-1" onclick={() => doc.toggleChecked(id)}>
						{#if b.props.checked}<Check size={11} strokeWidth={3.2} />{/if}
					</button>
				</span>
			{:else if b.type === 'toggle'}
				<span class="marker" contenteditable="false">
					<button class="tog" class:open={!b.collapsed} tabindex="-1" title={b.collapsed ? 'Expand' : 'Collapse'} onclick={() => doc.toggleCollapsed(id)}>
						<ChevronRight size={14} />
					</button>
				</span>
			{:else if b.type === 'callout'}
				<span class="marker" contenteditable="false">
					<button class="emoji" tabindex="-1" title="Change icon" onclick={(e) => { const r = e.currentTarget.getBoundingClientRect(); picker = { x: r.left, y: r.bottom + 4 }; }}>
						{b.props.icon || '💡'}
					</button>
				</span>
			{/if}

			{#if TEXT_TYPES.has(b.type)}
				<div class="content rt" class:blank={!b.html} data-editable contenteditable="true" spellcheck="true"
					role="textbox" tabindex="0" aria-multiline="true"
					data-placeholder={PLACEHOLDERS[b.type] ?? "Type '/' for commands"} use:content={b.html}></div>
			{:else if b.type === 'divider'}
				<div class="divider" contenteditable="false"><hr /></div>
			{:else if b.type === 'code'}
				<CodeBlock block={b} />
			{:else if b.type === 'equation'}
				<EquationBlock block={b} />
			{:else if b.type === 'table'}
				<TableBlock block={b} />
			{:else if b.type === 'bookmark'}
				<BookmarkBlock block={b} />
			{:else if MEDIA_TYPES.has(b.type)}
				<MediaBlock block={b} />
			{:else if b.type === 'embed'}
				<EmbedBlock block={b} />
			{:else if b.type === 'database'}
				<DatabaseBlock block={b} />
			{:else if b.type === 'synced'}
				<div class="synced-head" contenteditable="false">
					<span>Synced block</span>
					{#if refCount}<span class="faint">· {refCount} {refCount === 1 ? 'reference' : 'references'}</span>{/if}
					<span class="faint">· use the block menu to copy a synced reference</span>
				</div>
			{/if}

			{#if task && (task.due || task.priority || task.recurrence)}
				<button class="taskchip" contenteditable="false" class:overdue={task.due && task.due < localDate() && !b.props.checked}
					data-c={PRIORITY_COLOR[task.priority] || undefined} title="Open task" onclick={() => goto(`/tasks?view=open&task=${task.id}`)}>
					{#if task.recurrence}<Repeat size={10} />{/if}{task.due ? fmtDue(task.due) : ''}{#if task.priority}<i></i>{/if}
				</button>
			{/if}
			{#if cardCount}
				<button class="cards" contenteditable="false" title="{cardCount} {cardCount === 1 ? 'flashcard' : 'flashcards'} — click to view" onclick={openCards}>
					<Layers size={10} />{cardCount}
				</button>
			{/if}
			{#if refCount}
				<button class="refs" contenteditable="false" title="{refCount} {refCount === 1 ? 'reference' : 'references'} to this block"
					onclick={() => { doc.inspectBlock = id; prefs.panelOpen = true; }}>{refCount}</button>
			{/if}
		</div>

		{#if b.type === 'synced'}
			<div class="kids synced-body">
				{#each kids as kid, i (kid)}<Self id={kid} index={i} />{/each}
				{#if !kids.length}
					<button class="hollow" onclick={() => doc.focus(doc.insert(doc.make('paragraph'), id, 0), 'start')}>Empty synced block — click to write</button>
				{/if}
			</div>
		{:else if kids.length && !b.collapsed}
			<div class="kids">
				{#each kids as kid, i (kid)}<Self id={kid} index={i} />{/each}
			</div>
		{:else if b.type === 'toggle' && !b.collapsed}
			<button class="hollow" onclick={() => doc.focus(doc.insert(doc.make('paragraph'), id, 0), 'start')}>Empty toggle — click to add content</button>
		{/if}
	</div>

	{#if picker}
		<EmojiPicker x={picker.x} y={picker.y} onclose={() => (picker = null)}
			onpick={(e) => { doc.setProps(id, { icon: e || '💡' }); picker = null; }} />
	{/if}
{/if}

<style>
	.block { position: relative; }
	.row { position: relative; display: flex; align-items: flex-start; border-radius: var(--radius-sm); padding: var(--block-gap) 0; }
	.selected > .row { background: color-mix(in srgb, var(--accent) 16%, transparent); }
	:global(.flash) > .row { animation: flash 1.6s var(--ease); }
	@keyframes flash { 0%, 40% { background: color-mix(in srgb, var(--accent) 28%, transparent); } }

	.gutter { position: absolute; left: -62px; top: var(--block-gap); height: var(--lh); display: flex; align-items: center; opacity: 0; transition: opacity 0.1s; user-select: none; }
	.row:hover > .gutter { opacity: 1; }
	.g { width: 20px; height: 22px; display: grid; place-items: center; border-radius: 3px; color: var(--text-3); }
	.g:hover { background: var(--hover); color: var(--text); }
	.grip { cursor: grab; }

	.fold { position: absolute; left: -20px; top: var(--block-gap); width: 18px; height: var(--lh); display: grid; place-items: center; color: var(--text-3); opacity: 0; border-radius: 3px; user-select: none; }
	.row:hover > .fold, .fold:not(.open) { opacity: 1; }
	.fold:hover { color: var(--text); }
	.fold :global(svg), .tog :global(svg) { transition: transform 0.12s var(--ease); }
	.fold.open :global(svg), .tog.open :global(svg) { transform: rotate(90deg); }

	.block { --lh: calc(var(--editor-size) * 1.6); }
	.marker { flex: none; width: 24px; height: var(--lh); display: grid; place-items: center; user-select: none; color: var(--text-2); }
	.dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
	.num { width: auto; min-width: 24px; padding-right: 5px; justify-content: end; font-variant-numeric: tabular-nums; }
	.box { width: 15px; height: 15px; display: grid; place-items: center; border: 1.5px solid var(--text-3); border-radius: 3.5px; color: #17130c; transition: background 0.1s, border-color 0.1s; }
	.box:hover { border-color: var(--accent); }
	.box[aria-checked='true'] { background: var(--accent); border-color: var(--accent); }
	.tog { width: 20px; height: 20px; display: grid; place-items: center; border-radius: 3px; color: var(--text-2); }
	.tog:hover { background: var(--hover); }
	.emoji { font-size: 16px; line-height: 1; border-radius: 3px; width: 24px; height: 24px; }
	.emoji:hover { background: var(--hover); }

	.content { flex: 1; min-width: 0; min-height: var(--lh); line-height: 1.6; outline: none; white-space: pre-wrap; padding: 0 2px; cursor: text; }
	.content { position: relative; }
	.content.blank::before { content: attr(data-placeholder); position: absolute; left: 2px; top: 0; color: var(--text-3); pointer-events: none; white-space: nowrap; }
	.t-paragraph > .row > .content.blank:not(:focus)::before { content: ''; }

	.t-h1 { --lh: 36px; margin-top: 18px; }
	.t-h2 { --lh: 30px; margin-top: 14px; }
	.t-h3 { --lh: 27px; margin-top: 8px; }
	.t-h1 > .row > .content { font-size: 25px; font-weight: 680; letter-spacing: -0.015em; line-height: 36px; }
	.t-h2 > .row > .content { font-size: 20px; font-weight: 650; letter-spacing: -0.01em; line-height: 30px; }
	.t-h3 > .row > .content { font-size: 16.5px; font-weight: 640; line-height: 27px; }
	.block:first-child { margin-top: 0; }

	.t-quote > .row { margin: 3px 0; }
	.t-quote > .row > .content { border-left: 3px solid var(--text-3); padding-left: 12px; color: var(--text-2); font-style: italic; }
	.t-callout > .row { margin: 4px 0; padding: 10px 12px 10px 8px; background: var(--surface-2); border-radius: var(--radius); gap: 4px; }
	.t-callout > .row > .gutter { left: -62px; }
	.checked > .row > .content { color: var(--text-3); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--text-3) 70%, transparent); }

	.divider { flex: 1; height: 21px; display: flex; align-items: center; cursor: default; }
	.divider hr { width: 100%; border: 0; border-top: 1px solid var(--border-strong); margin: 0; }

	.refs { flex: none; align-self: flex-start; margin: calc((var(--lh) - 17px) / 2) 0 0 6px; min-width: 18px; height: 17px; padding: 0 5px; border-radius: 9px; font-size: 11px; font-weight: 600; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); user-select: none; }
	.refs:hover { background: color-mix(in srgb, var(--accent) 28%, transparent); }
	.cards, .taskchip { flex: none; align-self: flex-start; display: inline-flex; align-items: center; gap: 3px; margin: calc((var(--lh) - 18px) / 2) 0 0 6px; height: 18px; padding: 0 6px; border-radius: 9px; font: 600 11px var(--font-sans); user-select: none; }
	.cards { color: var(--c-purple); background: color-mix(in srgb, var(--c-purple) 15%, transparent); }
	.cards:hover { background: color-mix(in srgb, var(--c-purple) 28%, transparent); }
	.taskchip { color: var(--text-2); background: var(--surface-2); font-weight: 500; }
	.taskchip i { width: 6px; height: 6px; border-radius: 50%; background: var(--chip); }
	.taskchip.overdue { color: var(--danger); }

	.kids { margin-left: 24px; }
	.synced-head { flex: 1; display: flex; gap: 4px; align-items: center; height: 22px; font-size: 11.5px; color: var(--c-orange); user-select: none; font-family: var(--font-sans); }
	.synced-head span:last-child { opacity: 0; transition: opacity 0.12s; }
	.row:hover > .synced-head span:last-child { opacity: 1; }
	.kids.synced-body { margin-left: 0; padding: 2px 6px 2px 8px; border: 1px solid color-mix(in srgb, var(--c-orange) 45%, transparent); border-radius: var(--radius); }
	.hollow { margin-left: 26px; padding: 2px 4px; color: var(--text-3); border-radius: 3px; }
	.hollow:hover { background: var(--hover); }

	@media (hover: none) {
		.gutter { left: -26px; }
		.gutter .g:first-child { display: none; }
		.row:focus-within > .gutter { opacity: 1; }
	}
</style>
