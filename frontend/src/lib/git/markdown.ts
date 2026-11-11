/** A small, safe Markdown renderer for READMEs. Everything is escaped before any markup is added. */
import { highlightCode } from './highlight.ts';

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const safeUrl = (u: string) => (/^(https?:|mailto:|#)/i.test(u) ? u : null);

function inline(s: string, resolve: (url: string) => string): string {
	const codes: string[] = [];
	let out = esc(s).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
	out = out
		.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_, alt, url) => {
			const u = safeUrl(url) ?? resolve(url);
			return `<img src="${u}" alt="${alt}" loading="lazy" />`;
		})
		.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
			const u = safeUrl(url);
			return u ? `<a href="${u}" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
		})
		.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>')
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
		.replace(/__([^_]+)__/g, '<strong>$1</strong>')
		.replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
		.replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>')
		.replace(/~~([^~]+)~~/g, '<del>$1</del>');
	return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

export function renderReadme(text: string, resolve: (url: string) => string = () => '#'): string {
	const lines = text.replace(/\r/g, '').split('\n');
	const out: string[] = [];
	let list: 'ul' | 'ol' | null = null;
	let para: string[] = [];
	let quote: string[] = [];
	const flush = () => {
		if (para.length) out.push(`<p>${para.map((l) => inline(l, resolve)).join(' ')}</p>`);
		para = [];
	};
	const closeList = () => {
		if (list) out.push(`</${list}>`);
		list = null;
	};
	const closeQuote = () => {
		if (quote.length) out.push(`<blockquote>${renderReadme(quote.join('\n'), resolve)}</blockquote>`);
		quote = [];
	};
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];
		const fence = line.match(/^\s*(```|~~~)\s*([\w+-]*)/);
		if (fence) {
			flush(); closeList(); closeQuote();
			const body: string[] = [];
			while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i]);
			out.push(`<pre><code>${highlightCode(body.join('\n'), fence[2] || '')}</code></pre>`);
			continue;
		}
		if (/^\s*>/.test(line)) {
			flush(); closeList();
			quote.push(line.replace(/^\s*>\s?/, ''));
			continue;
		}
		closeQuote();
		const h = line.match(/^(#{1,6})\s+(.*?)\s*#*$/);
		const ul = line.match(/^\s*[-*+]\s+(?:\[( |x|X)\]\s+)?(.*)/);
		const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
		if (h) {
			flush(); closeList();
			const lvl = h[1].length;
			const id = h[2].toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-');
			out.push(`<h${lvl} id="${esc(id)}">${inline(h[2], resolve)}</h${lvl}>`);
		} else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
			flush(); closeList();
			out.push('<hr />');
		} else if (ul || ol) {
			flush();
			const kind = ul ? 'ul' : 'ol';
			if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
			const box = ul?.[1] !== undefined ? `<input type="checkbox" disabled ${ul[1] !== ' ' ? 'checked' : ''} /> ` : '';
			out.push(`<li>${box}${inline(ul ? ul[2] : ol![1], resolve)}</li>`);
		} else if (line.includes('|') && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] ?? '')) {
			flush(); closeList();
			const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
			const head = cells(line);
			i++;
			const rows: string[][] = [];
			while (i + 1 < lines.length && lines[i + 1].includes('|') && lines[i + 1].trim()) rows.push(cells(lines[++i]));
			out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c, resolve)}</th>`).join('')}</tr></thead><tbody>${rows
				.map((r) => `<tr>${r.map((c) => `<td>${inline(c, resolve)}</td>`).join('')}</tr>`)
				.join('')}</tbody></table>`);
		} else if (!line.trim()) {
			flush(); closeList();
		} else {
			closeList();
			para.push(line.trim());
		}
	}
	flush(); closeList(); closeQuote();
	return out.join('');
}
