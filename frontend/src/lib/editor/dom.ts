import { loadKatex, math } from './katex.svelte.ts';

export function blockEl(id: string): HTMLElement | null {
	return document.querySelector<HTMLElement>(`[data-block-id="${id}"]`);
}

export function editableOf(id: string, root: ParentNode | null = null): HTMLElement | null {
	const sel = `[data-block-id="${id}"] > .row [data-editable]`;
	return (root ?? document).querySelector<HTMLElement>(sel) ?? (root ? document.querySelector<HTMLElement>(sel) : null);
}

export function blockIdOf(node: Node | null): string | null {
	const el = node instanceof Element ? node : node?.parentElement;
	return el?.closest<HTMLElement>('[data-block-id]')?.dataset.blockId ?? null;
}

function clean(html: string): string {
	html = html.replace(/​/g, '');
	if (html.endsWith('<br>') && !html.endsWith('<br><br>')) html = html.slice(0, -4);
	return html;
}

function isBlank(el: HTMLElement): boolean {
	return !el.textContent?.replace(/​/g, '') && !el.querySelector('a, .math, br');
}

/** Serialise an editable's content to the stored form (math spans hold their TeX). */
export function readHtml(el: HTMLElement): string {
	let src = el;
	if (el.querySelector('.math')) {
		src = el.cloneNode(true) as HTMLElement;
		src.querySelectorAll<HTMLElement>('.math').forEach((m) => (m.textContent = m.dataset.math ?? ''));
	}
	if (isBlank(src)) return '';
	return clean(src.innerHTML);
}

export function renderMath(el: HTMLElement) {
	const spans = el.querySelectorAll<HTMLElement>('.math');
	if (!spans.length) return;
	const katex = math.katex;
	if (!katex) {
		// Show the raw TeX until KaTeX arrives, then render for real.
		spans.forEach((m) => (m.contentEditable = 'false'));
		loadKatex().then(() => el.isConnected && renderMath(el));
		return;
	}
	spans.forEach((m) => {
		const tex = m.dataset.math ?? '';
		if (m.dataset.rendered === tex) return;
		try {
			katex.render(tex, m, { throwOnError: false, displayMode: false });
		} catch {
			m.textContent = tex;
		}
		m.dataset.rendered = tex;
		m.contentEditable = 'false';
	});
}

export function htmlTextLength(html: string): number {
	if (!html.includes('<') && !html.includes('&')) return html.length;
	const t = document.createElement('div');
	t.innerHTML = html;
	renderMath(t);
	return t.textContent?.length ?? 0;
}

export function htmlToText(html: string): string {
	const t = document.createElement('div');
	t.innerHTML = html.replace(/<br\s*\/?>/gi, '\n');
	return t.textContent ?? '';
}

function selectionIn(el: HTMLElement): Range | null {
	const sel = getSelection();
	if (!sel || !sel.rangeCount) return null;
	const r = sel.getRangeAt(0);
	return el.contains(r.startContainer) && el.contains(r.endContainer) ? r : null;
}

function offsetOf(el: HTMLElement, node: Node, offset: number): number {
	const r = document.createRange();
	r.selectNodeContents(el);
	r.setEnd(node, offset);
	return r.toString().length;
}

export function caretOffset(el: HTMLElement): number {
	const r = selectionIn(el);
	return r ? offsetOf(el, r.endContainer, r.endOffset) : 0;
}

export function selectionOffsets(el: HTMLElement): { start: number; end: number } | null {
	const r = selectionIn(el);
	if (!r) return null;
	return { start: offsetOf(el, r.startContainer, r.startOffset), end: offsetOf(el, r.endContainer, r.endOffset) };
}

function pointAt(el: HTMLElement, offset: number): [Node, number] {
	if (offset <= 0) return [el, 0];
	const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
	let node: Node | null;
	let remaining = offset;
	while ((node = walker.nextNode())) {
		const len = node.textContent!.length;
		if (remaining <= len) {
			const locked = node.parentElement?.closest<HTMLElement>('[contenteditable="false"]');
			if (locked && locked !== el && el.contains(locked)) {
				const parent = locked.parentNode!;
				return [parent, [...parent.childNodes].indexOf(locked) + 1];
			}
			return [node, remaining];
		}
		remaining -= len;
	}
	return [el, el.childNodes.length];
}

export function rangeForOffsets(el: HTMLElement, start: number, end: number): Range {
	const r = document.createRange();
	const [sn, so] = pointAt(el, start);
	const [en, eo] = pointAt(el, end);
	r.setStart(sn, so);
	r.setEnd(en, eo);
	return r;
}

