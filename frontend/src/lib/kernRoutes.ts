// Kern's own top-level paths. Everything else at the top level may be an app (/<slug>/…, served by
// the apps service). Keep in sync with src/routes and backend/kernapps/core.py (its tests check both).
export const KERN_ROUTES = [
	'apps', 'archive', 'cards', 'developer', 'doc', 'files', 'git', 'graph', 'intelligence', 'login',
	'mail', 'review', 'search', 'settings', 'signup', 'tag', 'tags', 'tasks', 'templates', 'trash', 'web'
];

/** Paths the web server answers itself (API, files, build output). */
export const KERN_SYSTEM = ['api', 'media', '_app', 'pdfjs', '_apps'];

/** True when the first path segment belongs to Kern, not to an app. */
export function isKernPath(pathname: string): boolean {
	const first = pathname.split('/')[1] ?? '';
	return first === '' || KERN_ROUTES.includes(first) || KERN_SYSTEM.includes(first) || first.includes('.');
}
