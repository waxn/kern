import { api } from '../api.ts';
import type { Recurrence } from '../types.ts';

export const tzo = () => new Date().getTimezoneOffset();

export function localDate(offsetDays = 0): string {
	const d = new Date();
	d.setDate(d.getDate() + offsetDays);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function fmtInterval(days: number | undefined): string {
	if (days === undefined) return '';
	const mins = days * 1440;
	if (mins < 60) return `${Math.max(1, Math.round(mins))}m`;
	if (mins < 1440) return `${Math.round(mins / 60)}h`;
	if (days < 30) return `${Math.round(days)}d`;
	if (days < 365) return `${(days / 30.44).toFixed(days < 90 ? 1 : 0).replace(/\.0$/, '')}mo`;
	return `${(days / 365.25).toFixed(1).replace(/\.0$/, '')}y`;
}

export function fmtDue(due: string | null, today = localDate()): string {
	if (!due) return '';
	const d = due.slice(0, 10);
	if (d === today) return 'Today';
	if (d === localDate(1)) return 'Tomorrow';
	if (d === localDate(-1)) return 'Yesterday';
	const date = new Date(d + 'T00:00');
	const diff = Math.round((date.getTime() - new Date(today + 'T00:00').getTime()) / 86400000);
	if (diff > 0 && diff < 7) return date.toLocaleDateString(undefined, { weekday: 'long' });
	return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
}

export function fmtRecurrence(r: Recurrence | null): string {
	if (!r) return '';
	const unit = { day: 'day', week: 'week', month: 'month', year: 'year' }[r.freq];
	return r.interval === 1 ? `Every ${unit}` : `Every ${r.interval} ${unit}s`;
}

export const PRIORITY = ['None', 'Low', 'Medium', 'High'];
export const PRIORITY_COLOR = ['', 'blue', 'orange', 'red'];

/** Sidebar badge counts, refreshed when something changes. */
class Counts {
	due = $state(0);
	today = $state(0);
	private timer: ReturnType<typeof setTimeout> | undefined;

	async load() {
		try {
			const [s, t] = await Promise.all([
				api.get<{ due_today: number; new_available: number }>(`/cards/stats?tzo=${tzo()}`),
				api.get<{ today: number; overdue: number }>(`/tasks/summary?today=${localDate()}`)
			]);
			this.due = s.due_today + s.new_available;
			this.today = t.today + t.overdue;
		} catch {
			/* offline */
		}
	}

	refresh() {
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.load(), 400);
	}
}

export const counts = new Counts();
