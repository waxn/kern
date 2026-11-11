<script lang="ts">
	type E = [string, string, string];
	const example = `curl -H 'X-Kern: 1' -H 'Content-Type: application/json' \\
  -d '{"title": "From the command line"}' http://localhost:8420/api/documents`;
	const groups: [string, string, E[]][] = [
		['Pages', 'Documents, their blocks and links. Ids are UUIDs.', [
			['GET', '/api/tree', 'Every live page and database entry (no blocks).'],
			['POST', '/api/documents', 'Create a page. Body: title, icon, parent, template (template id).'],
			['GET', '/api/documents/{id}', 'A page with blocks, resolved links, properties, card and task markers, and its content version.'],
			['PATCH', '/api/documents/{id}', 'Change title, icon, cover, is_favorite, is_archived, tags (ids). Adding a tag applies its templates.'],
			['DELETE', '/api/documents/{id}', 'Delete forever (only from the trash).'],
			['POST', '/api/documents/{id}/move', 'Body: parent, index.'],
			['POST', '/api/documents/{id}/duplicate', 'Copy a page with its sub-pages (and database).'],
			['POST', '/api/documents/{id}/trash', 'Move to trash with sub-pages.'],
			['POST', '/api/documents/{id}/restore', 'Bring back from the trash.'],
			['POST', '/api/documents/{id}/blocks/sync', 'Save blocks. Body: upserts [{id, parent, position, type, html, props, collapsed}], deletes [ids], base (version you edited), force. Returns 409 with the other version if the same blocks changed since base.'],
			['GET', '/api/documents/{id}/backlinks', 'Blocks that link to this page, grouped by page.'],
			['GET', '/api/blocks/{id}/backlinks', 'Blocks that reference a block.'],
			['PUT', '/api/documents/{id}/properties/{prop}', 'Set a property value. Body: value.'],
			['GET', '/api/trash', 'Pages in the trash.']
		]],
		['Tags and properties', '', [
			['GET / POST', '/api/tags', 'List (with page counts) or create {name, color}.'],
			['GET / PATCH / DELETE', '/api/tags/{id}', 'A tag with its properties, pages and block mentions.'],
			['GET / POST', '/api/properties', 'Property definitions. Body: name, type, tag or database, options, config.'],
			['PATCH / DELETE', '/api/properties/{id}', 'Rename, change type, options or config.']
		]],
		['Databases', 'A database is a page; its entries are pages too.', [
			['GET / POST', '/api/databases', 'List, or create {title, parent}.'],
			['GET', '/api/databases/{id}', 'Properties, views, rows with computed rollups and formulas, entry templates.'],
			['POST', '/api/databases/{id}/entries', 'New entry. Body: title, values {prop: value}, template.'],
			['POST', '/api/databases/{id}/entries/trash', 'Body: ids.'],
			['POST', '/api/databases/{id}/views', 'Body: type (table, board, calendar, gallery, list), config.'],
			['PATCH / DELETE', '/api/views/{id}', 'Body: name, type, config (filter, sorts, hidden, widths, group_by, date_prop, …).'],
			['POST', '/api/databases/{id}/property-order', 'Body: order [prop ids].']
		]],
		['Search, links, templates, graph', '', [
			['GET', '/api/search?q=&kind=', 'Full-text search; kind: doc, block, tag, card, task. Matches are wrapped in \\u0001…\\u0002.'],
			['GET', '/api/suggest?q=&kinds=doc,tag,block', 'Autocomplete.'],
			['GET / POST', '/api/templates', 'List, or create {title, template_tag, template_db} or {from: page id}.'],
			['PATCH / DELETE', '/api/templates/{id}', 'Bind to a tag or database.'],
			['GET', '/api/graph', 'Nodes (pages, tags, referenced blocks) and edges (child, ref, tag, relation).']
		]],
		['Flashcards', '', [
			['GET', '/api/cards/queue?tzo=&deck=&doc=&tag=', 'Next card to review, with the interval each rating would give. tzo = minutes from UTC (JavaScript getTimezoneOffset).'],
			['POST', '/api/cards/{id}/review', 'Body: rating (1 again … 4 easy), duration_ms.'],
			['POST', '/api/cards/undo', 'Undo the latest review.'],
			['GET', '/api/cards/stats?tzo=', 'Due, new, accuracy, forecast and history.'],
			['GET', '/api/cards?q=&deck=&state=&block=', 'Browse cards.'],
			['POST', '/api/cards/bulk', 'Body: ids, action (suspend, unsuspend, reset, deck, delete).'],
			['POST', '/api/notes', 'Create a card note {kind: basic | cloze | concept | occlusion, front, back, image, regions, deck}.'],
			['GET / PATCH / DELETE', '/api/notes/{id}', ''],
			['GET / POST', '/api/decks', ''],
			['PATCH / DELETE', '/api/decks/{id}', '']
		]],
		['Tasks', '', [
			['GET', '/api/tasks?view=&today=&tag=&project=&priority=&q=&sort=', 'view: inbox, today, upcoming, open, completed.'],
			['POST', '/api/tasks', 'Body: title, description, due, start, priority (0–3), recurrence {freq: day | week | month | year, interval}, project, document, tags — or block (turns a checklist block into a task).'],
			['GET / PATCH / DELETE', '/api/tasks/{id}', 'PATCH done: true completes it (recurring tasks move to their next date).'],
			['GET', '/api/tasks/summary?today=', 'Counts for the dashboard.']
		]],
		['Files, history, import and export', '', [
			['POST', '/api/files', 'Upload (multipart field file). Returns url.'],
			['GET', '/api/library?q=&type=', 'All files with where each is used.'],
			['PATCH / DELETE', '/api/library/{id}', ''],
			['GET / POST', '/api/documents/{id}/versions', 'List versions, or save one now.'],
			['GET', '/api/versions/{id}', 'A version with its blocks.'],
			['POST', '/api/versions/{id}/restore', 'Restore (the current state is saved first).'],
			['GET', '/api/export/document/{id}?as=md|html|json|opml|print&children=1', 'Export a page (zip when it has sub-pages or attachments).'],
			['GET', '/api/export/database/{id}?as=csv|json', ''],
			['GET', '/api/export/cards?as=csv|apkg&deck=', ''],
			['GET', '/api/export/workspace?as=md|html|json', ''],
			['POST', '/api/import', 'Multipart: files (repeat), paths (relative paths for folders), parent. Markdown, HTML, OPML, CSV, Kern JSON, .apkg, .zip.']
		]],
		['Backups and settings', '', [
			['GET / POST', '/api/backups', 'List, or create a backup now.'],
			['GET / DELETE', '/api/backups/{name}', 'Download or delete.'],
			['POST', '/api/backups/{name}/restore', 'Replace the workspace with a backup (a safety backup is made first).'],
			['POST', '/api/backups/upload-restore', 'Restore from an uploaded backup (multipart field file).'],
			['GET', '/api/storage', 'Sizes and counts.'],
			['GET / PATCH', '/api/settings', 'Key/value settings: prefs, flashcards, data.']
		]]
	];
