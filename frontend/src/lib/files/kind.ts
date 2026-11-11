/** What kind of viewer a file gets, from its MIME type and (because browsers often send none) its extension. */

export interface FileRef {
	id?: string;
	url: string;
	name: string;
	mime: string;
	size?: number;
}

export type FileKind = 'image' | 'video' | 'audio' | 'pdf' | 'markdown' | 'text' | 'docx' | 'office' | 'other';

const TEXT_EXT = new Set(
	('txt text log csv tsv json jsonc json5 yaml yml toml ini cfg conf env xml svg html htm css scss sass less ' +
		'js mjs cjs ts tsx jsx svelte vue py rb go rs java kt kts swift c h cc cpp hpp cs php pl lua r sql sh bash zsh fish ' +
		'ps1 bat dockerfile makefile gitignore editorconfig tex bib org rst adoc srt vtt diff patch')
		.split(' ')
);
const MD_EXT = new Set(['md', 'markdown', 'mdown', 'mkd']);
const OFFICE_EXT = new Set(['doc', 'odt', 'rtf', 'xls', 'xlsx', 'ods', 'ppt', 'pptx', 'odp', 'pages', 'numbers', 'key']);
const AUDIO_EXT = new Set(['mp3', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'wav', 'flac', 'weba']);
const VIDEO_EXT = new Set(['mp4', 'm4v', 'webm', 'mov', 'ogv', 'mkv']);

export function extOf(name: string): string {
	const base = name.toLowerCase().split('/').pop() ?? '';
	if (base === 'dockerfile' || base === 'makefile') return base;
	const i = base.lastIndexOf('.');
	return i > 0 ? base.slice(i + 1) : i === 0 ? base.slice(1) : '';
}

export function fileKind(f: { name: string; mime: string }): FileKind {
	const m = (f.mime || '').toLowerCase();
	const ext = extOf(f.name);
	if (MD_EXT.has(ext) || m === 'text/markdown') return 'markdown';
	if (ext === 'docx' || m === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') return 'docx';
	if (m === 'application/pdf' || ext === 'pdf') return 'pdf';
	if (ext === 'svg') return 'image';
	if (m.startsWith('image/')) return 'image';
	if (m.startsWith('video/') || VIDEO_EXT.has(ext)) return 'video';
	if (m.startsWith('audio/') || AUDIO_EXT.has(ext)) return 'audio';
	if (OFFICE_EXT.has(ext)) return 'office';
	if (m.startsWith('text/') || TEXT_EXT.has(ext) || /json|xml|javascript|yaml|toml|x-sh/.test(m)) return 'text';
	return 'other';
}

export const isMedia = (f: { name: string; mime: string }) => ['audio', 'video'].includes(fileKind(f));

/** Files that render as code (monospace, no wrapping by default) rather than prose. */
export function isCode(name: string): boolean {
	return !['txt', 'text', 'log', 'srt', 'vtt', 'org', 'rst', 'adoc', ''].includes(extOf(name));
}

export function fmtTime(s: number): string {
	if (!isFinite(s) || s < 0) s = 0;
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const sec = Math.floor(s % 60);
	const mm = h ? String(m).padStart(2, '0') : String(m);
	return (h ? h + ':' : '') + mm + ':' + String(sec).padStart(2, '0');
}

/** Two colours derived from a name, for audio "covers". */
export function coverColors(name: string): [string, string] {
	let h = 0;
	for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
	const a = h % 360;
	return [`hsl(${a} 55% 42%)`, `hsl(${(a + 50) % 360} 60% 24%)`];
}
