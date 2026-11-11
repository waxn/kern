import { api } from '#lib/api.ts';
import { debounce } from '#lib/util.ts';

export interface Prefs {
	// Synced to the server so they follow you between browsers.
	theme: 'dark' | 'light' | 'system';
	accent: string;
	font: 'sans' | 'serif' | 'mono';
	editorWidth: 'narrow' | 'normal' | 'wide' | 'full';
	density: 'comfortable' | 'compact';
	recentSearches: string[];
	editorSize: 'small' | 'medium' | 'large';
	defaultBlock: 'paragraph' | 'bullet';
	autosaveDelay: number;
	openIn: 'current' | 'tab';
	shortcuts: Record<string, string>;
	sidebarShow: { favorites: boolean; recent: boolean; databases: boolean };
	savedSearches: { id: string; name: string; q: string; kind: string }[];
	// Per-browser interface state.
	sidebarOpen: boolean;
	sidebarWidth: number;
	panelOpen: boolean;
	expanded: Record<string, boolean>;
	sections: Record<string, boolean>;
	tabs: string[];
	activeTab: number;
}

const SYNCED: (keyof Prefs)[] = [
	'theme', 'accent', 'font', 'editorWidth', 'density', 'recentSearches', 'editorSize', 'defaultBlock',
	'autosaveDelay', 'openIn', 'shortcuts', 'sidebarShow', 'savedSearches'
];

export const SHORTCUT_ACTIONS: [string, string, string][] = [
	['search', 'Search and quick switch', 'Mod+K'],
	['newPage', 'New page', 'Alt+N'],
	['toggleSidebar', 'Toggle sidebar', 'Mod+\\'],
	['togglePanel', 'Toggle page details', 'Mod+Shift+\\'],
	['closeTab', 'Close tab', 'Alt+W'],
	['nextTab', 'Next tab', 'Alt+]'],
	['prevTab', 'Previous tab', 'Alt+['],
	['tasks', 'Open tasks', 'Alt+T'],
	['review', 'Review flashcards', 'Alt+R'],
	['home', 'Go home', 'Alt+H']
];

/** "Mod+Shift+K" style name for a key event (Mod = Ctrl, or ⌘ on a Mac). */
export function comboOf(e: KeyboardEvent): string {
	const mac = /Mac|iPhone|iPad/.test(navigator.platform);
	const parts = [];
	if (mac ? e.metaKey : e.ctrlKey) parts.push('Mod');
	if (e.shiftKey) parts.push('Shift');
	if (e.altKey) parts.push('Alt');
	let k = e.code.startsWith('Key') ? e.code.slice(3) : e.code.startsWith('Digit') ? e.code.slice(5)
		: ({ Backslash: '\\', BracketLeft: '[', BracketRight: ']', Slash: '/', Period: '.', Comma: ',', Semicolon: ';', Quote: "'", Minus: '-', Equal: '=', Backquote: '`', Space: 'Space' } as Record<string, string>)[e.code] ?? e.key;
	if (k.length === 1) k = k.toUpperCase();
	parts.push(k);
	return parts.join('+');
}

export function shortcut(action: string): string {
	return prefs.shortcuts?.[action] ?? SHORTCUT_ACTIONS.find((a) => a[0] === action)?.[2] ?? '';
}
const KEY = 'kern:prefs';

const defaults: Prefs = {
	theme: 'dark',
	accent: '',
	font: 'sans',
	editorWidth: 'normal',
	density: 'comfortable',
	recentSearches: [],
	editorSize: 'medium',
	defaultBlock: 'paragraph',
	autosaveDelay: 600,
	openIn: 'current',
	shortcuts: {},
	sidebarShow: { favorites: true, recent: true, databases: true },
	savedSearches: [],
	sidebarOpen: true,
	sidebarWidth: 260,
	panelOpen: false,
	expanded: {},
	sections: {},
	tabs: ['/'],
	activeTab: 0
};

function readLocal(): Prefs {
	try {
		return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') };
	} catch {
		return { ...defaults };
	}
}

export const prefs = $state<Prefs>(readLocal());

const pushRemote = debounce(() => {
	const synced: Record<string, unknown> = {};
	for (const k of SYNCED) synced[k] = prefs[k];
	api.patch('/settings', { prefs: synced }).catch(() => {});
}, 800);

let lastSynced = '';

/** Persist the current preferences (call from a root $effect). */
export function persistPrefs() {
	const snapshot = JSON.stringify(prefs);
	try {
		localStorage.setItem(KEY, snapshot);
	} catch {
		/* storage unavailable */
	}
	const synced = JSON.stringify(SYNCED.map((k) => prefs[k]));
	if (lastSynced && synced !== lastSynced) pushRemote();
	lastSynced = synced;
}

export async function loadRemotePrefs() {
	try {
		const all = await api.get<{ prefs?: Partial<Prefs> }>('/settings');
		if (all.prefs) for (const k of SYNCED) if (k in all.prefs) (prefs as any)[k] = all.prefs[k];
	} catch {
		/* keep local */
	}
	lastSynced = JSON.stringify(SYNCED.map((k) => prefs[k]));
}

export function resolvedTheme(): 'dark' | 'light' {
	if (prefs.theme !== 'system') return prefs.theme;
	return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
