import type { BlockType } from '#lib/types.ts';
import { escapeHtml } from '#lib/util.ts';
import type { BlockTree } from './doc.svelte';
import { htmlToText } from './dom';

const INLINE = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'DEL', 'CODE', 'MARK', 'SUB', 'SUP']);
const BLOCKISH = new Set([
	'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'PRE', 'HR', 'TABLE',
	'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'MAIN', 'ASIDE', 'FIGURE', 'IMG', 'DL', 'DT', 'DD'
]);

function tree(type: BlockType, html = '', props: Record<string, any> = {}, children: BlockTree[] = []): BlockTree {
	if (type === 'todo') props = { checked: false, ...props };
	if (type === 'callout') props = { icon: '💡', ...props };
	return { type, html, props, collapsed: false, children };
}

/** Reduce arbitrary HTML to the inline subset the editor stores. */
export function sanitizeInline(node: Node, skip?: (el: Element) => boolean): string {
	let out = '';
	node.childNodes.forEach((child) => {
		if (child.nodeType === Node.TEXT_NODE) {
			out += escapeHtml((child.textContent ?? '').replace(/\s*\n\s*/g, ' '));
			return;
		}
		if (!(child instanceof HTMLElement)) return;
		if (skip?.(child)) return;
		const tag = child.tagName;
		const inner = () => sanitizeInline(child, skip);
		if (tag === 'BR') out += '<br>';
		else if (tag === 'A') {
			const ref = child.dataset.ref;
			const href = child.getAttribute('href') ?? '';
			if (ref && /^(doc|block|tag):[0-9a-f-]{36}$/.test(ref))
				out += `<a class="${escapeHtml(child.className)}" data-ref="${ref}" href="${escapeHtml(href)}" contenteditable="false">${escapeHtml(child.textContent ?? '')}</a>`;
			else if (/^(https?:|mailto:|tel:)/i.test(href)) out += `<a href="${escapeHtml(href)}">${inner()}</a>`;
			else out += inner();
		} else if (tag === 'SPAN' && child.dataset.math !== undefined) {
			out += `<span class="math" data-math="${escapeHtml(child.dataset.math)}" contenteditable="false">${escapeHtml(child.dataset.math)}</span>`;
		} else if (INLINE.has(tag)) {
			const t = tag === 'STRONG' ? 'b' : tag === 'EM' ? 'i' : tag.toLowerCase();
			const body = inner();
			if (body) out += `<${t}>${body}</${t}>`;
		} else if (tag === 'SPAN') {
			let body = inner();
			const st = child.style;
			if (body && (st.fontWeight === 'bold' || parseInt(st.fontWeight) >= 600)) body = `<b>${body}</b>`;
			if (body && st.fontStyle === 'italic') body = `<i>${body}</i>`;
			if (body && child.dataset.color) body = `<span data-color="${escapeHtml(child.dataset.color)}">${body}</span>`;
			out += body;
		} else if (tag !== 'SCRIPT' && tag !== 'STYLE' && tag !== 'META') out += inner();
	});
	return out;
}

const trimHtml = (h: string) => h.replace(/^(\s|&nbsp;|<br>)+|(\s|&nbsp;|<br>)+$/g, '');

function listItems(list: Element): BlockTree[] {
	const ordered = list.tagName === 'OL';
	const out: BlockTree[] = [];
	for (const li of list.children) {
		if (li.tagName !== 'LI') {
			if (li.tagName === 'UL' || li.tagName === 'OL') {
				const nested = listItems(li);
				if (out.length) out[out.length - 1].children.push(...nested);
				else out.push(...nested);
			}
			continue;
		}
		const box = li.querySelector<HTMLInputElement>(':scope > input[type=checkbox], :scope > p > input[type=checkbox]');
		const html = trimHtml(sanitizeInline(li, (el) => el.tagName === 'UL' || el.tagName === 'OL' || el.tagName === 'INPUT'));
		const children: BlockTree[] = [];
		li.querySelectorAll(':scope > ul, :scope > ol').forEach((n) => children.push(...listItems(n)));
		out.push(
			box ? tree('todo', html, { checked: box.checked }, children) : tree(ordered ? 'numbered' : 'bullet', html, {}, children)
		);
	}
	return out;
}