</script>

<div class="page-scroll">
	<div class="page">
		<h1>API</h1>
		<p class="lede">Everything the app does goes through this JSON API, so you can script your workspace. There is no login; requests that change data must send the header <code>X-Kern: 1</code> (this blocks other websites from writing to it).</p>
		<pre>{example}</pre>
		{#each groups as [name, intro, rows] (name)}
			<h2>{name}</h2>
			{#if intro}<p class="muted">{intro}</p>{/if}
			<div class="table">
				{#each rows as [m, path, desc] (m + path)}
					<div class="row"><span class="m">{m}</span><code>{path}</code><span class="d">{desc}</span></div>
				{/each}
			</div>
		{/each}
		<p class="faint small">Block html is a small inline subset (b, i, u, s, code, mark, span, a). Links are <code>&lt;a data-ref="doc:ID"&gt;</code>, <code>block:ID</code> or <code>tag:ID</code>; the server keeps backlinks, search and flashcards in step whenever blocks are saved.</p>
	</div>
</div>

<style>
	h2 { font-size: 16px; margin: 26px 0 6px; }
	pre { padding: 10px 12px; border-radius: var(--radius); background: var(--surface); font: 12.5px var(--font-mono); overflow-x: auto; }
	code { font-family: var(--font-mono); font-size: 12.5px; }
	p code { background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
	.table { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.row { display: grid; grid-template-columns: 130px minmax(0, 1.3fr) minmax(0, 2fr); gap: 12px; padding: 7px 12px; border-top: 1px solid var(--border); align-items: baseline; }
	.row:first-child { border-top: 0; }
	.m { font: 600 11px var(--font-mono); color: var(--accent); }
	.row code { overflow-wrap: anywhere; }
	.d { color: var(--text-2); font-size: 13px; }
	.small { margin-top: 20px; font-size: 12.5px; }
	@media (max-width: 760px) { .row { grid-template-columns: 1fr; gap: 2px; } }
</style>