export function setCaret(el: HTMLElement, pos: number | 'start' | 'end') {
	el.focus({ preventScroll: true });
	const sel = getSelection();
	if (!sel) return;
	const r = document.createRange();
	if (pos === 'start') {
		r.setStart(el, 0);
	} else if (pos === 'end') {
		r.selectNodeContents(el);
		r.collapse(false);
	} else {
		const [n, o] = pointAt(el, pos);
		r.setStart(n, o);
	}
	r.collapse(pos !== 'end');
	sel.removeAllRanges();
	sel.addRange(r);
	const rect = el.getBoundingClientRect();
	if (rect.top < 60 || rect.bottom > innerHeight - 20) el.scrollIntoView({ block: 'nearest' });
}

export function isAtStart(el: HTMLElement): boolean {
	const sel = getSelection();
	return !!sel?.isCollapsed && !!selectionIn(el) && caretOffset(el) === 0;
}

export function isAtEnd(el: HTMLElement): boolean {
	const sel = getSelection();
	return !!sel?.isCollapsed && !!selectionIn(el) && caretOffset(el) >= (el.textContent?.length ?? 0);
}

export function caretRect(): DOMRect | null {
	const sel = getSelection();
	if (!sel || !sel.rangeCount) return null;
	const r = sel.getRangeAt(0).cloneRange();
	r.collapse(false);
	let rect: DOMRect | undefined = r.getClientRects()[0];
	if (!rect || (!rect.height && !rect.width)) {
		const node = r.startContainer;
		if (node.nodeType === Node.TEXT_NODE && node.textContent!.length) {
			const probe = document.createRange();
			const o = r.startOffset;
			if (o > 0) {
				probe.setStart(node, o - 1);
				probe.setEnd(node, o);
				const pr = probe.getClientRects();
				const last = pr[pr.length - 1];
				if (last) rect = new DOMRect(last.right, last.top, 0, last.height);
			} else {
				probe.setStart(node, 0);
				probe.setEnd(node, 1);
				const first = probe.getClientRects()[0];
				if (first) rect = new DOMRect(first.left, first.top, 0, first.height);
			}
		}
		if (!rect || !rect.height) {
			const host = (node instanceof Element ? node : node.parentElement) as HTMLElement | null;
			if (!host) return null;
			const hr = host.getBoundingClientRect();
			const lh = parseFloat(getComputedStyle(host).lineHeight) || 22;
			rect = new DOMRect(hr.left, hr.top, 0, Math.min(lh, hr.height || lh));
		}
	}
	return rect;
}

function lineHeightOf(el: HTMLElement): number {
	const lh = parseFloat(getComputedStyle(el).lineHeight);
	return Number.isFinite(lh) ? lh : 22;
}

export function onFirstLine(el: HTMLElement): boolean {
	const r = caretRect();
	if (!r || !el.textContent) return true;
	return r.top - el.getBoundingClientRect().top < lineHeightOf(el) * 0.9;
}

export function onLastLine(el: HTMLElement): boolean {
	const r = caretRect();
	if (!r || !el.textContent) return true;
	return el.getBoundingClientRect().bottom - r.bottom < lineHeightOf(el) * 0.9;
}

/** Place the caret in `el` on its first/last line, as close as possible to x. */
export function setCaretNearX(el: HTMLElement, x: number, edge: 'top' | 'bottom') {
	const rect = el.getBoundingClientRect();
	const lh = lineHeightOf(el);
	const y = edge === 'top' ? rect.top + Math.min(lh / 2, rect.height / 2) : rect.bottom - Math.min(lh / 2, rect.height / 2);
	const cx = Math.max(rect.left + 1, Math.min(x, rect.right - 1));
	let node: Node | null = null;
	let offset = 0;
	const doc = document as any;
	if (doc.caretPositionFromPoint) {
		const p = doc.caretPositionFromPoint(cx, y);
		if (p) [node, offset] = [p.offsetNode, p.offset];
	} else if (doc.caretRangeFromPoint) {
		const p = doc.caretRangeFromPoint(cx, y);
		if (p) [node, offset] = [p.startContainer, p.startOffset];
	}
	if (!node || !el.contains(node) || !el.textContent) {
		setCaret(el, edge === 'top' ? 'start' : 'end');
		return;
	}
	el.focus({ preventScroll: true });
	const r = document.createRange();
	r.setStart(node, offset);
	r.collapse(true);
	const sel = getSelection()!;
	sel.removeAllRanges();
	sel.addRange(r);
	if (rect.top < 60 || rect.bottom > innerHeight - 20) el.scrollIntoView({ block: 'nearest' });
}

