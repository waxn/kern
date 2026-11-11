<script lang="ts">
	import { Bookmark, Check, Eye, FileText, Film, Image, Pencil, Plus, Search, Trash2, Upload } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { Doc } from '#lib/types.ts';

	interface WebArchive {
		id: string;
		url: string;
		title: string;
		kind: 'web' | 'video' | 'image' | 'mixed';
		thumbnail: string;
		duration: number | null;
		author: string;
		description: string;
		html_content: string;
		notes: string;
		todos: string[];
		is_processed: boolean;
		error_message: string | null;
		created_at: string;
		last_viewed_at: string | null;
	}

	interface WebArchiveDetail extends WebArchive {
		download_html: boolean;
		download_images: boolean;
		download_video: boolean;
		video_format: string;
		video_quality: string;
	}

	interface WebArchiveFormData {
		url?: string;
		title?: string;
		author?: string;
		description?: string;
		kind?: 'web' | 'video' | 'image' | 'mixed';
		notes?: string;
		todos?: string[];
		download_html?: boolean;
		download_images?: boolean;
		download_video?: boolean;
		video_format?: 'best' | 'audio';
		video_quality?: '1080p' | '720p' | '480p';
	}

	let list = $state<WebArchive[]>([]);
	let loaded = $state(false);
	let q = $state('');
	let view = $state<'grid' | 'list'>('grid');
	let archiveId = $state<string | null>(null);
	let editMode = $state<'view' | 'edit' | 'notes' | 'todo'>('view');
	let detail = $state<WebArchiveDetail | null>(null);
	let picker = $state<HTMLInputElement>();
	let newUrlInput = $state<HTMLInputElement>();

	async function load() {
		try {
			list = await api.get<WebArchive[]>('/web/list' + qs({ q }));
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}

	onMount(load);
	$effect(() => {
		void q;
		const t = setTimeout(load, 150);
		return () => clearTimeout(t);
	});

	let shown = $derived(list);

	async function upload(files: FileList | null) {
		if (!files?.length) return;
		for (const f of files) await api.upload(f).catch((e) => ui.error(e));
		load();
	}

	const icon = (k: string) => ({
		web: FileText,
		video: Film,
		image: Image,
		mixed: Bookmark,
	})[k];

	const kindLabel = (k: string) => ({
		web: 'Webpage',
		video: 'Video',
		image: 'Image',
		mixed: 'Mixed',
	})[k];

	function openArchive(id: string, e: MouseEvent) {
		e.preventDefault();
		archiveId = id;
		editMode = 'view';
	}

	async function loadDetail(id: string) {
		try {
			detail = await api.get<WebArchiveDetail>('/web/' + id);
			archiveId = id;
		} catch (e) {
			ui.error(e);
		}
	}

	function goBack() {
		archiveId = null;
		editMode = 'view';
	}

	async function createArchive(url: string) {
		if (!url.trim()) return;

		try {
			const data: WebArchiveFormData = {
				url,
				title: '',
				author: '',
				description: '',
				kind: detectKindFromUrl(url),
				notes: '',
				todos: [],
				download_html: true,
				download_images: false,
				download_video: false,
				video_format: 'best',
				video_quality: '',
			};

			const res = await api.post('/web/archive', data);
			if (res) {
				goBack();
				load();
			}
		} catch (e) {
			ui.error(e);
		}
	}

	function detectKindFromUrl(url: string): 'web' | 'video' | 'image' | 'mixed' {
		if (url.includes('youtube.com') || url.includes('youtu.be') ||
		    url.includes('vimeo.com') || url.includes('twitch.tv') ||
		    url.includes('tiktok.com')) return 'video';

		const ext = (new URL(url).pathname.toLowerCase() || '').split('/').pop()?.toLowerCase();
		if (ext === '.jpg' || ext === '.jpeg' || ext === '.png' ||
		    ext === '.gif' || ext === '.webp' || ext === '.bmp') return 'image';

		return 'web';
	}

	async function removeArchive(id: string) {
		const ok = await ui.confirm({
			title: 'Delete archive',
			message: 'This will permanently delete the archived content. This cannot be undone.',
			danger: true,
		});
		if (!ok) return;

		await api.del(`/web/${id}`).catch(() => {});
		goBack();
		load();
	}

	async function editNotes(id: string) {
		try {
			detail = await api.get<WebArchiveDetail>('/web/' + id);
			editMode = 'notes';
		} catch (e) {
			ui.error(e);
		}
	}

	async function saveNotes() {
		if (!detail || !archiveId) return;

		try {
			const notes = (document.getElementById('edit-notes') as HTMLTextAreaElement).value;
			await api.patch(`/web/${archiveId}`, { notes });
			goBack();
			loadDetail(archiveId);
		} catch (e) {
			ui.error(e);
		}
	}

	async function addTodo(text: string) {
		if (!detail || !archiveId) return;
		if (!text.trim()) return;

		try {
			const todos = detail.todos ? [...detail.todos, text.trim()] : [text.trim()];
			await api.patch(`/web/${archiveId}`, { todos });
			goBack();
			loadDetail(archiveId);
		} catch (e) {
			ui.error(e);
		}
	}

	async function downloadVideo(id: string) {
		const ok = await ui.confirm({
			title: 'Download video?',
			message: 'This will use yt-dlp to download the video or audio from the archived URL.',
		});
		if (!ok) return;

		try {
			detail = await api.get<WebArchiveDetail>('/web/' + id);
			const res = await api.post(`/web/${archiveId}/download-video`);
			if (res?.status === 'success') {
				goBack();
				loadDetail(archiveId);
				ui.toast('Video downloaded!');
			} else if (res) {
				ui.error(res.detail ?? 'Download failed');
			}
		} catch (e) {
			ui.error(e);
		}
	}

	function toggleTodo(todo: string) {
		if (!detail || !archiveId) return;

		try {
			const index = detail.todos.indexOf(todo);
			const todos = [...(detail.todos || [])];
			todos.splice(index, 1);
			api.patch(`/web/${archiveId}`, { todos }).catch(() => {});
		} catch (e) {
			// ignore errors in background toggle
		}
	}

	let todoInput = $state('');
	function onTodoEnter(e: Event) {
		const input = e.target as HTMLInputElement;
		addTodo(input.value);
		input.value = '';
	}
</script>

<div class="page-scroll">
	<div class="page wide">
		{#if archiveId}
			{@const ArchiveIcon = icon(detail?.kind || 'web')}

			<div class="titlebar">
				<button class="ghost" onclick={goBack}>← Back</button>
				<h1>{detail?.title || 'Untitled'}</h1>
				<span class="faint">{kindLabel(detail?.kind || 'web')}</span>
				<span class="grow"></span>
				{#if editMode !== 'edit'}
					<button class="btn" onclick={() => (editMode = 'edit')}><Pencil size={14} />Edit</button>
				{/if}
			</div>

			<div class="content">
				{@const thumbUrl = detail?.thumbnail || ''}
				<div class={detail?.kind === 'image' ? 'full-image' : ''}>
					{#if detail?.html_content}
						<iframe 
							src="about:blank" 
							class="content-frame"
							onload={(e) => {
								const iframe = e.target as HTMLIFrameElement;
								if (iframe.contentWindow) {
									try {
										iframe.contentWindow?.document.body.innerHTML = detail.html_content;
									} catch {}
								}
							}}
						></iframe>
					{:else if thumbUrl}
						<a class="thumbnail" href={thumbUrl} target="_blank">
							{#if detail.kind === 'image' && detail.raw_image}
								<img src="data:{detail.image_mime || 'image/png';base64},{detail.raw_image}" loading="lazy" />
							{:else}
								<ArchiveIcon size={128} strokeWidth={1.5} />
							{/if}
						</a>
					{:else}
						<ArchiveIcon size={128} strokeWidth={1.5} class="empty-icon" />
					{/if}

					<div class="meta">
						{#if detail?.duration}
							<span class="duration">{Math.floor(detail.duration)}s</span>
						{/if}
						{#if detail?.author}
							<span class="author">{detail.author}</span>
						{/if}
					</div>

					<div class="info">
						{@const description = detail?.description || ''}
						<p class="description truncate-3" style:lineClamp={3}>{description || 'No description available.'}</p>

						{#if editMode === 'edit' && newUrlInput}
							<input 
								type="text" 
								class="edit-url"
								placeholder="Edit URL..."
								bind:this={newUrlInput}
								onkeydown={(e) => e.key === 'Enter' && createArchive(newUrlInput.value)}
							>
						{/if}

						{#if detail?.error_message}
							<div class="error">{detail.error_message}</div>
						{/if}

						{#if editMode !== 'edit'}
							<div class="actions">
								{#if editMode === 'view'}
									<button class:ghost={editMode === 'view'} class:on={editMode === 'view'} onclick={() => (editMode = 'edit')}>Edit</button>
									<button class:ghost={editMode === 'notes' && !archiveId} class:on={editMode === 'notes' && !archiveId} onclick={() => editNotes(archiveId)}>Add notes</button>
								{:else if editMode === 'edit'}
									<input 
										type="text" 
										class="edit-title"
										bind:value={detail.title}
										oninput={() => api.patch(`/web/${archiveId}`, { title: detail.title }).catch(() => {})}
									>
								{/if}
							</div>
						{/if}

						{#if editMode === 'edit'}
							<div class="edit-row">
								<button class="btn ghost" onclick={() => (editMode = 'view')}>Cancel</button>
								<button class="btn primary" onclick={() => { createArchive(detail.url); loadDetail(archiveId); }}>Save</button>
							</div>
						{/if}

						{#if editMode === 'notes' && detail}
							<textarea 
								id="edit-notes"
								class="notes-editor"
								bind:value={detail.notes}
								placeholder="Add notes about this archive..."
								onkeydown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) ? saveNotes() : null}
							></textarea>
							<div class="edit-actions">
								<button class="btn ghost" onclick={() => (editMode = 'view')}>Cancel</button>
								<button class="btn primary" onclick={saveNotes}>Save notes</button>
							</div>
						{/if}

						{#if detail?.todos?.length}
							<div class="todos">
								{#each detail.todos as todo (todo)}
									<div class={detail.todos.indexOf(todo) === -1 ? 'done' : ''}>
										<input type="checkbox" checked={detail.todos.indexOf(todo) === -1} on:change={() => toggleTodo(todo)}>
										<span onclick={() => toggleTodo(todo)} class:strikethrough={detail.todos.indexOf(todo) === -1}>{todo}</span>
									</div>
								{/each}
							</div>

							<div class="add-todo">
								<input 
									type="text" 
									placeholder="Add a todo…"
									bind:value={todoInput}
									onkeydown={onTodoEnter}
								>
							</div>
						{/if}
					</div>

					<div class="foot">
						<span class="url truncate-1" style:lineClamp={1}>{detail?.url}</span>
						<div class="btns">
							<a class="icon-btn" href={detail?.url} target="_blank"><Eye size={14} />View</a>
							<button class="icon-btn" onclick={() => removeArchive(detail.id)}><Trash2 size={14} /></button>
						</div>

						{#if detail && detail.kind === 'video' && detail.url}
							<div class="download-video">
								<button class:primary={detail.download_video} class:on={detail.download_video ? 'on' : ''} onclick={() => downloadVideo(detail.id)}>
									{#if detail.download_video}
										<span class="check"><Check size={14} /><span>Downloaded</span></span>
									{:else}
										<Download size={14} /><span>Download</span>
									{/if}
								</button>
							</div>
						{/if}
					</div>

					{#if editMode !== 'view'}
						<input type="text" hidden bind:this={newUrlInput}>
					{/if}
				</div>
			</div>
		{:else}
			<div class="titlebar">
				<h1>Bookmarks</h1>
				<span class="faint">{list.length} {list.length === 1 ? 'archive' : 'archives'}</span>
				<span class="grow"></span>
				<input 
					type="text" 
					placeholder="Paste a URL to save…" 
					bind:value={newUrlInput?.value || ''}
					class="search-input"
					onkeydown={(e) => e.key === 'Enter' && createArchive(newUrlInput.value)}
				>
			</div>

			<div class="bar">
				<div class="search"><Search size={14} class="faint" /><input bind:value={q} placeholder="Search archives…" /></div>
				<label class="check"><input type="checkbox" onchange={() => {}} />Unused only</label>
				<button class="icon-btn" title="Upload files" onclick={() => picker?.click()}><Upload size={14} /></button>
				<input type="file" multiple hidden bind:this={picker}>
				<div class="seg"><button class:on={view === 'grid'} onclick={() => (view = 'grid')}>Grid</button><button class:on={view === 'list'} onclick={() => (view = 'list')}>List</button></div>
			</div>

			{#if shown.length}
				<div class={view}>
					{#each shown as a (a.id)}
						{@const AIcon = icon(a.kind)}
						<div class="archive-card">
							<button class="thumb" onclick={(e) => openArchive(a.id, e)}>
								{#if a.kind === 'image' && a.raw_image}
									<img src="data:{a.image_mime || 'image/png';base64},{a.raw_image}" loading="lazy" />
								{:else if a.thumbnail}
									<a href={a.thumbnail} target="_blank"><AIcon size={64} strokeWidth={1.5} /></a>
								{:else}
									<AIcon size={64} strokeWidth={1.5} />
								{/if}
							</button>

							<div class="meta">
								<span class="title truncate-1">{a.title || 'Untitled'}</span>
								<span class="kind">{kindLabel(a.kind)}</span>
								{#if a.duration}
									<span class="faint">{Math.floor(a.duration)}s</span>
								{/if}
							</div>

							<div class="actions">
								<button class="icon-btn" title="View snippet" onclick={(e) => { openArchive(a.id, e); }}>
									<Eye size={14} />
								</button>
								<button class="icon-btn" title="Edit" onclick={() => { loadDetail(a.id); (editMode = 'edit'); }}>
									<Pencil size={14} />
								</button>
							</div>
						</div>
					{/each}
				</div>

				{#if newUrlInput?.value && !newUrlInput.value.trim()}
					<div class="hint">Paste a URL above and press Enter to create an archive.</div>
				{:else if newUrlInput?.value}
					<p class="creating"><b>{newUrlInput.value}</b> was added. Processing…</p>
				{/if}
			{:else if loaded}
				<div class="empty">
					<Search size={48} class="faint" />
					<b>No archives yet</b>
					<p>Paste a URL above to save a webpage, video, or image.</p>
					<p class="faint">Supported: YouTube, Vimeo, webpages, images, and more.</p>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.page.wide { max-width: 1400px; }
	.titlebar { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
	.search-input { flex: 1; min-width: 200px; height: 28px; border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 0 10px; outline: none; font-size: 14px; }
	.search-input:focus { box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent); }

	.content { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(0, 360px); gap: 24px; }
	.full-image { grid-column: 1 / -1; position: relative; background: var(--surface-2); border-radius: 12px; overflow: hidden; }
	.thumbnail { display: block; width: 100%; height: 360px; display: grid; place-items: center; background: var(--surface-2); color: var(--text-2); text-decoration: none; transition: background 0.2s; }
	.thumbnail:hover { background: var(--hover); }
	.thumbnail img { max-width: 100%; max-height: 360px; object-fit: contain; }

	.empty-icon { color: var(--text-3); }
	.meta { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 13.5px; }
	.duration, .author { color: var(--c-purple); font-weight: 600; }
	.author::before { content: 'by '; }

	.info { display: flex; flex-direction: column; gap: 8px; }
	.description { font-size: 14px; line-height: 1.6; color: var(--text); }
	.truncate-3 { overflow: hidden; text-overflow: ellipsis; max-height: 42px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
	.truncate-1 { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	.error { background: color-mix(in srgb, var(--accent) 15%, transparent); color: color-mix(in srgb, var(--accent) 80%, var(--text)); padding: 8px; border-radius: 6px; font-size: 13px; margin-top: 6px; }

	.actions { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
	.edit-row, .edit-actions { display: flex; gap: 6px; align-items: center; margin-top: 6px; }
	.edit-title, .edit-url { border: 1px solid var(--border-strong); border-radius: 4px; padding: 4px 8px; font-size: 14px; width: 100%; box-sizing: border-box; }
	.edit-title:focus, .edit-url:focus { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent); }

	.notes-editor { 
		border: 1px solid var(--border-strong); 
		border-radius: var(--radius); 
		padding: 10px; 
		font-size: 14px; 
		min-height: 120px;
		resize: vertical;
		font-family: inherit;
	}

	.todos { display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto; margin-bottom: 8px; padding-right: 4px; }
	.todo-item { display: flex; align-items: center; gap: 6px; font-size: 13.5px; cursor: pointer; user-select: none; transition: color 0.2s; padding: 4px 6px; border-radius: 4px; }
	.todo-item:hover { background: var(--surface-2); }
	.todo-item.done { opacity: 0.7; }
	.todo-item span.strikethrough { text-decoration: line-through; }

	.add-todo { display: flex; gap: 6px; margin-bottom: 10px; }
	.add-todo input { border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 4px 8px; font-size: 13.5px; outline: none; flex: 1; min-width: 120px; }
	.add-todo input:focus { box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent); }

	.foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 16px; border-top: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
	.url { white-space: nowrap; }
	.btns { display: flex; gap: 4px; }
	.icon-btn { 
		display: flex; align-items: center; justify-content: center; 
		width: 28px; height: 28px; border-radius: 6px; 
		border: 1px solid transparent; 
		color: var(--text-2); background: var(--surface); 
		transition: all 0.2s; cursor: pointer;
	}
	.icon-btn:hover { color: var(--text); background: var(--hover); }

	.check { display: flex; align-items: center; gap: 5px; font-weight: 600; color: var(--c-purple); }

	.download-video { margin-left: auto; padding: 8px; border-radius: 8px; background: color-mix(in srgb, var(--accent) 10%, transparent); display: flex; align-items: center; gap: 6px; font-size: 13px; }
	.download-video button { background: none; border: none; cursor: pointer; color: var(--text); display: flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 4px; transition: all 0.2s; }
	.download-video button:hover { background: var(--hover); }
	.download-video button.on { color: var(--accent); }

	.archive-card { 
		display: grid; grid-template-columns: 120px minmax(0, 1fr) auto; 
		align-items: center; gap: 10px; 
		padding: 8px; border: 1px solid var(--border); 
		border-radius: 8px; margin-bottom: 6px; 
		cursor: pointer; transition: all 0.2s;
	}
	.archive-card:hover { background: var(--surface-2); }
	.archive-card .thumb { width: 100%; height: 70px; border-radius: 6px; overflow: hidden; position: relative; background: var(--surface); display: grid; place-items: center; }
	.thumb img { max-width: 100%; max-height: 70px; object-fit: cover; }
	.archive-card .meta { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
	.archive-card .kind, .archive-card .faint { font-size: 12.5px; color: var(--text-3); }

	.hint { padding: 6px 8px; color: var(--text-3); font-size: 12.5px; margin-top: 6px; background: var(--surface-2); border-radius: 4px; }
	.creating { padding: 8px; color: var(--c-purple); font-size: 13px; background: color-mix(in srgb, var(--accent) 8%, transparent); border-radius: 6px; margin-bottom: 6px; }

	@media (max-width: 800px) {
		.content { grid-template-columns: 1fr; }
		.full-image { grid-column: auto; }
	}

	/* Content frame */
	.content-frame { 
		position: absolute; inset: 0; border: none; width: 100%; height: 100%; pointer-events: none;
	}
</style>
