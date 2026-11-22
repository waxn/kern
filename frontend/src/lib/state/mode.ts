// Kern has two modes, like Claude's Chat and Code: Notes (pages, tasks, cards…)
// and Mail. Each has its own sidebar; Home and a few pages belong to both and
// keep whichever mode you were in.
import { goto } from '$app/navigation';
import { prefs } from './prefs.svelte';

export type Mode = 'notes' | 'mail';

/** Pages shared by both modes. */
const SHARED = ['/', '/settings', '/intelligence'];

export function isShared(path: string): boolean {
	return SHARED.includes(path);
}

export function modeFor(path: string): Mode {
	if (path === '/mail' || path.startsWith('/mail/')) return 'mail';
	if (isShared(path)) return prefs.appMode;
	return 'notes';
}

/** After every navigation: remember the mode and where it was left. */
export function trackMode(path: string, search = '') {
	const m = modeFor(path);
	if (prefs.appMode !== m) prefs.appMode = m;
	if (isShared(path)) return;
	if (m === 'mail') prefs.lastMailPath = path + search;
	else prefs.lastNotesPath = path + search;
}

export function switchMode(to: Mode) {
	prefs.appMode = to;
	const target = to === 'mail' ? prefs.lastMailPath || '/mail/inbox' : prefs.lastNotesPath || '/';
	goto(target.startsWith(to === 'mail' ? '/mail' : '/') ? target : to === 'mail' ? '/mail/inbox' : '/');
}
