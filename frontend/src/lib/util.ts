export function uid(): string {
	if (crypto.randomUUID) return crypto.randomUUID();
	// Non-secure contexts (plain http on a LAN address) lack randomUUID.
	const b = crypto.getRandomValues(new Uint8Array(16));
	b[6] = (b[6] & 0x0f) | 0x40;
	b[8] = (b[8] & 0x3f) | 0x80;
	const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
	return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function escapeHtml(s: string): string {
	return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
	let t: ReturnType<typeof setTimeout> | undefined;
	const wrapped = (...args: A) => {
		clearTimeout(t);
		t = setTimeout(() => fn(...args), ms);
	};
	wrapped.cancel = () => clearTimeout(t);
	return wrapped;
}

/** Turn FTS highlight markers (\x01 … \x02) into safe <mark> HTML. */
export function highlight(s: string): string {
	return escapeHtml(s).replace(/\x01/g, '<mark>').replace(/\x02/g, '</mark>');
}

export function stripMarks(s: string): string {
	return s.replace(/[\x01\x02]/g, '');
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
export function relTime(iso: string | null | undefined): string {
	if (!iso) return '';
	const diff = (new Date(iso).getTime() - Date.now()) / 1000;
	const abs = Math.abs(diff);
	if (abs < 45) return 'just now';
	if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
	if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
	if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
	return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function fullDate(iso: string | null | undefined): string {
	if (!iso) return '';
	return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function fileSize(n: number): string {
	if (n < 1024) return `${n} B`;
	if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
	if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
	return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
export const modKey = isMac ? '⌘' : 'Ctrl';
export function mod(e: KeyboardEvent | MouseEvent): boolean {
	return isMac ? e.metaKey : e.ctrlKey;
}

export const TAG_COLORS = ['gray', 'brown', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'red'];
