<script lang="ts">
	/* Plain text, Markdown and code: edit in place and save. Every save keeps the previous
	   content as a version on the server, restorable from History. */
	import { Columns2, Eye, History, Pencil, RotateCcw, Save, WrapText } from '@lucide/svelte';
	import { onMount, tick } from 'svelte';
	import { api, ApiError } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, mod, modKey, relTime } from '#lib/util.ts';
	import { fileKind, isCode, type FileRef } from './kind.ts';
	import { renderMarkdown } from './sanitize.ts';

	let { file, dirty = $bindable(false), onsaved }: { file: FileRef; dirty?: boolean; onsaved?: (f: FileRef) => void } = $props();

	const MAX_EDIT = 5 * 1024 * 1024;
	interface Version { id: string; url: string; size: number; reason: string; created_at: string }

	const markdown = $derived(fileKind(file) === 'markdown');
	let text = $state('');
	let saved = $state('');
	let base = $state<string | null>(null);
	let savedAt = $state<string | null>(null);
	let crlf = false;
	let loading = $state(true);
	let saving = $state(false);
	let readonly = $state<string>(''); // reason, when it cannot be edited
	let loadError = $state('');
	let mode = $state<'edit' | 'split' | 'preview'>('edit');
	let wrap = $state(true);
	let html = $state('');
	let historyOpen = $state(false);
	let versions = $state<Version[]>([]);
	let ta = $state<HTMLTextAreaElement>();
	let gutter = $state<HTMLDivElement>();
	let previewEl = $state<HTMLDivElement>();

	let lines = $derived(text.split('\n').length);
	$effect(() => {
		dirty = text !== saved;
	});

	onMount(() => {
		if (markdown) mode = 'split';
		wrap = !isCode(file.name);
		load();
	});

	async function load() {
		loading = true;
		loadError = '';
		try {
			const [res, meta] = await Promise.all([
				fetch(file.url, { cache: 'no-store' }),
				file.id ? api.get<{ base: string; updated_at: string | null; size: number }>(`/library/${file.id}/content`) : Promise.resolve(null)
			]);
			if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
			const buf = await res.arrayBuffer();
			let t: string;
			readonly = file.id ? '' : 'This file is not in your library, so it can only be viewed.';
			try {
				t = new TextDecoder('utf-8', { fatal: true }).decode(buf);
			} catch {
				t = new TextDecoder('windows-1252').decode(buf);
				readonly = 'This file is not UTF-8 text, so it is shown read-only.';
			}
			if (buf.byteLength > MAX_EDIT) {
				readonly = `This file is ${fileSize(buf.byteLength)}, too large to edit here (5 MB at most). Showing the first 1 MB.`;
				t = t.slice(0, 1024 * 1024);
			}
			if (t.charCodeAt(0) === 0xfeff) t = t.slice(1);
			crlf = /\r\n/.test(t);
			t = t.replace(/\r\n/g, '\n');
			text = saved = t;
			base = meta?.base ?? null;
			savedAt = meta?.updated_at ?? null;
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		}
		loading = false;
	}

	// Markdown preview, debounced while typing.
	$effect(() => {
		if (!markdown || mode === 'edit') return;
		const src = text;
		const t = setTimeout(() => renderMarkdown(src).then((h) => (html = h)), html ? 120 : 0);
		return () => clearTimeout(t);
	});

	async function save(force = false) {
		if (!file.id || readonly || saving || (!dirty && !force)) return;
		saving = true;
		const content = crlf ? text.replace(/\n/g, '\r\n') : text;
		try {
			const r = await api.put<FileRef & { base: string; updated_at: string }>(`/library/${file.id}/content`, { content, base: force ? null : base });
			saved = text;
			base = r.base;
			savedAt = r.updated_at;
			onsaved?.(r);
			if (historyOpen) loadVersions();
		} catch (e) {
			if (e instanceof ApiError && e.status === 409) {
				saving = false;
				const ok = await ui.confirm({
					title: 'This file changed elsewhere',
					message: 'Someone saved a newer version since you opened it. Save yours anyway? The other version stays in History.',
					confirmLabel: 'Save mine'
				});
				if (ok) return save(true);
				return;
			}
			ui.error(e);
		}
		saving = false;
	}

	async function loadVersions() {
		if (!file.id) return;
		try {
			versions = (await api.get<{ versions: Version[] }>(`/library/${file.id}/versions`)).versions;
		} catch (e) {
			ui.error(e);
		}
	}
	function toggleHistory() {
		historyOpen = !historyOpen;
		if (historyOpen) loadVersions();
	}
	async function restore(v: Version) {
		const ok = await ui.confirm({
			title: 'Restore this version?',
			message: `Replaces the current content with the version from ${new Date(v.created_at).toLocaleString()}.${dirty ? ' Your unsaved changes will be lost.' : ''} The current content is kept in History.`,
			confirmLabel: 'Restore'
		});
		if (!ok || !file.id) return;
		try {
			await api.post(`/library/${file.id}/versions/${v.id}/restore`);
			await load();
			await loadVersions();
			ui.toast('Version restored');
		} catch (e) {
			ui.error(e);
		}
	}

	/* Editing helpers: keep the textarea's undo history by going through insertText. */
	function insert(s: string) {
		if (!ta) return;
		if (!document.execCommand('insertText', false, s)) {
			ta.setRangeText(s, ta.selectionStart, ta.selectionEnd, 'end');
			text = ta.value;
		}
	}
	const indentUnit = () => (/^\t/m.test(text) || !/^ {2,}\S/m.test(text) ? '\t' : / {4}\S/.test(text) && !/^ {2}\S/m.test(text) ? '    ' : '  ');

	function keydown(e: KeyboardEvent) {
		if (!ta || readonly) return;
		if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey && !e.altKey) {
			e.preventDefault();
			const unit = indentUnit();
			const { selectionStart: s, selectionEnd: en, value } = ta;
			const lineStart = value.lastIndexOf('\n', s - 1) + 1;
			if (s === en && !e.shiftKey) return insert(unit);
			// Indent / outdent every selected line.
			const end = en > s && value[en - 1] === '\n' ? en - 1 : en;
			const block = value.slice(lineStart, end);
			const next = block
				.split('\n')
				.map((l) => (e.shiftKey ? l.replace(new RegExp('^(\\t| {1,' + Math.max(2, unit.length) + '})'), '') : unit + l))
				.join('\n');
			ta.setSelectionRange(lineStart, end);
			insert(next);
			ta.setSelectionRange(lineStart, lineStart + next.length);
		} else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
			// Keep the current line's indentation (and continue Markdown lists).
			const { selectionStart: s, value } = ta;
			const line = value.slice(value.lastIndexOf('\n', s - 1) + 1, s);
			let lead = line.match(/^[\t ]*/)![0];
			if (markdown) {
				const list = line.match(/^([\t ]*)([-*+]|\d+[.)])( \[[ x]\])? /);
				if (list) {
					if (line.trim() === list[0].trim()) return; // empty item: let Enter end the list
					const n = list[2].match(/^\d+/);
					lead = list[1] + (n ? `${Number(n[0]) + 1}${list[2].slice(-1)}` : list[2]) + (list[3] ? ' [ ]' : '') + ' ';
				}
			}
			if (!lead) return;
			e.preventDefault();
			insert('\n' + lead);
		}
	}

	function windowKey(e: KeyboardEvent) {
		if (mod(e) && e.key.toLowerCase() === 's') {
			e.preventDefault();
			save();
		}
	}

	function syncScroll() {
		if (gutter && ta) gutter.scrollTop = ta.scrollTop;
		if (mode === 'split' && previewEl && ta) {
			const f = ta.scrollTop / Math.max(1, ta.scrollHeight - ta.clientHeight);
			previewEl.scrollTop = f * (previewEl.scrollHeight - previewEl.clientHeight);
		}
	}
	$effect(() => {
		void mode;
		tick().then(syncScroll);
	});
