import type { Doc } from '#lib/types.ts';

/** Text typed into the link box that is meant as a web address rather than a page search. */
export function looksLikeUrl(text: string): boolean {
	const t = text.trim();
	if (!t || /\s/.test(t)) return false;
	return /^[a-z][a-z0-9+.-]*:/i.test(t) || /^(www\.)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i.test(t);
}

export interface PageHit {
	id: string;
	title: string;
	icon: string;
	/** Parent pages, "A / B", for telling same-named pages apart. */
	path: string;
}

/**
 * Pages to offer in the "link to page" picker: title matches first (prefix before substring),
 * then the most recently opened. An empty query lists recent pages.
 */
export function findPages(docs: Record<string, Doc>, query: string, exclude: string | null, limit = 8): PageHit[] {
	const q = query.trim().toLowerCase();
	const rank = (d: Doc) => {
		const t = (d.title || 'Untitled').toLowerCase();
		return !q ? 1 : t === q ? 0 : t.startsWith(q) ? 1 : t.includes(q) ? 2 : 3;
	};
	return Object.values(docs)
		.filter((d) => d.id !== exclude && !d.is_template && !d.trashed_at && rank(d) < 3)
		.sort((a, b) => rank(a) - rank(b) || (b.last_opened_at ?? '').localeCompare(a.last_opened_at ?? ''))
		.slice(0, limit)
		.map((d) => ({ id: d.id, title: d.title, icon: d.icon, path: parentPath(docs, d) }));
}

function parentPath(docs: Record<string, Doc>, d: Doc): string {
	const names: string[] = [];
	let cur = d.parent ? docs[d.parent] : undefined;
	for (let guard = 0; cur && guard < 32; guard++) {
		names.unshift(cur.title || 'Untitled');
		cur = cur.parent ? docs[cur.parent] : undefined;
	}
	return names.join(' / ');
}
