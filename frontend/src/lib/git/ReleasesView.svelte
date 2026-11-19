<script lang="ts">
	import { Download, FileArchive, Pencil, Plus, Tag, Trash2, Upload, X } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { renderReadme } from '#lib/git/markdown.ts';
	import { archiveUrl, type Release, type RepoDetail } from '#lib/git/types.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, fullDate, relTime } from '#lib/util.ts';

	let { repo, onchange }: { repo: RepoDetail; onchange: () => void } = $props();
	let name = $derived(repo.name);

	let releases = $state<Release[]>([]);
	let loaded = $state(false);
	let form = $state<{
		id: number | null; tag: string; target: string; title: string; notes: string;
		draft: boolean; prerelease: boolean; preview: boolean; files: File[];
	} | null>(null);
	let busy = $state(false);
	let progress = $state(0);
	let over = $state(false);
	let removing = $state<{ id: number; tag: boolean } | null>(null);
	let picker: HTMLInputElement | undefined = $state();

	async function load() {
		try {
			releases = await api.get<Release[]>(`/git/repos/${name}/releases`);
		} catch (e) {
			ui.error(e);
		} finally {
			loaded = true;
		}
	}
	$effect(() => {
		void name;
		load();
	});

	let freeTags = $derived(repo.tag_list.filter((t) => !releases.some((r) => r.tag === t.name)));
	const NEW = '\u0000new';
	let tagChoice = $state(NEW);

	function start(r?: Release) {
		removing = null;
		if (r) form = { id: r.id, tag: r.tag, target: '', title: r.title, notes: r.notes, draft: r.draft, prerelease: r.prerelease, preview: false, files: [] };
		else {
			tagChoice = NEW;
			form = { id: null, tag: '', target: repo.default_branch ?? '', title: '', notes: '', draft: false, prerelease: false, preview: false, files: [] };
		}
	}
	function chooseTag(v: string) {
		tagChoice = v;
		if (form) form.tag = v === NEW ? '' : v;
	}

	function addFiles(list: FileList | File[] | null) {
		if (!form || !list) return;
		for (const f of Array.from(list)) if (!form.files.some((x) => x.name === f.name)) form.files.push(f);
	}

	/** Multipart upload with progress (fetch cannot report upload progress). */
	function upload(id: number, files: File[]): Promise<void> {
		return new Promise((resolve, reject) => {
			const fd = new FormData();
			for (const f of files) fd.append('files', f);
			const x = new XMLHttpRequest();
			x.open('POST', `/api/git/repos/${name}/releases/${id}/assets`);
			x.setRequestHeader('X-Kern', '1');
			x.upload.onprogress = (e) => e.lengthComputable && (progress = e.loaded / e.total);
			x.onload = () => {
				if (x.status >= 200 && x.status < 300) return resolve();
				let msg = x.statusText;
				try { msg = JSON.parse(x.responseText).detail ?? msg; } catch { /* not json */ }
				reject(new Error(msg));
			};
			x.onerror = () => reject(new Error('Cannot reach the server.'));
			x.send(fd);
		});
	}

	async function save() {
		if (!form || busy) return;
		busy = true;
		progress = 0;
		let id = form.id;
		try {
			const body = { title: form.title, notes: form.notes, draft: form.draft, prerelease: form.prerelease };
			if (id == null) {
				const r = await api.post<Release>(`/git/repos/${name}/releases`, { ...body, tag: form.tag.trim(), target: form.target || undefined });
				id = r.id;
				onchange(); // a new tag may have been made
			} else await api.patch<Release>(`/git/repos/${name}/releases/${id}`, body);
			if (form.files.length) await upload(id, form.files);
			form = null;
			ui.toast('Release saved');
		} catch (e) {
			ui.error(e);
			if (id != null && form && form.id == null) form.id = id; // saved already; retry only uploads
		} finally {
			busy = false;
			load();
		}
	}

	async function dropAsset(r: Release, aid: number) {
		try {
			await api.del(`/git/repos/${name}/releases/${r.id}/assets/${aid}`);
			load();
		} catch (e) {
			ui.error(e);
		}
	}

	async function remove(r: Release) {
		try {
			await api.del(`/git/repos/${name}/releases/${r.id}?delete_tag=${removing?.tag ? 1 : 0}`);
			if (removing?.tag) onchange();
			removing = null;
			load();
		} catch (e) {
			ui.error(e);
		}
	}

	const notesHtml = (s: string) => renderReadme(s);
</script>

