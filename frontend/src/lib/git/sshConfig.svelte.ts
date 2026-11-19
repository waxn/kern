// Shared state for git over SSH: what the server reports (GET /api/git/config) and whether
// clone boxes show the HTTP or the SSH URL (remembered in localStorage).
import { api } from '#lib/api.ts';

export interface SshInfo { enabled: boolean; host: string; port: number; fingerprint: string | null }

const KEY = 'kern.git.clone';

function readMode(): 'http' | 'ssh' {
	try {
		return localStorage.getItem(KEY) === 'ssh' ? 'ssh' : 'http';
	} catch {
		return 'http';
	}
}

export const gitSsh = $state<{ info: SshInfo | null; username: string; mode: 'http' | 'ssh' }>({
	info: null,
	username: '',
	mode: readMode()
});

let pending: Promise<void> | null = null;

/** Load the config once (every clone box asks); pass force to refresh. */
export function loadSshInfo(force = false): Promise<void> {
	if (force) pending = null;
	pending ??= api
		.get<{ username: string; ssh?: SshInfo }>('/git/config')
		.then((c) => {
			gitSsh.info = c.ssh ?? null;
			gitSsh.username = c.username;
		})
		.catch(() => {
			pending = null;
		});
	return pending;
}

export function setCloneMode(m: 'http' | 'ssh') {
	gitSsh.mode = m;
	try {
		localStorage.setItem(KEY, m);
	} catch {
		/* private mode: the choice just isn't remembered */
	}
}

/** ssh://git@host:port/name.git, or the owner-qualified form ssh://git@host:port/owner/name.git. */
export function sshCloneUrl(info: SshInfo, name: string, owner?: string) {
	const port = info.port === 22 ? '' : `:${info.port}`;
	return `ssh://git@${info.host}${port}/${owner ? owner + '/' : ''}${name}.git`;
}

/** The URL clone boxes currently show for a repository (SSH when enabled and chosen). */
export function activeCloneUrl(name: string, http: string) {
	return gitSsh.info?.enabled && gitSsh.mode === 'ssh' ? sshCloneUrl(gitSsh.info, name) : http;
}
