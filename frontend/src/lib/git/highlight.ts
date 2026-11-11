/** A tiny, dependency-free syntax highlighter: comments, strings, numbers and keywords.
 *  Not a parser — just enough colour to make code easy to scan. Output is escaped HTML. */

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const KW = {
	c: 'auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false NULL nullptr class public private protected virtual template typename namespace using new delete this throw try catch include define',
	js: 'await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield async as interface type enum implements readonly declare keyof satisfies',
	py: 'False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield self match case',
	rs: 'as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
	go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false',
	sh: 'if then else elif fi case esac for while until do done in function return local export echo exit set unset readonly shift source',
	sql: 'select from where insert into values update set delete create table index primary key foreign references join left right inner outer on group by order having limit offset and or not null as distinct union all drop alter add',
	rb: 'alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield require',
	java: 'abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public return short static super switch synchronized this throw throws try void volatile while true false null var val fun when object data sealed override'
} as const;

type Family = keyof typeof KW | 'css' | 'md' | 'json' | 'html' | 'none';

const EXT: Record<string, Family> = {
	c: 'c', h: 'c', cc: 'c', cpp: 'c', cxx: 'c', hpp: 'c', cs: 'java', java: 'java', kt: 'java', kts: 'java', scala: 'java', swift: 'rs', dart: 'js',
	js: 'js', mjs: 'js', cjs: 'js', jsx: 'js', ts: 'js', tsx: 'js', mts: 'js', svelte: 'html', vue: 'html', html: 'html', htm: 'html', xml: 'html', svg: 'html',
	py: 'py', pyi: 'py', rs: 'rs', go: 'go', sh: 'sh', bash: 'sh', zsh: 'sh', fish: 'sh', sql: 'sql', rb: 'rb', php: 'js', lua: 'py',
	css: 'css', scss: 'css', sass: 'css', less: 'css', json: 'json', toml: 'sh', yaml: 'sh', yml: 'sh', ini: 'sh', dockerfile: 'sh', makefile: 'sh',
	md: 'md', markdown: 'md', javascript: 'js', typescript: 'js', python: 'py', rust: 'rs', shell: 'sh', console: 'sh'
};

export function familyOf(nameOrLang: string): Family {
	const base = nameOrLang.toLowerCase().split('/').pop() ?? '';
	if (base === 'dockerfile' || base === 'makefile') return 'sh';
	const ext = base.includes('.') ? base.split('.').pop()! : base;
	return EXT[ext] ?? 'none';
}

const cache = new Map<string, Set<string>>();
function kw(f: keyof typeof KW) {
	if (!cache.has(f)) cache.set(f, new Set(KW[f].split(' ')));
	return cache.get(f)!;
}

function lineComment(f: Family): string | null {
	if (f === 'py' || f === 'sh' || f === 'rb') return '#';
	if (f === 'sql') return '--';
	if (f === 'none' || f === 'md' || f === 'json' || f === 'html' || f === 'css') return null;
	return '//';
}

/** Highlight a whole file. Block comments may span lines, so this works on the full text. */
export function highlightCode(code: string, nameOrLang: string): string {
	const f = familyOf(nameOrLang);
	if (f === 'none' || f === 'md') return esc(code);
	const lc = lineComment(f);
	const block = f === 'py' ? null : f === 'html' ? ['<!--', '-->'] : f === 'sh' || f === 'rb' ? null : ['/*', '*/'];
	const words = f in KW ? kw(f as keyof typeof KW) : null;
	let out = '';
	let i = 0;
	const n = code.length;
	const span = (cls: string, s: string) => `<span class="hl-${cls}">${esc(s)}</span>`;
	while (i < n) {
		const ch = code[i];
		if (block && code.startsWith(block[0], i)) {
			const end = code.indexOf(block[1], i + block[0].length);
			const j = end < 0 ? n : end + block[1].length;
			out += span('c', code.slice(i, j));
			i = j;
		} else if (lc && code.startsWith(lc, i) && !(lc === '#' && /[\w$]/.test(code[i - 1] ?? ''))) {
			const end = code.indexOf('\n', i);
			const j = end < 0 ? n : end;
			out += span('c', code.slice(i, j));
			i = j;
		} else if (ch === '"' || ch === "'" || ch === '`') {
			const triple = f === 'py' && code.startsWith(ch.repeat(3), i);
			const q = triple ? ch.repeat(3) : ch;
			let j = i + q.length;
			while (j < n) {
				if (code[j] === '\\') { j += 2; continue; }
				if (code.startsWith(q, j)) { j += q.length; break; }
				if (code[j] === '\n' && !triple && ch !== '`') break;
				j++;
			}
			out += span('s', code.slice(i, j));
			i = j;
		} else if (/[0-9]/.test(ch) && !/[\w$]/.test(code[i - 1] ?? '')) {
			const m = code.slice(i).match(/^(0x[\da-f_]+|\d[\d_]*(\.\d+)?(e[+-]?\d+)?)/i)!;
			out += span('n', m[0]);
			i += m[0].length;
		} else if (/[A-Za-z_$@]/.test(ch)) {
			const m = code.slice(i).match(/^[@$]?[\w$-]*/)!;
			let w = m[0];
			if (f !== 'css' && f !== 'html') w = w.replace(/-.*$/, '') || ch;
			const lower = f === 'sql' ? w.toLowerCase() : w;
			if (words?.has(lower)) out += span('k', w);
			else if (f === 'json' && (w === 'true' || w === 'false' || w === 'null')) out += span('k', w);
			else if (f !== 'css' && code[i + w.length] === '(') out += span('f', w);
			else if (f === 'html' && code[i - 1] === '<') out += span('k', w);
			else if (f === 'html' && code[i - 1] === '/' && code[i - 2] === '<') out += span('k', w);
			else if (f === 'css' && code[i + w.length] === ':' ) out += span('f', w);
			else out += esc(w);
			i += w.length;
		} else {
			out += esc(ch);
			i++;
		}
	}
	return out;
}
