<script lang="ts">
	import { ArrowLeft, Bookmark, Check, Download, ExternalLink, FileText, Film, Image as ImageIcon, Plus, RefreshCw, Search, Trash2, X } from '@lucide/svelte';
	import { onDestroy, onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { relTime } from '#lib/util.ts';

	type Kind = 'web' | 'video' | 'image' | 'mixed';
	interface Todo { text: string; done: boolean }
	interface Item {
		id: string; url: string; title: string; kind: Kind; thumbnail: string; duration: number | null;
		author: string; description: string; is_processed: boolean; error_message: string | null;
		video_status: '' | 'downloading' | 'done' | 'error'; video_url: string; created_at: string;
		todo_count: number;
	}
	interface Detail extends Item {
		has_html: boolean; notes: string; todos: Todo[]; video_format: 'best' | 'audio'; video_quality: '' | '1080p' | '720p' | '480p';
	}

	let list = $state<Item[]>([]);
	let loaded = $state(false);
	let q = $state('');
	let kind = $state('');
	let view = $state<'grid' | 'list'>('grid');
	let newUrl = $state('');
	let adding = $state(false);

	let detail = $state<Detail | null>(null);
	let html = $state('');
	let title = $state('');
	let author = $state('');
	let description = $state('');
	let notes = $state('');
	let todoText = $state('');
	let poll: ReturnType<typeof setInterval> | undefined;

	const kinds: { id: string; label: string }[] = [
		{ id: '', label: 'All' }, { id: 'web', label: 'Pages' }, { id: 'video', label: 'Videos' }, { id: 'image', label: 'Images' }
	];
	const icons = { web: FileText, video: Film, image: ImageIcon, mixed: Bookmark };

	async function load() {
		try {
			list = await api.get<Item[]>('/web/list' + qs({ q, kind }));
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);
	onDestroy(() => clearInterval(poll));
	$effect(() => {
		void q; void kind;
		const t = setTimeout(load, 150);
		return () => clearTimeout(t);
	});

	function setDetail(d: Detail) {
		detail = d;
		title = d.title; author = d.author; description = d.description; notes = d.notes;
		clearInterval(poll);
		if (d.video_status === 'downloading') poll = setInterval(refresh, 2000);
	}

	async function refresh() {
		if (!detail) return;
		try {
			const d = await api.get<Detail>('/web/' + detail.id);
			const was = detail.video_status;
			detail = { ...detail, video_status: d.video_status, video_url: d.video_url, error_message: d.error_message, duration: d.duration };
			if (d.video_status !== 'downloading') {
				clearInterval(poll);
				if (was === 'downloading' && d.video_status === 'done') ui.toast('Video downloaded');
				load();
			}
		} catch {
			clearInterval(poll);
		}
	}

	async function open(id: string) {
		try {
			setDetail(await api.get<Detail>('/web/' + id));
			html = '';
			if (detail?.has_html) {
				const p = await api.get<{ type: string; content?: string }>(`/web/${id}/preview`);
				if (p.type === 'html') html = p.content ?? '';
			}
		} catch (e) {
			ui.error(e);
		}
	}

	function back() {
		clearInterval(poll);
		detail = null;
		load();
	}

	async function add() {
		const url = newUrl.trim();
		if (!url || adding) return;
		adding = true;
		try {
			const d = await api.post<Detail>('/web/archive', { url });
			newUrl = '';
			if (d.error_message) ui.toast(d.error_message, { kind: 'error' });
			await load();
		} catch (e) {
			ui.error(e);
		}
		adding = false;
	}

	async function patch(body: Record<string, unknown>) {
		if (!detail) return;
		try {
			const d = await api.patch<Detail>('/web/' + detail.id, body);
			detail = { ...detail, ...d };
		} catch (e) {
			ui.error(e);
		}
	}

	const saveMeta = () => {
		if (detail && (title !== detail.title || author !== detail.author || description !== detail.description)) patch({ title, author, description });
	};
	const saveNotes = () => {
		if (detail && notes !== detail.notes) patch({ notes });
	};

	function addTodo() {
		const text = todoText.trim();
		if (!text || !detail) return;
		todoText = '';
		patch({ todos: [...detail.todos, { text, done: false }] });
	}
	const toggleTodo = (i: number) => detail && patch({ todos: detail.todos.map((t, j) => (j === i ? { ...t, done: !t.done } : t)) });
	const removeTodo = (i: number) => detail && patch({ todos: detail.todos.filter((_, j) => j !== i) });

	async function reprocess() {
		if (!detail) return;
		try {
			const d = await api.post<Detail>(`/web/${detail.id}/process`);
			setDetail({ ...detail, ...d });
		} catch (e) {
			ui.error(e);
		}
	}

	async function download() {
		if (!detail) return;
		try {
			const d = await api.post<Detail>(`/web/${detail.id}/download-video`, { video_format: detail.video_format, video_quality: detail.video_quality });
			detail = { ...detail, video_status: d.video_status, error_message: null };
			clearInterval(poll);
			poll = setInterval(refresh, 2000);
		} catch (e) {
			ui.error(e);
		}
	}

	async function remove() {
		if (!detail) return;
		const ok = await ui.confirm({
			title: `Delete “${detail.title || detail.url}”?`,
			message: 'The bookmark, its notes and any downloaded video are removed. This cannot be undone.',
			confirmLabel: 'Delete', danger: true
		});
		if (!ok) return;
		try {
			await api.del('/web/' + detail.id);
			back();
		} catch (e) {
			ui.error(e);
		}
	}

	const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };
	const dur = (s: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '');
	const frameDoc = (h: string) => `<base target="_blank"><style>body{font-family:system-ui,sans-serif;line-height:1.5;padding:12px;max-width:900px;margin:auto}img{max-width:100%;height:auto}</style>${h}`;
</script>

<div class="page-scroll">
	<div class="page wide">
		{#if detail}
			{@const Icon = icons[detail.kind]}
			<div class="titlebar">
				<button class="btn ghost" onclick={back}><ArrowLeft size={14} />Back</button>
				<h1 class="truncate">{detail.title || host(detail.url)}</h1>
				<span class="grow"></span>
				<button class="icon-btn" title="Re-fetch page" onclick={reprocess}><RefreshCw size={14} /></button>
				<a class="icon-btn" title="Open original" href={detail.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} /></a>
				<button class="icon-btn" title="Delete" onclick={remove}><Trash2 size={14} /></button>
			</div>

			<div class="content">
				<div class="main">
					{#if detail.video_url}
						<!-- svelte-ignore a11y_media_has_caption -->
						<video class="media" src={detail.video_url} controls preload="metadata"></video>
					{:else if html}
						<iframe class="frame" title="Archived page" sandbox="" srcdoc={frameDoc(html)}></iframe>
					{:else if detail.kind === 'image' && detail.thumbnail}
						<img class="media" src={detail.thumbnail} alt={detail.title} />
					{:else}
						<div class="placeholder">
							{#if detail.thumbnail}<img src={detail.thumbnail} alt="" />{:else}<Icon size={96} strokeWidth={1.25} />{/if}
						</div>
					{/if}
				</div>

				<div class="side">
					{#if detail.error_message}<div class="error">{detail.error_message}</div>{/if}
					<div class="faint small">{host(detail.url)} · saved {relTime(detail.created_at)}{detail.duration ? ' · ' + dur(detail.duration) : ''}</div>

					<label>Title<input bind:value={title} onblur={saveMeta} onkeydown={(e) => e.key === 'Enter' && (e.target as HTMLElement).blur()} /></label>
					<label>Author<input bind:value={author} onblur={saveMeta} /></label>
					<label>Description<textarea rows="3" bind:value={description} onblur={saveMeta}></textarea></label>

					{#if detail.kind === 'video'}
						<div class="box">
							<b>Download video</b>
							<div class="row">
								<select value={detail.video_format} onchange={(e) => detail && (detail.video_format = (e.target as HTMLSelectElement).value as 'best' | 'audio')}>
									<option value="best">Video</option><option value="audio">Audio only</option>
								</select>
								{#if detail.video_format === 'best'}
									<select value={detail.video_quality} onchange={(e) => detail && (detail.video_quality = (e.target as HTMLSelectElement).value as Detail['video_quality'])}>
										<option value="">Best quality</option><option value="1080p">1080p</option><option value="720p">720p</option><option value="480p">480p</option>
									</select>
								{/if}
								<button class="btn primary" disabled={detail.video_status === 'downloading'} onclick={download}>
									{#if detail.video_status === 'downloading'}Downloading…
									{:else if detail.video_status === 'done'}<Check size={14} />Re-download
									{:else}<Download size={14} />Download{/if}
								</button>
							</div>
						</div>
					{/if}

					<label>Notes<textarea rows="5" bind:value={notes} onblur={saveNotes} placeholder="Add notes about this bookmark…"></textarea></label>

					<div class="todos">
						<b>To-do</b>
						{#each detail.todos as t, i}
							<div class="todo" class:done={t.done}>
								<input type="checkbox" checked={t.done} onchange={() => toggleTodo(i)} />
								<span class="grow">{t.text}</span>
								<button class="icon-btn" title="Remove" onclick={() => removeTodo(i)}><X size={12} /></button>
							</div>
						{/each}
						<input placeholder="Add a to-do and press Enter" bind:value={todoText} onkeydown={(e) => e.key === 'Enter' && addTodo()} />
					</div>
				</div>
			</div>
		{:else}
			<div class="titlebar">
				<h1>Bookmarks</h1>
				<span class="faint">{list.length} {list.length === 1 ? 'item' : 'items'}</span>
				<span class="grow"></span>
				<form class="add" onsubmit={(e) => { e.preventDefault(); add(); }}>
					<input placeholder="Paste a URL to save…" bind:value={newUrl} disabled={adding} />
					<button class="btn primary" disabled={adding || !newUrl.trim()}><Plus size={14} />{adding ? 'Saving…' : 'Save'}</button>
				</form>
			</div>

			<div class="bar">
				<div class="search"><Search size={14} class="faint" /><input bind:value={q} placeholder="Search bookmarks…" /></div>
				<div class="seg">
					{#each kinds as k}<button class:on={kind === k.id} onclick={() => (kind = k.id)}>{k.label}</button>{/each}
				</div>
				<div class="seg">
					<button class:on={view === 'grid'} onclick={() => (view = 'grid')}>Grid</button>
					<button class:on={view === 'list'} onclick={() => (view = 'list')}>List</button>
				</div>
			</div>

			{#if list.length}
				<div class={view}>
					{#each list as a (a.id)}
						{@const AIcon = icons[a.kind]}
						<button class="card" onclick={() => open(a.id)}>
							<span class="thumb">
								{#if a.thumbnail}<img src={a.thumbnail} alt="" loading="lazy" referrerpolicy="no-referrer" />{:else}<AIcon size={40} strokeWidth={1.5} />{/if}
								{#if a.duration}<span class="badge">{dur(a.duration)}</span>{/if}
								{#if a.video_status === 'done'}<span class="badge left"><Download size={11} /></span>{/if}
							</span>
							<span class="info">
								<span class="t">{a.title || host(a.url)}</span>
								<span class="faint small">{host(a.url)}{a.author ? ' · ' + a.author : ''}</span>
								{#if view === 'list' && a.description}<span class="faint small d">{a.description}</span>{/if}
								{#if a.error_message}<span class="small err">Couldn't fetch</span>{/if}
							</span>
						</button>
					{/each}
				</div>
			{:else if loaded}
				<div class="empty">
					<Bookmark size={40} class="faint" />
					<b>{q || kind ? 'Nothing matches' : 'No bookmarks yet'}</b>
					<p class="faint">Paste a link above to save a page, video or image. YouTube and similar videos can be downloaded.</p>
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.page.wide { max-width: 1400px; }
	.titlebar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
	.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
	.add { display: flex; gap: 6px; flex: 1; max-width: 520px; }
	.add input, label input, label textarea, .todos > input, select {
		border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 5px 8px; font: inherit; font-size: 13.5px; background: var(--surface); color: var(--text); outline: none; min-width: 0;
	}
	.add input { flex: 1; }
	input:focus, textarea:focus, select:focus { box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent); }
	.bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
	.search { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 180px; border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 0 8px; }
	.search input { border: none; outline: none; flex: 1; background: none; color: inherit; height: 28px; font: inherit; box-shadow: none; }
	.small { font-size: 12.5px; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 2px 9px; border-radius: 4px; color: var(--text-2); font-size: 12.5px; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }

	.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
	.list { display: flex; flex-direction: column; gap: 6px; }
	.card { display: flex; flex-direction: column; text-align: left; gap: 8px; padding: 0; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); overflow: hidden; cursor: pointer; color: inherit; font: inherit; transition: background 0.15s; }
	.card:hover { background: var(--surface-2); }
	.list .card { flex-direction: row; align-items: center; padding: 6px; }
	.thumb { position: relative; display: grid; place-items: center; aspect-ratio: 16 / 9; background: var(--surface-2); color: var(--text-3); overflow: hidden; }
	.list .thumb { width: 120px; flex: none; border-radius: 6px; }
	.thumb img { width: 100%; height: 100%; object-fit: cover; }
	.badge { position: absolute; right: 6px; bottom: 6px; background: rgba(0, 0, 0, 0.7); color: #fff; font-size: 11px; padding: 1px 5px; border-radius: 4px; display: flex; align-items: center; gap: 3px; }
	.badge.left { right: auto; left: 6px; }
	.info { display: flex; flex-direction: column; gap: 2px; padding: 0 10px 10px; min-width: 0; }
	.list .info { padding: 0; }
	.t { font-weight: 600; font-size: 14px; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
	.d { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
	.err { color: var(--danger, #c0392b); }

	.empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 60px 0; text-align: center; }

	.content { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(280px, 380px); gap: 24px; align-items: start; }
	.media { width: 100%; max-height: 70vh; border-radius: 10px; background: #000; object-fit: contain; }
	.frame { width: 100%; height: 70vh; border: 1px solid var(--border); border-radius: 10px; background: #fff; }
	.placeholder { display: grid; place-items: center; min-height: 260px; background: var(--surface-2); border-radius: 10px; color: var(--text-3); overflow: hidden; }
	.placeholder img { max-width: 100%; max-height: 420px; }
	.side { display: flex; flex-direction: column; gap: 12px; }
	label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
	textarea { resize: vertical; }
	.box { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
	.row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
	.error { background: color-mix(in srgb, #c0392b 15%, transparent); padding: 8px; border-radius: 6px; font-size: 13px; }
	.todos { display: flex; flex-direction: column; gap: 4px; }
	.todo { display: flex; align-items: center; gap: 6px; font-size: 13.5px; }
	.todo.done span { text-decoration: line-through; opacity: 0.6; }
	.icon-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; height: 28px; border-radius: 6px; border: 1px solid transparent; color: var(--text-2); background: none; cursor: pointer; }
	.icon-btn:hover { color: var(--text); background: var(--hover); }

	@media (max-width: 800px) {
		.content { grid-template-columns: 1fr; }
	}
</style>
