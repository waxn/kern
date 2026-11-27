<script lang="ts">
	// Read-only look into the app's SQLite database: tables on the left, a paged data grid, the
	// schema of the table, and a collapsible box for ad-hoc SELECT queries.
	import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronRight, Database, Info, KeyRound, Play, RefreshCw, Table2, Eye } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { ApiError } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, modKey } from '#lib/util.ts';
	import { appsApi, type App, type DbCell, type DbInfo, type DbQueryResult, type DbRows, type DbTable } from './types.ts';

	let { app }: { app: App } = $props();

	let info = $state<DbInfo | null>(null);
	let loaded = $state(false);
	let infoError = $state('');
	let file = $state<string | null>(null);
	let tableName = $state<string | null>(null);
	let data = $state<DbRows | null>(null);
	let rowsLoading = $state(false);
	let rowsError = $state('');
	let offset = $state(0);
	let limit = $state(50);
	let order = $state('');
	let dir = $state<'asc' | 'desc'>('asc');
	let expanded = $state<Record<string, boolean>>({});
	let schemaOpen = $state(false);

	let sqlOpen = $state(false);
	let sql = $state('');
	let sqlTouched = false;
	let running = $state(false);
	let result = $state<DbQueryResult | null>(null);
	let sqlError = $state('');
	let sqlExpanded = $state<Record<string, boolean>>({});

	let sqliteFiles = $derived((info?.files ?? []).filter((f) => f.is_sqlite));
	let table = $derived<DbTable | null>(info?.tables.find((t) => t.name === tableName) ?? null);
	let pages = $derived(data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1);
	let page = $derived(data ? Math.floor(data.offset / data.limit) + 1 : 1);

	const quote = (n: string) => `"${n.replace(/"/g, '""')}"`;
	const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

	let infoSeq = 0;
	async function loadInfo(want?: string | null) {
		const seq = ++infoSeq;
		try {
			let r = await appsApi.dbInfo(app.slug, want);
			// The server did not pick a file itself: take the first SQLite one.
			if (!r.file && r.files.some((f) => f.is_sqlite) && !want) {
				r = await appsApi.dbInfo(app.slug, r.files.find((f) => f.is_sqlite)!.path);
			}
			if (seq !== infoSeq) return;
			info = r;
			infoError = '';
			file = r.file;
			if (!r.tables.some((t) => t.name === tableName)) {
				tableName = r.tables[0]?.name ?? null;
				resetGrid();
			}
			if (!sqlTouched) sql = tableName ? `SELECT * FROM ${quote(tableName)} LIMIT 100` : '';
			await loadRows();
		} catch (e) {
			if (seq !== infoSeq) return;
			infoError = message(e);
		}
		loaded = true;
	}

	function resetGrid() {
		offset = 0;
		order = '';
		dir = 'asc';
		expanded = {};
		schemaOpen = false;
		data = null;
	}

	let rowsSeq = 0;
	async function loadRows() {
		if (!file || !tableName) {
			data = null;
			return;
		}
		const seq = ++rowsSeq;
		rowsLoading = true;
		try {
			const r = await appsApi.dbRows(app.slug, { file, table: tableName, offset, limit, order, dir });
			if (seq !== rowsSeq) return;
			data = r;
			rowsError = '';
			expanded = {};
		} catch (e) {
			if (seq !== rowsSeq) return;
			rowsError = message(e);
			data = null;
		} finally {
			if (seq === rowsSeq) rowsLoading = false;
		}
	}

	onMount(() => {
		loadInfo();
	});

	function pickTable(t: DbTable) {
		if (t.name === tableName) return;
		tableName = t.name;
		resetGrid();
		rowsError = '';
		if (!sqlTouched) sql = `SELECT * FROM ${quote(t.name)} LIMIT 100`;
		loadRows();
	}

	function pickFile(path: string) {
		tableName = null;
		resetGrid();
		result = null;
		sqlError = '';
		sqlTouched = false;
		loadInfo(path);
	}

	function sortBy(col: string) {
		if (order !== col) {
			order = col;
			dir = 'asc';
		} else if (dir === 'asc') dir = 'desc';
		else {
			order = '';
			dir = 'asc';
		}
		offset = 0;
		loadRows();
	}

	function go(p: number) {
		offset = (Math.min(Math.max(1, p), pages) - 1) * limit;
		loadRows();
	}

	async function run() {
		if (!file || !sql.trim() || running) return;
		running = true;
		sqlError = '';
		try {
			result = await appsApi.dbQuery(app.slug, file, sql);
			sqlExpanded = {};
		} catch (e) {
			result = null;
			sqlError = message(e);
		} finally {
			running = false;
		}
	}

	function onSqlKey(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			run();
		}
	}

	function isBlob(c: DbCell): c is { blob: number } {
		return typeof c === 'object' && c !== null && 'blob' in c;
	}
	function text(c: DbCell): string {
		if (c === null) return 'NULL';
		if (isBlob(c)) return `BLOB · ${fileSize(c.blob)}`;
		return String(c);
	}

	function onWindowKey(e: KeyboardEvent) {
		if (e.key === 'Escape') schemaOpen = false;
	}
	function onWindowClick(e: MouseEvent) {
		if (schemaOpen && !(e.target as Element | null)?.closest?.('.schema-wrap')) schemaOpen = false;
	}
