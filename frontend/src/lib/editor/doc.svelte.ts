import { tick } from 'svelte';
import { api, ApiError } from '#lib/api.ts';
import { ui } from '#lib/state/ui.svelte.ts';
import { ws } from '#lib/state/workspace.svelte.ts';
import { prefs } from '#lib/state/prefs.svelte.ts';
import type { Block, BlockType, DocPayload, PropDef, RefInfo } from '#lib/types.ts';
import { escapeHtml, uid } from '#lib/util.ts';
import { CONTINUE_TYPES, LEAF_TYPES, TEXT_TYPES } from './blockTypes';
import { caretOffset, editableOf, htmlTextLength, htmlToText, setCaret } from './dom';

const ROOT = 'root';

export interface Focus {
	id: string;
	pos: number | 'start' | 'end';
}

export interface BlockTree {
	type: BlockType;
	html: string;
	props: Record<string, any>;
	collapsed: boolean;
	children: BlockTree[];
}

type Op =
	| { t: 'patch'; id: string; before: Partial<Block>; after: Partial<Block> }
	| { t: 'insert'; block: Block; parent: string | null; index: number }
	| { t: 'remove'; block: Block; parent: string | null; index: number }
	| { t: 'move'; id: string; from: { parent: string | null; index: number }; to: { parent: string | null; index: number } };

interface Tx {
	ops: Op[];
	before: Focus | null;
	after: Focus | null;
	typing?: string;
	time: number;
}

/** Refresh the display text of references from their current targets. */
export function hydrateRefs(html: string, refs: Record<string, RefInfo>): string {
	if (!html.includes('data-ref')) return html;
	const t = document.createElement('template');
	t.innerHTML = html;
	t.content.querySelectorAll<HTMLAnchorElement>('a[data-ref]').forEach((a) => {
		const key = a.dataset.ref!;
		const info = refs[key];
		a.classList.toggle('broken', !info || !!info.trashed);
		if (!info) return;
		const kind = key.split(':')[0];
		a.textContent = kind === 'tag' ? '#' + info.title : info.title || 'Untitled';
		if (kind === 'tag') {
			if (info.color) a.dataset.c = info.color;
			else delete a.dataset.c;
		}
	});
	return t.innerHTML;
}

export class EditorDoc {
	readonly id: string;
	blocks = $state<Record<string, Block>>({});
	kids = $state<Record<string, string[]>>({ [ROOT]: [] });
	refs = $state<Record<string, RefInfo>>({});
	blockBacklinks = $state<Record<string, number>>({});
	blockCards = $state<Record<string, number>>({});
	blockTasks = $state<DocPayload['block_tasks']>({});
	cardCount = $state(0);
	properties = $state<{ defs: PropDef[]; values: Record<string, any> }>({ defs: [], values: {} });
	backlinkCount = $state(0);
	status = $state<'loading' | 'ready' | 'missing' | 'error'>('loading');
	trashed = $state(false);
	/** The document record from the last load (templates are not in the workspace tree). */
	meta = $state<import('#lib/types.ts').Doc | null>(null);
	isTemplate = $state(false);
	saveState = $state<'saved' | 'dirty' | 'saving' | 'error'>('saved');
	selected = $state<string[]>([]);
	inspectBlock = $state<string | null>(null);
	/** Server content version this copy is based on; protects others' newer edits. */
	version: string | null = null;
	/** Set when the server refused a save because the same blocks changed elsewhere. */
	conflict = $state<{ ids: string[]; theirs: Block[] } | null>(null);
	private pendingChecked = false;
	private forceNext = false;
	/** Bumped whenever content is saved; lets panels refresh derived data. */
	savedSeq = $state(0);

	private dirty = new Set<string>();
	private deleted = new Set<string>();
	private undoStack: Tx[] = [];
	private redoStack: Tx[] = [];
	private tx: Tx | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private flushing: Promise<boolean> | null = null;
	private retry = 0;
	private editSeq = 0;
	private pendingCaret: Focus | null = null;
	selectionAnchor: string | null = null;

	constructor(id: string) {
		this.id = id;
	}

	// ------------------------------------------------------------ loading

	get hasUnsaved() {
		return this.dirty.size > 0 || this.deleted.size > 0 || !!this.flushing;
	}

