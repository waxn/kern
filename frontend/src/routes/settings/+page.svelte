<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Download, HardDrive, RotateCcw, Trash2, Upload, X } from '@lucide/svelte';
	import { onMount, untrack } from 'svelte';
	import { api } from '#lib/api.ts';
	import { download, importFiles } from '#lib/data/download.ts';
	import { counts } from '#lib/learn/util.svelte.ts';
	import { comboOf, prefs, SHORTCUT_ACTIONS, shortcut } from '#lib/state/prefs.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { ai } from '#lib/ai/ai.svelte.ts';
	import Sparkle from '#lib/ai/Sparkle.svelte';
	import { fileSize, fullDate, modKey } from '#lib/util.ts';

	type Section = 'appearance' | 'editor' | 'workspace' | 'flashcards' | 'ai' | 'shortcuts' | 'data';
	const sections: [Section, string][] = [
		['appearance', 'Appearance'], ['editor', 'Editor'], ['workspace', 'Workspace'], ['flashcards', 'Flashcards'],
		['ai', 'AI'], ['shortcuts', 'Keyboard'], ['data', 'Data & backups']
	];

	// ----- AI provider
	let aiForm = $state({ provider: '', model: '', base_url: '', api_key: '' });
	let aiTest = $state<{ ok: boolean; text: string } | null>(null);
	const MODEL_HINTS: Record<string, string[]> = {
		anthropic: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1'],
		openai: [], gemini: [], openrouter: [], ollama: ['llama3.3', 'qwen3', 'mistral'], custom: []
	};
	$effect(() => {
		if (section === 'ai' && !ai.config) ai.load();
	});
	let aiFilled = false;
	$effect(() => {
		const c = ai.config;
		if (!c || aiFilled) return;
		aiFilled = true;
		untrack(() => (aiForm = { provider: c.provider, model: c.model, base_url: c.base_url, api_key: '' }));
	});
	function pickProvider(p: string) {
		const info = ai.config?.providers[p];
		aiForm = { ...aiForm, provider: p, model: p === ai.config?.provider ? ai.config.model : (info?.model ?? ''), base_url: p === ai.config?.provider ? ai.config.base_url : (info?.base_url ?? '') };
		aiTest = null;
	}
	async function saveAi(extra: Record<string, unknown> = {}) {
		busy = 'ai';
		try {
			const body: Record<string, unknown> = { provider: aiForm.provider, model: aiForm.model, base_url: aiForm.base_url, ...extra };
			if (aiForm.api_key.trim()) body.api_key = aiForm.api_key.trim();
			ai.config = await api.put('/ai/config', body);
			aiForm.api_key = '';
			ui.toast('AI settings saved');
		} catch (e) {
			ui.error(e);
		} finally {
			busy = '';
		}
	}
	async function testAi() {
		await saveAi();
		busy = 'test';
		aiTest = null;
		try {
			const r = await api.post<{ reply: string }>('/ai/test');
			aiTest = { ok: true, text: `Connected. The model replied “${r.reply}”.` };
		} catch (e) {
			aiTest = { ok: false, text: (e as Error).message };
		} finally {
			busy = '';
		}
	}
	let section = $derived((page.url.searchParams.get('s') as Section) || 'appearance');
	const accents = ['#e2a85a', '#d98a6a', '#c9a227', '#7fbf8f', '#5fb3a8', '#74a9e0', '#a996e0', '#dc8fb9'];

	let fc = $state({ new_per_day: 20, reviews_per_day: 200, retention: 0.9, show_intervals: true });
	let data = $state({ auto_backup: true, backup_downloads: false });
	let backups = $state<{ name: string; size: number; created_at: string; kind: string; contents: { git: boolean; downloads: boolean } | null }[]>([]);
	let storage = $state<any>(null);
	let busy = $state('');
	let capturing = $state<string | null>(null);
	let fileInput = $state<HTMLInputElement>();
	let folderInput = $state<HTMLInputElement>();
	let restoreInput = $state<HTMLInputElement>();

	onMount(() => {
		api.get<Record<string, any>>('/settings').then((s) => {
			if (s.flashcards) fc = { ...fc, ...s.flashcards };
			if (s.data) data = { ...data, ...s.data };
		}).catch(() => {});
		loadData();
	});

	async function loadData() {
		try {
			[backups, storage] = await Promise.all([api.get<any[]>('/backups'), api.get<any>('/storage')]);
		} catch {
			/* offline */
		}
	}

	async function saveFc() {
		fc.new_per_day = Math.max(0, Math.min(9999, Math.round(fc.new_per_day || 0)));
		fc.reviews_per_day = Math.max(0, Math.min(99999, Math.round(fc.reviews_per_day || 0)));
		fc.retention = Math.max(0.7, Math.min(0.99, Number(fc.retention) || 0.9));
		await api.patch('/settings', { flashcards: $state.snapshot(fc) }).catch((e) => ui.error(e));
		counts.refresh();
	}

	async function saveData() {
		await api.patch('/settings', { data: $state.snapshot(data) }).catch((e) => ui.error(e));
	}

	async function backupNow() {
		busy = 'backup';
		try {
			const b = await api.post<{ name: string }>('/backups');
			ui.toast(`Backup ${b.name} created`);
			loadData();
		} catch (e) {
			ui.error(e);
		} finally {
			busy = '';
		}
	}

	async function restore(name: string | null, file?: File) {
		const ok = await ui.confirm({
			title: 'Restore this backup?',
			message: 'Everything in the workspace — pages, databases, cards, tasks, files, bookmarks, git repositories and settings — is replaced by the backup. A safety backup of the current state is made first. (Backups without videos keep the videos you have now; older backups without git repositories keep your current repositories.)',
			confirmLabel: 'Restore backup', danger: true
		});
		if (!ok) return;
		busy = 'restore';
		try {
			let res: any;
			if (file) {
				const form = new FormData();
				form.append('file', file);
				const r = await fetch('/api/backups/upload-restore', { method: 'POST', headers: { 'X-Kern': '1' }, body: form });
				res = await r.json();
				if (!r.ok) throw new Error(res.detail);
			} else res = await api.post(`/backups/${name}/restore`);
			try {
				for (const k of Object.keys(localStorage)) if (k.startsWith('kern:pending:')) localStorage.removeItem(k);
			} catch {
				/* ignore */
			}
			ui.toast(`Restored. The previous state was saved as ${res.safety_backup}.`);
			setTimeout(() => location.assign('/'), 1200);
		} catch (e) {
			ui.error(e);
		} finally {
			busy = '';
		}
	}

	async function removeBackup(name: string) {
		if (!(await ui.confirm({ title: `Delete ${name}?`, message: 'This backup file is removed permanently.', confirmLabel: 'Delete', danger: true }))) return;
		await api.del(`/backups/${name}`).catch((e) => ui.error(e));
		loadData();
	}

	async function doImport(files: FileList | null) {
		const list = [...(files ?? [])];
		if (!list.length) return;
		busy = 'import';
		if (await importFiles(list)) await ws.load();
		busy = '';
		loadData();
	}

	function capture(action: string) {
		capturing = action;
		ui.capturingShortcut = true;
	}

	function onKey(e: KeyboardEvent) {
		if (!capturing) return;
		e.preventDefault();
		e.stopPropagation();
		if (e.key === 'Escape') return stopCapture();
		if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;
		const combo = comboOf(e);
		if (!combo.includes('+') && !/^F\d+$/.test(combo)) {
			ui.toast('Use a modifier (Ctrl, Alt, Shift or ⌘) so the shortcut does not clash with typing.');
			return;
		}
		const clash = SHORTCUT_ACTIONS.find(([a]) => a !== capturing && shortcut(a) === combo);
		prefs.shortcuts = { ...prefs.shortcuts, [capturing]: combo };
		if (clash) ui.toast(`${combo} was also used for “${clash[1]}”; change that one too.`);
		stopCapture();
	}

	function stopCapture() {
		capturing = null;
		setTimeout(() => (ui.capturingShortcut = false));
	}

	const pretty = (c: string) => c.replace('Mod', modKey).replace(/\+/g, ' ');

	const editorKeys: [string, string][] = [
		['/', 'Insert a block'], ['[[', 'Link to a page'], ['((', 'Reference a block'], ['#', 'Mention a tag'],
		['Q :: A', 'Flashcard (also ;; and {{cloze}})'], [`${modKey} Shift C`, 'Make selection a cloze gap'],
		['Alt T', 'Make the block a task'], ['Tab / Shift Tab', 'Indent / outdent'], [`${modKey} Shift ↑ ↓`, 'Move block up / down'],
		[`${modKey} Enter`, 'Check to-do / fold children'], [`${modKey} D`, 'Duplicate block'], ['Esc', 'Select the current block'],
		['Shift ↑ ↓', 'Extend block selection'], [`${modKey} B / I / U`, 'Bold / italic / underline'], [`${modKey} Shift S`, 'Strikethrough'],
		[`${modKey} E`, 'Inline code'], [`${modKey} K (with selection)`, 'Add link'], [`${modKey} Shift H`, 'Highlight'],
		[`${modKey} Z / ${modKey} Shift Z`, 'Undo / redo'], ['Space · 1–4', 'Review: show answer · rate']
	];