function fragmentHtml(frag: DocumentFragment): string {
	const t = document.createElement('div');
	t.appendChild(frag);
	return readHtml(t);
}

/** Split the editable at the caret (deleting any selection). */
export function splitAtCaret(el: HTMLElement): { head: string; tail: string } {
	const r = selectionIn(el);
	if (!r) return { head: readHtml(el), tail: '' };
	r.deleteContents();
	const tailRange = document.createRange();
	tailRange.setStart(r.endContainer, r.endOffset);
	tailRange.setEnd(el, el.childNodes.length);
	const tail = fragmentHtml(tailRange.extractContents());
	return { head: readHtml(el), tail };
}

export function insertHtml(html: string) {
	document.execCommand('insertHTML', false, html);
}

export function insertText(text: string) {
	document.execCommand('insertText', false, text);
}

/** Announce a programmatic DOM edit so the block picks up the new content. */
export function notifyInput(el: HTMLElement) {
	el.dispatchEvent(new InputEvent('input', { bubbles: true }));
}

function closestIn(node: Node | null, selector: string, root: HTMLElement): HTMLElement | null {
	const el = node instanceof Element ? node : node?.parentElement;
	const hit = el?.closest<HTMLElement>(selector) ?? null;
	return hit && root.contains(hit) && hit !== root ? hit : null;
}

function unwrap(el: Element) {
	const parent = el.parentNode!;
	while (el.firstChild) parent.insertBefore(el.firstChild, el);
	parent.removeChild(el);
}

/** Wrap the selection in an element, or remove the wrapper if already inside one. */
export function toggleWrap(el: HTMLElement, tag: string, attrs: Record<string, string> = {}, matchSelector = tag) {
	const r = selectionIn(el);
	if (!r || r.collapsed) return;
	const existing = closestIn(r.commonAncestorContainer, matchSelector, el);
	const sel = getSelection()!;
	if (existing) {
		const first = existing.firstChild;
		const last = existing.lastChild;
		unwrap(existing);
		if (first && last) {
			const nr = document.createRange();
			nr.setStartBefore(first);
			nr.setEndAfter(last);
			sel.removeAllRanges();
			sel.addRange(nr);
		}
	} else {
		const frag = r.extractContents();
		frag.querySelectorAll(matchSelector).forEach(unwrap);
		const w = document.createElement(tag);
		for (const [k, v] of Object.entries(attrs)) w.setAttribute(k, v);
		w.appendChild(frag);
		r.insertNode(w);
		sel.removeAllRanges();
		const nr = document.createRange();
		nr.selectNodeContents(w);
		sel.addRange(nr);
	}
	el.normalize();
	notifyInput(el);
}

/** Apply (or clear, when value is '') a colour-like wrapper to the selection. */
export function applyWrap(el: HTMLElement, tag: string, attr: string, value: string) {
	const r = selectionIn(el);
	if (!r || r.collapsed) return;
	const selector = `${tag}[${attr}]`;
	const sel = getSelection()!;
	const outer = closestIn(r.commonAncestorContainer, selector, el);
	if (outer) {
		// Simplest predictable behaviour: retarget or drop the enclosing wrapper.
		if (value) outer.setAttribute(attr, value);
		else unwrap(outer);
	} else {
		const frag = r.extractContents();
		frag.querySelectorAll(selector).forEach(unwrap);
		if (value) {
			const w = document.createElement(tag);
			w.setAttribute(attr, value);
			w.appendChild(frag);
			r.insertNode(w);
			sel.removeAllRanges();
			const nr = document.createRange();
			nr.selectNodeContents(w);
			sel.addRange(nr);
		} else {
			const first = frag.firstChild;
			const last = frag.lastChild;
			r.insertNode(frag);
			if (first && last) {
				const nr = document.createRange();
				nr.setStartBefore(first);
				nr.setEndAfter(last);
				sel.removeAllRanges();
				sel.addRange(nr);
			}
		}
	}
	el.normalize();
	notifyInput(el);
}

export function refHtml(kind: 'doc' | 'block' | 'tag', id: string, title: string, href: string, color = ''): string {
	const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
	const cls = kind === 'tag' ? 'ref tag' : kind === 'block' ? 'ref blockref' : 'ref';
	const text = kind === 'tag' ? '#' + title : title || 'Untitled';
	const c = color ? ` data-c="${esc(color)}"` : '';
	return `<a class="${cls}" data-ref="${kind}:${id}" href="${esc(href)}" contenteditable="false"${c}>${esc(text)}</a>`;
}

export function mathHtml(tex: string): string {
	const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
	return `<span class="math" data-math="${esc(tex)}" contenteditable="false">${esc(tex)}</span>`;
}
