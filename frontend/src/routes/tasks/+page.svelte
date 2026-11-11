<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { CalendarDays, CheckCheck, Inbox, ListTodo, Plus, Search, Sun } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api, qs } from '#lib/api.ts';
	import { counts, fmtDue, fmtRecurrence, localDate, PRIORITY } from '#lib/learn/util.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { parseTask } from '#lib/tasks/parse.ts';
	import TaskDetail from '#lib/tasks/TaskDetail.svelte';
	import TaskRow from '#lib/tasks/TaskRow.svelte';
	import type { Task } from '#lib/types.ts';

	type View = 'inbox' | 'today' | 'upcoming' | 'completed' | 'open';
	const views: [View, string, any][] = [
		['inbox', 'Inbox', Inbox], ['today', 'Today', Sun], ['upcoming', 'Upcoming', CalendarDays],
		['open', 'All open', ListTodo], ['completed', 'Completed', CheckCheck]
	];

	let view = $derived((page.url.searchParams.get('view') as View) || 'today');
	let selectedId = $derived(page.url.searchParams.get('task'));
	let list = $state<Task[]>([]);
	let loaded = $state(false);
	let summary = $state<Record<string, number>>({});
	let draft = $state('');
	let tag = $state('');
	let project = $state('');
	let priority = $state('');
	let sort = $state('');
	let query = $state('');
	let input = $state<HTMLInputElement>();
	let extra = $state<Task | null>(null); // selected task outside the current list

	let parsed = $derived(draft.trim() ? parseTask(draft) : null);
	let selected = $derived(list.find((t) => t.id === selectedId) ?? (extra?.id === selectedId ? extra : null));
	let today = localDate();

	async function load() {
		try {
			const [l, s] = await Promise.all([
				api.get<Task[]>('/tasks' + qs({ view, today, tag, project, priority, sort, q: query.trim() })),
				api.get<Record<string, number>>(`/tasks/summary?today=${today}`)
			]);
			list = l;
			summary = s;
			loaded = true;
		} catch (e) {
			ui.error(e);
		}
	}

	$effect(() => {
		void view; void tag; void project; void priority; void sort; void query;
		const t = setTimeout(load, 120);
		return () => clearTimeout(t);
	});

	$effect(() => {
		const id = selectedId;
		if (id && !list.some((t) => t.id === id) && loaded)
			api.get<Task>(`/tasks/${id}`).then((t) => (extra = t)).catch(() => goto(`/tasks?view=${view}`));
	});

	onMount(() => {
		const k = (e: KeyboardEvent) => {
			if (e.key === 'q' && !(e.target as HTMLElement).closest('input, textarea, [contenteditable], select')) {
				e.preventDefault();
				input?.focus();
			}
		};
		addEventListener('keydown', k);
		return () => removeEventListener('keydown', k);
	});

	function setView(v: View) {
		goto(`/tasks?view=${v}`, { replace: true });
	}

	function select(id: string | null) {
		const u = new URL(page.url.href);
		if (id) u.searchParams.set('task', id);
		else u.searchParams.delete('task');
		goto(u.pathname + u.search, { replace: true });
	}

	let adding = false;
	async function add() {
		const p = parsed;
		if (!p || !p.title || adding) return;
		adding = true;
		const typed = draft;
		draft = '';
		try {
			const tags: string[] = [];
			for (const name of p.tags) {
				const t = ws.tags.find((x) => x.name.toLowerCase() === name.toLowerCase()) ?? (await ws.createTag(name));
				tags.push(t.id);
			}
			const body: Record<string, any> = { title: p.title, due: p.due, priority: p.priority, recurrence: p.recurrence, tags };
			if (!p.due && view === 'today') body.due = today;
			if (project) body.project = project;
			if (tag && !tags.includes(tag)) body.tags = [...tags, tag];
			await api.post('/tasks', body);
			counts.refresh();
			load();
		} catch (e) {
			if (!draft) draft = typed;
			ui.error(e);
		} finally {
			adding = false;
		}
	}

	async function patch(t: Task, p: Partial<Task>) {
		Object.assign(t, p);
		try {
			const saved = await api.patch<Task>(`/tasks/${t.id}`, { ...p, today });
			Object.assign(t, saved);
		} catch (e) {
			ui.error(e);
		}
		counts.refresh();
		load();
	}

	async function toggle(t: Task) {
		const was = t.done;
		await patch(t, { done: !t.done });
		if (!was) {
			ui.toast(t.recurrence ? `Next: ${fmtDue(t.due)}` : `Completed “${t.title || 'Untitled task'}”`, {
				action: t.recurrence ? undefined : { label: 'Undo', run: () => patch(t, { done: false }) }
			});
		}
	}

	async function remove(t: Task) {
		const ok = await ui.confirm({
			title: `Delete “${t.title || 'Untitled task'}”?`,
			message: t.block ? 'The checklist item in the page stays; it just stops being a task.' : 'This cannot be undone.',
			confirmLabel: 'Delete task', danger: true
		});
		if (!ok) return;
		await api.del(`/tasks/${t.id}`).catch((e) => ui.error(e));
		select(null);
		counts.refresh();
		load();
	}

	interface Group { key: string; label: string; tasks: Task[]; tone?: string }
	let groups = $derived.by((): Group[] => {
		if (view === 'today') {
			const over = list.filter((t) => t.due && t.due < today);
			const now = list.filter((t) => t.due === today);
			return [
				...(over.length ? [{ key: 'over', label: `Overdue · ${over.length}`, tasks: over, tone: 'danger' }] : []),
				{ key: 'today', label: `Today · ${now.length}`, tasks: now }
			];
		}
		if (view === 'upcoming' && !sort) {
			const map = new Map<string, Task[]>();
			for (const t of list) map.set(t.due!, [...(map.get(t.due!) ?? []), t]);
			return [...map.entries()].map(([d, tasks]) => ({ key: d, label: fmtDue(d, today), tasks }));
		}
		return [{ key: 'all', label: '', tasks: list }];
	});

	const tiles: [string, string, View][] = [['overdue', 'Overdue', 'today'], ['today', 'Due today', 'today'], ['upcoming', 'Next 7 days', 'upcoming'], ['inbox', 'Inbox', 'inbox'], ['completed_week', 'Done this week', 'completed']];
	let projects = $derived([...new Set(Object.values(ws.docs).map((d) => d.id))].map((id) => ws.docs[id]).sort((a, b) => (a.title || '').localeCompare(b.title || '')));
