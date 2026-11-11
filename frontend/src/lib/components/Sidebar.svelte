<script lang="ts">
	import { page } from '$app/state';
	import { Calendar, LayoutDashboard, Kanban, Archive, ChevronDown, ChevronRight, CircleCheck, Database, FolderOpen, Hash, House, Layers, LayoutTemplate, Network, PanelLeft, Plus, Search, Settings, Trash2 } from '@lucide/svelte';
	import { counts } from '#lib/learn/util.svelte.ts';
	import { importFiles } from '#lib/data/download.ts';
	import Logo from './Logo.svelte';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { Bookmark, Upload } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';
	import type { Doc, DbPayload } from '#lib/types.ts';
	import { newGroup, newPage } from '#lib/actions.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { modKey } from '#lib/util.ts';
	import TreeNode, { endTreeDrag, treeDragId } from './TreeNode.svelte';

	let roots = $derived(ws.children(null).filter((d) => d.kind !== 'group'));
	let path = $derived(page.url.pathname);
	let resizing = $state(false);

	const links = [
		{ href: '/graph', label: 'Graph', icon: Network },
		{ href: '/templates', label: 'Templates', icon: LayoutTemplate },
		{ href: '/files', label: 'Files', icon: FolderOpen },
		{ href: '/tags', label: 'Tags', icon: Hash },
		{ href: '/archive', label: 'Archive', icon: Archive },
		{ href: '/trash', label: 'Trash', icon: Trash2 },
		{ href: '/settings', label: 'Settings', icon: Settings }
	];

	function nav(e: MouseEvent, href: string) {
		e.preventDefault();
		open(href, e);
		ui.mobileNav = false;
	}

	async function createMenu(e: MouseEvent) {
		const anchor = e.currentTarget as Element;
		let templates: Doc[] = [];
		try {
			templates = (await api.get<Doc[]>('/templates')).filter((t) => !t.template_db);
		} catch {
			/* offline */
		}
		ui.menuBelow(anchor, [
			{ label: 'Page', icon: Plus, onSelect: () => newPage() },
			{ label: 'Group', icon: LayoutDashboard, onSelect: () => newGroup() },
			{ label: 'Database', icon: Database, onSelect: () => newDatabase() },
			{ label: 'Kanban board', icon: Kanban, onSelect: () => newDatabase('kanban') },
			{ label: 'Calendar', icon: Calendar, onSelect: () => newDatabase('calendar') },
			{ label: 'Import…', icon: Upload, onSelect: () => importInput?.click() },
			...(templates.length ? [{ heading: 'From template' }] : []),
			...templates.map((t) => ({
				label: `${t.icon ? t.icon + ' ' : ''}${t.title || 'Untitled'}`,
				onSelect: async () => {
					try {
						const doc = await api.post<Doc>('/documents', { template: t.id });
						ws.docs[doc.id] = doc;
						goto(`/doc/${doc.id}`);
					} catch (err) {
						ui.error(err);
					}
				}
			})),
			{ separator: true },
			{ label: 'Manage templates', icon: LayoutTemplate, onSelect: () => goto('/templates') }
		]);
	}

	async function newDatabase(preset?: string) {
		try {
			const p = await api.post<DbPayload>('/databases', { title: '', preset });
			await ws.load();
			goto(`/doc/${p.database.page}`);
		} catch (err) {
			ui.error(err);
		}
	}

	let importInput = $state<HTMLInputElement>();

	function startResize(e: PointerEvent) {
		resizing = true;
		const move = (ev: PointerEvent) => (prefs.sidebarWidth = Math.max(200, Math.min(460, ev.clientX)));
		const up = () => {
			resizing = false;
			removeEventListener('pointermove', move);
			removeEventListener('pointerup', up);
		};
		addEventListener('pointermove', move);
		addEventListener('pointerup', up);
		e.preventDefault();
	}

	function dropRoot(e: DragEvent) {
		const id = treeDragId();
		endTreeDrag();
		if (!id) return;
		e.preventDefault();
		ws.moveDoc(id, null);
	}
</script>

