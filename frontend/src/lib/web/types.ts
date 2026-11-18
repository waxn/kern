/** Watching bookmarks for changes, and their saved history (see backend/notes/monitor.py). */

export type Mode = 'auto' | 'posts' | 'price' | 'content';
export interface Price { amount: number; currency: string; display: string; source: 'structured' | 'text' }
export interface PostRef { title: string; url: string; date: string }

export type Change =
	| { type: 'posts'; count: number; added: PostRef[]; at?: string }
	| { type: 'price'; old: Price; new: Price; at?: string }
	| { type: 'content'; added: number; removed: number; snippets: string[]; at?: string };

/** On list items: only set for watched bookmarks or ones with unseen changes. */
export interface MonitorSummary {
	enabled: boolean; mode: Mode; unseen: number; last_changed_at: string | null; price: string; error: boolean;
}

export interface Monitor {
	enabled: boolean; mode: Mode; resolved_mode: '' | Exclude<Mode, 'auto'>; interval: number; archive: boolean;
	error: string; last_checked_at: string | null; next_check_at: string | null; last_changed_at: string | null;
	unseen: number; last_change: Change | null; price: Price | null;
	price_history: { at: string; amount: number; display: string }[]; latest: PostRef[]; feed_url: string;
}

export interface Version {
	id: number; created_at: string; trigger: 'saved' | 'manual' | 'change' | 'refetch'; url: string; title: string;
	change: Change | Record<string, never>; price: string; size: number; has_page: boolean; prev: number | null;
}

export interface DiffOp { op: 'eq' | 'add' | 'del' | 'skip'; lines?: string[]; count?: number }
export interface Diff { from: number | null; to: number; from_at?: string; to_at?: string; added: number; removed: number; ops: DiffOp[] }

export const MODES: [Mode, string][] = [['auto', 'Automatic'], ['posts', 'New posts'], ['price', 'Price'], ['content', 'Any change']];
export const MODE_LABEL: Record<string, string> = { posts: 'new posts', price: 'the price', content: 'any change' };
export const INTERVALS: [number, string][] = [
	[60, 'Every hour'], [180, 'Every 3 hours'], [360, 'Every 6 hours'], [720, 'Twice a day'],
	[1440, 'Daily'], [4320, 'Every 3 days'], [10080, 'Weekly']
];
export const TRIGGER_LABEL: Record<Version['trigger'], string> = {
	saved: 'Bookmarked', manual: 'Snapshot', change: 'Change found', refetch: 'Re-fetched'
};

const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`;

/** One line describing a change, e.g. "2 new posts" or "Price $20 → $17.50". */
export function changeText(c: Change | Record<string, never> | null | undefined): string {
	if (!c || !('type' in c)) return '';
	if (c.type === 'posts') return plural(c.count, 'new post');
	if (c.type === 'price') return `Price ${c.old.display} → ${c.new.display}`;
	const parts = [];
	if (c.added) parts.push(`+${c.added}`);
	if (c.removed) parts.push(`−${c.removed}`);
	return `Text changed (${parts.join(' / ')} ${c.added + c.removed === 1 ? 'line' : 'lines'})`;
}

export function priceDirection(c: Change | Record<string, never> | null | undefined): 'up' | 'down' | '' {
	if (!c || !('type' in c) || c.type !== 'price') return '';
	return c.new.amount < c.old.amount ? 'down' : 'up';
}
