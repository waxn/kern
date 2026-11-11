<script lang="ts">
	import { Calendar, CalendarClock, Check, CircleCheck, Database, FilePlus, Kanban, RefreshCw } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { newPage } from '#lib/actions.ts';
	import { api } from '#lib/api.ts';
	import DatabaseView from '#lib/db/DatabaseView.svelte';
	import { counts } from '#lib/learn/util.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { parseTask } from '#lib/tasks/parse.ts';
	import type { DbPayload, Task } from '#lib/types.ts';
	import TreeNode from './TreeNode.svelte';

	let { id }: { id: string } = $props();

	interface Agenda {
		tasks: Task[];
		events: { id: string; title: string; icon: string; date: string; database: string; database_title: string; property: string }[];
	}

	let children = $derived(ws.children(id));
	let notes = $derived(children.filter((d) => !d.database));
	let dbs = $derived(children.filter((d) => d.database));
	let agenda = $state<Agenda | null>(null);
	let taskDraft = $state('');
	let adding = $state(false);

	async function loadAgenda() {
		try {
			agenda = await api.get<Agenda>(`/documents/${id}/agenda?days=30`);
		} catch {
			/* offline */
		}
	}
	onMount(() => {
		loadAgenda();
		const onFocus = () => loadAgenda();
		addEventListener('focus', onFocus);
		return () => removeEventListener('focus', onFocus);
	});

	async function newDb(preset?: 'kanban' | 'calendar') {
		try {
			await api.post<DbPayload>('/databases', { title: '', parent: id, preset });
			await ws.load();
			loadAgenda();
		} catch (e) {
			ui.error(e);
		}
	}

	async function addNote() {
		const doc = await newPage(id, false);
		if (doc) prefs.expanded[id] = true;
	}

	async function addTask() {
		const p = parseTask(taskDraft);
		if (!p.title || adding) return;
		adding = true;
		try {
			const tags: string[] = [];
			for (const name of p.tags) {
				const t = ws.tags.find((x) => x.name.toLowerCase() === name.toLowerCase()) ?? (await ws.createTag(name));
				tags.push(t.id);
			}
			await api.post('/tasks', { title: p.title, due: p.due, priority: p.priority, recurrence: p.recurrence, tags, project: id });
			taskDraft = '';
			counts.refresh();
			loadAgenda();
		} catch (e) {
			ui.error(e);
		} finally {
			adding = false;
		}
	}

	async function complete(t: Task) {
		try {
			await api.patch(`/tasks/${t.id}`, { done: true });
			counts.refresh();
			loadAgenda();
		} catch (e) {
			ui.error(e);
		}
	}

	type Item = { key: string; date: string; title: string; icon: string; sub: string; kind: 'task' | 'event'; task?: Task; href: string; priority?: number };
	let items = $derived.by<Item[]>(() => {
		if (!agenda) return [];
		const list: Item[] = [
			...agenda.tasks.map((t) => ({
				key: 't' + t.id, date: t.due!, title: t.title, icon: '', sub: 'Task', kind: 'task' as const, task: t,
				href: `/tasks?task=${t.id}`, priority: t.priority
			})),
			...agenda.events.map((e) => ({
				key: 'e' + e.id + e.property, date: e.date.slice(0, 10), title: e.title || 'Untitled', icon: e.icon,
				sub: e.database_title || 'Calendar', kind: 'event' as const, href: `/doc/${e.id}`
			}))
		];
		return list.sort((a, b) => a.date.localeCompare(b.date));
	});

	const todayIso = () => {
		const d = new Date();
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	};

	function dayLabel(iso: string) {
		const today = todayIso();
		const d = new Date(iso + 'T00:00:00');
		const diff = Math.round((d.getTime() - new Date(today + 'T00:00:00').getTime()) / 86400000);
		if (diff < 0) return 'Overdue';
		if (diff === 0) return 'Today';
		if (diff === 1) return 'Tomorrow';
		if (diff < 7) return d.toLocaleDateString(undefined, { weekday: 'long' });
		return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
	}

	let grouped = $derived.by(() => {
		const out: { label: string; items: Item[] }[] = [];
		for (const it of items) {
			const label = dayLabel(it.date);
			const last = out[out.length - 1];
			if (last?.label === label) last.items.push(it);
			else out.push({ label, items: [it] });
		}
		return out;
	});

	let stats = $derived([
		`${notes.length} ${notes.length === 1 ? 'note' : 'notes'}`,
		`${dbs.length} ${dbs.length === 1 ? 'collection' : 'collections'}`,
		...(agenda ? [`${items.length} upcoming`] : [])
	]);
</script>