</script>

<svelte:window onkeydown={windowKey} />

<div class="ed">
	<div class="tools">
		{#if markdown}
			<div class="seg">
				<button class:on={mode === 'edit'} onclick={() => (mode = 'edit')} title="Edit"><Pencil size={13} />Edit</button>
				<button class:on={mode === 'split'} onclick={() => (mode = 'split')} title="Side by side"><Columns2 size={13} />Split</button>
				<button class:on={mode === 'preview'} onclick={() => (mode = 'preview')} title="Preview"><Eye size={13} />Preview</button>
			</div>
		{/if}
		{#if mode !== 'preview'}<button class="icon-btn" class:on={wrap} title="Wrap lines" onclick={() => (wrap = !wrap)}><WrapText size={15} /></button>{/if}
		<span class="status faint">
			{#if loading}Loading…{:else if readonly}Read-only{:else if saving}Saving…{:else if dirty}<b class="unsaved">●</b> Unsaved changes{:else if savedAt}Saved {relTime(savedAt)}{:else}{lines} lines{/if}
		</span>
		<span class="grow"></span>
		{#if file.id}<button class="btn ghost" class:on={historyOpen} onclick={toggleHistory}><History size={14} />History</button>{/if}
		{#if !readonly}<button class="btn primary" disabled={!dirty || saving || loading} onclick={() => save()} title="Save ({modKey}+S)"><Save size={14} />Save</button>{/if}
	</div>
	{#if readonly}<div class="note">{readonly}</div>{/if}

	<div class="body">
		{#if loadError}
			<div class="empty center"><b>Could not open this file</b>{loadError}</div>
		{:else}
			{#if mode !== 'preview'}
				<div class="code" class:wrap class:prose={!isCode(file.name)}>
					{#if !wrap}<div class="gutter" bind:this={gutter} aria-hidden="true">{#each { length: lines } as _, i (i)}<div>{i + 1}</div>{/each}</div>{/if}
					<textarea bind:this={ta} bind:value={text} spellcheck={!isCode(file.name)} readonly={!!readonly || loading}
						onkeydown={keydown} onscroll={syncScroll} aria-label="File content" wrap={wrap ? 'soft' : 'off'}></textarea>
				</div>
			{/if}
			{#if markdown && mode !== 'edit'}
				<div class="preview" bind:this={previewEl}><article class="md">{@html html}</article></div>
			{/if}
		{/if}
		{#if historyOpen}
			<aside class="history">
				<div class="htitle">History</div>
				<p class="faint small">Each save keeps the previous content here (the last 50).</p>
				{#each versions as v (v.id)}
					<div class="ver">
						<div class="vmeta"><span>{new Date(v.created_at).toLocaleString()}</span><span class="faint">{fileSize(v.size)}{v.reason === 'restore' ? ' · before restore' : ''}</span></div>
						<a class="icon-btn" href={v.url} target="_blank" rel="noopener" title="Open this version"><Eye size={14} /></a>
						<button class="icon-btn" title="Restore this version" onclick={() => restore(v)}><RotateCcw size={14} /></button>
					</div>
				{:else}<p class="faint small">No earlier versions yet.</p>{/each}
			</aside>
		{/if}
	</div>
</div>

<style>
	.ed { height: 100%; display: flex; flex-direction: column; min-height: 0; }
	.tools { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-bottom: 1px solid var(--border); flex: none; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 4px; color: var(--text-2); font-size: 12.5px; }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.status { font-size: 12.5px; margin-left: 4px; }
	.unsaved { color: var(--accent); }
	.grow { flex: 1; }
	.btn.on { background: var(--hover); color: var(--text); }
	.note { padding: 6px 12px; font-size: 12.5px; color: var(--text-2); background: color-mix(in srgb, var(--c-yellow) 12%, var(--bg)); border-bottom: 1px solid var(--border); }
	.body { flex: 1; min-height: 0; display: flex; }
	.code { flex: 1; min-width: 0; display: flex; background: var(--bg); }
	.gutter { flex: none; overflow: hidden; padding: 12px 10px 40px 14px; text-align: right; color: var(--text-3); font: 12.5px/1.6 var(--font-mono); user-select: none; border-right: 1px solid var(--border); min-width: 46px; }
	textarea { flex: 1; min-width: 0; resize: none; border: 0; outline: 0; background: none; color: var(--text); padding: 12px 16px 40px; font: 12.5px/1.6 var(--font-mono); tab-size: 4; white-space: pre; overflow: auto; }
	.wrap textarea { white-space: pre-wrap; overflow-wrap: anywhere; }
	.prose textarea { font: 14.5px/1.65 var(--font-sans); max-width: 860px; margin: 0 auto; padding: 22px 28px 60px; }
	.prose.wrap { justify-content: center; }
	.preview { flex: 1; min-width: 0; overflow: auto; border-left: 1px solid var(--border); background: var(--surface); }
	.code + .preview { max-width: 50%; }
	.center { margin: 40px auto; max-width: 460px; }
	.history { width: 270px; flex: none; overflow: auto; border-left: 1px solid var(--border); padding: 10px; background: var(--bg-side); }
	.htitle { font-weight: 600; margin-bottom: 2px; }
	.small { font-size: 12px; margin: 0 0 10px; }
	.ver { display: flex; align-items: center; gap: 2px; padding: 5px 4px; border-radius: var(--radius-sm); }
	.ver:hover { background: var(--hover); }
	.vmeta { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: 12.5px; }
	.vmeta .faint { font-size: 11.5px; }

	/* Markdown preview */
	.md { max-width: 760px; margin: 0 auto; padding: 22px 30px 60px; line-height: 1.65; overflow-wrap: anywhere; }
	.md :global(h1), .md :global(h2), .md :global(h3) { line-height: 1.25; margin: 1.3em 0 0.5em; font-weight: 650; }
	.md :global(h1) { font-size: 1.7em; }
	.md :global(h2) { font-size: 1.35em; padding-bottom: 0.2em; border-bottom: 1px solid var(--border); }
	.md :global(h3) { font-size: 1.12em; }
	.md :global(:first-child) { margin-top: 0; }
	.md :global(a) { color: var(--accent); }
	.md :global(code) { font: 0.88em var(--font-mono); background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }
	.md :global(pre) { background: var(--code-bg); padding: 12px 14px; border-radius: 6px; overflow: auto; }
	.md :global(pre code) { background: none; padding: 0; }
	.md :global(blockquote) { margin: 0.8em 0; padding: 0 0 0 14px; border-left: 3px solid var(--border-strong); color: var(--text-2); }
	.md :global(table) { border-collapse: collapse; margin: 0.8em 0; }
	.md :global(th), .md :global(td) { border: 1px solid var(--border-strong); padding: 4px 10px; }
	.md :global(img) { max-width: 100%; }
	.md :global(hr) { border: 0; border-top: 1px solid var(--border); margin: 1.5em 0; }
	.md :global(li > input[type='checkbox']) { margin-right: 6px; }

	@media (max-width: 760px) {
		.code + .preview { display: none; }
		.history { position: absolute; right: 0; top: 44px; bottom: 0; box-shadow: var(--shadow); }
	}
</style>
