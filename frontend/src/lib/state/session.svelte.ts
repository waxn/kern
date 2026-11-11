import { api, ApiError, hooks } from '#lib/api.ts';

export interface User {
	id: number;
	username: string;
	email: string;
	is_admin: boolean;
	is_active: boolean;
	date_joined: string;
	last_login: string | null;
}

export interface Site {
	needs_setup: boolean;
	site_name: string;
	landing_enabled: boolean;
	signup_mode: 'closed' | 'open' | 'approval';
	allow_git: boolean;
	user: User | null;
}

class Session {
	ready = $state(false);
	unreachable = $state(false);
	site = $state<Site | null>(null);

	get user() {
		return this.site?.user ?? null;
	}
}

export const session = new Session();

const UID_KEY = 'kern:uid';

export async function loadSession() {
	try {
		session.site = await api.get<Site>('/site');
		session.unreachable = false;
		// A different person using this browser must never see the previous person's cached data.
		const uid = session.user ? String(session.user.id) : null;
		const last = safe(() => localStorage.getItem(UID_KEY));
		if (uid && last !== uid) {
			if (last) await wipeLocal();
			safe(() => localStorage.setItem(UID_KEY, uid));
		}
	} catch (e) {
		// Server unreachable: keep the signed-in app usable offline when we know who was here.
		session.unreachable = true;
		if (!session.site && safe(() => localStorage.getItem(UID_KEY)))
			session.site = {
				needs_setup: false, site_name: 'Kern', landing_enabled: false, signup_mode: 'closed', allow_git: true,
				user: { id: Number(localStorage.getItem(UID_KEY)), username: '', email: '', is_admin: false, is_active: true, date_joined: '', last_login: null }
			};
	} finally {
		session.ready = true;
	}
}

function safe<T>(fn: () => T): T | null {
	try {
		return fn();
	} catch {
		return null;
	}
}

/** Forget everything this browser stored for the app (preferences, unsent edits, offline copies). */
export async function wipeLocal() {
	safe(() => {
		for (const k of Object.keys(localStorage)) if (k.startsWith('kern')) localStorage.removeItem(k);
	});
	safe(() => sessionStorage.clear());
	try {
		for (const k of await caches.keys()) if (k.startsWith('kern-data') || k.startsWith('kern-media')) await caches.delete(k);
	} catch {
		/* no cache storage */
	}
}

export async function login(username: string, password: string) {
	const site = await api.post<Site>('/auth/login', { username, password });
	enter(site);
}

export async function signup(username: string, password: string, email: string) {
	const r = await api.post<Site & { pending?: boolean }>('/auth/signup', { username, password, email });
	if (r.pending) return { pending: true };
	enter(r);
	return { pending: false };
}

export async function finishSetup(body: unknown) {
	enter(await api.post<Site>('/setup', body));
}

/** Start the app fresh as this user (a reload resets every in-memory store). */
function enter(site: Site) {
	session.site = site;
	const last = safe(() => localStorage.getItem(UID_KEY));
	const next = String(site.user!.id);
	const go = () => {
		safe(() => localStorage.setItem(UID_KEY, next));
		const target = location.pathname === '/login' || location.pathname === '/signup' ? '/' : location.pathname + location.search;
		location.replace(target);
	};
	if (last && last !== next) wipeLocal().then(go);
	else go();
}

let leaving = false;
export async function logout() {
	if (leaving) return;
	leaving = true;
	try {
		const { flushAll } = await import('#lib/editor/doc.svelte.ts');
		await flushAll(true);
	} catch {
		/* nothing pending */
	}
	try {
		await api.post('/auth/logout');
	} catch (e) {
		if (!(e instanceof ApiError)) throw e;
	}
	await wipeLocal();
	location.replace('/');
}

hooks.onSignedOut = () => {
	// The server ended the session (expired, signed out elsewhere, account disabled).
	if (leaving || !session.site?.user) return;
	session.site = { ...session.site, user: null };
};
