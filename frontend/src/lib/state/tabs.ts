import { goto } from '$app/navigation';
import { newPage } from '#lib/actions.ts';
import { modeFor } from './mode.ts';
import { prefs } from './prefs.svelte';
import { ws } from './workspace.svelte';

export function tabInfo(path: string): { title: string; icon: string } {
	const doc = path.match(/^\/doc\/([^/]+)/);
	if (doc) {
		const d = ws.docs[doc[1]];
		return { title: d ? d.title || 'Untitled' : 'Page', icon: d?.icon ?? '' };
	}
	const tag = path.match(/^\/tag\/([^/]+)/);
	if (tag) return { title: '#' + (ws.tagMap[tag[1]]?.name ?? 'tag'), icon: '' };
	const repo = path.match(/^\/git\/([^/]+)/);
	if (repo) return { title: repo[1], icon: '' };
	if (path === '/mail' || path.startsWith('/mail/')) {
		const view = path.split('/')[2] ?? 'inbox';
		const pages: Record<string, string> = { packages: 'Packages', scheduled: 'Scheduled', files: 'Files', blocklist: 'Blocked senders', stats: 'Stats', starred: 'Starred', all: 'All mail', search: 'Search', snoozed: 'Snoozed', drafts: 'Drafts', sent: 'Sent', archive: 'Archive', junk: 'Junk', trash: 'Trash' };
		return { title: 'Mail · ' + (pages[view] ?? (view === 'inbox' ? 'Inbox' : 'Folder')), icon: '' };
	}
	const names: Record<string, string> = {
		'/': 'Home', '/tags': 'Tags', '/trash': 'Trash', '/archive': 'Archive', '/settings': 'Settings',
		'/templates': 'Templates', '/graph': 'Graph', '/tasks': 'Tasks', '/cards': 'Flashcards', '/review': 'Review',
		'/files': 'Files', '/developer': 'API', '/search': 'Search', '/intelligence': 'Intelligence', '/git': 'Git'
	};
	return { title: names[path] ?? 'Kern', icon: '' };
}

/** Called on every navigation: keep the tab strip in step with the URL. */
export function syncTabs(path: string) {
	const i = prefs.tabs.indexOf(path);
	if (i >= 0) prefs.activeTab = i;
	else if (prefs.tabs.length === 0) {
		prefs.tabs = [path];
		prefs.activeTab = 0;
	} else {
		const at = Math.min(prefs.activeTab, prefs.tabs.length - 1);
		prefs.tabs[at] = path;
		prefs.activeTab = at;
	}
}

export function openTab(path: string, activate = true) {
	const i = prefs.tabs.indexOf(path);
	if (i < 0) prefs.tabs.splice(prefs.activeTab + 1, 0, path);
	if (activate) {
		prefs.activeTab = prefs.tabs.indexOf(path);
		goto(path);
	}
}

/** Open a path honouring ctrl/cmd/middle click for "new tab". */
export function open(path: string, e?: MouseEvent | KeyboardEvent) {
	const modified = !!e && (e.ctrlKey || e.metaKey || (e instanceof MouseEvent && e.button === 1));
	// "Open pages in new tabs" flips the meaning of a modified click.
	const newTab = prefs.openIn === 'tab' && path.startsWith('/doc/') && !prefs.tabs.includes(path) ? !modified : modified;
	if (newTab) openTab(path, !e?.shiftKey);
	else goto(path);
}

export function closeTab(index: number) {
	if (prefs.tabs.length <= 1) {
		prefs.tabs = ['/'];
		prefs.activeTab = 0;
		goto('/');
		return;
	}
	const wasActive = index === prefs.activeTab;
	prefs.tabs.splice(index, 1);
	if (index < prefs.activeTab) prefs.activeTab--;
	if (wasActive) {
		prefs.activeTab = Math.min(index, prefs.tabs.length - 1);
		goto(prefs.tabs[prefs.activeTab]);
	}
}

/** Drop tabs that point at documents which no longer exist. */
export function closeTabsFor(ids: string[]) {
	const gone = new Set(ids.map((id) => `/doc/${id}`));
	const current = prefs.tabs[prefs.activeTab];
	const kept = prefs.tabs.filter((p) => !gone.has(p));
	if (kept.length === prefs.tabs.length) return;
	prefs.tabs = kept.length ? kept : ['/'];
	const i = prefs.tabs.indexOf(current);
	prefs.activeTab = i >= 0 ? i : Math.min(prefs.activeTab, prefs.tabs.length - 1);
	if (i < 0) goto(prefs.tabs[prefs.activeTab]);
}

/** The "+" next to where you are: a new tab (then the tab strip shows). In
 *  Notes it is a new page; in Mail, Home (or the Inbox when Home is open). */
export function newTab(path: string) {
	if (modeFor(path) === 'notes') {
		newPage(null, true);
		return;
	}
	openTab(path === '/' ? '/mail/inbox' : '/');
}
