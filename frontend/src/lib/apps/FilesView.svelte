<script lang="ts">
	// The app's source on its branch: browse, edit and add files. Saving commits to the repository
	// (and deploys, when auto-deploy is on), exactly like a push.
	import { File, FilePlus, FolderGit2, Save, Trash2 } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { highlightCode } from '#lib/git/highlight.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize } from '#lib/util.ts';
	import type { App } from './types.ts';

	let { app, onchange }: { app: App; onchange: () => void } = $props();
	let files = $state<{ path: string; size: number }[]>([]);
	let sha = $state<string | null>(null);
	let editable = $state(false);
	let loaded = $state(false);
	let current = $state<string | null>(null);
	let content = $state('');
	let original = $state('');
	let binary = $state(false);
	let editing = $state(false);
	let saving = $state(false);
	let message = $state('');
	let newPath = $state<string | null>(null);

	async function load(select?: string) {
		try {
			const r = await api.get<{ sha: string | null; files: { path: string; size: number }[]; editable: boolean }>(`/apps/${app.slug}/files`);
			files = r.files;
			sha = r.sha;
			editable = r.editable;
			const pick = select ?? current ?? files.find((f) => /^(readme\.md|app\.py|index\.html|server\.js|main\.py)$/i.test(f.path))?.path ?? files[0]?.path;
			if (pick && files.some((f) => f.path === pick)) await show(pick);
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(() => load());

	async function show(path: string) {
		if (dirty && !(await ui.confirm({ title: 'Discard your changes?', message: `${current} has changes that are not saved.`, confirmLabel: 'Discard', danger: true }))) return;
		try {
			const r = await api.get<{ content: string | null; binary: boolean }>(`/apps/${app.slug}/files?path=${encodeURIComponent(path)}`);
			current = path;
			binary = r.binary || r.content === null;
			content = original = r.content ?? '';
			editing = false;
			newPath = null;
		} catch (e) {
			ui.error(e);
		}
	}

	let dirty = $derived(editing && (content !== original || newPath !== null));

	async function save() {
		const path = newPath ?? current;
		if (!path) return;
		saving = true;
		try {
			await api.put(`/apps/${app.slug}/files`, { path, content, message: message.trim() || (newPath ? `Add ${path}` : `Edit ${path}`) });
			ui.toast(app.auto_deploy ? 'Saved. Deploying…' : 'Saved to the repository');
			original = content;
			message = '';
			editing = false;
			newPath = null;
			await load(path);
			onchange();
		} catch (e) {
			ui.error(e);
		} finally {
			saving = false;
		}
	}

	async function remove() {
		if (!current) return;
		if (!(await ui.confirm({ title: `Delete ${current}?`, message: 'The deletion is committed to the repository; the file stays in its history.', confirmLabel: 'Delete', danger: true }))) return;
		try {
			await api.del(`/apps/${app.slug}/files?path=${encodeURIComponent(current)}`);
			current = null;
			await load();
			onchange();
		} catch (e) {
			ui.error(e);
		}
	}

	function startNew() {
		newPath = '';
		current = null;
		content = original = '';
		binary = false;
		editing = true;
	}

	// Folders first-level grouping for the list.
	let tree = $derived.by(() => {
		const rows: { path: string; name: string; depth: number; dir: boolean; size: number }[] = [];
		const seen = new Set<string>();
		for (const f of files) {
			const parts = f.path.split('/');
			for (let i = 0; i < parts.length - 1; i++) {
				const dir = parts.slice(0, i + 1).join('/');
				if (!seen.has(dir)) {
					seen.add(dir);
					rows.push({ path: dir, name: parts[i], depth: i, dir: true, size: 0 });
				}
			}
			rows.push({ path: f.path, name: parts[parts.length - 1], depth: parts.length - 1, dir: false, size: f.size });
		}
		return rows;
	});

	let highlighted = $derived(current && !editing && !binary ? highlightCode(content, current) : '');
</script>

{#if loaded && !sha}
	<div class="empty">
		<b>No code yet</b>
		{app.source === 'kern' ? `The branch ${app.branch} of ${app.repo} is empty.` : 'Deploy once to fetch the repository.'}
		{#if editable}<div><button class="btn primary first" onclick={startNew}><FilePlus size={14} />Add a file</button></div>{/if}
	</div>
{:else if loaded}
	<div class="files">
		<aside>
			<div class="side-head">
				<span class="faint">{files.length} files</span>
				<span class="grow"></span>
				{#if editable}<button class="icon-btn" title="New file" onclick={startNew}><FilePlus size={14} /></button>{/if}
				{#if app.source === 'kern'}<a class="icon-btn" href="/git/{app.repo}" title="Open the repository" onclick={(e) => { e.preventDefault(); open(`/git/${app.repo}`, e); }}><FolderGit2 size={14} /></a>{/if}
			</div>
			<div class="list">
				{#each tree as r (r.path + (r.dir ? '/' : ''))}
					{#if r.dir}
						<div class="dir" style:padding-left="{10 + r.depth * 12}px">{r.name}/</div>
					{:else}
						<button class="file" class:on={current === r.path} style:padding-left="{10 + r.depth * 12}px" onclick={() => show(r.path)}>
							<File size={12} /><span class="truncate">{r.name}</span>
						</button>
					{/if}
				{/each}
			</div>
		</aside>
		<section>
			{#if current || newPath !== null}
				<div class="fhead">
					{#if newPath !== null}
						<input class="input mono path" bind:value={newPath} placeholder="folder/name.ext" spellcheck="false" />
					{:else}
						<b class="mono truncate">{current}</b>
						<span class="faint">{fileSize(files.find((f) => f.path === current)?.size ?? 0)}</span>
					{/if}
					<span class="grow"></span>
					{#if editable && !binary && !editing}
						<button class="btn" onclick={() => (editing = true)}>Edit</button>
						<button class="icon-btn" title="Delete file" onclick={remove}><Trash2 size={14} /></button>
					{/if}
					{#if editing}
						<button class="btn ghost" onclick={() => { if (newPath !== null) { newPath = null; load(); } else { content = original; editing = false; } }}>Cancel</button>
					{/if}
				</div>
				{#if binary}
					<p class="faint pad">This file is binary or too large to show.</p>
				{:else if editing}
					<textarea class="code mono" bind:value={content} spellcheck="false"
						onkeydown={(e) => {
							if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(); }
							if (e.key === 'Tab') { e.preventDefault(); const t = e.currentTarget; const s = t.selectionStart; content = content.slice(0, s) + '\t' + content.slice(t.selectionEnd); queueMicrotask(() => t.setSelectionRange(s + 1, s + 1)); }
						}}></textarea>
					<div class="commit">
						<input class="input" bind:value={message} placeholder={newPath !== null ? `Add ${newPath || 'file'}` : `Edit ${current}`} onkeydown={(e) => e.key === 'Enter' && save()} />
						<button class="btn primary" disabled={saving || !dirty || (newPath !== null && !newPath.trim())} onclick={save}><Save size={14} />{saving ? 'Saving…' : app.auto_deploy ? 'Commit and deploy' : 'Commit'}</button>
					</div>
				{:else}
					<pre class="code mono view">{@html highlighted}</pre>
				{/if}
			{:else}
				<p class="faint pad">Pick a file.</p>
			{/if}
		</section>
	</div>
	{#if !editable}<p class="faint note">The code comes from {app.git_url}. Change it there and deploy.</p>{/if}
{/if}

<style>
	.files { display: grid; grid-template-columns: 230px 1fr; height: calc(100dvh - 230px); min-height: 380px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	aside { display: flex; flex-direction: column; border-right: 1px solid var(--border); background: var(--surface); min-height: 0; }
	.side-head { display: flex; align-items: center; gap: 2px; padding: 6px 6px 6px 10px; border-bottom: 1px solid var(--border); font-size: 12px; }
	.grow { flex: 1; }
	.list { flex: 1; overflow-y: auto; padding: 4px 0; }
	.dir { padding: 3px 10px; font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }
	.file { display: flex; align-items: center; gap: 6px; width: 100%; padding: 3px 10px; font: 12.5px var(--font-mono); color: var(--text-2); text-align: left; }
	.file:hover { background: var(--hover); color: var(--text); }
	.file.on { background: var(--active); color: var(--text); }
	section { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
	.fhead { display: flex; align-items: center; gap: 8px; padding: 6px 8px 6px 12px; border-bottom: 1px solid var(--border); font-size: 12.5px; min-height: 41px; }
	.fhead .path { flex: 1; max-width: 360px; }
	.mono { font-family: var(--font-mono); }
	.code { flex: 1; margin: 0; padding: 12px 14px; font-size: 12.5px; line-height: 1.6; overflow: auto; tab-size: 4; }
	textarea.code { border: 0; outline: 0; resize: none; background: var(--bg); color: var(--text); white-space: pre; }
	.view { white-space: pre; }
	.commit { display: flex; gap: 8px; padding: 8px; border-top: 1px solid var(--border); background: var(--surface); }
	.commit .input { flex: 1; }
	.pad { padding: 16px; margin: 0; }
	.note { font-size: 12.5px; margin: 8px 0 0; }
	.first { margin-top: 12px; }
	@media (max-width: 700px) { .files { grid-template-columns: 1fr; height: auto; } aside { max-height: 200px; border-right: 0; border-bottom: 1px solid var(--border); } .code { min-height: 360px; } }
</style>
