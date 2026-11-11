<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import {
		ChartColumn, ChevronLeft, Code, Copy, Download, File, FileCode, FileText, Folder, FolderGit2, GitBranch,
		GitCommitHorizontal, History, Image, Pencil, Tag, Trash2
	} from '@lucide/svelte';
	import { api, ApiError, qs } from '#lib/api.ts';
	import CloneBox from '#lib/git/CloneBox.svelte';
	import DiffView from '#lib/git/DiffView.svelte';
	import StatsView from '#lib/git/StatsView.svelte';
	import { highlightCode } from '#lib/git/highlight.ts';
	import { renderReadme } from '#lib/git/markdown.ts';
	import { cloneUrl, short, type Blob, type Commit, type CommitDetail, type RepoDetail, type Stats, type TreeResult } from '#lib/git/types.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, fullDate, relTime } from '#lib/util.ts';

	let name = $derived(page.params.name ?? '');
	let rest = $derived(page.params.rest ?? '');
	let view = $derived.by(() => {
		const [head, ...tail] = rest.split('/');
		const arg = tail.join('/');
		if (head === 'tree') return { kind: 'tree' as const, arg };
		if (head === 'blob') return { kind: 'blob' as const, arg };
		if (head === 'commits') return { kind: 'commits' as const, arg };
		if (head === 'commit') return { kind: 'commit' as const, arg };
		if (head === 'branches') return { kind: 'branches' as const, arg };
		if (head === 'stats') return { kind: 'stats' as const, arg };
		return { kind: 'tree' as const, arg: '' };
	});
	let refParam = $derived(page.url.searchParams.get('ref') ?? '');

	let repo = $state<RepoDetail | null>(null);
	let missing = $state(false);
	let ref = $derived(refParam || repo?.default_branch || '');

	let treeData = $state<TreeResult | null>(null);
	let blob = $state<Blob | null>(null);
	let commits = $state<Commit[]>([]);
	let more = $state(false);
	let pageNo = $state(0);
	let detail = $state<CommitDetail | null>(null);
	let stats = $state<Stats | null>(null);
	let loading = $state(false);
	let error = $state('');
	let mdMode = $state<'preview' | 'code'>('preview');

	async function loadRepo() {
		try {
			repo = await api.get<RepoDetail>(`/git/repos/${name}`);
			missing = false;
		} catch (e) {
			if (e instanceof ApiError && e.status === 404) missing = true;
			else ui.error(e);
		}
	}

	$effect(() => {
		void name;
		repo = null;
		stats = null;
		loadRepo();
	});

	// Load whatever the current view needs.
	$effect(() => {
		const v = view;
		const r = refParam;
		if (!repo || repo.name !== name || repo.empty) return;
		const my = ++seq;
		const fresh = () => my === seq; // ignore responses for a view we have already left
		error = '';
		loading = true;
		const base = `/git/repos/${name}`;
		const get = <T,>(url: string, apply: (d: T) => void) => api.get<T>(url).then((d) => fresh() && apply(d));
		let p: Promise<unknown>;
		if (v.kind === 'tree') p = get<TreeResult>(base + '/tree' + qs({ ref: r, path: v.arg }), (d) => (treeData = d));
		else if (v.kind === 'blob') { mdMode = 'preview'; p = get<Blob>(base + '/blob' + qs({ ref: r, path: v.arg }), (d) => (blob = d)); }
		else if (v.kind === 'commits') { pageNo = 0; p = get<{ commits: Commit[]; more: boolean }>(base + '/commits' + qs({ ref: r, path: v.arg }), (d) => { commits = d.commits; more = d.more; }); }
		else if (v.kind === 'commit') p = get<CommitDetail>(`${base}/commits/${encodeURIComponent(v.arg)}`, (d) => (detail = d));
		else if (v.kind === 'stats') p = get<Stats>(base + '/stats' + qs({ ref: r }), (d) => (stats = d));
		else p = Promise.resolve();
		p.catch((e) => fresh() && (error = e instanceof Error ? e.message : String(e))).finally(() => fresh() && (loading = false));
	});
	let seq = 0;

	async function loadMore() {
		const d = await api.get<{ commits: Commit[]; more: boolean }>(`/git/repos/${name}/commits` + qs({ ref: refParam, path: view.arg, page: pageNo + 1 }));
		pageNo++;
		commits = [...commits, ...d.commits];
		more = d.more;
	}

	const href = (kind: string, arg = '', r = refParam) => `/git/${name}${kind ? '/' + kind : ''}${arg ? '/' + arg : ''}${r ? '?ref=' + encodeURIComponent(r) : ''}`;
	function go(e: MouseEvent, url: string) {
		if (e.ctrlKey || e.metaKey || e.button === 1) return;
		e.preventDefault();
		goto(url);
	}
	function setRef(r: string) {
		const kind = view.kind === 'commit' || view.kind === 'branches' ? 'tree' : view.kind;
		const arg = kind === 'tree' || kind === 'blob' || kind === 'commits' ? view.arg : '';
		goto(href(kind === 'tree' && !arg ? '' : kind, arg, r === repo?.default_branch ? '' : r));
	}

	let crumbs = $derived.by(() => {
		const parts = view.arg ? view.arg.split('/') : [];
		return parts.map((p, i) => ({ name: p, path: parts.slice(0, i + 1).join('/') }));
	});

	let isMarkdown = $derived(!!blob && /\.(md|markdown|mdx)$/i.test(blob.path));
	let isImage = $derived(!!blob && /\.(png|jpe?g|gif|webp|avif|ico|bmp)$/i.test(blob.path));
	let codeLines = $derived(blob?.text != null ? highlightCode(blob.text.replace(/\n$/, ''), blob.path).split('\n') : []);
	const rawUrl = (p: string, inline = false) => `/api/git/repos/${name}/raw` + qs({ ref: refParam, path: p, inline: inline ? 1 : undefined });
	const resolveImg = (base: string) => (u: string) => {
		const clean = u.replace(/^\.\//, '');
		if (clean.startsWith('/') || clean.includes('..')) return '#';
		return rawUrl(base ? `${base}/${clean}` : clean, true);
	};

	let byDay = $derived.by(() => {
		const groups: { day: string; items: Commit[] }[] = [];
		for (const c of commits) {
			const day = new Date(c.date).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
			if (groups.at(-1)?.day !== day) groups.push({ day, items: [] });
			groups.at(-1)!.items.push(c);
		}
		return groups;
	});

	const entryIcon = (n: string, t: string) => (t === 'tree' ? Folder : t === 'commit' ? FolderGit2 : /\.(png|jpe?g|gif|svg|webp|ico)$/i.test(n) ? Image : /\.(md|txt|rst)$/i.test(n) || /^readme/i.test(n) ? FileText : /\.\w+$/.test(n) ? FileCode : File);

	async function editDescription() {
		if (!repo) return;
		const d = prompt('Description', repo.description);
		if (d === null) return;
		try {
			repo = await api.patch<RepoDetail>(`/git/repos/${name}`, { description: d });
		} catch (e) {
			ui.error(e);
		}
	}

	async function setDefault(b: string) {
		try {
			repo = await api.patch<RepoDetail>(`/git/repos/${name}`, { default_branch: b });
			ui.toast(`Default branch is now ${b}`);
		} catch (e) {
			ui.error(e);
		}
	}

	async function remove() {
		if (!repo) return;
		const ok = await ui.confirm({
			title: `Delete “${name}”?`,
			message: `This permanently deletes the repository and all of its history (${fileSize(repo.size)}). Clones elsewhere are not affected. This cannot be undone.`,
			confirmLabel: 'Delete repository', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/git/repos/${name}`);
			ui.toast(`Deleted ${name}`);
			goto('/git');
		} catch (e) {
			ui.error(e);
		}
	}

	const copy = (s: string, what: string) => navigator.clipboard?.writeText(s).then(() => ui.toast(`${what} copied`));
	let tab = $derived(view.kind === 'blob' ? 'tree' : view.kind === 'commit' ? 'commits' : view.kind);
</script>

{#snippet commitBar(c: Commit | null)}
	{#if c}
		<div class="lastc">
			<span class="who">{c.author}</span>
			<a class="subj truncate" href={href('commit', c.sha, '')} onclick={(e) => go(e, href('commit', c.sha, ''))} title={c.subject}>{c.subject}</a>
			<span class="grow"></span>
			<a class="sha" href={href('commit', c.sha, '')} onclick={(e) => go(e, href('commit', c.sha, ''))}>{short(c.sha)}</a>
			<span class="faint" title={fullDate(c.date)}>{relTime(c.date)}</span>
		</div>
	{/if}
{/snippet}

<div class="page-scroll">
	<div class="page wide">
		{#if missing}
			<div class="empty"><b>Repository not found</b>“{name}” does not exist. <a href="/git" onclick={(e) => go(e, '/git')}>Back to repositories</a></div>
		{:else if repo}
			<div class="crumb">
				<a href="/git" onclick={(e) => go(e, '/git')}><ChevronLeft size={14} />Git</a>
			</div>
			<div class="head">
				<div class="title">
					<h1><FolderGit2 size={20} strokeWidth={1.75} />{repo.name}</h1>
					<button class="desc" onclick={editDescription} title="Edit description">
						{#if repo.description}{repo.description}{:else}<span class="faint">Add a description</span>{/if}<Pencil size={12} />
					</button>
				</div>
				<div class="hact">
					<div class="cb"><CloneBox name={repo.name} /></div>
					<button class="icon-btn" title="Delete repository" onclick={remove}><Trash2 size={15} /></button>
				</div>
			</div>

			{#if repo.empty}
				<div class="setup">
					<h3>This repository is empty</h3>
					<p class="muted">Push an existing project to it:</p>
					<pre><code>git remote add kern {cloneUrl(repo.name)}
git push -u kern main</code></pre>
					<button class="btn ghost" onclick={() => copy(`git remote add kern ${cloneUrl(repo!.name)}\ngit push -u kern main`, 'Commands')}><Copy size={13} />Copy</button>
					<p class="muted">Or start fresh:</p>
					<pre><code>git clone {cloneUrl(repo.name)}
cd {repo.name}
echo "# {repo.name}" &gt; README.md
git add README.md &amp;&amp; git commit -m "First commit"
git push -u origin main</code></pre>
				</div>
			{:else}
				<nav class="tabs">
					<a class:on={tab === 'tree'} href={href('')} onclick={(e) => go(e, href(''))}><Code size={14} />Code</a>
					<a class:on={tab === 'commits'} href={href('commits')} onclick={(e) => go(e, href('commits'))}><History size={14} />Commits</a>
					<a class:on={tab === 'branches'} href={href('branches', '', '')} onclick={(e) => go(e, href('branches', '', ''))}><GitBranch size={14} />Branches <em>{repo.branch_list.length}</em> · Tags <em>{repo.tag_list.length}</em></a>
					<a class:on={tab === 'stats'} href={href('stats')} onclick={(e) => go(e, href('stats'))}><ChartColumn size={14} />Stats</a>
					<span class="grow"></span>
					{#if tab !== 'branches' && view.kind !== 'commit'}
						<label class="refsel">
							{#if repo.tag_list.some((t) => t.name === ref) && !repo.branch_list.some((b) => b.name === ref)}<Tag size={13} />{:else}<GitBranch size={13} />{/if}
							<select value={ref} onchange={(e) => setRef(e.currentTarget.value)}>
								<optgroup label="Branches">{#each repo.branch_list as b (b.name)}<option value={b.name}>{b.name}</option>{/each}</optgroup>
								{#if repo.tag_list.length}<optgroup label="Tags">{#each repo.tag_list as t (t.name)}<option value={t.name}>{t.name}</option>{/each}</optgroup>{/if}
								{#if ref && !repo.branch_list.some((b) => b.name === ref) && !repo.tag_list.some((t) => t.name === ref)}<option value={ref}>{short(ref)}</option>{/if}
							</select>
						</label>
					{/if}
				</nav>

				{#if error}
					<div class="empty"><b>Could not load this</b>{error}</div>
				{:else if view.kind === 'tree' && treeData}
					{#if crumbs.length}
						<div class="path">
							<a href={href('')} onclick={(e) => go(e, href(''))}>{repo.name}</a>
							{#each crumbs as c (c.path)}<span class="faint">/</span><a href={href('tree', c.path)} onclick={(e) => go(e, href('tree', c.path))}>{c.name}</a>{/each}
						</div>
					{/if}
					<div class="box">
						{@render commitBar(treeData.last_commit)}
						<div class="entries">
							{#if view.arg}
								{@const up = view.arg.split('/').slice(0, -1).join('/')}
								<a class="ent" href={up ? href('tree', up) : href('')} onclick={(e) => go(e, up ? href('tree', up) : href(''))}><Folder size={15} class="ic" /><span>..</span></a>
							{/if}
							{#each treeData.entries as en (en.path)}
								{@const Icon = entryIcon(en.name, en.type)}
								{@const to = en.type === 'tree' ? href('tree', en.path) : en.type === 'blob' ? href('blob', en.path) : ''}
								<a class="ent" class:dir={en.type === 'tree'} href={to || undefined} onclick={(e) => to && go(e, to)}>
									<Icon size={15} class="ic" /><span class="truncate">{en.name}</span>
									<span class="grow"></span>
									{#if en.type === 'commit'}<span class="faint">submodule</span>{:else if en.size != null}<span class="faint sz">{fileSize(en.size)}</span>{/if}
								</a>
							{:else}
								<p class="faint pad">This folder is empty.</p>
							{/each}
						</div>
					</div>
					{#if treeData.readme}
						<div class="box readme">
							<div class="bh"><FileText size={14} />{treeData.readme.name}</div>
							{#if treeData.readme.markdown}
								<div class="md">{@html renderReadme(treeData.readme.text, resolveImg(view.arg))}</div>
							{:else}
								<pre class="plain">{treeData.readme.text}</pre>
							{/if}
						</div>
					{/if}
				{:else if view.kind === 'blob' && blob && blob.path === view.arg}
					<div class="path">
						<a href={href('')} onclick={(e) => go(e, href(''))}>{repo.name}</a>
						{#each crumbs as c, i (c.path)}<span class="faint">/</span>{#if i < crumbs.length - 1}<a href={href('tree', c.path)} onclick={(e) => go(e, href('tree', c.path))}>{c.name}</a>{:else}<b>{c.name}</b>{/if}{/each}
					</div>
					<div class="box">
						{@render commitBar(blob.last_commit)}
						<div class="bh">
							<span class="faint">{#if blob.lines != null}{blob.lines} lines · {/if}{fileSize(blob.size)}</span>
							<span class="grow"></span>
							{#if isMarkdown}
								<div class="seg"><button class:on={mdMode === 'preview'} onclick={() => (mdMode = 'preview')}>Preview</button><button class:on={mdMode === 'code'} onclick={() => (mdMode = 'code')}>Code</button></div>
							{/if}
							{#if blob.text != null}<button class="icon-btn" title="Copy contents" onclick={() => copy(blob!.text ?? '', 'File')}><Copy size={14} /></button>{/if}
							<a class="icon-btn" title="Download" href={rawUrl(blob.path)}><Download size={14} /></a>
							<a class="icon-btn" title="History" href={href('commits', blob.path)} onclick={(e) => go(e, href('commits', blob!.path))}><History size={14} /></a>
						</div>
						{#if isImage}
							<div class="img"><img src={rawUrl(blob.path, true)} alt={blob.path} /></div>
						{:else if blob.binary}
							<p class="faint pad">Binary file not shown. <a href={rawUrl(blob.path)}>Download</a></p>
						{:else if isMarkdown && mdMode === 'preview'}
							<div class="md">{@html renderReadme(blob.text ?? '', resolveImg(blob.path.split('/').slice(0, -1).join('/')))}</div>
						{:else}
							<div class="code">
								<table><tbody>
									{#each codeLines as l, i (i)}<tr><td class="ln">{i + 1}</td><td>{@html l || ' '}</td></tr>{/each}
								</tbody></table>
							</div>
							{#if blob.truncated}<p class="faint pad">Showing the first {fileSize(1024 * 1024)}. <a href={rawUrl(blob.path)}>Download the whole file</a></p>{/if}
						{/if}
					</div>
				{:else if view.kind === 'commits'}
					{#if view.arg}<p class="muted filter">History of <code>{view.arg}</code> · <a href={href('commits')} onclick={(e) => go(e, href('commits'))}>show all</a></p>{/if}
					{#each byDay as g (g.day)}
						<div class="day"><GitCommitHorizontal size={14} />Commits on {g.day}</div>
						<div class="box commits">
							{#each g.items as c (c.sha)}
								<div class="cm">
									<div class="cmain">
										<a class="subj" href={href('commit', c.sha, '')} onclick={(e) => go(e, href('commit', c.sha, ''))}>{c.subject}</a>
										<span class="faint sub"><b>{c.author}</b> committed {relTime(c.date)}{c.parents.length > 1 ? ' · merge' : ''}</span>
									</div>
									<button class="sha" title="Copy full SHA" onclick={() => copy(c.sha, 'SHA')}>{short(c.sha)}</button>
									<a class="icon-btn" title="Browse files at this commit" href={href('', '', c.sha)} onclick={(e) => go(e, href('', '', c.sha))}><Code size={14} /></a>
								</div>
							{/each}
						</div>
					{:else}
						{#if !loading}<div class="empty"><b>No commits</b>Nothing here yet.</div>{/if}
					{/each}
					{#if more}<div class="morewrap"><button class="btn" onclick={loadMore}>Older commits</button></div>{/if}
				{:else if view.kind === 'commit' && detail && detail.sha.startsWith(view.arg)}
					<div class="box chead">
						<h2>{detail.subject}</h2>
						{#if detail.body}<pre class="body">{detail.body}</pre>{/if}
						<div class="cmeta">
							<span><b>{detail.author}</b> <span class="faint">&lt;{detail.email}&gt;</span> committed <span title={fullDate(detail.date)}>{relTime(detail.date)}</span></span>
							<span class="grow"></span>
							{#each detail.parents as p, i (p)}
								<span class="faint">{i === 0 ? (detail.parents.length > 1 ? 'parents' : 'parent') : ''}</span>
								<a class="sha" href={href('commit', p, '')} onclick={(e) => go(e, href('commit', p, ''))}>{short(p)}</a>
							{/each}
							<span class="faint">commit</span>
							<button class="sha" title="Copy full SHA" onclick={() => copy(detail!.sha, 'SHA')}>{short(detail.sha)}</button>
							<a class="btn ghost sm" href={href('', '', detail.sha)} onclick={(e) => go(e, href('', '', detail!.sha))}><Code size={13} />Browse files</a>
						</div>
					</div>
					<p class="summary">
						<b>{detail.files.length}</b> file{detail.files.length === 1 ? '' : 's'} changed,
						<span class="add">{detail.additions} addition{detail.additions === 1 ? '' : 's'}</span>,
						<span class="del">{detail.deletions} deletion{detail.deletions === 1 ? '' : 's'}</span>
						{#if detail.truncated}<span class="faint"> · large diff, some lines hidden</span>{/if}
					</p>
					<DiffView files={detail.files} onopen={(p) => goto(href('blob', p, detail!.sha))} />
				{:else if view.kind === 'branches'}
					<h3 class="section-title">Branches</h3>
					<div class="box">
						{#each repo.branch_list as b (b.name)}
							<div class="br">
								<GitBranch size={14} class="ic" />
								<a class="bn" href={href('', '', b.name === repo.default_branch ? '' : b.name)} onclick={(e) => go(e, href('', '', b.name === repo!.default_branch ? '' : b.name))}>{b.name}</a>
								{#if b.name === repo.default_branch}<span class="chip">default</span>{/if}
								<span class="faint truncate bs">{b.subject}</span>
								<span class="grow"></span>
								<span class="faint">{relTime(b.date)}</span>
								<a class="sha" href={href('commit', b.sha, '')} onclick={(e) => go(e, href('commit', b.sha, ''))}>{short(b.sha)}</a>
								{#if b.name !== repo.default_branch}<button class="btn ghost sm" onclick={() => setDefault(b.name)}>Make default</button>{:else}<span class="sm-pad"></span>{/if}
							</div>
						{/each}
					</div>
					<h3 class="section-title">Tags</h3>
					{#if repo.tag_list.length}
						<div class="box">
							{#each repo.tag_list as t (t.name)}
								<div class="br">
									<Tag size={14} class="ic" />
									<a class="bn" href={href('', '', t.name)} onclick={(e) => go(e, href('', '', t.name))}>{t.name}</a>
									<span class="faint truncate bs">{t.subject}</span>
									<span class="grow"></span>
									<span class="faint">{relTime(t.date)}</span>
									<a class="sha" href={href('commit', t.sha, '')} onclick={(e) => go(e, href('commit', t.sha, ''))}>{short(t.sha)}</a>
								</div>
							{/each}
						</div>
					{:else}
						<div class="empty"><b>No tags</b>Create one with <code>git tag v1.0 &amp;&amp; git push --tags</code></div>
					{/if}
				{:else if view.kind === 'stats' && stats && !stats.empty}
					<StatsView {stats} />
				{:else if loading}
					<p class="faint pad">Loading…</p>
				{/if}
			{/if}
		{/if}
	</div>
</div>

<style>
	.wide { max-width: 1060px; }
	.crumb a { display: inline-flex; align-items: center; gap: 2px; font-size: 12.5px; color: var(--text-3); text-decoration: none; margin-bottom: 6px; }
	.crumb a:hover { color: var(--text); }
	.head { display: flex; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
	.title { flex: 1; min-width: 220px; }
	h1 { display: flex; align-items: center; gap: 8px; }
	h1 :global(svg) { color: var(--accent); }
	.desc { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); text-align: left; padding: 0; }
	.desc :global(svg) { opacity: 0; color: var(--text-3); }
	.desc:hover :global(svg) { opacity: 1; }
	.hact { display: flex; align-items: center; gap: 4px; }
	.cb { width: 360px; max-width: calc(100vw - 80px); }
	.grow { flex: 1; }
	.tabs { display: flex; align-items: center; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 14px; flex-wrap: wrap; }
	.tabs a { display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; margin-bottom: -1px; color: var(--text-2); text-decoration: none; border-bottom: 2px solid transparent; font-size: 13.5px; }
	.tabs a:hover { color: var(--text); }
	.tabs a.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 550; }
	.tabs em { font-style: normal; font-size: 11.5px; padding: 0 5px; border-radius: 8px; background: var(--surface-2); color: var(--text-2); font-weight: 500; }
	.refsel { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 4px 0 8px; margin-bottom: 4px; border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-2); }
	.refsel select { border: 0; outline: 0; background: none; color: var(--text); font: 13px var(--font-mono); max-width: 200px; }
	.path { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; font-size: 14px; }
	.path a { color: var(--accent); text-decoration: none; }
	.path a:hover { text-decoration: underline; }
	.box { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface); margin-bottom: 14px; }
	.lastc { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--surface-2); border-bottom: 1px solid var(--border); font-size: 13px; }
	.lastc .who { font-weight: 600; white-space: nowrap; }
	.lastc .subj { color: var(--text-2); text-decoration: none; }
	.lastc .subj:hover { color: var(--accent); }
	.sha { font: 12px var(--font-mono); color: var(--text-2); text-decoration: none; padding: 1px 6px; border-radius: 4px; background: var(--code-bg); white-space: nowrap; }
	a.sha:hover, button.sha:hover { color: var(--accent); }
	.ent { display: flex; align-items: center; gap: 9px; padding: 6px 12px; border-top: 1px solid var(--border); color: var(--text); text-decoration: none; font-size: 13.5px; }
	.ent:first-child { border-top: 0; }
	.ent:hover { background: var(--hover); }
	.ent:hover span:not(.faint) { color: var(--accent); }
	.ent :global(.ic) { flex: none; color: var(--text-3); }
	.ent.dir :global(.ic) { color: var(--c-blue); }
	.sz { font-variant-numeric: tabular-nums; font-size: 12px; }
	.pad { padding: 12px 14px; margin: 0; }
	.bh { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid var(--border); font-size: 12.5px; font-weight: 550; }
	.readme .bh { background: var(--surface-2); }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 1px 9px; border-radius: 4px; color: var(--text-2); font-size: 12px; font-weight: 500; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.code { overflow-x: auto; }
	.code table { border-collapse: collapse; font: 12.5px/1.6 var(--font-mono); width: 100%; tab-size: 4; }
	.code td { white-space: pre; padding: 0 14px 0 0; vertical-align: top; }
	.code td.ln { width: 1%; min-width: 44px; padding: 0 12px; text-align: right; color: var(--text-3); user-select: none; }
	.code tr:first-child td { padding-top: 8px; }
	.code tr:last-child td { padding-bottom: 8px; }
	.code tr:hover td { background: var(--hover); }
	.img { padding: 20px; display: grid; place-items: center; background: repeating-conic-gradient(var(--surface-2) 0 25%, transparent 0 50%) 0 0 / 16px 16px; }
	.img img { max-width: 100%; max-height: 70vh; }
	.plain { margin: 0; padding: 16px 20px; font: 12.5px/1.6 var(--font-mono); white-space: pre-wrap; }
	.md { padding: 8px 28px 20px; line-height: 1.65; overflow-wrap: anywhere; }
	.md :global(h1), .md :global(h2) { padding-bottom: 6px; border-bottom: 1px solid var(--border); }
	.md :global(h1) { font-size: 1.7em; margin: 18px 0 12px; }
	.md :global(h2) { font-size: 1.35em; margin: 22px 0 10px; }
	.md :global(h3) { font-size: 1.12em; margin: 18px 0 8px; }
	.md :global(h4), .md :global(h5), .md :global(h6) { font-size: 1em; margin: 14px 0 6px; }
	.md :global(p) { margin: 0 0 12px; }
	.md :global(a) { color: var(--accent); }
	.md :global(img) { max-width: 100%; }
	.md :global(code) { font: 0.88em var(--font-mono); padding: 1.5px 5px; border-radius: 4px; background: var(--code-bg); }
	.md :global(pre) { padding: 12px 14px; border-radius: 6px; background: var(--code-bg); overflow-x: auto; }
	.md :global(pre code) { padding: 0; background: none; font-size: 12.5px; line-height: 1.55; }
	.md :global(blockquote) { margin: 0 0 12px; padding: 0 14px; border-left: 3px solid var(--border-strong); color: var(--text-2); }
	.md :global(table) { border-collapse: collapse; margin: 0 0 12px; }
	.md :global(th), .md :global(td) { border: 1px solid var(--border-strong); padding: 5px 10px; }
	.md :global(hr) { border: 0; border-top: 1px solid var(--border); margin: 18px 0; }
	.md :global(ul), .md :global(ol) { padding-left: 24px; margin: 0 0 12px; }
	:global(.hl-k) { color: var(--c-purple); }
	:global(.hl-s) { color: var(--c-green); }
	:global(.hl-c) { color: var(--text-3); font-style: italic; }
	:global(.hl-n) { color: var(--c-orange); }
	:global(.hl-f) { color: var(--c-blue); }
	.filter { font-size: 13px; }
	.filter code { font: 12px var(--font-mono); }
	.day { display: flex; align-items: center; gap: 8px; margin: 14px 0 8px; font-size: 12.5px; color: var(--text-2); }
	.day :global(svg) { color: var(--text-3); }
	.commits { margin-bottom: 4px; }
	.cm { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-top: 1px solid var(--border); }
	.cm:first-child { border-top: 0; }
	.cm:hover { background: var(--hover); }
	.cmain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
	.cm .subj { color: var(--text); font-weight: 550; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.cm .subj:hover { color: var(--accent); }
	.cm .sub { font-size: 12px; }
	.cm .sub b { font-weight: 550; color: var(--text-2); }
	.morewrap { display: flex; justify-content: center; margin-top: 12px; }
	.chead { padding: 14px 16px; }
	.chead h2 { margin: 0 0 6px; font-size: 17px; font-weight: 650; }
	.body { margin: 0 0 10px; font: 13px/1.55 var(--font-sans); white-space: pre-wrap; color: var(--text-2); }
	.cmeta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 13px; padding-top: 10px; border-top: 1px solid var(--border); }
	.btn.sm { height: 24px; padding: 0 8px; font-size: 12px; }
	.summary { font-size: 13px; color: var(--text-2); margin: 0 0 10px; }
	.add { color: var(--c-green); } .del { color: var(--c-red); }
	.br { display: flex; align-items: center; gap: 9px; padding: 8px 12px; border-top: 1px solid var(--border); font-size: 13px; }
	.br:first-child { border-top: 0; }
	.br :global(.ic) { color: var(--text-3); flex: none; }
	.bn { font: 13px var(--font-mono); color: var(--accent); text-decoration: none; white-space: nowrap; }
	.bn:hover { text-decoration: underline; }
	.bs { max-width: 420px; }
	.sm-pad { width: 88px; }
	.setup { padding: 18px 22px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
	.setup h3 { margin: 0 0 4px; font-size: 15px; }
	.setup p { margin: 14px 0 6px; font-size: 13px; }
	.setup pre { margin: 0 0 6px; padding: 10px 14px; border-radius: 6px; background: var(--code-bg); font: 12.5px/1.6 var(--font-mono); overflow-x: auto; }
	@media (max-width: 700px) { .bs, .sm-pad { display: none; } }
</style>
