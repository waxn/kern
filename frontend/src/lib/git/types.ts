export interface CommitBrief { sha: string; date: string; subject: string; author: string }

export interface Repo {
	name: string;
	description: string;
	size: number;
	empty: boolean;
	default_branch: string | null;
	branches: number;
	last_push: string | null;
	created: string | null;
	last_commit: CommitBrief | null;
}

export interface Ref { name: string; sha: string; date: string; subject: string; author?: string }
export interface RepoDetail extends Repo { branch_list: Ref[]; tag_list: Ref[] }

export interface Commit {
	sha: string;
	parents: string[];
	author: string;
	email: string;
	date: string;
	committer: string;
	committed: string;
	subject: string;
	body: string;
}

export interface TreeEntry { name: string; path: string; type: 'tree' | 'blob' | 'commit'; mode: string; size: number | null; sha: string }

export interface TreeResult {
	sha: string | null;
	path: string;
	entries: TreeEntry[];
	readme: { path: string; name: string; text: string; markdown: boolean } | null;
	last_commit: Commit | null;
}

export interface Blob {
	path: string;
	size: number;
	binary: boolean;
	truncated: boolean;
	text: string | null;
	lines?: number;
	sha: string;
	last_commit: Commit | null;
}

export interface DiffLine { t: '+' | '-' | ' '; o: number | null; n: number | null; s: string }
export interface DiffFile {
	old_path: string | null;
	new_path: string | null;
	status: 'added' | 'deleted' | 'modified' | 'renamed';
	binary: boolean;
	additions: number;
	deletions: number;
	truncated: boolean;
	hunks: { header: string; lines: DiffLine[] }[];
}
export interface CommitDetail extends Commit { files: DiffFile[]; truncated: boolean; additions: number; deletions: number }

export interface Contributor { name: string; email: string; commits: number; additions: number; deletions: number; first: string; last: string }
export interface Language { name: string; color: string; files: number; bytes: number; lines: number }
export interface Stats {
	empty: boolean;
	sha?: string;
	totals: { commits: number; files: number; lines: number; bytes: number; size: number; contributors: number; branches: number; tags: number; active_days: number };
	first_commit: string | null;
	last_commit: string | null;
	heatmap: [string, number][];
	months: [string, number][];
	punchcard: number[][];
	contributors: Contributor[];
	languages: Language[];
}

export const cloneUrl = (name: string) => `${location.origin}/git/${name}.git`;
export const short = (sha: string) => sha.slice(0, 7);
