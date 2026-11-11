<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { ChevronRight, CloudOff, Ellipsis, FileText, Image, Layers, PanelRight, Smile, Star } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { onMount, tick } from 'svelte';
	import { docMenu, newPage } from '#lib/actions.ts';
	import { api } from '#lib/api.ts';
	import { blockEl } from '#lib/editor/dom.ts';
	import { getDoc } from '#lib/editor/doc.svelte.ts';
	import Editor from '#lib/editor/Editor.svelte';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { debounce, modKey } from '#lib/util.ts';
	import DatabaseView from '#lib/db/DatabaseView.svelte';
	import DocMeta from './DocMeta.svelte';
	import TemplateBar from './TemplateBar.svelte';
	import ExportDialog from './ExportDialog.svelte';
	import VersionHistory from './VersionHistory.svelte';
	import { importFiles } from '#lib/data/download.ts';
	import { Download, History, Upload } from '@lucide/svelte';
	import EmojiPicker from './EmojiPicker.svelte';
	import RightPanel from './RightPanel.svelte';

	let { id }: { id: string } = $props();
	const doc = getDoc(id);

	let meta = $derived(ws.docs[id] ?? doc.meta ?? undefined);
	let crumbs = $derived(ws.path(id));
	let subpages = $derived(ws.children(id));
	let titleEl = $state<HTMLElement>();
	let picker = $state<{ x: number; y: number } | null>(null);
	let coverInput = $state<HTMLInputElement>();
	let showHistory = $state(false);
	let showExport = $state(false);
	let importInput = $state<HTMLInputElement>();

	function moreMenu(el: Element) {
		if (!meta) return;
		ui.menuBelow(el, [
			...docMenu(meta),
			{ separator: true },
			{ label: 'Version history', icon: History, onSelect: () => (showHistory = true) },
			{ label: 'Export…', icon: Download, onSelect: () => (showExport = true) },
			{ label: 'Import into this page…', icon: Upload, onSelect: () => importInput?.click() }
		]);
	}

	const saveTitle = debounce((title: string) => {
		api.patch(`/documents/${id}`, { title }).catch((e) => ui.error(e));
	}, 400);

	// Keep the heading in step with renames made elsewhere (sidebar, other tab).
	$effect(() => {
		const t = meta?.title ?? '';
		if (titleEl && document.activeElement !== titleEl && titleEl.textContent !== t) titleEl.textContent = t;
	});

	function onTitleInput() {
		const title = (titleEl!.textContent ?? '').replace(/\n/g, ' ');
		if (ws.docs[id]) ws.docs[id].title = title;
		else if (doc.meta) doc.meta.title = title;
		saveTitle(title);
	}

	function focusBody() {
		const first = doc.children(null)[0];
		doc.focus(first ?? doc.append('paragraph'), 'start');
	}

	function titleKey(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === 'ArrowDown') {
			e.preventDefault();
			focusBody();
		}
	}

	function focusTitle() {
		if (!titleEl) return;
		titleEl.focus();
		const r = document.createRange();
		r.selectNodeContents(titleEl);
		r.collapse(false);
		getSelection()?.removeAllRanges();
		getSelection()?.addRange(r);
	}

	async function revealHash() {
		const target = decodeURIComponent(page.url.hash.slice(1));
		if (!target || doc.status !== 'ready' || !doc.blocks[target]) return;
		let p = doc.blocks[target].parent;
		while (p) {
			if (doc.blocks[p].collapsed) doc.toggleCollapsed(p, false);
			p = doc.blocks[p].parent;
		}
		await tick();
		const el = blockEl(target);
		if (!el) return;
		el.scrollIntoView({ block: 'center' });
		el.classList.add('flash');
		setTimeout(() => el.classList.remove('flash'), 1600);
	}

	let revealed = false;
	$effect(() => {
		if (doc.status === 'ready' && !revealed) {
			revealed = true;
			ws.touchOpened(id);
			if (page.url.hash) revealHash();
			else if (!meta?.title && !doc.children(null).length) tick().then(focusTitle);
		}
	});
	afterNavigate(() => {
		if (revealed) revealHash();
	});

	onMount(() => () => {
		saveTitle.cancel();
		doc.flush();
	});

	async function uploadCover(file: File | undefined) {
		if (!file) return;
		try {
			const a = await api.upload(file);
			await ws.updateDoc(id, { cover: a.url });
		} catch (e) {
			ui.error(e);
		}
	}

	async function restore() {
		await ws.restoreDoc(id).catch((e) => ui.error(e));
		doc.load();
	}