</script>

<svelte:window onkeydowncapture={onKey} />

{#snippet seg(key: string, options: [any, string][])}
	<div class="seg">
		{#each options as [v, label] (v)}
			<button class:on={(prefs as any)[key] === v} onclick={() => ((prefs as any)[key] = v)}>{label}</button>
		{/each}
	</div>
{/snippet}

<div class="page-scroll">
	<div class="page">
		<h1>Settings</h1>
		<nav class="tabs">
			{#each sections as [s, label] (s)}<button class:on={section === s} onclick={() => goto(`/settings?s=${s}`, { replace: true })}>{label}</button>{/each}
		</nav>

		{#if section === 'appearance'}
			<p class="lede">Appearance and editor settings follow you to every browser that opens this workspace.</p>
			<div class="group">
				<div class="item"><div><b>Theme</b><span>Match your system or pick one.</span></div>{@render seg('theme', [['dark', 'Dark'], ['light', 'Light'], ['system', 'System']])}</div>
				<div class="item">
					<div><b>Accent color</b><span>Used for links, selection and highlights.</span></div>
					<div class="accents">
						{#each accents as a (a)}<button class="sw" class:on={prefs.accent === a} style:background={a} title={a} aria-label="Accent {a}" onclick={() => (prefs.accent = a)}></button>{/each}
						<input type="color" title="Custom color" value={prefs.accent || '#e2a85a'} oninput={(e) => (prefs.accent = e.currentTarget.value)} />
						<button class="btn ghost" disabled={!prefs.accent} onclick={() => (prefs.accent = '')}>Reset</button>
					</div>
				</div>
				<div class="item"><div><b>Editor font</b><span>Typeface for page content.</span></div>{@render seg('font', [['sans', 'Sans'], ['serif', 'Serif'], ['mono', 'Mono']])}</div>
				<div class="item"><div><b>Text size</b><span>Size of page content.</span></div>{@render seg('editorSize', [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']])}</div>
				<div class="item"><div><b>Editor width</b><span>Maximum line length of pages.</span></div>{@render seg('editorWidth', [['narrow', 'Narrow'], ['normal', 'Normal'], ['wide', 'Wide'], ['full', 'Full']])}</div>
				<div class="item"><div><b>Density</b><span>Compact fits more on screen.</span></div>{@render seg('density', [['comfortable', 'Comfortable'], ['compact', 'Compact']])}</div>
			</div>
		{:else if section === 'editor'}
			<div class="group">
				<div class="item"><div><b>New lines start as</b><span>Block type when you press Enter after text or a heading. Lists always continue as lists.</span></div>{@render seg('defaultBlock', [['paragraph', 'Text'], ['bullet', 'Bullets']])}</div>
				<div class="item"><div><b>Autosave</b><span>How soon after you stop typing changes are saved. Everything is also saved when you leave a page.</span></div>{@render seg('autosaveDelay', [[300, 'Instant'], [600, 'Normal'], [2000, 'Relaxed']])}</div>
				<div class="item"><div><b>Formatting while typing</b><span>Markdown shortcuts like <code># </code>, <code>- </code>, <code>[] </code>, <code>```</code> and <code>---</code> turn into blocks as you type.</span></div><span class="faint">Always on</span></div>
			</div>
		{:else if section === 'workspace'}
			<div class="group">
				<div class="item"><div><b>Open pages in</b><span>Where a click on a page link opens. {modKey}+click does the opposite.</span></div>{@render seg('openIn', [['current', 'Current tab'], ['tab', 'New tab']])}</div>
				<div class="item"><div><b>Sidebar sections</b><span>Which shortcut sections appear above your pages.</span></div>
					<div class="checks">
						{#each [['favorites', 'Favorites'], ['recent', 'Recent'], ['databases', 'Databases']] as [k, label] (k)}
							<label><input type="checkbox" checked={(prefs.sidebarShow as any)?.[k] !== false} onchange={(e) => (prefs.sidebarShow = { ...prefs.sidebarShow, [k]: e.currentTarget.checked })} />{label}</label>
						{/each}
					</div>
				</div>
				<div class="item col"><div><b>Favorites</b><span>Pages pinned in the sidebar.</span></div>
					<div class="favs">
						{#each ws.favorites as d (d.id)}
							<span class="chip">{d.icon} {d.title || 'Untitled'}<button title="Remove from favorites" onclick={() => ws.updateDoc(d.id, { is_favorite: false })}><X size={11} /></button></span>
						{:else}<span class="faint">No favorites. Use the ☆ on any page.</span>{/each}
					</div>
				</div>
				<div class="item"><div><b>Recently opened</b><span>Shown in the sidebar, Home and search.</span></div>
					<button class="btn" onclick={async () => { await api.post('/recent/clear'); await ws.load(); ui.toast('Recent pages cleared'); }}>Clear recent</button></div>
				<div class="item"><div><b>Archive and trash</b><span>Archived pages are hidden but kept; trashed pages can be restored until you empty the trash.</span></div>
					<div class="row"><a class="btn" href="/archive">Archive · {ws.archived.length}</a><a class="btn" href="/trash">Trash</a></div></div>
			</div>
		{:else if section === 'flashcards'}
			<div class="group">
				<div class="item"><div><b>New cards per day</b><span>How many unseen cards to introduce each day.</span></div><input class="input num" type="number" min="0" bind:value={fc.new_per_day} onchange={saveFc} /></div>
				<div class="item"><div><b>Reviews per day</b><span>Upper limit on review cards shown per day.</span></div><input class="input num" type="number" min="0" bind:value={fc.reviews_per_day} onchange={saveFc} /></div>
				<div class="item"><div><b>Desired retention</b><span>FSRS schedules reviews so you recall this share of cards. Higher means more reviews.</span></div>
					<span class="ret"><input type="range" min="0.7" max="0.99" step="0.01" bind:value={fc.retention} onchange={saveFc} /><b>{Math.round(fc.retention * 100)}%</b></span></div>
				<div class="item"><div><b>Show next intervals</b><span>Label answer buttons with when the card comes back.</span></div><input type="checkbox" bind:checked={fc.show_intervals} onchange={saveFc} /></div>
				<div class="item"><div><b>Export cards</b><span>All cards, for spreadsheets or Anki.</span></div>
					<div class="row"><button class="btn" onclick={() => download('/export/cards?as=csv')}>CSV</button><button class="btn" onclick={() => download('/export/cards?as=apkg')}>Anki (.apkg)</button></div></div>
			</div>
		{:else if section === 'ai'}
			<div class="aihead"><Sparkle size={22} /><div><b>AI assistant</b><span>Optional. Generates flashcards and templates, and writes in pages when you type <kbd>/</kbd> then <kbd>Space</kbd>. Nothing is sent anywhere until you set a provider and use it.</span></div>
				{#if ai.config?.configured}<span class="chip" data-c="green">Ready</span>{:else}<span class="chip">Not set up</span>{/if}</div>
			{#if ai.config}
				<div class="group">
					<div class="item col"><div><b>Provider</b></div>
						<div class="providers">
							{#each Object.entries(ai.config.providers) as [k, p] (k)}
								<button class="prov" class:on={aiForm.provider === k} onclick={() => pickProvider(k)}>{p.label}</button>
							{/each}
						</div>
					</div>
					{#if aiForm.provider}
						{@const info = ai.config.providers[aiForm.provider]}
						{#if info.needs_key || aiForm.provider === 'custom' || aiForm.provider === 'ollama'}
							<div class="item"><div><b>API key</b><span>{ai.config.has_key && ai.config.provider === aiForm.provider ? `Saved${ai.config.key_hint ? ` (ends in …${ai.config.key_hint})` : ''}. Leave empty to keep it.` : info.needs_key ? 'Stored on your Kern server only; the browser never receives it.' : 'Optional for local servers.'}</span></div>
								<div class="row">
									<input class="input wide" type="password" autocomplete="off" bind:value={aiForm.api_key} placeholder={ai.config.has_key ? '••••••••' : aiForm.provider === 'anthropic' ? 'sk-ant-…' : 'API key'} />
									{#if ai.config.has_key}<button class="btn ghost" onclick={() => saveAi({ clear_key: true })}>Remove</button>{/if}
								</div>
							</div>
						{/if}
						<div class="item"><div><b>Model</b><span>{aiForm.provider === 'anthropic' ? 'Claude Opus 5.5 is the default; Sonnet 5.5 and Haiku 5.5 are faster and cheaper.' : 'The model name exactly as your provider spells it.'}</span></div>
							<input class="input wide" list="ai-models" bind:value={aiForm.model} placeholder="model name" />
							<datalist id="ai-models">{#each MODEL_HINTS[aiForm.provider] ?? [] as m (m)}<option value={m}></option>{/each}</datalist>
						</div>
						{#if aiForm.provider !== 'anthropic'}
							<div class="item"><div><b>Base URL</b><span>{aiForm.provider === 'ollama' ? 'Inside Docker, host.docker.internal reaches the machine Kern runs on. Without Docker, use http://localhost:11434/v1.' : 'An OpenAI-compatible endpoint (the part before /chat/completions).'}</span></div>
								<input class="input wide" bind:value={aiForm.base_url} placeholder="https://…/v1" /></div>
						{/if}
						<div class="item">
							<div>{#if aiTest}<span class:ok={aiTest.ok} class:bad={!aiTest.ok} class="test">{aiTest.text}</span>{:else}<span>Save, then send a tiny test request.</span>{/if}</div>
							<div class="row">
								<button class="btn" disabled={!!busy} onclick={testAi}>{busy === 'test' ? 'Testing…' : 'Save & test'}</button>
								<button class="btn primary" disabled={!!busy} onclick={() => saveAi()}>Save</button>
							</div>
						</div>
					{/if}
				</div>
				<p class="faint small">When you use the assistant, your prompt and the current page (or the page you pick) are sent to the provider. The key is included in backups of this workspace, so keep backups private.</p>
			{/if}
		{:else if section === 'shortcuts'}
			<div class="section-title">App shortcuts · click to change</div>
			<div class="group">
				{#each SHORTCUT_ACTIONS as [action, label, def] (action)}
					<div class="item tight">
						<div><b>{label}</b></div>
						<div class="row">
							<button class="keybtn" class:capturing={capturing === action} onclick={() => capture(action)}>{capturing === action ? 'Press keys… (Esc cancels)' : pretty(shortcut(action))}</button>
							{#if prefs.shortcuts?.[action] && prefs.shortcuts[action] !== def}
								<button class="icon-btn" title="Reset to {pretty(def)}" onclick={() => { const { [action]: _, ...rest } = prefs.shortcuts; prefs.shortcuts = rest; }}><RotateCcw size={13} /></button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
			<div class="section-title">In the editor</div>
			<div class="group keys">{#each editorKeys as [k, label] (k)}<div class="key"><span>{label}</span><kbd>{k}</kbd></div>{/each}</div>
		{:else if section === 'data'}
			<div class="section-title">Import</div>
			<div class="group">
				<div class="item"><div><b>Import files</b><span>Markdown, HTML, OPML, CSV (becomes a database), Kern JSON, Anki decks (.apkg) or a .zip of any of these. Pages link up by title; images come along.</span></div>
					<div class="row">
						<input type="file" multiple hidden bind:this={fileInput} accept=".md,.markdown,.txt,.html,.htm,.opml,.csv,.json,.zip,.apkg" onchange={(e) => doImport(e.currentTarget.files)} />
						<input type="file" hidden bind:this={folderInput} webkitdirectory onchange={(e) => doImport(e.currentTarget.files)} />
						<button class="btn" disabled={!!busy} onclick={() => fileInput?.click()}><Upload size={14} />Files…</button>
						<button class="btn" disabled={!!busy} onclick={() => folderInput?.click()}><Upload size={14} />Folder…</button>
					</div>
				</div>
			</div>
			<div class="section-title">Export</div>
			<div class="group">
				<div class="item"><div><b>Whole workspace</b><span>Every page as Markdown or HTML in folders, databases as CSV, with attachments — readable without Kern. JSON keeps everything for re-importing.</span></div>
					<div class="row">
						<button class="btn" onclick={() => download('/export/workspace?as=md')}><Download size={14} />Markdown</button>
						<button class="btn" onclick={() => download('/export/workspace?as=html')}>HTML</button>
						<button class="btn" onclick={() => download('/export/workspace?as=json')}>JSON</button>
					</div>
				</div>
				<div class="item"><div><b>Single pages, databases and decks</b><span>Use “Export…” in a page's ⋯ menu, or the export buttons under Flashcards.</span></div></div>
			</div>
			<div class="section-title">Backups</div>
			<div class="group">
				<div class="item"><div><b>Automatic daily backup</b><span>Keeps the last 7, inside the data volume. Copy them elsewhere for safety.</span></div>
					<input type="checkbox" bind:checked={data.auto_backup} onchange={saveData} /></div>
				<div class="item"><div><b>Include downloaded videos</b><span>Videos saved from bookmarks{storage ? ` (${fileSize(storage.downloads_bytes)} now)` : ''}. They can be downloaded again, so they're left out unless this is on.</span></div>
					<input type="checkbox" bind:checked={data.backup_downloads} onchange={saveData} /></div>
				<div class="item"><div><b>Back up now</b><span>Pages, databases, cards, tasks, files and their versions, bookmarks, git repositories and settings in one .zip.</span></div>
					<div class="row">
						<button class="btn primary" disabled={!!busy} onclick={backupNow}><HardDrive size={14} />{busy === 'backup' ? 'Backing up…' : 'Create backup'}</button>
						<input type="file" hidden accept=".zip" bind:this={restoreInput} onchange={(e) => { const f = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (f) restore(null, f); }} />
						<button class="btn" disabled={!!busy} onclick={() => restoreInput?.click()}><Upload size={14} />Restore from file…</button>
					</div>
				</div>
				{#each backups as b (b.name)}
					<div class="item tight">
						<div><b>{fullDate(b.created_at)}</b><span>{b.kind === 'auto' ? 'Automatic' : b.kind === 'prerestore' ? 'Safety copy before a restore' : 'Manual'} · {fileSize(b.size)}{b.contents ? (b.contents.git ? '' : ' · no git repositories (older backup)') + (b.contents.downloads ? ' · with videos' : '') : ''} · {b.name}</span></div>
						<div class="row">
							<a class="btn ghost" href="/api/backups/{b.name}" download><Download size={13} />Download</a>
							<button class="btn ghost" disabled={!!busy} onclick={() => restore(b.name)}><RotateCcw size={13} />Restore</button>
							<button class="icon-btn" title="Delete backup" onclick={() => removeBackup(b.name)}><Trash2 size={13} /></button>
						</div>
					</div>
				{:else}<div class="item"><span class="faint">No backups yet.</span></div>{/each}
			</div>
			{#if storage}
				<div class="section-title">Storage</div>
				<div class="group stats">
					<div><b>{fileSize(storage.database_bytes)}</b><span>Database</span></div>
					<div><b>{fileSize(storage.media_bytes - (storage.downloads_bytes ?? 0))}</b><span>Files</span></div>
					<div><b>{fileSize(storage.downloads_bytes ?? 0)}</b><span>Videos</span></div>
					<div><b>{fileSize(storage.git_bytes ?? 0)}</b><span>Git</span></div>
					<div><b>{fileSize(storage.backups_bytes)}</b><span>Backups</span></div>
					{#each Object.entries(storage.counts) as [k, v] (k)}<div><b>{Number(v).toLocaleString()}</b><span>{k}</span></div>{/each}
				</div>
				<p class="faint small">Data folder: <code>{storage.data_dir}</code> · <a href="/developer">API documentation</a></p>
			{/if}
		{/if}
	</div>
</div>

<style>
	.tabs { display: flex; gap: 2px; margin: 8px 0 16px; border-bottom: 1px solid var(--border); overflow-x: auto; }
	.tabs button { padding: 7px 10px; color: var(--text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
	.tabs button:hover { color: var(--text-2); }
	.tabs button.on { color: var(--text); border-bottom-color: var(--accent); }
	.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
	.item { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.item.tight { padding: 7px 14px; }
	.item.col { flex-direction: column; align-items: stretch; }
	.item:first-child { border-top: 0; }
	.item > div:first-child { flex: 1; min-width: 220px; }
	.item b { display: block; font-weight: 550; }
	.item span { color: var(--text-3); font-size: 12.5px; }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 3px 11px; border-radius: 4px; color: var(--text-2); }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.accents { display: flex; align-items: center; gap: 7px; }
	.sw { width: 20px; height: 20px; border-radius: 50%; }
	.sw.on { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--text-2); }
	input[type='color'] { width: 26px; height: 24px; padding: 0; border: 1px solid var(--border-strong); border-radius: 4px; background: none; }
	.num { width: 90px; text-align: right; }
	.ret { display: flex; align-items: center; gap: 8px; }
	input[type='range'], .item input[type='checkbox'], .checks input { accent-color: var(--accent); }
	.item > input[type='checkbox'] { width: 16px; height: 16px; }
	.row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
	.row a.btn { text-decoration: none; }
	.checks { display: flex; gap: 14px; }
	.checks label { display: flex; align-items: center; gap: 5px; color: var(--text-2); }
	.favs { display: flex; flex-wrap: wrap; gap: 6px; }
	.favs .chip button { display: grid; color: inherit; opacity: 0.6; }
	.keybtn { min-width: 120px; padding: 3px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius); font: 12.5px var(--font-mono); color: var(--text-2); background: var(--bg); }
	.keybtn:hover { border-color: var(--accent); }
	.keybtn.capturing { border-color: var(--accent); color: var(--accent); }
	.keys { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
	.key { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 14px; border-bottom: 1px solid var(--border); color: var(--text-2); }
	.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 0; }
	.stats div { display: flex; flex-direction: column; padding: 10px 14px; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); }
	.stats b { font-size: 17px; font-weight: 600; }
	.stats span { color: var(--text-3); font-size: 12px; text-transform: capitalize; }
	.small { font-size: 12.5px; }
	.aihead { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
	.aihead div { flex: 1; }
	.aihead b { display: block; }
	.aihead span { color: var(--text-3); font-size: 12.5px; }
	.providers { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
	.prov { padding: 5px 11px; border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-2); }
	.prov:hover { background: var(--hover); }
	.prov.on { border-color: var(--accent); color: var(--text); background: color-mix(in srgb, var(--accent) 10%, transparent); }
	.wide { width: min(320px, 100%); }
	.test.ok { color: var(--c-green); }
	.test.bad { color: var(--danger); }
	code { font-family: var(--font-mono); font-size: 0.9em; background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
</style>
