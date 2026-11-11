import type { DbRow, FilterGroup, FilterRule, PropDef, PropType } from '../types.ts';
import { ws } from '../state/workspace.svelte.ts';

export const TITLE = 'title';

export interface Col {
	id: string;
	name: string;
	type: PropType | 'title';
	def?: PropDef;
}

export function titleOf(row: DbRow): string {
	return ws.docs[row.id]?.title ?? row.title;
}

export function rawValue(row: DbRow, col: Col): any {
	if (col.type === 'title') return titleOf(row);
	return row.values[col.id];
}

function optionName(def: PropDef | undefined, id: string): string {
	return def?.options.find((o) => o.id === id)?.name ?? '';
}

/** A comparable/searchable representation of a cell. */
export function plainValue(row: DbRow, col: Col): string | number | boolean | null | string[] {
	const v = rawValue(row, col);
	if (v === null || v === undefined || v === '') return null;
	switch (col.type) {
		case 'select':
		case 'status':
			return optionName(col.def, v) || null;
		case 'multi_select':
			return (v as string[]).map((x) => optionName(col.def, x)).filter(Boolean);
		case 'relation':
			return (v as string[]).map((x) => ws.docs[x]?.title || 'Untitled');
		case 'formula':
			return typeof v === 'object' && v && 'error' in v ? null : v;
		default:
			return v;
	}
}

function isEmpty(v: any): boolean {
	return v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0) || v === false;
}

function dayOf(v: any): string {
	return typeof v === 'string' ? v.slice(0, 10) : '';
}

export function todayStr(offset = 0): string {
	const d = new Date();
	d.setDate(d.getDate() + offset);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function resolveDate(value: any): string {
	if (value === 'today') return todayStr();
	if (value === 'tomorrow') return todayStr(1);
	if (value === 'yesterday') return todayStr(-1);
	return String(value ?? '');
}

function matchRule(row: DbRow, rule: FilterRule, cols: Record<string, Col>): boolean {
	const col = cols[rule.prop];
	if (!col) return true;
	const raw = rawValue(row, col);
	const v = plainValue(row, col);
	const op = rule.op;
	if (op === 'empty') return isEmpty(col.type === 'boolean' ? null : v);
	if (op === 'not_empty') return !isEmpty(col.type === 'boolean' ? null : v);
	const t = col.type;
	const want = rule.value;
	if (want === undefined || want === null || want === '') {
		if (t !== 'boolean') return true; // incomplete rule: ignore
	}
	if (t === 'boolean') return !!raw === (want === true || want === 'true');
	if (t === 'select' || t === 'status') {
		const ids = Array.isArray(want) ? want : [want];
		return op === 'is_not' ? !ids.includes(raw) : ids.includes(raw);
	}
	if (t === 'multi_select' || t === 'relation') {
		const list: string[] = Array.isArray(raw) ? raw : [];
		const ids = Array.isArray(want) ? want : [want];
		const hit = ids.some((x) => list.includes(x));
		return op === 'not_contains' ? !hit : hit;
	}
	if (t === 'date' || t === 'created_time' || t === 'last_edited_time') {
		const d = dayOf(raw);
		const w = resolveDate(want);
		if (!d) return false;
		if (op === 'is') return d === w;
		if (op === 'before') return d < w;
		if (op === 'after') return d > w;
		if (op === 'on_or_before') return d <= w;
		if (op === 'on_or_after') return d >= w;
		if (op === 'past_week') return d >= todayStr(-7) && d <= todayStr();
		if (op === 'next_week') return d >= todayStr() && d <= todayStr(7);
		return true;
	}
	const numeric = t === 'number' || t === 'rating' || typeof v === 'number';
	if (numeric && ['=', '!=', '>', '<', '>=', '<='].includes(op)) {
		if (v === null || v === undefined || typeof v === 'object') return false;
		const a = Number(v);
		const b = Number(want);
		return op === '=' ? a === b : op === '!=' ? a !== b : op === '>' ? a > b : op === '<' ? a < b : op === '>=' ? a >= b : a <= b;
	}
	const s = (Array.isArray(v) ? v.join(', ') : String(v ?? '')).toLowerCase();
	const w = String(want).toLowerCase();
	if (op === 'contains') return s.includes(w);
	if (op === 'not_contains') return !s.includes(w);
	if (op === 'is') return s === w;
	if (op === 'is_not') return s !== w;
	if (op === 'starts_with') return s.startsWith(w);
	if (op === 'ends_with') return s.endsWith(w);
	return true;
}

export function matchGroup(row: DbRow, group: FilterGroup, cols: Record<string, Col>): boolean {
	if (!group.rules.length) return true;
	const test = (r: FilterRule | FilterGroup) =>
		'rules' in r ? matchGroup(row, r, cols) : matchRule(row, r, cols);
	return group.op === 'or' ? group.rules.some(test) : group.rules.every(test);
}

export function compareRows(a: DbRow, b: DbRow, col: Col): number {
	let x = plainValue(a, col);
	let y = plainValue(b, col);
	if (col.type === 'select' || col.type === 'status') {
		// Order by option position, as Notion does.
		const idx = (row: DbRow) => col.def!.options.findIndex((o) => o.id === rawValue(row, col));
		x = idx(a);
		y = idx(b);
		if (x < 0) x = null;
		if (y < 0) y = null;
	}
	if (Array.isArray(x)) x = x.join(', ');
	if (Array.isArray(y)) y = y.join(', ');
	if (x === null || x === undefined || x === '') return y === null || y === undefined || y === '' ? 0 : 1;
	if (y === null || y === undefined || y === '') return -1;
	if (typeof x === 'number' && typeof y === 'number') return x - y;
	if (typeof x === 'boolean' || typeof y === 'boolean') return Number(!!x) - Number(!!y);
	return String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: 'base' });
}

export const OPS: Record<string, [string, string][]> = {
	text: [['contains', 'contains'], ['not_contains', 'does not contain'], ['is', 'is'], ['is_not', 'is not'], ['starts_with', 'starts with'], ['ends_with', 'ends with'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
	number: [['=', '='], ['!=', '≠'], ['>', '>'], ['<', '<'], ['>=', '≥'], ['<=', '≤'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
	date: [['is', 'is'], ['before', 'is before'], ['after', 'is after'], ['on_or_before', 'is on or before'], ['on_or_after', 'is on or after'], ['past_week', 'is within the past week'], ['next_week', 'is within the next week'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
	select: [['is', 'is'], ['is_not', 'is not'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
	multi: [['contains', 'contains'], ['not_contains', 'does not contain'], ['empty', 'is empty'], ['not_empty', 'is not empty']],
	boolean: [['is', 'is']]
};

export function opsFor(t: Col['type']): [string, string][] {
	if (t === 'number' || t === 'rating') return OPS.number;
	if (t === 'date' || t === 'created_time' || t === 'last_edited_time') return OPS.date;
	if (t === 'select' || t === 'status') return OPS.select;
	if (t === 'multi_select' || t === 'relation') return OPS.multi;
	if (t === 'boolean') return OPS.boolean;
	return OPS.text;
}