</script>

<div class="wrap">
	<div class="main">
		<div class="page-scroll">
			<div class="page">
				<h1>Tasks</h1>
				<div class="tiles">
					{#each tiles as [k, label, v] (k)}
						<button class="tile" class:danger={k === 'overdue' && summary[k]} onclick={() => setView(v)}><b>{summary[k] ?? 0}</b><span>{label}</span></button>
					{/each}
				</div>

				<div class="views">
					{#each views as [v, label, Icon] (v)}
						<button class:on={view === v} onclick={() => setView(v)}><Icon size={14} />{label}</button>
					{/each}
				</div>

				{#if view !== 'completed'}
					<form class="add" onsubmit={(e) => { e.preventDefault(); add(); }}>
						<Plus size={16} class="faint" />
						<input bind:this={input} bind:value={draft} placeholder="Add a task — try “Call Sam tomorrow !2 #work every week”" />
						{#if parsed && parsed.tokens.length}
							<span class="tokens">
								{#if parsed.due}<span class="chip">{fmtDue(parsed.due, today)}</span>{/if}
								{#if parsed.recurrence}<span class="chip">{fmtRecurrence(parsed.recurrence)}</span>{/if}
								{#if parsed.priority}<span class="chip" data-c={['', 'blue', 'orange', 'red'][parsed.priority]}>{PRIORITY[parsed.priority]}</span>{/if}
								{#each parsed.tags as t (t)}<span class="chip">#{t}</span>{/each}
							</span>
						{/if}
						<kbd>Q</kbd>
					</form>
				{/if}

				<div class="filters">
					<div class="search"><Search size={13} class="faint" /><input bind:value={query} placeholder="Search tasks" /></div>
					<select class="input" bind:value={tag}><option value="">Any tag</option>{#each ws.tags as t (t.id)}<option value={t.id}>#{t.name}</option>{/each}</select>
					<select class="input" bind:value={project}><option value="">Any project</option>{#each projects as d (d.id)}<option value={d.id}>{d.title || 'Untitled'}</option>{/each}</select>
					<select class="input" bind:value={priority}><option value="">Any priority</option><option value="1">Low or higher</option><option value="2">Medium or higher</option><option value="3">High</option></select>
					<select class="input" bind:value={sort}><option value="">Sort: default</option><option value="due">Due date</option><option value="priority">Priority</option><option value="created">Newest</option><option value="title">Name</option></select>
				</div>

				{#each groups as g (g.key)}
					{#if g.label}<div class="section-title" class:danger-text={g.tone === 'danger'}>{g.label}</div>{/if}
					<div class="list">
						{#each g.tasks as t (t.id)}
							<TaskRow task={t} active={t.id === selectedId} onselect={() => select(t.id)} ontoggle={() => toggle(t)} />
						{/each}
					</div>
				{/each}
				{#if loaded && !list.length}
					<div class="empty">
						{#if view === 'inbox'}<b>Inbox zero</b>Tasks without a date, project or page land here.
						{:else if view === 'today'}<b>Nothing due today</b>Add a task above, or tick off something from Upcoming.
						{:else if view === 'upcoming'}<b>Nothing scheduled</b>Give tasks a due date to see them here.
						{:else if view === 'completed'}<b>No completed tasks yet</b>
						{:else}<b>No open tasks</b>{/if}
					</div>
				{/if}
				<p class="hint faint">Checklist items in pages become tasks from their block menu (“Make task”), and stay in sync both ways.</p>
			</div>
		</div>
	</div>
	{#if selected}
		{#key selected.id}
			<TaskDetail task={selected} onchange={(p) => patch(selected!, p)} onclose={() => select(null)} ondelete={() => remove(selected!)} />
		{/key}
	{/if}
</div>

<style>
	.wrap { position: relative; display: flex; height: 100%; }
	.main { flex: 1; min-width: 0; }
	.tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin: 10px 0 16px; }
	.tile { display: flex; flex-direction: column; align-items: flex-start; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; text-align: left; }
	.tile:hover { background: var(--hover); }
	.tile b { font-size: 21px; font-weight: 650; font-variant-numeric: tabular-nums; }
	.tile span { font-size: 12px; color: var(--text-3); }
	.tile.danger b { color: var(--danger); }
	.views { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 10px; overflow-x: auto; }
	.views button { display: flex; align-items: center; gap: 6px; padding: 7px 10px; color: var(--text-3); border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
	.views button:hover { color: var(--text-2); }
	.views button.on { color: var(--text); border-bottom-color: var(--accent); }
	.add { display: flex; align-items: center; gap: 8px; height: 38px; padding: 0 10px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); }
	.add:focus-within { border-color: color-mix(in srgb, var(--accent) 60%, var(--border-strong)); }
	.add input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font-size: 14px; }
	.tokens { display: flex; gap: 4px; }
	.filters { display: flex; gap: 6px; margin: 10px 0 4px; flex-wrap: wrap; }
	.filters .input { width: auto; }
	.search { display: flex; align-items: center; gap: 5px; height: 28px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); flex: 1; min-width: 140px; }
	.search input { flex: 1; border: 0; outline: 0; background: none; }
	.list { border-top: 1px solid var(--border); }
	.danger-text { color: var(--danger); }
	.hint { margin-top: 24px; font-size: 12px; }
	@media (max-width: 760px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); } .add kbd, .tokens { display: none; } }
</style>