{#snippet section(key: string, label: string)}
	<button class="sec" onclick={() => (prefs.sections[key] = !prefs.sections[key])}>
		<ChevronRight size={11} class={prefs.sections[key] ? '' : 'open'} />{label}
	</button>
{/snippet}

<input type="file" multiple hidden bind:this={importInput} accept=".md,.markdown,.txt,.html,.htm,.opml,.csv,.json,.zip,.apkg"
	onchange={async (e) => { const f = [...(e.currentTarget.files ?? [])]; e.currentTarget.value = ''; if (f.length && (await importFiles(f))) ws.load(); }} />

<aside class="sidebar" class:resizing style:width="{prefs.sidebarWidth}px">
	<div class="head">
		<a class="brand" href="/" onclick={(e) => nav(e, '/')}>
			<Logo size={20} />
			Kern
		</a>
		<button class="icon-btn" title="Hide sidebar ({modKey}+\)" onclick={() => { prefs.sidebarOpen = false; ui.mobileNav = false; }}>
			<PanelLeft size={15} />
		</button>
	</div>

	<div class="top">
		<button class="nav" onclick={() => { ui.openSearch(); ui.mobileNav = false; }}>
			<Search size={15} strokeWidth={1.75} /><span>Search</span><kbd>{modKey} K</kbd>
		</button>
		<div class="split">
			<button class="nav" onclick={() => { newPage(); ui.mobileNav = false; }}>
				<Plus size={15} strokeWidth={1.75} /><span>New page</span><kbd>Alt N</kbd>
			</button>
			<button class="icon-btn more" title="New database or page from template" onclick={createMenu}><ChevronDown size={13} /></button>
		</div>
		<a class="nav" class:active={path === '/'} href="/" onclick={(e) => nav(e, '/')}>
			<House size={15} strokeWidth={1.75} /><span>Home</span>
		</a>
		<a class="nav" class:active={path === '/tasks'} href="/tasks" onclick={(e) => nav(e, '/tasks')}>
			<CircleCheck size={15} strokeWidth={1.75} /><span>Tasks</span>{#if counts.today}<em class="badge">{counts.today}</em>{/if}
		</a>
		<a class="nav" class:active={path === '/cards' || path === '/review'} href="/cards" onclick={(e) => nav(e, '/cards')}>
			<Layers size={15} strokeWidth={1.75} /><span>Flashcards</span>{#if counts.due}<em class="badge">{counts.due}</em>{/if}
		</a>
		<a class="nav intel" class:active={path === '/intelligence'} href="/intelligence" onclick={(e) => nav(e, '/intelligence')}>
			<Sparkle size={15} /><span>Intelligence</span>
		</a>
	</div>

	<div class="scroll">
		{#if ws.favorites.length && prefs.sidebarShow?.favorites !== false}
			{@render section('fav', 'Favorites')}
			{#if !prefs.sections.fav}
				{#each ws.favorites as doc (doc.id)}<TreeNode {doc} flat />{/each}
			{/if}
		{/if}

		{#if ws.recents.length && prefs.sidebarShow?.recent !== false}
			{@render section('recent', 'Recent')}
			{#if !prefs.sections.recent}
				{#each ws.recents.slice(0, 5) as doc (doc.id)}<TreeNode {doc} flat />{/each}
			{/if}
		{/if}

		{#if prefs.savedSearches?.length}
			{@render section('saved', 'Saved searches')}
			{#if !prefs.sections.saved}
				{#each prefs.savedSearches as s (s.id)}
					{@const href = `/search?q=${encodeURIComponent(s.q)}${s.kind ? '&kind=' + s.kind : ''}`}
					<a class="nav saved" class:active={path === '/search' && page.url.searchParams.get('q') === s.q} {href} onclick={(e) => nav(e, href)}>
						<Bookmark size={14} strokeWidth={1.75} /><span class="truncate">{s.name}</span>
					</a>
				{/each}
			{/if}
		{/if}

		{#if ws.databases.length && prefs.sidebarShow?.databases !== false}
			{@render section('dbs', 'Databases')}
			{#if !prefs.sections.dbs}
				{#each ws.databases as doc (doc.id)}<TreeNode {doc} flat />{/each}
			{/if}
		{/if}

		<div class="sec-row">
			{@render section('groups', 'Groups')}
			<button class="icon-btn add" title="New group" onclick={() => newGroup()}><Plus size={13} /></button>
		</div>
		{#if !prefs.sections.groups}
			{#each ws.groups as doc (doc.id)}<TreeNode {doc} />{/each}
			{#if ws.loaded && !ws.groups.length}
				<button class="hint" onclick={() => newGroup()}>Make a dashboard for a class or project…</button>
			{/if}
		{/if}

		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="sec-row" ondragover={(e) => treeDragId() && e.preventDefault()} ondrop={dropRoot}>
			{@render section('pages', 'Pages')}
			<button class="icon-btn add" title="New page" onclick={() => newPage()}><Plus size={13} /></button>
		</div>
		{#if !prefs.sections.pages}
			{#each roots as doc (doc.id)}<TreeNode {doc} />{/each}
			{#if ws.loaded && !roots.length}
				<button class="hint" onclick={() => newPage()}>No pages yet. Create one…</button>
			{/if}
		{/if}
	</div>

	<nav class="foot">
		{#each links as l (l.href)}
			<a class="nav" class:active={path === l.href || (l.href === '/tags' && path.startsWith('/tag/'))} href={l.href} onclick={(e) => nav(e, l.href)}>
				<l.icon size={15} strokeWidth={1.75} /><span>{l.label}</span>
			</a>
		{/each}
	</nav>

	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="resizer" onpointerdown={startResize}></div>
</aside>

<style>
	.sidebar { position: relative; flex: none; display: flex; flex-direction: column; height: 100%; background: var(--bg-side); border-right: 1px solid var(--border); user-select: none; }
	.head { display: flex; align-items: center; justify-content: space-between; height: 40px; padding: 0 8px 0 12px; }
	.brand { display: flex; align-items: center; gap: 7px; font-weight: 650; letter-spacing: -0.01em; text-decoration: none; }
	.top, .foot { padding: 2px 6px; }
	.foot { border-top: 1px solid var(--border); padding: 6px; }
	.nav { display: flex; align-items: center; gap: 8px; width: 100%; height: var(--row-h); padding: 0 8px; border-radius: var(--radius-sm); color: var(--text-2); text-decoration: none; }
	.nav:hover { background: var(--hover); color: var(--text); }
	.nav.active { background: var(--active); color: var(--text); }
	.nav span { flex: 1; text-align: left; }
	.intel :global(.sparkle) { transition: transform .35s var(--ease); }
	.intel:hover :global(.sparkle) { transform: rotate(45deg) scale(1.08); }
	.badge { font-style: normal; min-width: 18px; padding: 0 5px; border-radius: 9px; font-size: 11px; font-weight: 600; text-align: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); }
	.split { display: flex; align-items: center; }
	.split .nav { flex: 1; }
	.more { width: 22px; height: 22px; margin-left: 2px; }
	.nav kbd { opacity: 0; border: 0; background: none; transition: opacity 0.12s; }
	.nav:hover kbd { opacity: 1; }
	.scroll { flex: 1; overflow-y: auto; padding: 0 6px 12px; }
	.sec-row { display: flex; align-items: center; }
	.sec-row :global(.sec) { flex: 1; }
	.sec { display: flex; align-items: center; gap: 4px; width: 100%; padding: 14px 8px 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); }
	.sec:hover { color: var(--text-2); }
	.sec :global(svg) { transition: transform 0.12s var(--ease); }
	.sec :global(svg.open) { transform: rotate(90deg); }
	.add { width: 20px; height: 20px; margin-top: 10px; margin-right: 4px; }
	.hint { padding: 6px 10px; color: var(--text-3); text-align: left; }
	.hint:hover { color: var(--text-2); }
	.resizer { position: absolute; top: 0; right: -3px; width: 6px; height: 100%; cursor: col-resize; z-index: 5; }
	.resizer:hover, .resizing .resizer { background: color-mix(in srgb, var(--accent) 40%, transparent); }
</style>