</script>

<svelte:window onkeydown={onWindowKey} onclick={onWindowClick} />

{#snippet grid(columns: string[], rows: DbCell[][], opts: { sortable: boolean; exp: Record<string, boolean>; toggle: (k: string) => void })}
	<div class="gridwrap">
		<table>
			<thead>
				<tr>
					<th class="rn">#</th>
					{#each columns as c, ci (ci)}
						<th>
							{#if opts.sortable}
								<button class="sort" class:on={order === c} onclick={() => sortBy(c)} title="Sort by {c}">
									<span class="truncate">{c}</span>
									{#if order === c}{#if dir === 'asc'}<ArrowUp size={11} />{:else}<ArrowDown size={11} />{/if}{/if}
								</button>
							{:else}
								<span class="truncate">{c}</span>
							{/if}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as row, ri (ri)}
					<tr>
						<td class="rn">{(opts.sortable && data ? data.offset : 0) + ri + 1}</td>
						{#each row as cell, ci (ci)}
							{@const k = `${ri}:${ci}`}
							<td class:null={cell === null} class:blob={isBlob(cell)} class:num={typeof cell === 'number'} class:open={opts.exp[k]}>
								<button class="cell" title={opts.exp[k] ? 'Collapse' : 'Expand'} onclick={() => opts.toggle(k)}>{text(cell)}</button>
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		{#if !rows.length}<p class="none">No rows.</p>{/if}
	</div>
{/snippet}

{#if infoError && !info}
	<div class="empty"><b>Can't read the database</b>{infoError}<div><button class="btn first" onclick={() => loadInfo()}><RefreshCw size={13} />Try again</button></div></div>
{:else if loaded && !sqliteFiles.length}
	<div class="empty">
		<Database size={22} />
		<b>No database yet</b>
		This app has no SQLite database. It shows up here once the app creates a <code>.db</code> or <code>.sqlite</code> file in its data folder.
		<div><button class="btn first" onclick={() => loadInfo()}><RefreshCw size={13} />Check again</button></div>
	</div>
{:else if loaded && info}
	<div class="db">
		<div class="bar">
			{#if sqliteFiles.length > 1}
				<select class="input filepick" value={file} onchange={(e) => pickFile(e.currentTarget.value)} aria-label="Database file">
					{#each sqliteFiles as f (f.path)}<option value={f.path}>{f.path} ({fileSize(f.size)})</option>{/each}
				</select>
			{:else if file}
				<span class="fname mono truncate" title={file}><Database size={13} />{file}</span>
				<span class="faint">{fileSize(sqliteFiles[0]?.size ?? 0)}</span>
			{/if}
			<span class="grow"></span>
			<button class="icon-btn" title="Reload" onclick={() => loadInfo(file)}><RefreshCw size={14} /></button>
		</div>

		<div class="main">
			<aside>
				<div class="side-head faint">{info.tables.length} {info.tables.length === 1 ? 'table' : 'tables'}</div>
				<div class="tlist">
					{#each info.tables as t (t.name)}
						<button class="titem" class:on={t.name === tableName} onclick={() => pickTable(t)} title={t.name}>
							{#if t.kind === 'view'}<Eye size={12} />{:else}<Table2 size={12} />{/if}
							<span class="truncate">{t.name}</span>
							<span class="count faint">{t.rows.toLocaleString()}</span>
						</button>
					{:else}
						<p class="none">No tables.</p>
					{/each}
				</div>
			</aside>

			<section>
				{#if table}
					<div class="fhead">
						<b class="mono truncate">{table.name}</b>
						{#if table.kind === 'view'}<span class="tag">view</span>{/if}
						<span class="faint">{table.columns.length} columns</span>
						<div class="schema-wrap">
							<button class="icon-btn" class:on={schemaOpen} title="Schema" aria-expanded={schemaOpen} onclick={() => (schemaOpen = !schemaOpen)}><Info size={14} /></button>
							{#if schemaOpen}
								<div class="pop" role="dialog" aria-label="Schema of {table.name}">
									<div class="pop-head mono">{table.name}</div>
									<table class="schema">
										<tbody>
											{#each table.columns as c (c.name)}
												<tr>
													<td class="mono">{c.name}{#if c.pk}<KeyRound size={11} />{/if}</td>
													<td class="mono faint">{c.type || '—'}</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}
						</div>
						<span class="grow"></span>
						{#if rowsLoading}<span class="faint">Loading…</span>{/if}
					</div>
					{#if rowsError}
						<p class="err pad">{rowsError}</p>
					{:else if data}
						{@render grid(data.columns, data.rows, { sortable: true, exp: expanded, toggle: (k) => (expanded[k] = !expanded[k]) })}
						<div class="pager">
							<span class="faint">{data.total ? `${(data.offset + 1).toLocaleString()}–${(data.offset + data.rows.length).toLocaleString()} of ${data.total.toLocaleString()}` : '0 rows'}</span>
							<span class="grow"></span>
							<select class="input" value={limit} onchange={(e) => { limit = Number(e.currentTarget.value); offset = 0; loadRows(); }} aria-label="Rows per page">
								{#each [25, 50, 100, 200] as n (n)}<option value={n}>{n} / page</option>{/each}
							</select>
							<button class="icon-btn" disabled={page <= 1} title="Previous page" onclick={() => go(page - 1)}><ChevronLeft size={15} /></button>
							<span class="faint pg">{page} / {pages}</span>
							<button class="icon-btn" disabled={page >= pages} title="Next page" onclick={() => go(page + 1)}><ChevronRight size={15} /></button>
						</div>
					{:else if rowsLoading}
						<p class="none">Loading…</p>
					{/if}
				{:else}
					<p class="none">{info.tables.length ? 'Pick a table.' : 'This database has no tables yet.'}</p>
				{/if}
			</section>
		</div>

		<div class="sqlbox">
			<button class="sqltoggle" aria-expanded={sqlOpen} onclick={() => (sqlOpen = !sqlOpen)}>
				{#if sqlOpen}<ChevronDown size={14} />{:else}<ChevronRight size={14} />{/if}
				<b>SQL</b><span class="faint">read-only, SELECT only</span>
			</button>
			{#if sqlOpen}
				<div class="sqlbody">
					<textarea class="input mono" rows="4" bind:value={sql} spellcheck="false" placeholder="SELECT * FROM …" oninput={() => (sqlTouched = true)} onkeydown={onSqlKey}></textarea>
					<div class="sqlacts">
						<button class="btn primary" disabled={running || !sql.trim() || !file} onclick={run}><Play size={13} />{running ? 'Running…' : 'Run'}</button>
						<span class="faint">{modKey}+Enter</span>
						<span class="grow"></span>
						{#if result}
							<span class="faint">{result.rows.length.toLocaleString()} {result.rows.length === 1 ? 'row' : 'rows'} · {result.seconds.toFixed(3)}s{result.truncated ? ' · truncated' : ''}</span>
						{/if}
					</div>
					{#if sqlError}<p class="err">{sqlError}</p>{/if}
					{#if result}
						{#if result.truncated}<p class="faint note">The result was cut off. Add a LIMIT or narrow the query to see the rest.</p>{/if}
						{@render grid(result.columns, result.rows, { sortable: false, exp: sqlExpanded, toggle: (k) => (sqlExpanded[k] = !sqlExpanded[k]) })}
					{/if}
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.db { display: flex; flex-direction: column; gap: 10px; }
	.bar { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
	.fname { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); }
	.filepick { max-width: min(420px, 100%); font-family: var(--font-mono); font-size: 12.5px; }
	.grow { flex: 1; }
	.mono { font-family: var(--font-mono); }
	.main { display: grid; grid-template-columns: 220px minmax(0, 1fr); height: calc(100dvh - 300px); min-height: 360px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	aside { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--border); background: var(--surface); }
	.side-head { padding: 8px 10px; font-size: 12px; border-bottom: 1px solid var(--border); }
	.tlist { flex: 1; overflow-y: auto; padding: 4px 0; }
	.titem { display: flex; align-items: center; gap: 6px; width: 100%; padding: 4px 10px; font: 12.5px var(--font-mono); color: var(--text-2); text-align: left; }
	.titem:hover { background: var(--hover); color: var(--text); }
	.titem.on { background: var(--active); color: var(--text); }
	.titem :global(svg) { flex: none; color: var(--text-3); }
	.titem .truncate { flex: 1; }
	.count { flex: none; font-size: 11.5px; font-variant-numeric: tabular-nums; }
	section { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
	.fhead { display: flex; align-items: center; gap: 8px; padding: 6px 8px 6px 12px; border-bottom: 1px solid var(--border); font-size: 12.5px; min-height: 41px; }
	.tag { padding: 1px 6px; border-radius: 4px; font-size: 11px; background: var(--surface-2); color: var(--text-2); }
	.schema-wrap { position: relative; }
	.pop { position: absolute; z-index: 20; top: calc(100% + 6px); left: 0; min-width: 240px; max-width: min(380px, 80vw); max-height: 320px; overflow: auto; padding: 8px 0; border-radius: 8px; border: 1px solid var(--border-strong); background: var(--surface-2); box-shadow: var(--shadow); }
	.pop-head { padding: 0 12px 6px; font-weight: 600; font-size: 12.5px; border-bottom: 1px solid var(--border); }
	.schema { width: 100%; border-collapse: collapse; font-size: 12px; }
	.schema td { padding: 3px 12px; }
	.schema td:first-child :global(svg) { margin-left: 5px; vertical-align: -1px; color: var(--accent); }
	.gridwrap { flex: 1; min-height: 0; overflow: auto; background: var(--bg); }
	table { border-collapse: separate; border-spacing: 0; font: 12.5px var(--font-mono); min-width: 100%; }
	thead th { position: sticky; top: 0; z-index: 2; padding: 0; text-align: left; font-weight: 600; background: var(--surface); border-bottom: 1px solid var(--border-strong); border-right: 1px solid var(--border); color: var(--text-2); max-width: 300px; }
	thead th > span { display: block; padding: 6px 10px; }
	.sort { display: flex; align-items: center; gap: 4px; width: 100%; padding: 6px 10px; text-align: left; font-weight: 600; color: var(--text-2); }
	.sort:hover, .sort.on { color: var(--text); background: var(--hover); }
	.sort.on :global(svg) { color: var(--accent); flex: none; }
	tbody td { padding: 0; border-bottom: 1px solid var(--border); border-right: 1px solid var(--border); max-width: 300px; vertical-align: top; }
	tbody tr:hover td { background: var(--hover); }
	.rn { position: sticky; left: 0; z-index: 1; min-width: 40px; padding: 4px 8px; text-align: right; color: var(--text-3); background: var(--surface); font-size: 11.5px; user-select: none; }
	thead .rn { z-index: 3; }
	.cell { display: block; width: 100%; padding: 4px 10px; text-align: left; font: inherit; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
	td.open { max-width: 640px; }
	td.open .cell { white-space: pre-wrap; overflow-wrap: anywhere; }
	td.num .cell { text-align: right; font-variant-numeric: tabular-nums; color: var(--c-blue); }
	td.null .cell { color: var(--text-3); font-style: italic; }
	td.blob .cell { color: var(--c-purple); }
	.pager { display: flex; align-items: center; gap: 6px; padding: 5px 8px 5px 12px; border-top: 1px solid var(--border); background: var(--surface); font-size: 12.5px; }
	.pager .input { height: 26px; font-size: 12px; }
	.pg { min-width: 54px; text-align: center; font-variant-numeric: tabular-nums; }
	.none { margin: 0; padding: 16px; color: var(--text-3); font-size: 13px; }
	.pad { padding: 12px; margin: 0; }
	.err { margin: 0; color: var(--danger); font: 12.5px/1.5 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
	.note { margin: 0; font-size: 12.5px; }
	.sqlbox { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.sqltoggle { display: flex; align-items: center; gap: 6px; width: 100%; padding: 8px 12px; font-size: 13px; text-align: left; background: var(--surface); color: var(--text-2); }
	.sqltoggle:hover { background: var(--hover); }
	.sqltoggle b { color: var(--text); font-weight: 550; }
	.sqlbody { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid var(--border); }
	.sqlbody textarea { width: 100%; font-size: 12.5px; line-height: 1.5; resize: vertical; white-space: pre; overflow: auto; }
	.sqlacts { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
	.sqlbody .gridwrap { max-height: 360px; border: 1px solid var(--border); border-radius: 6px; flex: none; }
	.empty :global(svg) { color: var(--text-3); margin-bottom: 6px; }
	.empty code { font: 12px var(--font-mono); }
	.first { margin-top: 12px; }
	@media (max-width: 700px) {
		.main { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); height: auto; }
		aside { max-height: 150px; border-right: 0; border-bottom: 1px solid var(--border); }
		.gridwrap { max-height: 60dvh; }
		.pager { flex-wrap: wrap; }
	}
</style>
