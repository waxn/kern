<script lang="ts">
	import { FileText, Layers, Plus, Search } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { counts, localDate, tzo } from '#lib/learn/util.svelte.ts';
	import TaskRow from '#lib/tasks/TaskRow.svelte';
	import type { CardStats, Task } from '#lib/types.ts';
	import { newPage } from '#lib/actions.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Doc } from '#lib/types.ts';
	import { modKey, relTime } from '#lib/util.ts';

	let edited = $derived(
		Object.values(ws.docs).filter((d) => !d.is_archived).sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1)).slice(0, 14)
	);
	let total = $derived(Object.keys(ws.docs).length);
	let tasks = $state<Task[]>([]);
	let cards = $state<CardStats | null>(null);

	async function loadToday() {
		try {
			[tasks, cards] = await Promise.all([
				api.get<Task[]>(`/tasks?view=today&today=${localDate()}`),
				api.get<CardStats>(`/cards/stats?tzo=${tzo()}`)
			]);
		} catch {
			/* offline */
		}
	}
	onMount(loadToday);

	async function toggle(t: Task) {
		await api.patch(`/tasks/${t.id}`, { done: !t.done, today: localDate() }).catch(() => {});
		counts.refresh();
		loadToday();
	}
</script>

{#snippet row(d: Doc, time: string | null)}
	<a class="row" href="/doc/{d.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${d.id}`, e); }}>
		<span class="ico">{#if d.icon}{d.icon}{:else}<FileText size={15} strokeWidth={1.75} />{/if}</span>
		<span class="title truncate" class:faint={!d.title}>{d.title || 'Untitled'}</span>
		<span class="path truncate">{ws.path(d.id).map((p) => p.title || 'Untitled').join(' / ')}</span>
		<span class="time">{relTime(time)}</span>
	</a>
{/snippet}

<div class="page-scroll">
	<div class="page">
		<h1>Home</h1>
		<p class="lede">{total} {total === 1 ? 'page' : 'pages'} · {ws.tags.length} {ws.tags.length === 1 ? 'tag' : 'tags'}</p>
		<div class="actions">
			<button class="btn primary" onclick={() => newPage()}><Plus size={15} />New page</button>
			<button class="btn" onclick={() => ui.openSearch()}><Search size={14} />Search <kbd>{modKey} K</kbd></button>
		</div>

		{#if tasks.length || (cards && cards.due_today + cards.new_available)}
			<div class="today">
				<section>
					<div class="section-title">Today · {tasks.length} {tasks.length === 1 ? 'task' : 'tasks'}</div>
					{#if tasks.length}
						<div class="tasks">{#each tasks.slice(0, 8) as t (t.id)}<TaskRow task={t} onselect={() => goto(`/tasks?view=today&task=${t.id}`)} ontoggle={() => toggle(t)} />{/each}</div>
						{#if tasks.length > 8}<a class="more" href="/tasks?view=today">All {tasks.length} tasks →</a>{/if}
					{:else}<p class="faint">Nothing due today.</p>{/if}
				</section>
				{#if cards}
					<section class="study">
						<div class="section-title">Flashcards</div>
						<div class="studybox">
							<Layers size={18} />
							<div><b>{cards.due_today} due · {cards.new_available} new</b><span class="faint">{cards.reviewed_today} reviewed today</span></div>
							<button class="btn primary" disabled={!cards.due_today && !cards.new_available} onclick={() => goto('/review')}>Study</button>
						</div>
					</section>
				{/if}
			</div>
		{/if}

		{#if ws.loaded && total === 0}
			<div class="empty" style="margin-top:28px">
				<b>Your workspace is empty</b>
				Create a page to start writing. Type <kbd>/</kbd> in a page for blocks and <kbd>[[</kbd> to link pages together.
			</div>
		{:else}
			{#if ws.favorites.length}
				<div class="section-title">Favorites</div>
				<div class="list">{#each ws.favorites as d (d.id)}{@render row(d, d.updated_at)}{/each}</div>
			{/if}
			<div class="section-title">Recently edited</div>
			<div class="list">{#each edited as d (d.id)}{@render row(d, d.updated_at)}{/each}</div>
		{/if}
	</div>
</div>

<style>
	.actions { display: flex; gap: 8px; }
	.today { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 24px; }
	.tasks { border-top: 1px solid var(--border); }
	.more { display: block; margin-top: 6px; font-size: 12.5px; color: var(--text-3); text-decoration: none; }
	.studybox { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; color: var(--c-purple); }
	.studybox div { flex: 1; display: flex; flex-direction: column; color: var(--text); }
	.studybox span { font-size: 12px; }
	@media (max-width: 760px) { .today { grid-template-columns: 1fr; } }
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.row { display: grid; grid-template-columns: 22px minmax(0, 1.2fr) minmax(0, 1fr) auto; align-items: center; gap: 8px; height: 34px; padding: 0 12px; text-decoration: none; border-top: 1px solid var(--border); }
	.row:first-child { border-top: 0; }
	.row:hover { background: var(--hover); }
	.ico { display: grid; place-items: center; color: var(--text-2); }
	.path, .time { color: var(--text-3); font-size: 12.5px; }
	.time { text-align: right; white-space: nowrap; }
	@media (max-width: 760px) { .row { grid-template-columns: 22px 1fr auto; } .path { display: none; } }
</style>
