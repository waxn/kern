import type { Recurrence } from '../types.ts';

export interface Parsed {
	title: string;
	due: string | null;
	priority: number;
	tags: string[];
	recurrence: Recurrence | null;
	tokens: string[]; // recognised pieces, for the preview chips
}

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

function iso(d: Date): string {
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function plus(days: number, from = new Date()): string {
	const d = new Date(from);
	d.setDate(d.getDate() + days);
	return iso(d);
}

/** Quick-add syntax: "Pay rent tomorrow !2 #home every month". */
export function parseTask(input: string, now = new Date()): Parsed {
	let text = ` ${input} `;
	const out: Parsed = { title: '', due: null, priority: 0, tags: [], recurrence: null, tokens: [] };
	const take = (re: RegExp, fn: (m: RegExpMatchArray) => void) => {
		const m = text.match(re);
		if (!m) return;
		fn(m);
		out.tokens.push(m[0].trim());
		text = text.replace(m[0], ' ');
	};

	take(/\s!(1|2|3|low|med|medium|high)(?=\s)/i, (m) => {
		const v = m[1].toLowerCase();
		out.priority = v === 'low' ? 1 : v.startsWith('med') ? 2 : v === 'high' ? 3 : Number(v);
	});
	let m: RegExpMatchArray | null;
	while ((m = text.match(/\s#([\p{L}\d_-]+)(?=\s)/u))) {
		out.tags.push(m[1]);
		out.tokens.push('#' + m[1]);
		text = text.replace(m[0], ' ');
	}
	take(/\s(?:every\s+(\d+)\s+(day|week|month|year)s?|every\s+(day|week|month|year)|(daily|weekly|monthly|yearly))(?=\s)/i, (m) => {
		const map: Record<string, Recurrence['freq']> = { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' };
		const freq = (m[2] || m[3] || map[m[4]?.toLowerCase()])?.toLowerCase() as Recurrence['freq'];
		out.recurrence = { freq, interval: m[1] ? Number(m[1]) : 1 };
	});
	take(/\s(\d{4}-\d{2}-\d{2})(?=\s)/, (m) => (out.due = m[1]));
	if (!out.due) take(/\s(today|tod)(?=\s)/i, () => (out.due = iso(now)));
	if (!out.due) take(/\s(tomorrow|tmr|tmrw)(?=\s)/i, () => (out.due = plus(1, now)));
	if (!out.due) take(/\snext\s+week(?=\s)/i, () => (out.due = plus(7, now)));
	if (!out.due) take(/\sin\s+(\d+)\s+(day|week)s?(?=\s)/i, (m) => (out.due = plus(Number(m[1]) * (m[2].toLowerCase() === 'week' ? 7 : 1), now)));
	if (!out.due)
		take(/\s(?:on\s+)?(sun|mon|tue|wed|thu|fri|sat)[a-z]*(?=\s)/i, (m) => {
			const target = DAYS.indexOf(m[1].toLowerCase());
			const diff = (target - now.getDay() + 7) % 7 || 7;
			out.due = plus(diff, now);
		});
	if (out.recurrence && !out.due) out.due = iso(now);
	out.title = text.replace(/\s+/g, ' ').trim();
	return out;
}