<div class="group">
	<p class="stats faint">{stats.join(' · ')}</p>

	<div class="create">
		<button class="tile" onclick={addNote}><FilePlus size={16} /><span>Note</span></button>
		<button class="tile" onclick={() => newDb('calendar')}><Calendar size={16} /><span>Calendar</span></button>
		<button class="tile" onclick={() => newDb('kanban')}><Kanban size={16} /><span>Board</span></button>
		<button class="tile" onclick={() => newDb()}><Database size={16} /><span>Database</span></button>
	</div>

	<div class="grid">
		<div class="col main">
			{#each dbs as d (d.id)}
				<section class="card db">
					<DatabaseView dbId={d.database!} inline />
				</section>
			{:else}
				<section class="card blank">
					<CalendarClock size={22} strokeWidth={1.5} />
					<div>
						<b>Plan this group</b>
						<p class="muted">Add a calendar for deadlines and classes (month and week views), a board for assignments, or a database for anything else. They live here, inside the group.</p>
						<div class="row">
							<button class="btn" onclick={() => newDb('calendar')}><Calendar size={14} />Add a calendar</button>
							<button class="btn ghost" onclick={() => newDb('kanban')}><Kanban size={14} />Add a board</button>
						</div>
					</div>
				</section>
			{/each}
		</div>

		<aside class="col side">
			<section class="card">
				<header class="ch">
					<span>Upcoming</span>
					<button class="icon-btn" title="Refresh" onclick={loadAgenda}><RefreshCw size={13} /></button>
				</header>
				<form class="quick" onsubmit={(e) => { e.preventDefault(); addTask(); }}>
					<CircleCheck size={14} class="faint" />
					<input class="bare" placeholder="Add a task… (e.g. Lab report friday !2)" bind:value={taskDraft} disabled={adding} />
				</form>
				{#if !agenda}
					<p class="faint pad">Loading…</p>
				{:else if !items.length}
					<p class="faint pad">Nothing due in the next 30 days. Dated tasks and calendar entries in this group show up here.</p>
				{:else}
					<div class="agenda">
						{#each grouped as g (g.label)}
							<div class="day" class:overdue={g.label === 'Overdue'}>{g.label}</div>
							{#each g.items as it (it.key)}
								<div class="item">
									{#if it.kind === 'task'}
										<button class="check" class:p1={it.priority === 3} class:p2={it.priority === 2} title="Complete" onclick={() => complete(it.task!)}><Check size={10} strokeWidth={3} /></button>
									{:else}
										<span class="dot"></span>
									{/if}
									<a class="it-title truncate" href={it.href} onclick={(e) => { e.preventDefault(); open(it.href, e); }}>{it.icon ? it.icon + ' ' : ''}{it.title}</a>
									<span class="it-sub faint truncate">{it.sub}{g.label === 'Overdue' ? ' · ' + it.date.slice(5) : ''}</span>
								</div>
							{/each}
						{/each}
					</div>
				{/if}
			</section>

			<section class="card">
				<header class="ch">
					<span>Notes</span>
					<button class="icon-btn" title="New note" onclick={addNote}><FilePlus size={13} /></button>
				</header>
				{#if notes.length}
					<div class="tree">{#each notes as d (d.id)}<TreeNode doc={d} />{/each}</div>
				{:else}
					<button class="faint pad hint" onclick={addNote}>No notes yet. Write the first one…</button>
				{/if}
			</section>
		</aside>
	</div>

	<div class="section-title overview">Overview</div>
</div>

<style>
	.group { margin-bottom: 4px; }
	.stats { margin: 2px 0 18px; font-size: 13px; }
	.create { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
	.tile { display: inline-flex; align-items: center; gap: 8px; height: 36px; padding: 0 14px 0 12px; border-radius: 10px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); font-weight: 520;
		transition: border-color .15s var(--ease), color .15s var(--ease), background .15s var(--ease); }
	.tile:hover { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, var(--border-strong)); background: color-mix(in srgb, var(--accent) 7%, var(--surface)); }
	.tile :global(svg) { color: var(--accent); }

	.grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
	.col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
	.card { border: 1px solid var(--border); border-radius: 12px; background: color-mix(in srgb, var(--surface) 55%, transparent); padding: 10px 12px; min-width: 0; }
	.card.db { padding: 4px 14px 6px; }
	.card.db :global(.dbv.inline) { margin: 6px 0 4px; }
	.card.blank { display: flex; gap: 14px; padding: 18px; color: var(--text-2); border-style: dashed; }
	.card.blank b { display: block; color: var(--text); margin-bottom: 2px; }
	.card.blank p { margin: 0 0 12px; line-height: 1.5; }
	.row { display: flex; gap: 6px; flex-wrap: wrap; }
	.ch { display: flex; align-items: center; justify-content: space-between; margin: 0 -4px 6px 0; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); }
	.ch .icon-btn { width: 22px; height: 22px; }
	.pad { margin: 4px 0; font-size: 13px; line-height: 1.5; }
	.hint { text-align: left; }
	.hint:hover { color: var(--text-2); }
	.quick { display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 8px; margin-bottom: 8px; border-radius: 8px; background: var(--hover); }
	.bare { flex: 1; min-width: 0; border: 0; outline: none; background: none; color: var(--text); font: inherit; font-size: 13px; }
	.agenda { display: flex; flex-direction: column; }
	.day { margin: 8px 0 2px; font-size: 12px; font-weight: 600; color: var(--text-2); }
	.day:first-child { margin-top: 0; }
	.day.overdue { color: var(--danger); }
	.item { display: grid; grid-template-columns: 16px minmax(0, 1fr); column-gap: 8px; align-items: center; padding: 3px 0; }
	.it-title { color: var(--text); text-decoration: none; font-size: 13.5px; }
	.it-title:hover { text-decoration: underline; text-decoration-color: var(--text-3); }
	.it-sub { grid-column: 2; font-size: 11.5px; }
	.check { display: grid; place-items: center; width: 15px; height: 15px; border-radius: 50%; border: 1.5px solid var(--text-3); color: transparent; }
	.check:hover { border-color: var(--c-green); color: var(--c-green); }
	.check.p1 { border-color: var(--c-red); }
	.check.p2 { border-color: var(--c-orange); }
	.dot { justify-self: center; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
	.tree { margin: 0 -6px; }
	.overview { margin-top: 28px; }

	@media (max-width: 1100px) {
		.grid { grid-template-columns: minmax(0, 1fr); }
		.side { order: -1; }
	}
</style>
