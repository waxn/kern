<script lang="ts">
	import { CircleCheck, Copy, FilePlus, FileText, Hash, Layers, Link2, ListTree, Repeat, Text, Trash2 } from '@lucide/svelte';
	import { counts } from '#lib/learn/util.svelte.ts';
	import { tick } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui, type MenuItem } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { BlockType, Suggestion } from '#lib/types.ts';
	import { escapeHtml, mod } from '#lib/util.ts';
	import BlockNode from './BlockNode.svelte';
	import { BLOCK_SPECS, LEAF_TYPES, TEXT_TYPES, TURN_INTO, type BlockSpec } from './blockTypes';
	import { setEditor } from './context';
	import type { BlockTree, EditorDoc } from './doc.svelte';
	import {
		applyWrap, blockIdOf, htmlToText, caretOffset, caretRect, editableOf, insertHtml, insertText, isAtEnd, isAtStart,
		mathHtml, notifyInput, onFirstLine, onLastLine, rangeForOffsets, readHtml, refHtml, renderMath,
		selectionOffsets, setCaret, setCaretNearX, splitAtCaret, toggleWrap
	} from './dom';
	import FormatToolbar from './FormatToolbar.svelte';
	import AiInline from '#lib/ai/AiInline.svelte';
	import { htmlToTrees, textToTrees, treesToText } from './paste';
	import SuggestMenu, { type MenuEntry } from './SuggestMenu.svelte';

	let { doc, onexit, rootId = null }: { doc: EditorDoc; onexit?: () => void; rootId?: string | null } = $props();

	const KERN_MIME = 'application/x-kern-blocks';
	let root = $state<HTMLElement>();
	let toolbar = $state<FormatToolbar>();
	const fresh = $state<{ id: string | null }>({ id: null });

	type MenuKind = 'slash' | 'ref' | 'tag' | 'blockref';
	let menu = $state<{ kind: MenuKind; id: string; query: string; len: number; rect: DOMRect; index: number; items: MenuEntry[]; data: any[] } | null>(null);
	let math = $state<{ x: number; y: number; tex: string; span: HTMLElement | null; id: string; range: Range | null } | null>(null);
	let mathInput = $state<HTMLInputElement>();
	let indicator = $state<{ top: number; left: number; width: number } | null>(null);

	let dragIds: string[] = [];
	let dropTarget: { id: string; where: 'before' | 'after' | 'inside' } | null = null;
	let dragFrom: string | null = null;
	let crossSelecting = false;
	let selFocus: string | null = null;
	let suggestSeq = 0;

	setEditor({
		get doc() { return doc; },
		fresh,
		startDrag,
		blockMenu,
		uploadInto
	});

	/** Events from nested editors (embeds) or embedded widgets are theirs, not ours. */
	const mine = (e: Event) => (e.target as HTMLElement | null)?.closest?.('[data-editor], [data-editor-skip]') === root;
	const editableFrom = (t: EventTarget | null) => (t as HTMLElement | null)?.closest?.<HTMLElement>('[data-editable]') ?? null;
	const collapsed = () => !!getSelection()?.isCollapsed;

	// ------------------------------------------------------------ typing

	const SHORTCUTS: Record<string, BlockType> = {
		'#': 'h1', '##': 'h2', '###': 'h3', '-': 'bullet', '*': 'bullet', '1.': 'numbered',
		'[]': 'todo', '[ ]': 'todo', '>': 'toggle', '"': 'quote'
	};

	function onBeforeInput(e: Event) {
		if (!mine(e)) return;
		const el = editableFrom(e.target);
		const id = el && blockIdOf(el);
		if (el && id) doc.noteCaret(id, caretOffset(el));
	}

	function onInput(e: Event) {
		if (!mine(e)) return;
		const el = editableFrom(e.target);
		const id = el && blockIdOf(el);
		if (!el || !id || !doc.blocks[id]) return;
		if (el.dataset.plain !== undefined) {
			doc.setHtml(id, escapeHtml(el.innerText.replace(/\n$/, '')), caretOffset(el));
			return;
		}
		renderMath(el);
		doc.setHtml(id, readHtml(el), caretOffset(el));
		const ie = e as InputEvent;
		if (ie.inputType === 'insertText' && markdownShortcut(el, id, ie.data)) {
			menu = null;
			return;
		}
		detectTrigger(el, id);
	}

	function markdownShortcut(el: HTMLElement, id: string, data: string | null): boolean {
		const b = doc.blocks[id];
		if (!b || b.type !== 'paragraph' || !data) return false;
		const off = caretOffset(el);
		const before = (el.textContent ?? '').slice(0, off).replace(/ /g, ' ');
		let type: BlockType | undefined;
		if (data === ' ' && before.endsWith(' ')) type = SHORTCUTS[before.slice(0, -1)];
		else if (data === '`' && before === '```') type = 'code';
		else if (data === '-' && before === '---' && el.textContent === '---') type = 'divider';
		if (!type) return false;
		rangeForOffsets(el, 0, off).deleteContents();
		const html = readHtml(el);
		const t = type;
		doc.run(() => {
			doc.patch(id, { html });
			doc.setType(id, t);
			if (t === 'divider') doc.focus(doc.insertAfter(id, 'paragraph'), 'start');
			else doc.focus(id, 'start');
		});
		return true;
	}

	// ------------------------------------------------------------- menus

	function detectTrigger(el: HTMLElement, id: string) {
		const sel = getSelection();
		const node = sel?.anchorNode;
		if (!sel || !sel.isCollapsed || !node || node.nodeType !== Node.TEXT_NODE) return (menu = null);
		const before = node.textContent!.slice(0, sel.anchorOffset);
		let m: RegExpExecArray | null;
		let kind: MenuKind;
		let len: number;
		if ((m = /\[\[([^\[\]]{0,60})$/.exec(before))) [kind, len] = ['ref', m[1].length + 2];
		else if ((m = /\(\(([^()]{0,60})$/.exec(before))) [kind, len] = ['blockref', m[1].length + 2];
		else if ((m = /(?:^|\s)\/([\w ]{0,24})$/.exec(before))) [kind, len] = ['slash', m[1].length + 1];
		else if ((m = /(?:^|\s)#([\p{L}\d_-]{1,40})$/u.exec(before))) [kind, len] = ['tag', m[1].length + 1];
		else return (menu = null);
		const query = m[1];
		const rect = caretRect() ?? el.getBoundingClientRect();
		if (kind === 'slash' && query === ' ') {
			// "/" then space: ask the AI assistant.
			menu = null;
			const off = caretOffset(el);
			rangeForOffsets(el, Math.max(0, off - 2), off).deleteContents();
			doc.setHtml(id, readHtml(el));
			openAi(id, rect);
			return;
		}
		const same = menu && menu.kind === kind && menu.id === id;
		const next = { kind, id, query, len, rect, index: same ? menu!.index : 0, items: same ? menu!.items : [], data: same ? menu!.data : [] };
		if (kind === 'slash') {
			const s = query.toLowerCase().replace(/\s+/g, '');
			const specs = BLOCK_SPECS.filter(
				(sp) => !s || sp.label.toLowerCase().replace(/\s+/g, '').includes(s) || sp.keywords.split(' ').some((k) => k.startsWith(s))
			);
			if (!specs.length) return (menu = null);
			next.items = specs.map((sp) => ({ key: sp.label, label: sp.label, sub: sp.hint, icon: sp.icon, group: sp.group, hint: sp.shortcut }));
			next.data = specs;
		} else if (kind === 'ref') {
			const q = query.trim().toLowerCase();
			const docs = Object.values(ws.docs)
				.filter((d) => d.id !== doc.id && (d.title || 'Untitled').toLowerCase().includes(q))
				.sort((a, b) => {
					const as = a.title.toLowerCase().startsWith(q) ? 0 : 1;
					const bs = b.title.toLowerCase().startsWith(q) ? 0 : 1;
					return as - bs || (b.last_opened_at ?? '').localeCompare(a.last_opened_at ?? '');
				})
				.slice(0, 8);
			next.items = docs.map((d) => ({
				key: d.id, label: d.title || 'Untitled', emoji: d.icon || undefined, icon: FileText,
				sub: ws.path(d.id).map((p) => p.title || 'Untitled').join(' / ') || undefined, group: 'Link to page'
			}));
			next.data = [...docs];
			if (q && !docs.some((d) => d.title.toLowerCase() === q)) {
				next.items.push({ key: 'create', label: `Create page “${query.trim()}”`, icon: FilePlus, group: 'New' });
				next.data.push({ create: true });
			}
		} else if (kind === 'tag') {
			const q = query.toLowerCase();
			const tags = ws.tags.filter((t) => t.name.toLowerCase().includes(q)).slice(0, 8);
			next.items = tags.map((t) => ({ key: t.id, label: t.name, icon: Hash, color: t.color, group: 'Tag' }));
			next.data = [...tags];
			if (!tags.some((t) => t.name.toLowerCase() === q)) {
				next.items.push({ key: 'create', label: `Create tag “${query}”`, icon: Hash, group: 'New' });
				next.data.push({ create: true });
			}
		} else loadBlockSuggestions(query);
		next.index = Math.min(next.index, Math.max(0, next.items.length - 1));
		menu = next;
	}

	async function loadBlockSuggestions(query: string) {
		const mine = ++suggestSeq;
		let res: Suggestion[] = [];
		if (query.trim()) {
			try {
				res = await api.get<Suggestion[]>('/suggest' + qs({ q: query, kinds: 'block', limit: 8 }));
			} catch {
				/* offline: no suggestions */
			}
		}
		if (mine !== suggestSeq || !menu || menu.kind !== 'blockref') return;
		menu.items = res.map((r) => ({ key: r.id, label: r.title || '(empty block)', sub: r.doc_title || 'Untitled', icon: Text, group: 'Reference a block' }));
		menu.data = res;
		menu.index = 0;
	}

	function menuKeys(e: KeyboardEvent): boolean {
		if (!menu) return false;
		const n = menu.items.length;
		if (e.key === 'Escape') {
			e.preventDefault();
			menu = null;
			return true;
		}
		if (!n) return false;
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			menu.index = (menu.index + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
			return true;
		}
		if (e.key === 'Enter' || e.key === 'Tab') {
			e.preventDefault();
			choose(menu.index);
			return true;
		}
		return false;
	}

	async function choose(i: number) {
		const m = menu;
		const item = m?.data[i];
		if (!m || !item) return;
		menu = null;
		const el = editableOf(m.id, root);
		if (!el) return;
		const off = caretOffset(el);
		const start = Math.max(0, off - m.len);
		const r = rangeForOffsets(el, start, off);
		r.deleteContents();
		r.collapse(true);
		const sel = getSelection()!;
		sel.removeAllRanges();
		sel.addRange(r);
		if (m.kind === 'slash') return applySpec(m.id, el, item as BlockSpec);
		let html = '';
		try {
			if (m.kind === 'ref') {
				const d = item.create ? await ws.createDoc({ title: m.query.trim() }) : item;
				doc.refs[`doc:${d.id}`] = { title: d.title, icon: d.icon };
				html = refHtml('doc', d.id, d.title, `/doc/${d.id}`);
			} else if (m.kind === 'tag') {
				const t = item.create ? await ws.createTag(m.query) : item;
				doc.refs[`tag:${t.id}`] = { title: t.name, color: t.color };
				html = refHtml('tag', t.id, t.name, `/tag/${t.id}`, t.color);
			} else {
				doc.refs[`block:${item.id}`] = { title: item.title, doc: item.doc, doc_title: item.doc_title };
				html = refHtml('block', item.id, item.title || 'block', `/doc/${item.doc}#${item.id}`);
			}
		} catch (e) {
			ui.error(e);
		}
		if (item.create) setCaret(el, start);
		if (html) insertHtml(html + ' ');
		else doc.setHtml(m.id, readHtml(el));
	}

	function applySpec(id: string, el: HTMLElement, spec: BlockSpec) {
		const html = readHtml(el);
		doc.setHtml(id, html, caretOffset(el));
		if (spec.inline === 'math') return openMath(id, null);
		if (spec.ai) return openAi(id, caretRect() ?? el.getBoundingClientRect());
		const type = spec.type;
		doc.run(() => {
			if (TEXT_TYPES.has(type) || type === 'code') {
				if (!html) {
					doc.setType(id, type);
					doc.focus(id, 'start');
				} else doc.focus(doc.insertAfter(id, type), 'start');
				return;
			}
			let target = id;
			if (type === 'synced') {
				const sid = !html && !doc.children(id).length ? (doc.setType(id, 'synced'), id) : doc.insertAfter(id, 'synced');
				doc.focus(doc.insert(doc.make('paragraph'), sid, 0), 'start');
				return;
			}
			if (!html && !doc.children(id).length) doc.setType(id, type);
			else target = doc.insertAfter(id, type);
			if (spec.props) doc.setProps(target, spec.props);
			if (type === 'table') doc.setProps(target, { rows: [['', '', ''], ['', '', ''], ['', '', '']], header: true });
			// Keep a text block underneath so writing can continue.
			const { parent, index } = doc.loc(target);
			const nextId = doc.children(parent)[index + 1];
			const after = nextId && TEXT_TYPES.has(doc.blocks[nextId].type) ? nextId : doc.insertAfter(target, 'paragraph');
			if (type === 'divider') doc.focus(after, 'start');
			else fresh.id = target;
		});
	}

	// ---------------------------------------------------------------- AI

	let aiAt = $state<{ id: string; rect: DOMRect; selection: string } | null>(null);

	function openAi(id: string, rect: DOMRect) {
		aiAt = { id, rect, selection: htmlToText(doc.blocks[id]?.html ?? '').trim() };
	}

	async function insertAi(trees: BlockTree[], replace: boolean) {
		const at = aiAt;
		aiAt = null;
		if (!at || !trees.length || !doc.blocks[at.id]) return;
		const b = doc.blocks[at.id];
		doc.run(() => {
			const { parent, index } = doc.loc(at.id);
			const ids = doc.insertTrees(trees, parent, index + 1);
			if (replace || (b.type === 'paragraph' && !b.html && !doc.children(at.id).length)) doc.remove([at.id]);
			const last = ids[ids.length - 1];
			if (last) doc.focus(last, 'end');
		});
	}

	// -------------------------------------------------------------- math

	async function openMath(id: string, span: HTMLElement | null) {
		const sel = getSelection();
		const rect = span?.getBoundingClientRect() ?? caretRect();
		if (!rect) return;
		math = {
			x: rect.left, y: rect.bottom + 6, tex: span?.dataset.math ?? '', span, id,
			range: sel?.rangeCount ? sel.getRangeAt(0).cloneRange() : null
		};
		await tick();
		mathInput?.focus();
	}

	function saveMath() {
		const m = math;
		if (!m) return;
		math = null;
		const el = editableOf(m.id, root);
		if (!el) return;
		const tex = m.tex.trim();
		if (m.span) {
			if (tex) {
				m.span.dataset.math = tex;
				delete m.span.dataset.rendered;
				renderMath(el);
			} else m.span.remove();
			notifyInput(el);
			return;
		}
		el.focus();
		if (m.range) {
			const sel = getSelection()!;
			sel.removeAllRanges();
			sel.addRange(m.range);
		}
		if (tex) {
			insertHtml(mathHtml(tex) + ' ');
			renderMath(el);
		}
	}

	// ---------------------------------------------------------- keyboard

	function onKeydown(e: KeyboardEvent) {
		if (!mine(e)) return;
		if (e.isComposing) return;
		const target = e.target as HTMLElement;
		const el = editableFrom(target);
		if (!el) {
			if (target === root) selectionKeys(e);
			return;
		}
		const id = blockIdOf(el);
		if (!id || !doc.blocks[id]) return;
		if (menu && menuKeys(e)) return;
		const plain = el.dataset.plain !== undefined;
		const k = e.key;
		const lk = k.toLowerCase();
		const pd = () => e.preventDefault();
		const vertical = k === 'ArrowUp' ? -1 : k === 'ArrowDown' ? 1 : 0;

		if ((mod(e) || e.altKey) && e.shiftKey && vertical) {
			pd();
			const off = caretOffset(el);
			doc.moveVertically([id], vertical as -1 | 1);
			doc.focus(id, off);
			return;
		}
		if (mod(e) && !e.altKey) {
			if (lk === 'z') return pd(), e.shiftKey ? doc.redo() : doc.undo();
			if (lk === 'y') return pd(), doc.redo();
			if (lk === 'd') return pd(), doc.duplicate([id]);
			if (k === 'Enter') {
				pd();
				const b = doc.blocks[id];
				if (b.type === 'todo') doc.toggleChecked(id);
				else if (plain) doc.focus(doc.insertAfter(id, 'paragraph'), 'start');
				else if (doc.children(id).length || b.type === 'toggle') doc.toggleCollapsed(id);
				return;
			}
			if (lk === 'a') {
				const s = selectionOffsets(el);
				const len = el.textContent?.length ?? 0;
				if (!len || (s && s.start === 0 && s.end >= len)) {
					pd();
					doc.select(doc.visibleIds());
				}
				return;
			}
			if (plain) return;
			if (lk === 'b') return pd(), void document.execCommand('bold');
			if (lk === 'i') return pd(), void document.execCommand('italic');
			if (lk === 'u') return pd(), void document.execCommand('underline');
			if (lk === 's' && e.shiftKey) return pd(), void document.execCommand('strikeThrough');
			if (lk === 'e') return pd(), toggleWrap(el, 'code');
			if (lk === 'h' && e.shiftKey) return pd(), applyWrap(el, 'mark', 'data-bg', 'yellow');
			if (lk === 'k' && !collapsed()) return pd(), e.stopPropagation(), toolbar?.link();
			if (lk === 'c' && e.shiftKey && !collapsed()) return pd(), insertText(`{{${getSelection()!.toString()}}}`);
			return;
		}

		switch (k) {
			case 'Tab': {
				pd();
				if (plain) return insertText('\t');
				const off = caretOffset(el);
				if (e.shiftKey) doc.outdent([id]);
				else doc.indent([id]);
				doc.focus(id, off);
				return;
			}
			case 'Enter': {
				if (plain || e.shiftKey) return;
				pd();
				const b = doc.blocks[id];
				if (collapsed() && isAtStart(el) && b.html) doc.split(id, '', b.html);
				else {
					const { head, tail } = splitAtCaret(el);
					doc.split(id, head, tail);
				}
				return;
			}
			case 'Backspace':
				if (!collapsed() || !isAtStart(el)) return;
				if (plain) {
					if (!el.textContent) {
						pd();
						doc.run(() => { doc.setType(id, 'paragraph'); doc.focus(id, 'start'); });
					}
					return;
				}
				pd();
				doc.mergeBack(id);
				return;
			case 'Delete':
				if (plain || !collapsed() || !isAtEnd(el)) return;
				pd();
				doc.mergeForward(id);
				return;
			case 'ArrowUp':
			case 'ArrowDown': {
				if (e.altKey || !(vertical < 0 ? onFirstLine(el) : onLastLine(el))) return;
				const other = vertical < 0 ? doc.prevVisible(id) : doc.nextVisible(id);
				if (e.shiftKey) {
					pd();
					doc.selectionAnchor = id;
					selFocus = other ?? id;
					doc.selectRange(id, selFocus);
					return;
				}
				if (!other) {
					if (vertical < 0) pd(), onexit?.();
					return;
				}
				pd();
				const t = editableOf(other, root);
				if (t) setCaretNearX(t, caretRect()?.left ?? 0, vertical < 0 ? 'bottom' : 'top');
				else selectOne(other);
				return;
			}
			case 'ArrowLeft':
			case 'ArrowRight': {
				if (e.shiftKey || !collapsed()) return;
				const left = k === 'ArrowLeft';
				if (left ? !isAtStart(el) : !isAtEnd(el)) return;
				const other = left ? doc.prevVisible(id) : doc.nextVisible(id);
				if (!other) return;
				pd();
				if (editableOf(other, root)) doc.focus(other, left ? 'end' : 'start');
				else selectOne(other);
				return;
			}
			case 'Escape':
				pd();
				selectOne(id);
				return;
			case 't':
			case 'T':
				if (e.altKey && !mod(e)) {
					pd();
					makeTask(id);
				}
		}
	}

	function selectOne(id: string) {
		doc.selectionAnchor = selFocus = id;
		doc.select([id]);
	}

	/** Keys while whole blocks are selected (focus sits on the editor root). */
	function selectionKeys(e: KeyboardEvent) {
		const sel = doc.selected;
		if (!sel.length) return;
		const k = e.key;
		const lk = k.toLowerCase();
		const pd = () => e.preventDefault();
		const first = sel[0];
		const last = sel[sel.length - 1];
		const dir = k === 'ArrowUp' ? -1 : k === 'ArrowDown' ? 1 : 0;
		if (k === 'Escape') return pd(), void (doc.selected = []);
		if (mod(e) && lk === 'z') return pd(), e.shiftKey ? doc.redo() : doc.undo();
		if (mod(e) && lk === 'y') return pd(), doc.redo();
		if (mod(e) && lk === 'a') return pd(), doc.select(doc.visibleIds());
		if (mod(e) && lk === 'd') return pd(), doc.duplicate(sel);
		if (k === 'Backspace' || k === 'Delete') return pd(), doc.remove(sel);
		if (k === 'Tab') return pd(), e.shiftKey ? doc.outdent(sel) : doc.indent(sel);
		if (dir && (mod(e) || e.altKey) && e.shiftKey) return pd(), doc.moveVertically(sel, dir as -1 | 1);
		if (dir) {
			pd();
			const v = doc.visibleIds();
			if (e.shiftKey) {
				const anchor = doc.selectionAnchor && v.includes(doc.selectionAnchor) ? doc.selectionAnchor : first;
				const cur = selFocus && v.includes(selFocus) ? selFocus : dir < 0 ? first : last;
				selFocus = v[Math.max(0, Math.min(v.length - 1, v.indexOf(cur) + dir))];
				doc.selectionAnchor = anchor;
				doc.selectRange(anchor, selFocus);
				return;
			}
			const ni = v.indexOf(dir < 0 ? first : last) + dir;
			if (ni < 0) return (doc.selected = []), onexit?.();
			const nid = v[Math.min(ni, v.length - 1)];
			if (editableOf(nid, root)) doc.focus(nid, ni >= v.length || dir < 0 ? 'end' : 'start');
			else selectOne(nid);
			return;
		}
		if (k === 'Enter') {
			pd();
			if (sel.length === 1 && editableOf(last, root)) doc.focus(last, 'end');
			else doc.focus(doc.insertAfter(last, 'paragraph'), 'start');
		}
	}

	// ------------------------------------------------------------- mouse

	function onMouseDown(e: MouseEvent) {
		if (!mine(e)) return;
		if (e.button !== 0) return;
		const t = e.target as HTMLElement;
		if (t.closest('.gutter, .fold, .marker button, .refs, input, textarea, button')) return;
		const id = blockIdOf(t);
		if (e.shiftKey && id) {
			const from = doc.selectionAnchor ?? blockIdOf(document.activeElement);
			if (from && from !== id && doc.blocks[from]) {
				e.preventDefault();
				doc.selectionAnchor = from;
				selFocus = id;
				doc.selectRange(from, id);
				return;
			}
		}
		if (doc.selected.length) doc.selected = [];
		dragFrom = id;
		crossSelecting = false;
		if (id) doc.selectionAnchor = id;
	}

	// ----- notes attached to text: show after a short hover
	let noteTip = $state<{ el: HTMLElement; x: number; y: number; text: string; editing: boolean } | null>(null);
	let noteTimer: ReturnType<typeof setTimeout> | undefined;
	let hideTimer: ReturnType<typeof setTimeout> | undefined;

	function onNoteOver(e: MouseEvent) {
		const m = (e.target as HTMLElement).closest?.<HTMLElement>('mark[data-note]');
		if (!m || !root?.contains(m)) return;
		clearTimeout(hideTimer);
		if (noteTip?.el === m) return;
		clearTimeout(noteTimer);
		noteTimer = setTimeout(() => {
			const r = m.getBoundingClientRect();
			noteTip = { el: m, x: Math.min(r.left, innerWidth - 300), y: r.bottom + 6, text: m.dataset.note ?? '', editing: false };
		}, 350);
	}

	function onNoteOut(e: MouseEvent) {
		const m = (e.target as HTMLElement).closest?.('mark[data-note]');
		if (!m) return;
		clearTimeout(noteTimer);
		hideTimer = setTimeout(() => { if (!noteTip?.editing) noteTip = null; }, 250);
	}

	function saveNoteTip(remove = false) {
		const t = noteTip;
		noteTip = null;
		if (!t) return;
		const host = t.el.closest<HTMLElement>('[data-editable]');
		if (remove || !t.text.trim()) {
			t.el.replaceWith(...t.el.childNodes);
		} else t.el.dataset.note = t.text.trim();
		if (host) {
			host.normalize();
			notifyInput(host);
		}
	}

	function onMouseMove(e: MouseEvent) {
		if (!mine(e)) return;
		if (!(e.buttons & 1) || !dragFrom) return;
		const over = blockIdOf(document.elementFromPoint(e.clientX, e.clientY));
		if (!over) return;
		if (over !== dragFrom) {
			crossSelecting = true;
			selFocus = over;
			doc.selectRange(dragFrom, over);
		} else if (crossSelecting) {
			crossSelecting = false;
			doc.selected = [];
		}
	}

	function onClick(e: MouseEvent) {
		if (!mine(e)) return;
		const t = e.target as HTMLElement;
		const a = t.closest('a');
		if (a && a.closest('.rt')) {
			e.preventDefault();
			const href = a.getAttribute('href') ?? '';
			if (a.dataset.ref) {
				if (!a.classList.contains('broken') && href) open(href, e);
			} else if (href) window.open(a.href, '_blank', 'noopener');
			return;
		}
		const span = t.closest<HTMLElement>('.math');
		const host = span && editableFrom(span);
		if (span && host) openMath(blockIdOf(host)!, span);
	}

	function clickTail() {
		const list = doc.children(null);
		const last = list[list.length - 1];
		const b = last ? doc.blocks[last] : null;
		if (b && b.type === 'paragraph' && !b.html && !doc.children(last).length) doc.focus(last, 'start');
		else doc.focus(doc.append(prefs.defaultBlock || 'paragraph'), 'start');
	}

	// --------------------------------------------------------- clipboard

	function onCopy(e: ClipboardEvent, cut = false) {
		if (!mine(e) || !doc.selected.length || !e.clipboardData) return;
		e.preventDefault();
		const trees = doc.exportTrees(doc.selected);
		e.clipboardData.setData(KERN_MIME, JSON.stringify(trees));
		e.clipboardData.setData('text/plain', treesToText(trees));
		if (cut) doc.remove(doc.selected);
	}

	function insertTreesNear(trees: BlockTree[], el: HTMLElement | null) {
		if (!trees.length) return;
		const anchor = el ? blockIdOf(el) : doc.selected[doc.selected.length - 1];
		doc.run(() => {
			let ids: string[];
			if (!anchor || !doc.blocks[anchor]) ids = doc.insertTrees(trees, null, doc.children(null).length);
			else {
				const { parent, index } = doc.loc(anchor);
				ids = doc.insertTrees(trees, parent, index + 1);
				const b = doc.blocks[anchor];
				if (el && b.type === 'paragraph' && !b.html && !doc.children(anchor).length) doc.remove([anchor]);
			}
			const lastId = ids[ids.length - 1];
			if (editableOf(lastId, root) || TEXT_TYPES.has(doc.blocks[lastId].type)) doc.focus(lastId, 'end');
			else doc.select(ids);
		});
	}

	function onPaste(e: ClipboardEvent) {
		if (!mine(e)) return;
		const dt = e.clipboardData;
		if (!dt) return;
		const target = e.target as HTMLElement;
		const el = editableFrom(target);
		if (!el && target !== root) return; // inputs, table cells: native paste
		const kern = dt.getData(KERN_MIME);
		if (kern) {
			e.preventDefault();
			try {
				insertTreesNear(JSON.parse(kern), el);
			} catch {
				/* malformed clipboard */
			}
			return;
		}
		if (dt.files.length) {
			e.preventDefault();
			uploadFiles([...dt.files], el ? blockIdOf(el) : (doc.selected[doc.selected.length - 1] ?? null));
			return;
		}
		const text = dt.getData('text/plain');
		const html = dt.getData('text/html');
		e.preventDefault();
		const sync = /^kern-embed:([0-9a-f-]{36}):([0-9a-f-]{36})$/.exec(text.trim());
		if (sync) {
			insertTreesNear([{ type: 'embed', html: '', props: { kind: 'block', doc: sync[1], target: sync[2] }, collapsed: false, children: [] }], el);
			return;
		}
		if (el?.dataset.plain !== undefined) return insertText(text);
		if (el && !collapsed() && /^https?:\/\/\S+$/.test(text.trim())) return void document.execCommand('createLink', false, text.trim());
		const trees = html ? htmlToTrees(html) : textToTrees(text);
		if (!trees.length) return;
		if (el && trees.length === 1 && trees[0].type === 'paragraph' && !trees[0].children.length) insertHtml(trees[0].html);
		else insertTreesNear(trees, el);
	}

	// ----------------------------------------------------------- uploads

	async function uploadInto(id: string, file: File) {
		const a = await api.upload(file);
		doc.setProps(id, { url: a.url, name: a.name, size: a.size, mime: a.mime });
	}

	async function uploadFiles(files: File[], afterId: string | null) {
		ui.toast(files.length === 1 ? `Uploading ${files[0].name}…` : `Uploading ${files.length} files…`);
		for (const file of files) {
			try {
				const a = await api.upload(file);
				const kind = a.mime.split('/')[0];
				const type: BlockType = kind === 'image' ? 'image' : kind === 'video' ? 'video' : kind === 'audio' ? 'audio' : 'file';
				const props = { url: a.url, name: a.name, size: a.size, mime: a.mime };
				afterId = afterId && doc.blocks[afterId] ? doc.insertAfter(afterId, type, { props }) : doc.append(type, { props });
			} catch (e) {
				ui.error(e);
			}
		}
	}

	// ------------------------------------------------------- drag & drop

	function startDrag(id: string, e: DragEvent) {
		dragIds = doc.selected.includes(id) ? [...doc.selected] : [id];
		e.dataTransfer!.effectAllowed = 'move';
		e.dataTransfer!.setData('application/x-kern-drag', '1');
		const row = (e.currentTarget as HTMLElement).closest('.row');
		if (row) e.dataTransfer!.setDragImage(row, 0, 0);
	}

	function onDragOver(e: DragEvent) {
		if (!mine(e)) return;
		const files = e.dataTransfer?.types.includes('Files');
		if (!dragIds.length && !files) return;
		e.preventDefault();
		e.dataTransfer!.dropEffect = files ? 'copy' : 'move';
		const host = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>('[data-block-id]');
		const row = host?.querySelector<HTMLElement>(':scope > .row');
		if (!host || !row || !root || host.closest('[data-editor]') !== root || !doc.blocks[host.dataset.blockId!]) return;
		const id = host.dataset.blockId!;
		if (dragIds.some((d) => doc.isInside(id, d))) {
			indicator = null;
			dropTarget = null;
			return;
		}
		const r = row.getBoundingClientRect();
		const rr = root.getBoundingClientRect();
		const b = doc.blocks[id];
		let where: 'before' | 'after' | 'inside' = e.clientY < r.top + r.height / 2 ? 'before' : 'after';
		const canNest = !LEAF_TYPES.has(b.type) && !files;
		if (where === 'after' && canNest && ((doc.children(id).length && !b.collapsed) || e.clientX > r.left + 56)) where = 'inside';
		const inset = where === 'inside' ? 24 : 0;
		indicator = { top: (where === 'before' ? r.top : r.bottom) - rr.top - 1, left: r.left - rr.left + inset, width: r.width - inset };
		dropTarget = { id, where };
	}

	function endDrag() {
		dragIds = [];
		dropTarget = null;
		indicator = null;
	}

	function onDrop(e: DragEvent) {
		if (!mine(e)) return;
		const target = dropTarget;
		const ids = dragIds;
		const files = [...(e.dataTransfer?.files ?? [])];
		endDrag();
		if (files.length) {
			e.preventDefault();
			uploadFiles(files, target?.id ?? null);
		} else if (ids.length && target) {
			e.preventDefault();
			doc.moveBlocks(ids, target.id, target.where);
		}
	}

	// -------------------------------------------------------- block menu

	function blockMenu(at: MouseEvent | Element, id: string) {
		const b = doc.blocks[id];
		if (!b) return;
		const ids = doc.selected.includes(id) ? [...doc.selected] : [id];
		const items: MenuItem[] = [];
		if (ids.length === 1 && (TEXT_TYPES.has(b.type) || b.type === 'code')) {
			items.push({ heading: 'Turn into' });
			for (const s of TURN_INTO)
				items.push({ label: s.label, icon: s.icon, checked: s.type === b.type, onSelect: () => { doc.setType(id, s.type); doc.focus(id, 'end'); } });
			items.push({ separator: true });
		}
		if (ids.length === 1 && TEXT_TYPES.has(b.type)) {
			items.push({
				label: 'Create flashcard…', icon: Layers,
				onSelect: async () => {
					await doc.flush();
					const back = doc.children(id).map((k) => doc.blocks[k]?.html).filter(Boolean).join('<br>');
					ui.cardEditor = { init: { kind: 'basic', front: b.html, back, document: doc.id, block: id }, onsaved: () => doc.load() };
				}
			});
			if (!b.props.task)
				items.push({ label: 'Make task', icon: CircleCheck, hint: 'Alt T', onSelect: () => makeTask(id) });
			else
				items.push({ label: 'Open task', icon: CircleCheck, onSelect: () => open(`/tasks?view=open&task=${b.props.task}`) });
		}
		items.push({ label: 'Duplicate', icon: Copy, hint: 'Ctrl+D', onSelect: () => doc.duplicate(ids) });
		if (ids.length === 1) {
			items.push({
				label: 'Copy link to block', icon: Link2,
				onSelect: () => navigator.clipboard?.writeText(`${location.origin}/doc/${doc.id}#${id}`).then(() => ui.toast('Link copied'))
			});
			items.push({
				label: b.type === 'synced' ? 'Copy synced reference' : 'Copy embed reference', icon: Repeat,
				onSelect: () => navigator.clipboard?.writeText(`kern-embed:${doc.id}:${id}`).then(() =>
					ui.toast('Copied. Paste into any page to mirror this block.'))
			});
			if (doc.blockBacklinks[id])
				items.push({ label: 'Show references', icon: ListTree, onSelect: () => { doc.inspectBlock = id; prefs.panelOpen = true; } });
		}
		items.push({ label: ids.length > 1 ? `Delete ${ids.length} blocks` : 'Delete', icon: Trash2, danger: true, hint: 'Del', onSelect: () => doc.remove(ids) });
		if (at instanceof MouseEvent) ui.openMenu(at, items);
		else ui.menuBelow(at, items);
	}

	/** Turn a block into a checklist item backed by a task. */
	async function makeTask(id: string) {
		const b = doc.blocks[id];
		if (!b || b.props.task) return;
		if (b.type !== 'todo') doc.setType(id, 'todo');
		await doc.flush();
		try {
			const t = await api.post<{ id: string; due: string | null; priority: number; recurrence: any; done: boolean }>('/tasks', { block: id });
			doc.setProps(id, { task: t.id });
			doc.blockTasks[id] = t;
			counts.refresh();
			ui.toast('Added to Tasks', { action: { label: 'Open', run: () => open(`/tasks?view=open&task=${t.id}`) } });
		} catch (e) {
			ui.error(e);
		}
	}

	function onContextMenu(e: MouseEvent) {
		if (!mine(e)) return;
		const id = blockIdOf(e.target as Node);
		// Keep the native menu for text (spell-check, paste) unless blocks are selected.
		if (id && doc.selected.includes(id)) blockMenu(e, id);
	}
</script>

<svelte:window onmouseup={() => { dragFrom = null; crossSelecting = false; }} />

<!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
<div class="editor" bind:this={root} data-editor={doc.id} tabindex="-1" role="document"
	onkeydown={onKeydown} oninput={onInput} onbeforeinput={onBeforeInput}
	onmousedown={onMouseDown} onmousemove={onMouseMove} onclick={onClick} oncontextmenu={onContextMenu}
	onmouseover={onNoteOver} onmouseout={onNoteOut}
	oncopy={(e) => onCopy(e)} oncut={(e) => onCopy(e, true)} onpaste={onPaste}
	ondragover={onDragOver} ondrop={onDrop} ondragend={endDrag}
	ondragleave={(e) => { if (!root?.contains(e.relatedTarget as Node)) indicator = null; }}>
	{#if rootId}
		{#if doc.blocks[rootId]}<BlockNode id={rootId} index={doc.loc(rootId).index} />{:else}<div class="gone">The original block was deleted.</div>{/if}
	{:else}
		{#each doc.kids.root as id, i (id)}
			<BlockNode {id} index={i} />
		{/each}
	{/if}
	{#if indicator}
		<div class="drop" style:top="{indicator.top}px" style:left="{indicator.left}px" style:width="{indicator.width}px"></div>
	{/if}
</div>
{#if !rootId}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="tail" class:short={!onexit} onclick={clickTail}></div>
{/if}

{#if menu}
	<SuggestMenu items={menu.items} index={menu.index} rect={menu.rect} onchoose={choose} onhover={(i) => menu && (menu.index = i)}
		empty={menu.kind === 'blockref' ? (menu.query.trim() ? 'No matching blocks' : 'Type to search blocks…') : 'No matches'} />
{/if}

{#if root}<FormatToolbar {root} bind:this={toolbar} />{/if}

{#if aiAt}
	<AiInline docId={doc.id} selection={aiAt.selection} rect={aiAt.rect} oninsert={insertAi}
		onclose={() => { const id = aiAt?.id; aiAt = null; if (id && doc.blocks[id]) doc.focus(id, 'end'); }} />
{/if}

{#if noteTip}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="notetip popover" style:left="{noteTip.x}px" style:top="{noteTip.y}px"
		onmouseenter={() => clearTimeout(hideTimer)} onmouseleave={() => { if (!noteTip?.editing) noteTip = null; }}>
		{#if noteTip.editing}
			<!-- svelte-ignore a11y_autofocus -->
			<textarea class="input" rows="3" autofocus bind:value={noteTip.text}
				onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') noteTip = null; if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveNoteTip(); } }}></textarea>
			<div class="tipacts"><button class="btn ghost" onclick={() => saveNoteTip(true)}>Remove</button><button class="btn primary" onclick={() => saveNoteTip()}>Save</button></div>
		{:else}
			<p class="tiptext">{noteTip.text}</p>
			<div class="tipacts"><button class="btn ghost" onclick={() => noteTip && (noteTip.editing = true)}>Edit</button><button class="btn ghost" onclick={() => saveNoteTip(true)}>Remove note</button></div>
		{/if}
	</div>
{/if}

{#if math}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="backdrop" onmousedown={saveMath}></div>
	<form class="math-pop popover" style:left="{Math.min(math.x, innerWidth - 340)}px" style:top="{math.y}px" onsubmit={(e) => { e.preventDefault(); saveMath(); }}>
		<input class="input" bind:this={mathInput} bind:value={math.tex} placeholder="LaTeX, e.g. x^2 + y^2" spellcheck="false"
			onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') { e.preventDefault(); math = null; } }} />
		<button class="btn primary" type="submit">Done</button>
	</form>
{/if}

<style>
	.editor { position: relative; outline: none; font-family: var(--font-editor); font-size: var(--editor-size); }
	.tail { min-height: 30vh; cursor: text; }
	.tail.short { min-height: 12px; }
	.gone { padding: 6px 4px; color: var(--text-3); font-style: italic; }
	.drop { position: absolute; height: 2px; background: var(--accent); border-radius: 1px; pointer-events: none; z-index: 5; }
	.backdrop { position: fixed; inset: 0; z-index: 595; }
	.notetip { position: fixed; z-index: 597; width: 280px; padding: 10px 12px 8px; font-family: var(--font-sans); }
	.tiptext { margin: 0 0 6px; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }
	.notetip textarea { width: 100%; margin-bottom: 6px; }
	.tipacts { display: flex; justify-content: flex-end; gap: 4px; }
	.tipacts .btn { height: 24px; padding: 0 8px; font-size: 12px; }
	.math-pop { position: fixed; z-index: 596; display: flex; gap: 6px; padding: 6px; width: 330px; }
	.math-pop .input { flex: 1; font-family: var(--font-mono); font-size: 13px; }
</style>