</script>

<div class="docview">
	<div class="main">
		<header class="topbar">
			<nav class="crumbs">
				{#each crumbs as c (c.id)}
					<a class="crumb truncate" href="/doc/{c.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${c.id}`, e); }}>{c.icon} {c.title || 'Untitled'}</a>
					<ChevronRight size={12} class="faint" />
				{/each}
				<span class="crumb current truncate">{meta?.icon ?? ''} {meta?.title || 'Untitled'}</span>
			</nav>
			<span class="save" class:show={doc.saveState !== 'saved'} class:err={doc.saveState === 'error'} aria-live="polite">
				{#if doc.conflict}<CloudOff size={13} /> Not saved — conflict
				{:else if doc.saveState === 'error' && ws.offline}<CloudOff size={13} /> Offline — saved on this device
				{:else if doc.saveState === 'error'}<CloudOff size={13} /> Not saved — retrying
				{:else if doc.saveState === 'saved'}Saved{:else}Saving…{/if}
			</span>
			{#if doc.cardCount}
				<a class="btn ghost study" href="/review?doc={id}" title="Review this page's flashcards"
					onclick={(e) => { e.preventDefault(); goto(`/review?doc=${id}`); }}><Layers size={13} />Study {doc.cardCount}</a>
			{/if}
			{#if meta}
				<button class="icon-btn" class:on={meta.is_favorite} title={meta.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
					onclick={() => ws.updateDoc(id, { is_favorite: !meta.is_favorite }).catch(() => {})}>
					<Star size={15} fill={meta.is_favorite ? 'currentColor' : 'none'} />
				</button>
				<button class="icon-btn" class:on={prefs.panelOpen} title="Page details ({modKey}+Shift+\)" onclick={() => (prefs.panelOpen = !prefs.panelOpen)}>
					<PanelRight size={15} />
				</button>
				<button class="icon-btn" title="More" onclick={(e) => moreMenu(e.currentTarget)}><Ellipsis size={15} /></button>
			{/if}
		</header>

		<div class="scroll">
			{#if doc.status === 'loading'}
				<div class="sheet state faint">Loading…</div>
			{:else if doc.status === 'missing'}
				<div class="sheet state"><div class="empty"><b>Page not found</b>It may have been permanently deleted.</div></div>
			{:else if doc.status === 'error'}
				<div class="sheet state"><div class="empty"><b>Could not load this page</b>
					<button class="btn" style="margin-top:10px" onclick={() => doc.load()}>Try again</button></div></div>
			{:else}
				{#if doc.trashed}
					<div class="banner">This page is in the trash. <button class="btn" onclick={restore}>Restore</button></div>
				{/if}
				{#if doc.isTemplate}<TemplateBar id={id} />{/if}
				{#if meta?.cover}
					<div class="cover" style:background-image="url({JSON.stringify(meta.cover)})">
						<div class="cover-acts">
							<button class="btn" onclick={() => coverInput?.click()}>Change cover</button>
							<button class="btn" onclick={() => ws.updateDoc(id, { cover: '' }).catch(() => {})}>Remove</button>
						</div>
					</div>
				{/if}
				<input type="file" accept="image/*" hidden bind:this={coverInput} onchange={(e) => uploadCover(e.currentTarget.files?.[0])} />

				<div class="sheet" data-width={meta?.database ? "db" : prefs.editorWidth}>
					<div class="head" class:has-cover={!!meta?.cover} class:has-icon={!!meta?.icon}>
						{#if meta?.icon}
							<button class="icon" title="Change icon" onclick={(e) => { const r = e.currentTarget.getBoundingClientRect(); picker = { x: r.left, y: r.bottom + 6 }; }}>{meta.icon}</button>
						{/if}
						{#if meta && (!meta.icon || !meta.cover)}
							<div class="adders">
								{#if !meta.icon}
									<button class="btn ghost" onclick={(e) => { const r = e.currentTarget.getBoundingClientRect(); picker = { x: r.left, y: r.bottom + 6 }; }}><Smile size={14} />Add icon</button>
								{/if}
								{#if !meta.cover}
									<button class="btn ghost" onclick={() => coverInput?.click()}><Image size={14} />Add cover</button>
								{/if}
							</div>
						{/if}
						<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
						<h1 class="title" bind:this={titleEl} contenteditable="plaintext-only" role="textbox" tabindex="0" aria-label="Page title"
							data-placeholder="Untitled" class:blank={!meta?.title} spellcheck="true" oninput={onTitleInput} onkeydown={titleKey}></h1>
					</div>

					{#if meta?.database}
						<div class="dbpage"><DatabaseView dbId={meta.database} /></div>
					{:else}
						<DocMeta {doc} />
						<Editor {doc} onexit={focusTitle} />
					{/if}

					{#if subpages.length}
						<div class="subpages">
							<div class="section-title">Sub-pages</div>
							{#each subpages as s (s.id)}
								<a class="sub" href="/doc/{s.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${s.id}`, e); }}>
									<span class="ico">{#if s.icon}{s.icon}{:else}<FileText size={14} strokeWidth={1.75} />{/if}</span>
									<span class="truncate">{s.title || 'Untitled'}</span>
								</a>
							{/each}
							<button class="sub add" onclick={() => newPage(id)}>+ New sub-page</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	{#if prefs.panelOpen && doc.status === 'ready'}<RightPanel {doc} onhistory={() => (showHistory = true)} />{/if}
</div>

<input type="file" multiple hidden bind:this={importInput} accept=".md,.markdown,.txt,.html,.htm,.opml,.csv,.json,.zip,.apkg"
	onchange={async (e) => { const f = [...(e.currentTarget.files ?? [])]; e.currentTarget.value = ''; if (f.length && (await importFiles(f, id))) ws.load(); }} />

{#if showHistory}<VersionHistory {doc} onclose={() => (showHistory = false)} />{/if}
{#if showExport}<ExportDialog {id} onclose={() => (showExport = false)} />{/if}

{#if doc.conflict}
	<div class="overlay">
		<div class="conflict popover" role="alertdialog" aria-labelledby="conflict-title">
			<h2 id="conflict-title">This page changed somewhere else</h2>
			<p>While your edits were waiting to be saved (offline, or in another tab), {doc.conflict.ids.length === 1 ? 'a block you edited was' : `${doc.conflict.ids.length} blocks you edited were`} also changed elsewhere. Nothing has been overwritten. Choose what to keep:</p>
			{#if doc.conflict.theirs.length}
				<div class="theirs"><span class="faint">Their version now reads:</span>
					{#each doc.conflict.theirs.slice(0, 3) as b (b.id)}<div class="rt">{@html b.html || '<i>(empty)</i>'}</div>{/each}
				</div>
			{/if}
			<div class="choices">
				<button class="btn primary" onclick={() => doc.resolveConflict('copy')}>Keep both — save mine as a new page</button>
				<button class="btn" onclick={() => doc.resolveConflict('theirs')}>Use theirs, discard mine</button>
				<button class="btn ghost danger" onclick={() => doc.resolveConflict('mine')}>Use mine, overwrite theirs</button>
			</div>
		</div>
	</div>
{/if}

{#if picker}
	<EmojiPicker x={picker.x} y={picker.y} onclose={() => (picker = null)}
		onpick={(e) => { ws.updateDoc(id, { icon: e }).catch(() => {}); picker = null; }} />
{/if}

<style>
	.docview { position: relative; display: flex; height: 100%; }
	.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.topbar { flex: none; display: flex; align-items: center; gap: 4px; height: 38px; padding: 0 10px 0 16px; }
	.crumbs { flex: 1; min-width: 0; display: flex; align-items: center; gap: 4px; color: var(--text-2); overflow: hidden; }
	.crumb { flex: 0 1 auto; max-width: 180px; padding: 2px 5px; border-radius: var(--radius-sm); text-decoration: none; }
	a.crumb:hover { background: var(--hover); color: var(--text); }
	.crumb.current { color: var(--text); flex-shrink: 0.3; }
	.study { height: 26px; padding: 0 8px; text-decoration: none; color: var(--c-purple); }
	.save { display: flex; align-items: center; gap: 5px; margin-right: 6px; font-size: 12px; color: var(--text-3); opacity: 0; transition: opacity 0.4s 0.8s; white-space: nowrap; }
	.save.show { opacity: 1; transition: opacity 0.1s; }
	.save.err { color: var(--danger); }

	.scroll { flex: 1; overflow-y: auto; scroll-padding: 80px 0; }
	.sheet { margin: 0 auto; padding: 0 76px; max-width: calc(760px + 152px); }
	.sheet[data-width='narrow'] { max-width: calc(620px + 152px); }
	.sheet[data-width='wide'] { max-width: calc(980px + 152px); }
	.sheet[data-width='full'] { max-width: none; }
	.sheet[data-width='db'] { max-width: calc(1240px + 152px); }
	.state { padding-top: 60px; }
	.banner { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 8px; background: color-mix(in srgb, var(--danger) 16%, transparent); }

	.cover { position: relative; height: 200px; background-size: cover; background-position: center; }
	.cover-acts { position: absolute; right: 16px; bottom: 12px; display: flex; gap: 6px; opacity: 0; transition: opacity 0.12s; }
	.cover:hover .cover-acts { opacity: 1; }

	.head { position: relative; padding-top: 44px; }
	.head.has-cover { padding-top: 14px; }
	.head.has-cover.has-icon { padding-top: 0; }
	.icon { display: block; font-size: 54px; line-height: 1; margin: 0 0 6px -4px; padding: 4px; border-radius: 8px; }
	.has-cover .icon { margin-top: -34px; position: relative; }
	.icon:hover { background: var(--hover); }
	.adders { display: flex; gap: 2px; margin-left: -8px; height: 28px; opacity: 0; transition: opacity 0.12s; }
	.head:hover .adders, .adders:focus-within { opacity: 1; }
	.title { margin: 0 0 4px; font-family: var(--font-editor); font-size: 34px; line-height: 1.2; font-weight: 700; letter-spacing: -0.02em; outline: none; overflow-wrap: anywhere; cursor: text; }
	.title { position: relative; }
	.title.blank::before { content: attr(data-placeholder); position: absolute; left: 0; top: 0; color: var(--text-3); pointer-events: none; }

	.dbpage { margin: 8px 0 60px; }
	.overlay { position: fixed; inset: 0; z-index: 960; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.55); }
	.conflict { width: min(520px, 100%); padding: 18px; }
	.conflict h2 { margin: 0 0 8px; font-size: 16px; }
	.conflict p { margin: 0 0 10px; color: var(--text-2); }
	.theirs { padding: 8px 10px; margin-bottom: 12px; border-radius: var(--radius); background: var(--surface-2); font-size: 13px; }
	.choices { display: flex; flex-direction: column; gap: 6px; }
	.choices .danger { color: var(--danger); }
	.subpages { margin: 0 0 60px; padding-top: 4px; border-top: 1px solid var(--border); }
	.sub { display: flex; align-items: center; gap: 8px; width: 100%; height: 30px; padding: 0 6px; border-radius: var(--radius-sm); text-decoration: none; text-align: left; }
	.sub:hover { background: var(--hover); }
	.sub .ico { width: 18px; display: grid; place-items: center; color: var(--text-2); }
	.sub.add { color: var(--text-3); }

	@media (max-width: 760px) {
		.sheet, .sheet[data-width] { padding: 0 16px 0 30px; }
		.title { font-size: 27px; }
		.head { padding-top: 20px; }
		.adders { opacity: 1; }
		.crumb:not(.current) { display: none; }
		.crumbs :global(svg) { display: none; }
	}
</style>
