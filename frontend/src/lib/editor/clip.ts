// What the editor puts on the clipboard when blocks are copied, and what a paste does with it.
//
// Copying blocks stores their content (to paste a copy) and where they came from (the page and
// the block ids). Pasting into the same page makes a copy, as always. Pasting into a different
// page makes a live embed of those blocks: it shows the original, edits go both ways, and its
// last known content is kept so the embed can still show something if the original is deleted.
import type { Block, BlockType } from '#lib/types.ts';
import { escapeHtml } from '#lib/util.ts';
import type { BlockTree } from './doc.svelte';
import { sanitizeInline } from './paste';

export const KERN_MIME = 'application/x-kern-blocks';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TYPES = new Set<string>([
	'paragraph', 'h1', 'h2', 'h3', 'bullet', 'numbered', 'todo', 'toggle', 'quote', 'callout', 'divider', 'code',
	'equation', 'table', 'image', 'video', 'audio', 'file', 'bookmark', 'embed', 'synced', 'database'
]);
/** Embeds bigger than this keep no offline copy (the server applies the same limit). */
export const SNAPSHOT_LIMIT = 400;

export interface Clip {
	/** The page the blocks were copied from (null for clipboards from older versions). */
	doc: string | null;
	/** The copied top-level blocks, in page order. */
	ids: string[];
	trees: BlockTree[];
}

export function encodeClip(doc: string, ids: string[], trees: BlockTree[]): string {
	return JSON.stringify({ v: 2, doc, ids, trees });
}

/** Read a Kern clipboard (this format or the older bare list of trees). Unknown or unsafe parts are dropped. */
export function decodeClip(raw: string): Clip | null {
	let data: any;
	try {
		data = JSON.parse(raw);
	} catch {
		return null;
	}
	if (Array.isArray(data)) return { doc: null, ids: [], trees: cleanTrees(data) };
	if (!data || typeof data !== 'object' || !Array.isArray(data.trees)) return null;
	const doc = typeof data.doc === 'string' && UUID.test(data.doc) ? data.doc : null;
	const ids = Array.isArray(data.ids) ? data.ids.filter((x: unknown) => typeof x === 'string' && UUID.test(x)) : [];
	return { doc, ids: doc ? ids : [], trees: cleanTrees(data.trees) };
}

/**
 * Pasting into another page embeds the original blocks; pasting into the same page copies them.
 * Blocks that are themselves embeds or synced blocks are copied (an embed of an embed helps nobody).
 */
export function pasteMode(clip: Clip, targetDoc: string): 'copy' | 'embed' {
	if (!clip.doc || clip.doc === targetDoc || !clip.ids.length || clip.ids.length !== clip.trees.length) return 'copy';
	if (clip.trees.every((t) => t.type === 'embed' || t.type === 'synced')) return 'copy';
	return 'embed';
}

/** The embed block a cross-page paste inserts. */
export function embedTree(clip: Clip): BlockTree {
	return {
		type: 'embed', html: '', collapsed: false, children: [],
		props: { kind: 'range', doc: clip.doc, targets: [...clip.ids], snapshot: snapshotOf(clip.trees) }
	};
}

/** Trees small enough to keep as an embed's fallback copy, or null. */
export function snapshotOf(trees: BlockTree[]): BlockTree[] | null {
	let n = 0;
	const count = (ts: BlockTree[]) => ts.forEach((t) => { n++; count(t.children); });
	count(trees);
	return n && n <= SNAPSHOT_LIMIT ? stripTasks(trees) : null;
}

/** A copy must not take over the original's linked task (the task stays with the original block). */
export function stripTasks(trees: BlockTree[]): BlockTree[] {
	return trees.map((t) => {
		const { task: _task, ...props } = t.props ?? {};
		return { ...t, props, children: stripTasks(t.children ?? []) };
	});
}

const SAFE_URL = /^(https?:\/\/|\/media\/|data:image\/(png|jpe?g|gif|webp);)/i;

function inlineHtml(html: string): string {
	const t = document.createElement('template');
	t.innerHTML = html;
	return sanitizeInline(t.content);
}

/** Clipboard data can come from anywhere: keep known block types, safe inline HTML and safe links. */
export function cleanTrees(items: unknown, depth = 0): BlockTree[] {
	if (!Array.isArray(items) || depth > 30) return [];
	const out: BlockTree[] = [];
	for (const raw of items) {
		if (!raw || typeof raw !== 'object') continue;
		const t = raw as Record<string, any>;
		if (!TYPES.has(t.type)) continue;
		const type = t.type as BlockType;
		const html = typeof t.html === 'string' ? t.html : '';
		const props: Record<string, any> = t.props && typeof t.props === 'object' && !Array.isArray(t.props) ? { ...t.props } : {};
		for (const k of ['url', 'thumbnail', 'image']) if (k in props && !(typeof props[k] === 'string' && SAFE_URL.test(props[k]))) delete props[k];
		if (type === 'table' && Array.isArray(props.rows))
			props.rows = props.rows.filter(Array.isArray).map((r: unknown[]) => r.map((c) => inlineHtml(String(c ?? ''))));
		if (type === 'embed' && props.snapshot) props.snapshot = cleanTrees(props.snapshot, depth + 1);
		out.push({
			type, props, collapsed: !!t.collapsed,
			// Code keeps its text exactly (newlines included); everything else is inline rich text.
			html: type === 'code' ? escapeHtml(textOf(html)) : inlineHtml(html),
			children: cleanTrees(t.children, depth + 1)
		});
	}
	return out;
}

function textOf(html: string): string {
	const t = document.createElement('template');
	t.innerHTML = html.replace(/<br\s*\/?>/gi, '\n');
	return t.content.textContent ?? '';
}

/** Trees as flat blocks, for read-only rendering (StaticBlocks). */
export function treesToBlocks(trees: BlockTree[]): Block[] {
	const out: Block[] = [];
	let n = 0;
	const walk = (ts: BlockTree[], parent: string | null) =>
		ts.forEach((t, i) => {
			const id = `snap-${n++}`;
			out.push({ id, parent, position: i + 1, type: t.type, html: t.html, props: t.props ?? {}, collapsed: t.collapsed });
			walk(t.children ?? [], id);
		});
	walk(trees, null);
	return out;
}