	async load() {
		const seq = this.editSeq;
		try {
			const p = await api.get<DocPayload>(`/documents/${this.id}`);
			this.refs = p.refs;
			this.blockBacklinks = p.block_backlinks;
			this.blockCards = p.block_cards ?? {};
			this.blockTasks = p.block_tasks ?? {};
			this.cardCount = p.card_count ?? 0;
			this.properties = p.properties;
			this.backlinkCount = p.backlink_count;
			this.trashed = !!p.document.trashed_at;
			this.meta = p.document;
			this.isTemplate = p.document.is_template;
			// Never replace content the user has touched since the request started.
			if (this.status !== 'ready' || (!this.hasUnsaved && seq === this.editSeq)) {
				this.setBlocks(p.blocks);
				this.version = p.version ?? null;
			}
			this.status = 'ready';
			if (!this.pendingChecked) {
				this.pendingChecked = true;
				this.restorePending(p.blocks);
			}
		} catch (e) {
			if (this.status === 'ready') return; // keep showing what we have
			this.status = e instanceof ApiError && e.status === 404 ? 'missing' : 'error';
		}
	}

	private setBlocks(list: Block[]) {
		const blocks: Record<string, Block> = {};
		const kids: Record<string, string[]> = { [ROOT]: [] };
		for (const b of list) {
			blocks[b.id] = { ...b, html: hydrateRefs(b.html, this.refs) };
			kids[b.id] = [];
		}
		for (const b of list) {
			// Orphans (parent missing) surface at the top level rather than vanish.
			const key = b.parent && blocks[b.parent] ? b.parent : ROOT;
			if (key === ROOT) blocks[b.id].parent = null;
			kids[key].push(b.id);
		}
		for (const ids of Object.values(kids)) ids.sort((a, b) => blocks[a].position - blocks[b].position);
		if (this.status === 'ready' && JSON.stringify([blocks, kids]) === JSON.stringify([this.blocks, this.kids])) return;
		this.blocks = blocks;
		this.kids = kids;
		this.undoStack = [];
		this.redoStack = [];
		this.selected = [];
	}

	// --------------------------------------------------------- structure

	private list(parent: string | null): string[] {
		return (this.kids[parent ?? ROOT] ??= []);
	}

	loc(id: string): { parent: string | null; index: number } {
		const parent = this.blocks[id].parent;
		return { parent, index: this.list(parent).indexOf(id) };
	}

	children(id: string | null): string[] {
		return this.kids[id ?? ROOT] ?? [];
	}

	visibleIds(): string[] {
		const out: string[] = [];
		const walk = (key: string) => {
			for (const id of this.kids[key] ?? []) {
				out.push(id);
				if (!this.blocks[id]?.collapsed) walk(id);
			}
		};
		walk(ROOT);
		return out;
	}

	prevVisible(id: string): string | null {
		const v = this.visibleIds();
		const i = v.indexOf(id);
		return i > 0 ? v[i - 1] : null;
	}

	nextVisible(id: string): string | null {
		const v = this.visibleIds();
		const i = v.indexOf(id);
		return i >= 0 && i < v.length - 1 ? v[i + 1] : null;
	}

	isInside(id: string, ancestor: string): boolean {
		let cur: string | null = id;
		while (cur) {
			if (cur === ancestor) return true;
			cur = this.blocks[cur]?.parent ?? null;
		}
		return false;
	}

	/** Drop ids whose ancestor is also in the set; keep document order. */
	topLevel(ids: string[]): string[] {
		const set = new Set(ids);
		const order = new Map(this.allIds().map((id, i) => [id, i]));
		return ids
			.filter((id) => {
				let p = this.blocks[id]?.parent;
				while (p) {
					if (set.has(p)) return false;
					p = this.blocks[p]?.parent ?? null;
				}
				return !!this.blocks[id];
			})
			.sort((a, b) => order.get(a)! - order.get(b)!);
	}

	private allIds(): string[] {
		const out: string[] = [];
		const walk = (key: string) => {
			for (const id of this.kids[key] ?? []) {
				out.push(id);
				walk(id);
			}
		};
		walk(ROOT);
		return out;
	}

	private place(id: string, parent: string | null, index: number) {
		const list = this.list(parent);
		index = Math.max(0, Math.min(index, list.length));
		const prev = index > 0 ? this.blocks[list[index - 1]].position : null;
		const next = index < list.length ? this.blocks[list[index]].position : null;
		const pos =
			prev === null && next === null ? 1
			: prev === null ? next! - 1
			: next === null ? prev + 1
			: (prev + next) / 2;
		list.splice(index, 0, id);
		const b = this.blocks[id];
		b.parent = parent;
		b.position = pos;
		if (prev !== null && next !== null && next - prev < 1e-6) {
			list.forEach((bid, i) => {
				this.blocks[bid].position = i + 1;
				this.dirty.add(bid);
			});
		}
		this.dirty.add(id);
	}

