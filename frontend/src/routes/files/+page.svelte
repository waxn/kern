<script lang="ts">
	import { AudioLines, Copy, Download, Eye, FileText, Film, Image, Music, Pencil, Play, Search, Trash2, Upload } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import FilePreview from '#lib/components/FilePreview.svelte';
	import { fileKind, isMedia } from '#lib/files/kind.ts';
	import { player } from '#lib/files/player.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, relTime } from '#lib/util.ts';

	interface F { id: string; url: string; name: string; mime: string; size: number; created_at: string; used_in: { id: string | null; title: string; trashed: boolean }[] }
	let list = $state<F[]>([]);
	let loaded = $state(false);
	let q = $state('');
	let type = $state('');
	let view = $state<'grid' | 'list'>('grid');
	let preview = $state<F | null>(null);
	let picker = $state<HTMLInputElement>();
	let unusedOnly = $state(false);

	async function load() {
		try {
			list = await api.get<F[]>('/library' + qs({ q, type }));
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);
	$effect(() => {
		void q; void type;
		const t = setTimeout(load, 150);
		return () => clearTimeout(t);
	});

	let shown = $derived(unusedOnly ? list.filter((f) => !f.used_in.length) : list);
	let total = $derived(list.reduce((n, f) => n + f.size, 0));

	async function upload(files: FileList | null) {
		if (!files?.length) return;
		for (const f of files) await api.upload(f).catch((e) => ui.error(e));
		load();
	}

	async function rename(f: F) {
		const name = prompt('File name', f.name)?.trim();
		if (!name || name === f.name) return;
		await api.patch(`/library/${f.id}`, { name }).catch((e) => ui.error(e));
		load();
	}

	async function remove(f: F) {
		const used = f.used_in.length;
		const ok = await ui.confirm({
			title: `Delete “${f.name}”?`,
			message: used ? `It is still used in ${f.used_in.map((u) => u.title || 'Untitled').slice(0, 3).join(', ')}${used > 3 ? '…' : ''}. Those places will show a broken file. This cannot be undone.` : 'The file is not used anywhere. This cannot be undone.',
			confirmLabel: 'Delete file', danger: true
		});
		if (!ok) return;
		await api.del(`/library/${f.id}`).catch((e) => ui.error(e));
		load();
	}

	/** Media plays in the app-wide player (keeps going while you browse); everything else opens a viewer. */
	function openFile(f: F) {
		if (isMedia(f)) player.open(f);
		else preview = f;
	}

	const icon = (m: string) => (m.startsWith('image/') ? Image : m.startsWith('video/') ? Film : m.startsWith('audio/') ? Music : FileText);
	const types: [string, string][] = [['', 'All'], ['image', 'Images'], ['pdf', 'PDFs'], ['video', 'Video'], ['audio', 'Audio'], ['other', 'Other']];
</script>

<div class="page-scroll">
	<div class="page wide">
		<div class="titlebar">
			<h1>Files</h1>
			<span class="faint">{list.length} files · {fileSize(total)}</span>
			<span class="grow"></span>
			<input type="file" multiple hidden bind:this={picker} onchange={(e) => upload(e.currentTarget.files)} />
			<button class="btn primary" onclick={() => picker?.click()}><Upload size={14} />Upload</button>
		</div>
		<p class="lede">Everything you have uploaded. Files can be reused on any page from an image, video, audio or file block.</p>
		<div class="bar">
			<div class="search"><Search size={14} class="faint" /><input bind:value={q} placeholder="Search by name…" /></div>
			<div class="seg">{#each types as [t, label] (t)}<button class:on={type === t} onclick={() => (type = t)}>{label}</button>{/each}</div>
			<label class="check"><input type="checkbox" bind:checked={unusedOnly} />Unused only</label>
			<div class="seg"><button class:on={view === 'grid'} onclick={() => (view = 'grid')}>Grid</button><button class:on={view === 'list'} onclick={() => (view = 'list')}>List</button></div>
		</div>

		{#if shown.length}
			<div class={view}>
				{#each shown as f (f.id)}
					{@const Icon = icon(f.mime)}
					<div class="file">
						<button class="thumb" class:playing={player.file?.url === f.url} onclick={() => openFile(f)} title={isMedia(f) ? 'Play' : 'Open'}>
							{#if f.mime.startsWith('image/')}<img src={f.url} alt="" loading="lazy" />
							{:else if fileKind(f) === 'video' && view === 'grid'}<video src={f.url + '#t=1'} preload="metadata" muted playsinline tabindex="-1"></video><span class="playbadge"><Play size={16} fill="currentColor" /></span>
							{:else}<Icon size={view === 'grid' ? 28 : 16} strokeWidth={1.5} />{/if}
							{#if player.file?.url === f.url}<span class="nowplaying" title="Playing"><AudioLines size={13} /></span>{/if}
						</button>
						<div class="meta">
							<span class="name truncate" title={f.name}>{f.name}</span>
							<span class="sub faint">{fileSize(f.size)} · {relTime(f.created_at)}</span>
							<span class="uses">
								{#each f.used_in.slice(0, 3) as u (u.id ?? u.title)}
									{#if u.id}<a href="/doc/{u.id}" class:trashed={u.trashed} onclick={(e) => { e.preventDefault(); open(`/doc/${u.id}`, e); }}>{u.title || 'Untitled'}</a>{:else}<span>{u.title}</span>{/if}
								{:else}<span class="faint">Not used</span>{/each}
							</span>
						</div>
						<div class="acts">
							<button class="icon-btn" title={isMedia(f) ? 'Play' : 'Open'} onclick={() => openFile(f)}>{#if isMedia(f)}<Play size={14} />{:else}<Eye size={14} />{/if}</button>
							<a class="icon-btn" title="Download" href={f.url} download={f.name}><Download size={14} /></a>
							<button class="icon-btn" title="Copy link" onclick={() => navigator.clipboard?.writeText(location.origin + f.url).then(() => ui.toast('Link copied'))}><Copy size={14} /></button>
							<button class="icon-btn" title="Rename" onclick={() => rename(f)}><Pencil size={14} /></button>
							<button class="icon-btn" title="Delete" onclick={() => remove(f)}><Trash2 size={14} /></button>
						</div>
					</div>
				{/each}
			</div>
		{:else if loaded}
			<div class="empty"><b>{q || type || unusedOnly ? 'No files match' : 'No files yet'}</b>Upload here, or drop files onto any page.</div>
		{/if}
	</div>
</div>

{#if preview}<FilePreview file={preview} onclose={() => (preview = null)} onchange={load} />{/if}

<style>
	.wide { max-width: 1100px; }
	.titlebar { display: flex; align-items: baseline; gap: 12px; }
	.grow { flex: 1; }
	.bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
	.search { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 160px; height: 28px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); }
	.search input { flex: 1; border: 0; outline: 0; background: none; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 2px 9px; border-radius: 4px; color: var(--text-2); font-size: 12.5px; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.check { display: flex; align-items: center; gap: 5px; color: var(--text-2); font-size: 12.5px; }
	.check input { accent-color: var(--accent); }
	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
	.grid .file { position: relative; display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.grid .thumb { height: 120px; display: grid; place-items: center; background: var(--surface-2); color: var(--text-3); }
	.grid .thumb img, .grid .thumb video { width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
	.thumb { position: relative; }
	.playbadge { position: absolute; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: rgba(0, 0, 0, 0.55); }
	.nowplaying { position: absolute; left: 6px; bottom: 6px; display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; color: #17130c; background: var(--accent); }
	.list .nowplaying { left: auto; bottom: auto; width: 18px; height: 18px; }
	.thumb.playing { color: var(--accent); }
	.grid .meta { padding: 7px 9px; display: flex; flex-direction: column; min-width: 0; }
	.grid .acts { position: absolute; top: 6px; right: 6px; display: none; gap: 1px; padding: 2px; border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow); }
	.grid .file:hover .acts { display: flex; }
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.list .file { display: flex; align-items: center; gap: 10px; padding: 5px 10px; border-top: 1px solid var(--border); }
	.list .file:first-child { border-top: 0; }
	.list .thumb { width: 34px; height: 34px; flex: none; display: grid; place-items: center; border-radius: 4px; overflow: hidden; background: var(--surface-2); color: var(--text-3); }
	.list .thumb img { width: 100%; height: 100%; object-fit: cover; }
	.list .meta { flex: 1; min-width: 0; display: grid; grid-template-columns: minmax(0, 2fr) 160px minmax(0, 1.5fr); gap: 10px; align-items: center; }
	.list .acts { display: flex; gap: 1px; }
	.name { font-weight: 500; }
	.sub { font-size: 12px; }
	.uses { display: flex; gap: 6px; font-size: 12px; overflow: hidden; white-space: nowrap; }
	.uses a { color: var(--text-2); text-decoration: none; }
	.uses a:hover { color: var(--accent); }
	.uses a.trashed { text-decoration: line-through; }
	@media (hover: none) { .grid .acts { display: flex; } }
</style>