<div class="top">
	<h3 class="section-title">Releases</h3>
	<span class="grow"></span>
	{#if !form}<button class="btn primary" onclick={() => start()}><Plus size={14} />New release</button>{/if}
</div>

{#if form}
	<div class="box form">
		{#if form.id == null}
			<div class="row">
				<label class="lbl">Tag
					<select class="input" value={tagChoice} onchange={(e) => chooseTag(e.currentTarget.value)}>
						<option value={NEW}>Create new tag…</option>
						{#each freeTags as t (t.name)}<option value={t.name}>{t.name}</option>{/each}
					</select>
				</label>
				{#if tagChoice === NEW}
					<label class="lbl">New tag name<input class="input mono" placeholder="v1.0.0" bind:value={form.tag} maxlength="200" /></label>
					<label class="lbl">From branch or commit
						<select class="input" bind:value={form.target}>
							{#each repo.branch_list as b (b.name)}<option value={b.name}>{b.name}</option>{/each}
						</select>
					</label>
				{/if}
			</div>
		{:else}
			<p class="muted tagline"><Tag size={13} /> <code>{form.tag}</code></p>
		{/if}
		<label class="lbl">Title<input class="input" placeholder={form.tag || 'Release title'} bind:value={form.title} maxlength="200" /></label>
		<div class="lbl">
			<span class="nh">Notes <span class="grow"></span>
				<span class="seg"><button class:on={!form.preview} onclick={() => form && (form.preview = false)}>Write</button><button class:on={form.preview} onclick={() => form && (form.preview = true)}>Preview</button></span>
			</span>
			{#if form.preview}
				<div class="md prev">{#if form.notes.trim()}{@html notesHtml(form.notes)}{:else}<span class="faint">Nothing to preview.</span>{/if}</div>
			{:else}
				<textarea class="input" rows="7" placeholder="What changed? Markdown is supported." bind:value={form.notes}></textarea>
			{/if}
		</div>
		<div
			class="drop" class:over role="button" tabindex="0"
			ondragover={(e) => { e.preventDefault(); over = true; }} ondragleave={() => (over = false)}
			ondrop={(e) => { e.preventDefault(); over = false; addFiles(e.dataTransfer?.files ?? null); }}
			onclick={() => picker?.click()} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && picker?.click()}
		>
			<Upload size={16} />Drop files here or click to choose. A file with the same name replaces the old one.
			<input bind:this={picker} type="file" multiple hidden onchange={(e) => { addFiles(e.currentTarget.files); e.currentTarget.value = ''; }} />
		</div>
		{#if form.files.length}
			<ul class="files">
				{#each form.files as f, i (f.name)}
					<li><FileArchive size={13} /><span class="truncate">{f.name}</span><span class="faint">{fileSize(f.size)}</span><button class="icon-btn" title="Remove" onclick={() => form?.files.splice(i, 1)}><X size={13} /></button></li>
				{/each}
			</ul>
		{/if}
		{#if busy && form.files.length}<div class="bar"><i style:width={Math.round(progress * 100) + '%'}></i></div>{/if}
		<div class="row end">
			<label class="chk"><input type="checkbox" bind:checked={form.draft} />Draft</label>
			<label class="chk"><input type="checkbox" bind:checked={form.prerelease} />Pre-release</label>
			<span class="grow"></span>
			<button class="btn ghost" disabled={busy} onclick={() => (form = null)}>Cancel</button>
			<button class="btn primary" disabled={busy || (form.id == null && !form.tag.trim())} onclick={save}>{busy ? 'Saving…' : form.id == null ? (form.draft ? 'Save draft' : 'Publish release') : 'Save'}</button>
		</div>
	</div>
{/if}

{#each releases as r (r.id)}
	<div class="box rel">
		<div class="rh">
			<h2>{r.title || r.tag}</h2>
			{#if r.draft}<span class="chip" data-c="gray">Draft</span>{/if}
			{#if r.prerelease}<span class="chip" data-c="orange">Pre-release</span>{/if}
			{#if r.tag_missing}<span class="chip" data-c="red" title="The tag was deleted from the repository">Tag missing</span>{/if}
			<span class="grow"></span>
			<button class="icon-btn" title="Edit" onclick={() => start(r)}><Pencil size={14} /></button>
			<button class="icon-btn" title="Delete" onclick={() => (removing = { id: r.id, tag: false })}><Trash2 size={14} /></button>
		</div>
		<div class="meta faint">
			<span class="tg"><Tag size={12} />{r.tag}</span>
			<span title={fullDate(r.published ?? r.created)}>{r.draft ? 'created' : 'released'} {relTime(r.published ?? r.created)}</span>
		</div>
		{#if removing?.id === r.id}
			<div class="rm">
				<span>Delete this release and its {r.assets.length} file{r.assets.length === 1 ? '' : 's'}?</span>
				{#if !r.tag_missing}<label class="chk"><input type="checkbox" bind:checked={removing.tag} />Also delete the tag <code>{r.tag}</code></label>{/if}
				<span class="grow"></span>
				<button class="btn ghost sm" onclick={() => (removing = null)}>Cancel</button>
				<button class="btn danger sm" onclick={() => remove(r)}>Delete</button>
			</div>
		{/if}
		{#if r.notes.trim()}<div class="md">{@html notesHtml(r.notes)}</div>{/if}
		<div class="assets">
			{#each r.assets as a (a.id)}
				<div class="as">
					<FileArchive size={14} class="ic" />
					<a href={a.url} download={a.filename} class="truncate">{a.filename}</a>
					<span class="grow"></span>
					<span class="faint" title={a.sha256 ? `SHA-256 ${a.sha256}` : ''}>{fileSize(a.size)}</span>
					<span class="faint dl" title="Downloads"><Download size={11} />{a.downloads}</span>
					<button class="icon-btn" title="Remove file" onclick={() => dropAsset(r, a.id)}><X size={13} /></button>
				</div>
			{/each}
			{#if !r.tag_missing}
				<div class="as src">
					<FileArchive size={14} class="ic" />
					<a href={archiveUrl(name, r.tag, 'zip')} download>Source code (zip)</a>
					<span class="grow"></span>
				</div>
				<div class="as src">
					<FileArchive size={14} class="ic" />
					<a href={archiveUrl(name, r.tag, 'tar.gz')} download>Source code (tar.gz)</a>
					<span class="grow"></span>
				</div>
			{/if}
		</div>
	</div>
{:else}
	{#if loaded && !form}
		<div class="empty"><b>No releases yet</b>Publish a tag with notes and downloadable files.</div>
	{/if}
{/each}

<style>
	.top { display: flex; align-items: center; margin-bottom: 10px; }
	.top .section-title { margin: 0; }
	.grow { flex: 1; }
	.form { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
	.row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
	.row.end { align-items: center; }
	.lbl { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); flex: 1; min-width: 160px; }
	.mono { font-family: var(--font-mono); }
	.tagline { display: flex; align-items: center; gap: 6px; margin: 0; }
	.nh { display: flex; align-items: center; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 1px 9px; border-radius: 4px; color: var(--text-2); font-size: 12px; font-weight: 500; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.prev { min-height: 120px; padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--radius); }
	.drop { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 16px; border: 1px dashed var(--border-strong); border-radius: 8px; color: var(--text-2); font-size: 13px; cursor: pointer; text-align: center; }
	.drop:hover, .drop.over { border-color: var(--accent); background: var(--hover); }
	.files { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
	.files li { display: flex; align-items: center; gap: 8px; }
	.files li :global(svg) { color: var(--text-3); flex: none; }
	.files .truncate { flex: 1; min-width: 0; }
	.bar { height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden; }
	.bar i { display: block; height: 100%; background: var(--accent); transition: width 0.15s; }
	.chk { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); }
	.rel { padding: 14px 16px 6px; }
	.rh { display: flex; align-items: center; gap: 8px; }
	.rh h2 { margin: 0; font-size: 17px; font-weight: 650; }
	.meta { display: flex; align-items: center; gap: 12px; font-size: 12.5px; margin: 4px 0 8px; }
	.tg { display: inline-flex; align-items: center; gap: 4px; font-family: var(--font-mono); color: var(--text-2); }
	.rm { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 10px; margin-bottom: 8px; border-radius: var(--radius); background: var(--surface-2); font-size: 13px; }
	.rm code { font: 12px var(--font-mono); }
	.md { padding: 0; line-height: 1.6; overflow-wrap: anywhere; font-size: 14px; }
	.md :global(p) { margin: 0 0 10px; }
	.md :global(a) { color: var(--accent); }
	.md :global(code) { font: 0.88em var(--font-mono); padding: 1.5px 5px; border-radius: 4px; background: var(--code-bg); }
	.md :global(pre) { padding: 10px 12px; border-radius: 6px; background: var(--code-bg); overflow-x: auto; }
	.md :global(pre code) { padding: 0; background: none; }
	.md :global(ul), .md :global(ol) { padding-left: 22px; margin: 0 0 10px; }
	.md :global(h1), .md :global(h2), .md :global(h3) { font-size: 1.05em; margin: 12px 0 6px; }
	.assets { margin: 10px -16px 0; border-top: 1px solid var(--border); }
	.as { display: flex; align-items: center; gap: 9px; padding: 6px 16px; border-top: 1px solid var(--border); font-size: 13px; }
	.as:first-child { border-top: 0; }
	.as :global(.ic) { color: var(--text-3); flex: none; }
	.as a { color: var(--accent); text-decoration: none; }
	.as a:hover { text-decoration: underline; }
	.as.src a { color: var(--text-2); }
	.dl { display: inline-flex; align-items: center; gap: 3px; min-width: 38px; font-size: 12px; }
	.btn.sm { height: 24px; padding: 0 8px; font-size: 12px; }
</style>