	private unplace(id: string): number {
		const list = this.list(this.blocks[id].parent);
		const i = list.indexOf(id);
		if (i >= 0) list.splice(i, 1);
		return i;
	}

	// ----------------------------------------------------------- history

	private apply(op: Op, forward: boolean) {
		switch (op.t) {
			case 'patch': {
				const b = this.blocks[op.id];
				if (b) {
					Object.assign(b, forward ? op.after : op.before);
					this.dirty.add(op.id);
				}
				break;
			}
			case 'insert':
			case 'remove': {
				const add = (op.t === 'insert') === forward;
				const id = op.block.id;
				if (add) {
					this.blocks[id] = { ...op.block, props: { ...op.block.props } };
					this.kids[id] ??= [];
					this.place(id, op.parent, op.index);
					this.deleted.delete(id);
				} else if (this.blocks[id]) {
					this.unplace(id);
					delete this.blocks[id];
					delete this.kids[id];
					this.dirty.delete(id);
					this.deleted.add(id);
				}
				break;
			}
			case 'move': {
				const dest = forward ? op.to : op.from;
				this.unplace(op.id);
				this.place(op.id, dest.parent, dest.index);
				break;
			}
		}
	}

	private record(op: Op) {
		this.apply(op, true);
		if (this.tx) this.tx.ops.push(op);
		else this.pushTx({ ops: [op], before: null, after: null, time: Date.now() });
	}

	private pushTx(tx: Tx) {
		this.undoStack.push(tx);
		if (this.undoStack.length > 400) this.undoStack.shift();
		this.redoStack = [];
		this.touch();
	}

	/** Group several changes into one undo step. */
	run<T>(fn: () => T): T {
		if (this.tx) return fn();
		const tx: Tx = { ops: [], before: this.captureFocus(), after: null, time: Date.now() };
		this.tx = tx;
		try {
			return fn();
		} finally {
			this.tx = null;
			if (tx.ops.length) this.pushTx(tx);
		}
	}

	private captureFocus(): Focus | null {
		const host = (document.activeElement as HTMLElement | null)?.closest?.<HTMLElement>('[data-block-id]');
		const id = host?.dataset.blockId;
		if (!id || !this.blocks[id]) return null;
		const el = editableOf(id);
		return { id, pos: el && el.contains(document.activeElement) ? caretOffset(el) : 'end' };
	}

