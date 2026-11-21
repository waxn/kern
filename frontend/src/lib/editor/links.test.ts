import { describe, expect, it } from 'vitest';
import type { Doc } from '#lib/types.ts';
import { findPages, looksLikeUrl } from './links';

const doc = (id: string, title: string, extra: Partial<Doc> = {}): Doc => ({
	id, title, parent: null, icon: '', cover: '', position: 0, is_favorite: false, is_archived: false, trashed_at: null,
	created_at: '', updated_at: '', last_opened_at: null, entry_of: null, database: null, is_template: false,
	template_tag: null, template_db: null, tags: [], ...extra
});

describe('link box', () => {
	it('tells web addresses from page searches', () => {
		for (const u of ['https://a.org', 'example.com', 'www.example.com/x?y=1', 'mailto:a@b.c']) expect(looksLikeUrl(u)).toBe(true);
		for (const q of ['', 'biology', 'cell biology', 'notes.']) expect(looksLikeUrl(q)).toBe(false);
	});

	it('ranks exact and prefix matches first, then recent, and skips the current page and templates', () => {
		const docs = Object.fromEntries([
			doc('1', 'Cell biology', { last_opened_at: '2026-01-03' }),
			doc('2', 'Biology', { last_opened_at: '2026-01-01' }),
			doc('3', 'Biology notes', { last_opened_at: '2026-01-02' }),
			doc('4', 'Biology template', { is_template: true }),
			doc('5', 'Biology current')
		].map((d) => [d.id, d]));
		expect(findPages(docs, 'biology', '5').map((p) => p.id)).toEqual(['2', '3', '1']);
		expect(findPages(docs, '', '5').map((p) => p.id)).toEqual(['1', '3', '2']);
		expect(findPages(docs, 'zzz', null)).toEqual([]);
	});

	it('shows where a page lives', () => {
		const docs = Object.fromEntries([doc('a', 'School'), doc('b', 'Bio', { parent: 'a' }), doc('c', 'Cells', { parent: 'b' })].map((d) => [d.id, d]));
		expect(findPages(docs, 'cells', null)[0].path).toBe('School / Bio');
	});
});
