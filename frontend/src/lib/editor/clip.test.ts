import { describe, expect, it } from 'vitest';
import { cleanTrees, decodeClip, embedTree, encodeClip, pasteMode, snapshotOf, SNAPSHOT_LIMIT, stripTasks, treesToBlocks } from './clip';
import type { BlockTree } from './doc.svelte';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
const X = '33333333-3333-4333-8333-333333333333';
const Y = '44444444-4444-4444-8444-444444444444';
const t = (type: any, html = '', children: BlockTree[] = [], props: Record<string, any> = {}): BlockTree => ({ type, html, props, collapsed: false, children });

describe('kern clipboard', () => {
	it('round-trips the source page and block ids', () => {
		const trees = [t('h2', '<b>Title</b>'), t('bullet', 'one', [t('bullet', 'nested')])];
		const clip = decodeClip(encodeClip(A, [X, Y], trees))!;
		expect(clip.doc).toBe(A);
		expect(clip.ids).toEqual([X, Y]);
		expect(clip.trees[0]).toMatchObject({ type: 'h2', html: '<b>Title</b>' });
		expect(clip.trees[1].children[0].html).toBe('nested');
	});

	it('reads the older bare list of trees as a plain copy', () => {
		const clip = decodeClip(JSON.stringify([t('paragraph', 'hi')]))!;
		expect(clip.doc).toBeNull();
		expect(pasteMode(clip, B)).toBe('copy');
	});

	it('copies on the same page and embeds on another one', () => {
		const clip = decodeClip(encodeClip(A, [X], [t('paragraph', 'x')]))!;
		expect(pasteMode(clip, A)).toBe('copy');
		expect(pasteMode(clip, B)).toBe('embed');
	});

	it('copies a cut (no ids) and blocks that are already embeds', () => {
		expect(pasteMode(decodeClip(encodeClip(A, [], [t('paragraph', 'x')]))!, B)).toBe('copy');
		expect(pasteMode(decodeClip(encodeClip(A, [X], [t('embed', '', [], { kind: 'doc', target: B })]))!, B)).toBe('copy');
	});

	it('drops ids that are not uuids and rejects junk', () => {
		const clip = decodeClip(JSON.stringify({ v: 2, doc: A, ids: [X, '../etc', 5], trees: [t('paragraph', 'x')] }))!;
		expect(clip.ids).toEqual([X]);
		expect(decodeClip('not json')).toBeNull();
		expect(decodeClip(JSON.stringify({ doc: 'nope', trees: [] }))!.doc).toBeNull();
	});

	it('builds a range embed with the content as its offline copy', () => {
		const clip = decodeClip(encodeClip(A, [X], [t('todo', 'pay', [], { checked: false, task: 'task-1' })]))!;
		const e = embedTree(clip);
		expect(e.type).toBe('embed');
		expect(e.props).toMatchObject({ kind: 'range', doc: A, targets: [X] });
		expect(e.props.snapshot[0].props).toEqual({ checked: false });
	});
});

describe('cleaning pasted trees', () => {
	it('keeps formatting, highlights, notes and refs but strips scripts and handlers', () => {
		const html = '<b>bold</b> <mark data-bg="yellow">hi</mark> <mark data-note="n">x</mark>' +
			`<a class="ref" data-ref="doc:${A}" href="/doc/${A}">P</a><img src=x onerror="alert(1)"><script>alert(2)</script>`;
		const [c] = cleanTrees([t('paragraph', html)]);
		expect(c.html).toContain('<b>bold</b>');
		expect(c.html).toContain('<mark data-bg="yellow">hi</mark>');
		expect(c.html).toContain('<mark data-note="n">x</mark>');
		expect(c.html).toContain(`data-ref="doc:${A}"`);
		expect(c.html).not.toMatch(/onerror|script|<img/);
	});

	it('keeps code exactly, drops unknown types and unsafe links', () => {
		const out = cleanTrees([
			t('code', 'a &lt; b<br>\n  c'),
			t('evil' as any, 'x'),
			t('bookmark', '', [], { url: 'javascript:alert(1)', title: 'x' }),
			t('image', '', [], { url: 'https://example.org/a.png' })
		]);
		expect(out.map((o) => o.type)).toEqual(['code', 'bookmark', 'image']);
		expect(out[0].html).toBe('a &lt; b\n\n  c');
		expect(out[1].props.url).toBeUndefined();
		expect(out[2].props.url).toBe('https://example.org/a.png');
	});

	it('keeps text links to pages', () => {
		const [c] = cleanTrees([t('paragraph', `see <a class="doclink" data-doc="${A}" href="/doc/${A}"><i>this</i></a>`)]);
		expect(c.html).toBe(`see <a class="doclink" data-doc="${A}" href="/doc/${A}"><i>this</i></a>`);
	});
});

describe('snapshots', () => {
	it('keeps no copy of very large ranges', () => {
		const many = Array.from({ length: SNAPSHOT_LIMIT + 1 }, () => t('paragraph', 'x'));
		expect(snapshotOf(many)).toBeNull();
		expect(snapshotOf([t('paragraph', 'x')])).toHaveLength(1);
	});

	it('flattens trees for read-only display', () => {
		const blocks = treesToBlocks([t('bullet', 'a', [t('bullet', 'b')]), t('paragraph', 'c')]);
		expect(blocks.map((b) => [b.html, b.parent === null])).toEqual([['a', true], ['b', false], ['c', true]]);
		expect(blocks[1].parent).toBe(blocks[0].id);
	});

	it('strips linked tasks at every level', () => {
		const [top] = stripTasks([t('todo', 'a', [t('todo', 'b', [], { task: '1' })], { task: '2', checked: true })]);
		expect(top.props).toEqual({ checked: true });
		expect(top.children[0].props).toEqual({});
	});
});
