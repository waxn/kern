/** HTML from file content (Markdown, Word) is untrusted: render it through DOMPurify. Loaded lazily. */

async function purify() {
	const { default: DOMPurify } = await import('dompurify');
	return DOMPurify;
}

export async function safeHtml(html: string): Promise<string> {
	const p = await purify();
	return p.sanitize(html, { FORBID_TAGS: ['style', 'form', 'button', 'textarea', 'select'], FORBID_ATTR: ['style'] });
}

export async function renderMarkdown(text: string): Promise<string> {
	const { marked } = await import('marked');
	return safeHtml(await marked.parse(text, { gfm: true }));
}
