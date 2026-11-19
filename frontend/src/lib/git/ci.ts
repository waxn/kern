import { api, qs } from '#lib/api.ts';

export type RunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | 'error';
export type JobStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'cancelled' | 'error';

export interface CiRun {
	id: number;
	repo: string;
	ref: string;
	branch: string | null;
	tag: string | null;
	sha: string;
	subject: string;
	trigger: 'push' | 'manual' | 'rerun';
	pusher: string;
	status: RunStatus;
	error: string;
	created: string;
	started: string | null;
	finished: string | null;
	duration: number | null;
}

export interface CiJob {
	name: string;
	status: JobStatus;
	note: string;
	exit_code: number | null;
	started: string | null;
	finished: string | null;
	duration: number | null;
}

export interface CiArtifact { job: string; name: string; size: number }
export interface CiRunDetail extends CiRun { jobs: CiJob[]; artifacts: CiArtifact[] }
export interface CiLog { text: string; offset: number; size: number; done: boolean; status: JobStatus }
export interface CiPipeline { found: boolean; error: string; manual: boolean; jobs: string[] }
export interface CiSecret { name: string; updated: string }
export type CiStatusMap = Record<string, { status: RunStatus; run: number }>;

export const FINISHED: string[] = ['success', 'failed', 'cancelled', 'error'];
export const isLive = (s: string) => s === 'queued' || s === 'running';

export const STATUS_LABEL: Record<string, string> = {
	queued: 'Queued', running: 'Running', success: 'Passed', failed: 'Failed', cancelled: 'Cancelled',
	error: 'Error', skipped: 'Skipped', pending: 'Waiting'
};

export function fmtDuration(s: number | null | undefined): string {
	if (s == null) return '';
	const t = Math.round(s);
	if (t < 60) return `${t}s`;
	const m = Math.floor(t / 60);
	if (m < 60) return `${m}m ${String(t % 60).padStart(2, '0')}s`;
	return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

export const runUrl = (repo: string, id: number) => `/git/${encodeURIComponent(repo)}/run/${id}`;

export const artifactUrl = (repo: string, run: number, a: CiArtifact) =>
	`/api/git/repos/${encodeURIComponent(repo)}/ci/runs/${run}/artifacts/${encodeURIComponent(a.job)}/${a.name.split('/').map(encodeURIComponent).join('/')}`;

/** Latest run status for each commit (only commits that have a run appear in the result). */
export async function loadStatuses(repo: string, shas: string[]): Promise<CiStatusMap> {
	const out: CiStatusMap = {};
	for (let i = 0; i < shas.length; i += 100) {
		const part = shas.slice(i, i + 100);
		try {
			Object.assign(out, await api.get<CiStatusMap>(`/git/repos/${encodeURIComponent(repo)}/ci/status` + qs({ shas: part.join(',') })));
		} catch {
			/* status dots are decoration: never break the page for them */
		}
	}
	return out;
}

// eslint-disable-next-line no-control-regex
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
/** Terminal colour codes and carriage-return progress updates are dropped from a log line. */
export const cleanLine = (s: string) => {
	const i = s.lastIndexOf('\r');
	return (i >= 0 ? s.slice(i + 1) : s).replace(ANSI, '');
};