	private touch() {
		this.editSeq++;
		this.saveState = 'dirty';
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.flush(), prefs.autosaveDelay || 600);
	}

	get canUndo() {
		return this.undoStack.length > 0;
	}

	undo() {
		const tx = this.undoStack.pop();
		if (!tx) return;
		for (let i = tx.ops.length - 1; i >= 0; i--) this.apply(tx.ops[i], false);
		this.redoStack.push(tx);
		this.afterHistory(tx.before);
	}

	redo() {
		const tx = this.redoStack.pop();
		if (!tx) return;
		for (const op of tx.ops) this.apply(op, true);
		this.undoStack.push(tx);
		this.afterHistory(tx.after);
	}

	private afterHistory(focus: Focus | null) {
		this.selected = [];
		this.touch();
		if (focus && this.blocks[focus.id]) this.focus(focus.id, focus.pos);
	}

	// ------------------------------------------------------------- focus

	/** Move the caret into a block once the DOM has caught up. */
	focus(id: string, pos: number | 'start' | 'end' = 'end') {
		if (this.tx) this.tx.after = { id, pos };
		this.selected = [];
		// Prefer the copy of the block inside the editor that has focus (a block can be embedded).
		const root = (document.activeElement as HTMLElement | null)?.closest?.('[data-editor]') ?? null;
		tick().then(() => {
			const el = editableOf(id, root?.isConnected ? root : null);
			if (el) setCaret(el, pos);
			else this.select([id]);
		});
	}

	select(ids: string[]) {
		this.selected = ids;
		if (ids.length) {
			(document.activeElement as HTMLElement | null)?.blur?.();
			getSelection()?.removeAllRanges();
			tick().then(() => document.querySelector<HTMLElement>(`[data-editor="${this.id}"]`)?.focus({ preventScroll: true }));
		}
	}

	selectRange(a: string, b: string) {
		const v = this.visibleIds();
		let i = v.indexOf(a);
		let j = v.indexOf(b);
		if (i < 0 || j < 0) return;
		if (i > j) [i, j] = [j, i];
		this.select(v.slice(i, j + 1));
	}

	noteCaret(id: string, pos: number) {
		this.pendingCaret = { id, pos };
	}

	// ------------------------------------------------------------ edits

	make(type: BlockType, init: Partial<Block> = {}): Block {
		const props: Record<string, any> = type === 'todo' ? { checked: false } : type === 'callout' ? { icon: '💡' } : {};
		return { id: uid(), parent: null, position: 0, type, html: '', collapsed: false, ...init, props: { ...props, ...init.props } };
	}

	private snap(id: string): Block {
		return $state.snapshot(this.blocks[id]) as Block;
	}

	insert(block: Block, parent: string | null, index: number): string {
		this.record({ t: 'insert', block, parent, index });
		return block.id;
	}

	patch(id: string, after: Partial<Block>) {
		const b = this.blocks[id];
		if (!b) return;
		const before: Partial<Block> = {};
		for (const k of Object.keys(after) as (keyof Block)[]) (before as any)[k] = $state.snapshot(b[k]);
		this.record({ t: 'patch', id, before, after });
	}

	/** Text typed into a block. Consecutive keystrokes fold into one undo step. */
	setHtml(id: string, html: string, caret?: number) {
		const b = this.blocks[id];
		if (!b || b.html === html) return;
		const now = Date.now();
		const last = this.undoStack[this.undoStack.length - 1];
		const after: Focus = { id, pos: caret ?? 'end' };
		if (last && last.typing === id && now - last.time < 1200 && last.ops.length === 1 && last.ops[0].t === 'patch') {
			last.ops[0].after = { html };
			last.time = now;
			last.after = after;
			b.html = html;
			this.dirty.add(id);
			this.redoStack = [];
			this.touch();
			return;
		}
		const before = this.pendingCaret?.id === id ? this.pendingCaret : { id, pos: 'end' as const };
		const prev = b.html;
		b.html = html;
		this.dirty.add(id);
		this.pushTx({ ops: [{ t: 'patch', id, before: { html: prev }, after: { html } }], before, after, typing: id, time: now });
	}

	setProps(id: string, props: Record<string, any>) {
		const b = this.blocks[id];
		if (b) this.patch(id, { props: { ...$state.snapshot(b.props), ...props } });
	}

	toggleCollapsed(id: string, value?: boolean) {
		const b = this.blocks[id];
		if (!b) return;
		b.collapsed = value ?? !b.collapsed;
		this.dirty.add(id);
		this.touch();
	}

	toggleChecked(id: string) {
		const b = this.blocks[id];
		if (b?.type === 'todo') this.setProps(id, { checked: !b.props.checked });
	}

	setType(id: string, type: BlockType) {
		const b = this.blocks[id];
		if (!b || b.type === type) return;
		this.run(() => {
			const patch: Partial<Block> = { type };
			const props = { ...$state.snapshot(b.props) };
			if (type === 'todo') props.checked ??= false;
			if (type === 'callout') props.icon ??= '💡';
			patch.props = props;
			if (type === 'code') patch.html = escapeHtml(htmlToText(b.html));
			else if (b.type === 'code') patch.html = b.html.replace(/\n/g, '<br>');
			else if (!TEXT_TYPES.has(type)) patch.html = '';
			this.patch(id, patch);
			if (LEAF_TYPES.has(type)) {
				// Leaf blocks cannot hold children: lift them out below.
				const { parent, index } = this.loc(id);
				[...this.children(id)].forEach((kid, i) => this.moveTo(kid, parent, index + 1 + i));
			}
		});
	}

	private moveTo(id: string, parent: string | null, index: number) {
		const from = this.loc(id);
		if (from.parent === parent && from.index < index) index--; // index is in the pre-move list
		this.record({ t: 'move', id, from, to: { parent, index } });
	}

	/** Move a block so it sits immediately before `beforeId` (or last) in `parent`. */
	private moveBefore(id: string, parent: string | null, beforeId: string | null) {
		const from = this.loc(id);
		const list = this.list(parent).filter((x) => x !== id);
		const index = beforeId ? Math.max(0, list.indexOf(beforeId)) : list.length;
		if (beforeId && !list.includes(beforeId)) return;
		this.record({ t: 'move', id, from, to: { parent, index } });
	}

	/** Enter: split a block at the caret. */
	split(id: string, head: string, tail: string) {
		const b = this.blocks[id];
		if (!b) return;
		this.run(() => {
			const { parent, index } = this.loc(id);
			const hasKids = this.children(id).length > 0;
			if (!head && !tail && b.type !== 'paragraph' && !hasKids) {
				// Enter on an empty list item leaves the list.
				if (b.parent) this.outdent([id]);
				else this.setType(id, 'paragraph');
				this.focus(id, 'start');
				return;
			}
			const next: BlockType = CONTINUE_TYPES.has(b.type) ? b.type : (prefs.defaultBlock as BlockType) || 'paragraph';
			if (!head && tail) {
				// Caret at the start: open a blank line above, keep this block intact.
				if (b.html !== tail) this.patch(id, { html: tail });
				this.insert(this.make(next), parent, index);
				this.focus(id, 'start');
				return;
			}
			if (b.html !== head) this.patch(id, { html: head });
			const openParent = !b.collapsed && (hasKids || b.type === 'toggle');
			const nb = this.make(openParent && b.type === 'toggle' ? 'paragraph' : next, { html: tail });
			if (openParent) this.insert(nb, id, 0);
			else this.insert(nb, parent, index + 1);
			this.focus(nb.id, 'start');
		});
	}

	/** Backspace at the start of a block. Returns false if nothing happened. */
	mergeBack(id: string): boolean {
		const b = this.blocks[id];
		if (!b) return false;
		if (b.type !== 'paragraph') {
			this.run(() => {
				this.setType(id, 'paragraph');
				this.focus(id, 'start');
			});
			return true;
		}
		const prevId = this.prevVisible(id);
		if (!prevId) return false;
		const prev = this.blocks[prevId];
		if (!TEXT_TYPES.has(prev.type)) {
			if (!b.html && !this.children(id).length) this.run(() => this.removeTree(id));
			this.select([prevId]);
			return true;
		}
		this.run(() => {
			const offset = htmlTextLength(prev.html);
			const { parent, index } = this.loc(id);
			[...this.children(id)].forEach((kid, i) => this.moveTo(kid, parent, index + 1 + i));
			this.patch(prevId, { html: prev.html + b.html });
			this.removeTree(id);
			this.focus(prevId, offset);
		});
		return true;
	}

	/** Delete at the end of a block: pull the next block's text in. */
	mergeForward(id: string): boolean {
		const b = this.blocks[id];
		const nextId = this.nextVisible(id);
		if (!b || !nextId) return false;
		const next = this.blocks[nextId];
		if (!TEXT_TYPES.has(next.type)) {
			this.select([nextId]);
			return true;
		}
		this.run(() => {
			const offset = htmlTextLength(b.html);
			const { parent, index } = this.loc(nextId);
			[...this.children(nextId)].forEach((kid, i) => this.moveTo(kid, parent, index + 1 + i));
			this.patch(id, { html: b.html + next.html });
			this.removeTree(nextId);
			this.focus(id, offset);
		});
		return true;
	}

	private removeTree(id: string) {
		for (const kid of [...this.children(id)].reverse()) this.removeTree(kid);
		const { parent, index } = this.loc(id);
		this.record({ t: 'remove', block: this.snap(id), parent, index });
	}

	remove(ids: string[]) {
		const tops = this.topLevel(ids);
		if (!tops.length) return;
		this.run(() => {
			const v = this.visibleIds();
			const before = v[v.indexOf(tops[0]) - 1] ?? null;
			for (const id of tops) this.removeTree(id);
			this.selected = [];
			if (!this.children(null).length) {
				const id = this.insert(this.make('paragraph'), null, 0);
				this.focus(id, 'start');
			} else if (before && this.blocks[before]) this.focus(before, 'end');
			else this.focus(this.children(null)[0], 'start');
		});
	}

	insertAfter(id: string, type: BlockType, init: Partial<Block> = {}): string {
		const { parent, index } = this.loc(id);
		return this.insert(this.make(type, init), parent, index + 1);
	}

	append(type: BlockType = 'paragraph', init: Partial<Block> = {}): string {
		return this.insert(this.make(type, init), null, this.children(null).length);
	}

	indent(ids: string[]) {
		this.run(() => {
			for (const id of this.topLevel(ids)) {
				const { parent, index } = this.loc(id);
				if (index === 0) continue;
				const target = this.list(parent)[index - 1];
				if (LEAF_TYPES.has(this.blocks[target].type)) continue;
				if (this.blocks[target].collapsed) this.toggleCollapsed(target, false);
				this.moveTo(id, target, this.children(target).length);
			}
		});
	}

	outdent(ids: string[]) {
		this.run(() => {
			for (const id of this.topLevel(ids).reverse()) {
				const p = this.blocks[id].parent;
				if (!p) continue;
				const up = this.loc(p);
				this.moveTo(id, up.parent, up.index + 1);
			}
		});
	}

	moveVertically(ids: string[], dir: -1 | 1) {
		const tops = this.topLevel(ids);
		if (!tops.length) return;
		const parent = this.blocks[tops[0]].parent;
		if (tops.some((id) => this.blocks[id].parent !== parent)) return;
		const list = this.list(parent);
		const first = list.indexOf(tops[0]);
		const last = list.indexOf(tops[tops.length - 1]);
		this.run(() => {
			if (dir < 0 && first > 0) this.moveTo(list[first - 1], parent, last + 1);
			else if (dir > 0 && last < list.length - 1) this.moveTo(list[last + 1], parent, first);
		});
	}

	/** Drag and drop. */
	moveBlocks(ids: string[], target: string, where: 'before' | 'after' | 'inside') {
		const tops = this.topLevel(ids);
		if (!tops.length || tops.some((id) => this.isInside(target, id))) return;
		this.run(() => {
			const set = new Set(tops);
			if (where === 'inside') {
				if (this.blocks[target].collapsed) this.toggleCollapsed(target, false);
				const first = this.children(target).find((x) => !set.has(x)) ?? null;
				for (const id of tops) this.moveBefore(id, target, first);
			} else {
				const parent = this.blocks[target].parent;
				const list = this.list(parent);
				const anchor =
					where === 'before' ? target : (list.slice(list.indexOf(target) + 1).find((x) => !set.has(x)) ?? null);
				for (const id of tops) this.moveBefore(id, parent, anchor);
			}
		});
	}

	exportTrees(ids: string[]): BlockTree[] {
		const build = (id: string): BlockTree => {
			const b = this.snap(id);
			return { type: b.type, html: b.html, props: b.props, collapsed: b.collapsed, children: this.children(id).map(build) };
		};
		return this.topLevel(ids).map(build);
	}

	/** Insert trees (paste, duplicate) starting at parent/index. Returns the new top-level ids. */
	insertTrees(trees: BlockTree[], parent: string | null, index: number): string[] {
		const out: string[] = [];
		this.run(() => {
			const add = (t: BlockTree, p: string | null, i: number): string => {
				const id = this.insert(this.make(t.type, { html: t.html, props: t.props, collapsed: t.collapsed }), p, i);
				t.children.forEach((c, ci) => add(c, id, ci));
				return id;
			};
			trees.forEach((t, i) => out.push(add(t, parent, index + i)));
		});
		return out;
	}

	duplicate(ids: string[]) {
		const tops = this.topLevel(ids);
		if (!tops.length) return;
		this.run(() => {
			const lastTop = tops[tops.length - 1];
			const { parent, index } = this.loc(lastTop);
			const created = this.insertTrees(this.exportTrees(tops), parent, index + 1);
			if (this.selected.length) this.selected = created;
			else this.focus(created[created.length - 1], 'end');
		});
	}

	// -------------------------------------------------------------- sync

	async flush(keepalive = false): Promise<boolean> {
		clearTimeout(this.timer);
		if (this.flushing) {
			await this.flushing;
			if (!this.dirty.size && !this.deleted.size) return this.saveState === 'saved';
		}
		if (!this.dirty.size && !this.deleted.size) {
			if (this.saveState !== 'error') this.saveState = 'saved';
			return true;
		}
		const upIds = [...this.dirty];
		const delIds = [...this.deleted];
		this.dirty.clear();
		this.deleted.clear();
		const upserts = upIds
			.filter((id) => this.blocks[id])
			.map((id) => {
				const b = $state.snapshot(this.blocks[id]) as Block;
				return { id: b.id, parent: b.parent, position: b.position, type: b.type, html: b.html, props: b.props, collapsed: b.collapsed };
			});
		this.saveState = 'saving';
		this.flushing = (async () => {
			try {
				const force = this.forceNext;
				this.forceNext = false;
				const res = await api.post<{ updated_at: string; version?: string; patched?: Block[]; block_cards?: Record<string, number> }>(
					`/documents/${this.id}/blocks/sync`,
					{ upserts, deletes: delIds, base: this.version, force },
					keepalive ? { keepalive: true } : undefined
				);
				if (res?.version) this.version = res.version;
				this.conflict = null;
				if (!this.dirty.size && !this.deleted.size) clearPending(this.id);
				if (ws.offline) ws.offline = false;
				const w = ws.docs[this.id];
				if (w && res?.updated_at) w.updated_at = res.updated_at;
				if (w?.empty && upserts.some((b) => b.html.replace(/<[^>]*>|&nbsp;/g, '').trim() || !['paragraph', 'bullet', 'numbered', 'todo', 'quote'].includes(b.type))) w.empty = false;
				if (res?.block_cards) {
					const before = this.cardCount;
					this.blockCards = res.block_cards;
					this.cardCount = Object.values(res.block_cards).reduce((a, b) => a + b, 0);
					if (before !== this.cardCount) import('#lib/learn/util.svelte.ts').then((m) => m.counts.refresh());
				}
				// The server can change a block (a recurring task un-ticks itself).
				for (const b of res?.patched ?? []) {
					const mine = this.blocks[b.id];
					if (mine && !this.dirty.has(b.id)) mine.props = b.props;
				}
				if (upserts.some((u) => u.type === 'todo' && u.props?.task)) this.refreshTasks();
				this.retry = 0;
				this.savedSeq++;
				return true;
			} catch (e) {
				for (const id of upIds) if (this.blocks[id]) this.dirty.add(id);
				for (const id of delIds) if (!this.blocks[id]) this.deleted.add(id);
				this.saveState = 'error';
				const status = e instanceof ApiError ? e.status : 0;
				if (status === 409) {
					this.conflict = { ids: (e as ApiError).data?.conflict ?? [], theirs: (e as ApiError).data?.blocks ?? [] };
					this.persistPending();
				} else if (status === 0 || status >= 502) {
					// Offline (or the server is down behind the proxy): keep the edits on this device and keep trying.
					this.persistPending();
					ws.offline = true;
					this.retry = Math.min(this.retry + 1, 5);
					clearTimeout(this.timer);
					this.timer = setTimeout(() => this.flush(), 1500 * 2 ** this.retry);
				} else if (status >= 400 && status < 500) {
					// The server rejected the change; retrying the same payload will not help.
					ui.toast(`Changes could not be saved: ${(e as Error).message}`, { kind: 'error' });
				} else {
					this.retry = Math.min(this.retry + 1, 5);
					clearTimeout(this.timer);
					this.timer = setTimeout(() => this.flush(), 1500 * 2 ** this.retry);
				}
				return false;
			} finally {
				this.flushing = null;
			}
		})();
		const ok = await this.flushing;
		if (ok) {
			if (this.dirty.size || this.deleted.size) {
				this.saveState = 'dirty';
				this.timer = setTimeout(() => this.flush(), 300);
			} else this.saveState = 'saved';
		}
		return ok;
	}

	// ---------------------------------------------------- offline and conflicts

	/** Write unsaved changes to this device so they survive a reload or going offline. */
	persistPending() {
		const prev = readPending(this.id);
		const ids = new Set([...this.dirty, ...(prev?.upserts.map((b) => b.id) ?? [])]);
		const upserts = [...ids].filter((id) => this.blocks[id]).map((id) => $state.snapshot(this.blocks[id]) as Block);
		const deletes = [...new Set([...this.deleted, ...(prev?.deletes ?? [])])].filter((id) => !this.blocks[id]);
		if (!upserts.length && !deletes.length) return clearPending(this.id);
		writePending(this.id, { base: prev?.base ?? this.version, upserts, deletes, saved_at: new Date().toISOString() });
	}

	/** Re-apply edits left on this device (offline, or a closed tab) on top of the server copy. */
	private restorePending(server: Block[]) {
		const pending = readPending(this.id);
		if (!pending) return;
		const byId = new Map(server.map((b) => [b.id, b]));
		const same = (a: Block, b: Block | undefined) =>
			!!b && a.html === b.html && a.type === b.type && a.parent === b.parent && a.position === b.position &&
			a.collapsed === b.collapsed && JSON.stringify(a.props ?? {}) === JSON.stringify(b.props ?? {});
		const upserts = pending.upserts.filter((b) => !same(b, byId.get(b.id)));
		const deletes = pending.deletes.filter((id) => byId.has(id));
		if (!upserts.length && !deletes.length) return clearPending(this.id);
		const gone = new Set(deletes);
		const merged = new Map(server.filter((b) => !gone.has(b.id)).map((b) => [b.id, b]));
		for (const b of upserts) merged.set(b.id, b);
		this.setBlocks([...merged.values()]);
		this.version = pending.base ?? this.version;
		for (const b of upserts) this.dirty.add(b.id);
		for (const id of deletes) this.deleted.add(id);
		this.saveState = 'dirty';
		ui.toast(`Recovered ${upserts.length + deletes.length} unsaved ${upserts.length + deletes.length === 1 ? 'change' : 'changes'} from this device`);
		this.flush();
	}

	async resolveConflict(choice: 'mine' | 'theirs' | 'copy') {
		if (choice === 'mine') {
			this.forceNext = true;
			this.conflict = null;
			await this.flush();
			return;
		}
		if (choice === 'copy') {
			try {
				const title = (ws.docs[this.id]?.title || this.meta?.title || 'Untitled') + ' (my offline version)';
				const copy = await api.post<{ id: string }>('/documents', { title, parent: ws.docs[this.id]?.parent ?? null });
				const ids = new Map(Object.keys(this.blocks).map((id) => [id, uid()]));
				const upserts = Object.values($state.snapshot(this.blocks) as Record<string, Block>).map((b) => ({
					...b, id: ids.get(b.id)!, parent: b.parent ? (ids.get(b.parent) ?? null) : null,
					props: { ...b.props, task: undefined }
				}));
				await api.post(`/documents/${copy.id}/blocks/sync`, { upserts, deletes: [] });
				await ws.load();
				ui.toast('Your version was saved as a separate page', { action: { label: 'Open', run: () => import('$app/navigation').then((m) => m.goto(`/doc/${copy.id}`)) } });
			} catch (e) {
				ui.error(e);
				return;
			}
		}
		this.dirty.clear();
		this.deleted.clear();
		clearPending(this.id);
		this.conflict = null;
		this.saveState = 'saved';
		this.status = 'loading';
		await this.load();
	}

	async refreshTasks() {
		try {
			const p = await api.get<DocPayload>(`/documents/${this.id}`);
			this.blockTasks = p.block_tasks ?? {};
		} catch {
			/* keep */
		}
		const { counts } = await import('#lib/learn/util.svelte.ts');
		counts.refresh();
	}
}

