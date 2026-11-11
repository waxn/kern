/** A small, safe Markdown renderer for assistant replies (everything is escaped first). */

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function inline(s: string, link: (title: string) => string | null): string {
	const codes: string[] = [];
	let out = esc(s).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
	out = out
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
		.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
		.replace(/\[\[([^\]]+)\]\]/g, (_, t) => {
			const href = link(t);
			return href ? `<a class="ref" href="${href}">${t}</a>` : t;
		})
		.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
	return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

export function renderMarkdown(text: string, link: (title: string) => string | null = () => null): string {
	const lines = text.replace(/\r/g, '').split('\n');
	const out: string[] = [];
	let list: 'ul' | 'ol' | null = null;
	let para: string[] = [];
	const flush = () => {
		if (para.length) out.push(`<p>${para.map((l) => inline(l, link)).join('<br>')}</p>`);
		para = [];
	};
	const close = () => {
		if (list) out.push(`</${list}>`);
		list = null;
	};
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];
		if (line.startsWith('```')) {
			flush(); close();
			const body: string[] = [];
			while (++i < lines.length && !lines[i].startsWith('```')) body.push(lines[i]);
			out.push(`<pre><code>${esc(body.join('\n'))}</code></pre>`);
			continue;
		}
		const h = line.match(/^(#{1,3})\s+(.*)/);
		const ul = line.match(/^\s*[-*]\s+(?:\[( |x)\]\s+)?(.*)/);
		const ol = line.match(/^\s*\d+[.)]\s+(.*)/);
		if (h) {
			flush(); close();
			out.push(`<h4>${inline(h[2], link)}</h4>`);
		} else if (ul || ol) {
			flush();
			const kind = ul ? 'ul' : 'ol';
			if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
			const box = ul?.[1] !== undefined ? (ul[1] === 'x' ? '☑ ' : '☐ ') : '';
			out.push(`<li>${box}${inline(ul ? ul[2] : ol![1], link)}</li>`);
		} else if (!line.trim()) {
			flush(); close();
		} else {
			close();
			para.push(line);
		}
	}
	flush(); close();
	return out.join('');
}
