import { api } from '#lib/api.ts';

export type AppState = 'new' | 'stopped' | 'starting' | 'running' | 'crashed' | 'building' | 'failed';
export type Access = 'private' | 'users' | 'public';

export interface Deploy {
	number: number;
	sha: string;
	short: string;
	subject: string;
	trigger: string;
	who: string;
	status: 'queued' | 'building' | 'starting' | 'live' | 'failed' | 'old' | 'cancelled';
	error: string;
	runtime: string;
	rollback_of: number | null;
	created: string;
	started: string | null;
	finished: string | null;
	seconds: number | null;
}

export interface Metrics {
	running: boolean;
	pid: number | null;
	port: number | null;
	number: number | null;
	uptime: number;
	cpu: number;
	rss: number;
	restarts: number;
	held: boolean;
	deploying: number | null;
	last_exit: number | null;
	backoff: number;
}

export interface App {
	id: number;
	slug: string;
	name: string;
	description: string;
	icon: string;
	color: string;
	path: string;
	access: Access;
	enabled: boolean;
	state: AppState;
	state_detail: string;
	state_at: string | null;
	source: 'kern' | 'url';
	repo: string;
	git_url: string;
	branch: string;
	subdir: string;
	auto_deploy: boolean;
	created: string;
	updated: string;
	live: Deploy | null;
	latest: Deploy | null;
	metrics: Metrics | null;
	runtime: string;
	// detail only
	build_cmd?: string;
	start_cmd?: string;
	health_path?: string;
	runtime_setting?: string;
	public_paths?: string[];
	strip_prefix?: boolean;
	has_token?: boolean;
	hook_path?: string;
	env_names?: string[];
	worker?: boolean;
	isolated?: boolean;
}

export interface Starter {
	key: string;
	name: string;
	icon: string;
	description: string;
	public_paths: string[];
}

export const ACCESS_LABEL: Record<Access, string> = {
	private: 'Only me',
	users: 'Signed-in users',
	public: 'Everyone'
};

export const RUNTIME_LABEL: Record<string, string> = {
	static: 'Static', python: 'Python', node: 'Node.js', command: 'Command'
};

/** What to show for an app right now: its state, refined by what the worker and the newest deployment say. */
export function view(a: App, worker = true): { label: string; tone: 'ok' | 'busy' | 'off' | 'bad'; detail: string } {
	const dep = a.latest;
	const deploying = dep && (dep.status === 'queued' || dep.status === 'building' || dep.status === 'starting');
	if (!worker) return { label: 'Service offline', tone: 'bad', detail: 'The apps service is not running.' };
	if (deploying && a.state === 'running') return { label: 'Deploying', tone: 'busy', detail: `Deployment #${dep!.number} is ${dep!.status}.` };
	if (deploying) return { label: dep!.status === 'queued' ? 'Queued' : 'Building', tone: 'busy', detail: `Deployment #${dep!.number}` };
	switch (a.state) {
		case 'running': return { label: 'Running', tone: 'ok', detail: '' };
		case 'starting': return { label: 'Starting', tone: 'busy', detail: a.state_detail };
		case 'building': return { label: 'Building', tone: 'busy', detail: a.state_detail };
		case 'crashed': return { label: a.metrics?.held ? 'Crashed' : 'Restarting', tone: 'bad', detail: a.state_detail };
		case 'failed': return { label: 'Failed', tone: 'bad', detail: a.state_detail };
		case 'stopped': return { label: 'Stopped', tone: 'off', detail: '' };
		default: return { label: a.live ? 'Stopped' : 'Not deployed', tone: 'off', detail: a.state_detail };
	}
}

export function uptime(s: number): string {
	if (s < 60) return `${s}s`;
	if (s < 3600) return `${Math.floor(s / 60)}m`;
	if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
	return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export const TRIGGER_LABEL: Record<string, string> = {
	push: 'Push', manual: 'Manual', hook: 'Deploy hook', ai: 'AI builder', rollback: 'Rollback', create: 'Created', edit: 'Edited in Kern'
};

export const appsApi = {
	list: () => api.get<{ apps: App[]; worker: boolean; isolated: boolean }>('/apps'),
	get: (slug: string) => api.get<App>(`/apps/${slug}`),
	patch: (slug: string, body: Partial<App> & Record<string, unknown>) => api.patch<App>(`/apps/${slug}`, body),
	action: (slug: string, action: 'start' | 'stop' | 'restart' | 'deploy', body: Record<string, unknown> = {}) =>
		api.post<App>(`/apps/${slug}/${action}`, body),
	remove: (slug: string, deleteRepo: boolean) =>
		fetch(`/api/apps/${slug}`, { method: 'DELETE', headers: { 'X-Kern': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ delete_repo: deleteRepo }) })
};