// ------------------------------------------------------------ device storage

interface Pending {
	base: string | null;
	upserts: Block[];
	deletes: string[];
	saved_at: string;
}
const PENDING = 'kern:pending:';

function readPending(id: string): Pending | null {
	try {
		const raw = localStorage.getItem(PENDING + id);
		return raw ? (JSON.parse(raw) as Pending) : null;
	} catch {
		return null;
	}
}

function writePending(id: string, p: Pending) {
	try {
		localStorage.setItem(PENDING + id, JSON.stringify(p));
	} catch {
		/* storage full or blocked: edits stay in memory */
	}
}

function clearPending(id: string) {
	try {
		localStorage.removeItem(PENDING + id);
	} catch {
		/* ignore */
	}
}

/** Documents with edits stored on this device. */
export function pendingDocIds(): string[] {
	try {
		return Object.keys(localStorage).filter((k) => k.startsWith(PENDING)).map((k) => k.slice(PENDING.length));
	} catch {
		return [];
	}
}

// ---------------------------------------------------------------- registry

const cache = new Map<string, EditorDoc>();

/** Open documents stay in memory, so switching tabs never drops unsaved edits. */
export function getDoc(id: string): EditorDoc {
	let doc = cache.get(id);
	if (!doc) {
		doc = new EditorDoc(id);
		cache.set(id, doc);
		doc.load();
	} else if (!doc.hasUnsaved) doc.load();
	return doc;
}

/** Reload a document that changed on the server, if it is open here and has no unsaved edits. */
export function refreshDoc(id: string) {
	const doc = cache.get(id);
	if (doc && !doc.hasUnsaved) doc.load();
}

export async function releaseDoc(id: string, keep = false) {
	const doc = cache.get(id);
	if (!doc) return;
	await doc.flush();
	if (!keep) cache.delete(id);
}

export function flushAll(keepalive = false) {
	for (const doc of cache.values())
		if (doc.hasUnsaved) {
			if (keepalive) doc.persistPending(); // in case the page closes before the request lands
			doc.flush(keepalive);
		}
}

/** Load (and so save) every document that has edits waiting on this device. */
export function syncPending() {
	for (const id of pendingDocIds()) getDoc(id);
	flushAll();
}

export function anyUnsaved(): boolean {
	for (const doc of cache.values()) if (doc.hasUnsaved || doc.saveState === 'error') return true;
	return false;
}