function walk(container: Node, out: BlockTree[]) {
	let run = document.createElement('div');
	const flush = () => {
		const html = trimHtml(sanitizeInline(run));
		if (html) out.push(tree('paragraph', html));
		run = document.createElement('div');
	};
	container.childNodes.forEach((node) => {
		if (!(node instanceof HTMLElement) || !BLOCKISH.has(node.tagName)) {
			if (node instanceof HTMLElement && node.tagName === 'BR') return flush();
			run.appendChild(node.cloneNode(true));
			return;
		}
		flush();
		const tag = node.tagName;
		if (/^H[1-6]$/.test(tag)) {
			const level = Math.min(3, Number(tag[1])) as 1 | 2 | 3;
			const html = trimHtml(sanitizeInline(node));
			if (html) out.push(tree(`h${level}` as BlockType, html));
		} else if (tag === 'UL' || tag === 'OL') out.push(...listItems(node));
		else if (tag === 'BLOCKQUOTE') {
			const html = trimHtml(sanitizeInline(node));
			if (html) out.push(tree('quote', html));
		} else if (tag === 'PRE') out.push(tree('code', escapeHtml(node.textContent ?? '')));
		else if (tag === 'HR') out.push(tree('divider'));
		else if (tag === 'IMG') {
			const src = node.getAttribute('src') ?? '';
			if (/^https?:/i.test(src)) out.push(tree('image', '', { url: src, name: node.getAttribute('alt') ?? '' }));
		} else if (tag === 'TABLE') {
			const rows = [...node.querySelectorAll('tr')].map((tr) =>
				[...tr.querySelectorAll('th,td')].map((c) => trimHtml(sanitizeInline(c)))
			);
			const width = Math.max(0, ...rows.map((r) => r.length));
			if (width) out.push(tree('table', '', { rows: rows.map((r) => [...r, ...Array(width - r.length).fill('')]), header: !!node.querySelector('th') }));
		} else if ([...node.children].some((c) => BLOCKISH.has(c.tagName))) walk(node, out);
		else {
			const html = trimHtml(sanitizeInline(node));
			if (html) out.push(tree('paragraph', html));
		}
	});
	flush();
}

export function htmlToTrees(html: string): BlockTree[] {
	const doc = new DOMParser().parseFromString(html, 'text/html');
	const out: BlockTree[] = [];
	walk(doc.body, out);
	return out;
}

const MD: [RegExp, BlockType][] = [
	[/^### +/, 'h3'], [/^## +/, 'h2'], [/^# +/, 'h1'],
	[/^[-*+] \[[ xX]\] +/, 'todo'], [/^\[[ xX]?\] +/, 'todo'],
	[/^[-*+•] +/, 'bullet'], [/^\d+[.)] +/, 'numbered'], [/^> +/, 'quote']
];

function inlineMd(text: string): string {
	return escapeHtml(text)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
		.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=$|[\s).,;:!?])/g, '$1<i>$2</i>')
		.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>');
}

/** Plain text / Markdown to blocks. Indentation nests list items. */
export function textToTrees(text: string): BlockTree[] {
	const root: BlockTree[] = [];
	const stack: { indent: number; node: BlockTree }[] = [];
	const lines = text.replace(/\r\n?/g, '\n').split('\n');
	for (let i = 0; i < lines.length; i++) {
		const raw = lines[i];
		if (!raw.trim()) {
			stack.length = 0;
			continue;
		}
		if (/^\s*```/.test(raw)) {
			const body: string[] = [];
			for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i]);
			root.push(tree('code', escapeHtml(body.join('\n'))));
			stack.length = 0;
			continue;
		}
		if (/^\s*(---+|\*\*\*+)\s*$/.test(raw)) {
			root.push(tree('divider'));
			stack.length = 0;
			continue;
		}
		const indent = raw.match(/^[ \t]*/)![0].replace(/\t/g, '    ').length;
		let body = raw.trim();
		let type: BlockType = 'paragraph';
		let props: Record<string, any> = {};
		for (const [re, t] of MD) {
			const m = re.exec(body);
			if (m) {
				type = t;
				if (t === 'todo') props = { checked: /\[[xX]\]/.test(m[0]) };
				body = body.slice(m[0].length);
				break;
			}
		}
		const node = tree(type, inlineMd(body), props);
		while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
		if (stack.length && indent > 0) stack[stack.length - 1].node.children.push(node);
		else root.push(node);
		stack.push({ indent, node });
	}
	return root;
}

const PREFIX: Partial<Record<BlockType, string>> = {
	h1: '# ', h2: '## ', h3: '### ', bullet: '- ', numbered: '1. ', quote: '> ', toggle: '- ', callout: '> '
};

export function treesToText(trees: BlockTree[], depth = 0): string {
	const pad = '  '.repeat(depth);
	return trees
		.map((t) => {
			let line: string;
			if (t.type === 'divider') line = '---';
			else if (t.type === 'code') line = '```\n' + htmlToText(t.html) + '\n```';
			else if (t.type === 'todo') line = `- [${t.props.checked ? 'x' : ' '}] ` + htmlToText(t.html);
			else if (t.type === 'equation') line = `$$${t.props.tex ?? ''}$$`;
			else if (t.type === 'table') line = (t.props.rows ?? []).map((r: string[]) => '| ' + r.map(htmlToText).join(' | ') + ' |').join('\n');
			else if (t.props.url) line = t.props.url;
			else line = (PREFIX[t.type] ?? '') + htmlToText(t.html);
			const self = line.split('\n').map((l) => pad + l).join('\n');
			return t.children.length ? self + '\n' + treesToText(t.children, depth + 1) : self;
		})
		.join('\n');
}
