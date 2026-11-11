<script lang="ts">
	import { Check, FileText, Flag, Repeat } from '@lucide/svelte';
	import { fmtDue, localDate, PRIORITY_COLOR } from '../learn/util.svelte.ts';
	import { open } from '../state/tabs.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { Task } from '../types.ts';

	let { task, active = false, onselect, ontoggle }: { task: Task; active?: boolean; onselect: () => void; ontoggle: () => void } = $props();
	let today = localDate();
	let overdue = $derived(!task.done && !!task.due && task.due < today);
	let where = $derived(task.project ?? task.document);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="task" class:active class:done={task.done} onclick={onselect}>
	<button class="box" data-c={PRIORITY_COLOR[task.priority] || undefined} role="checkbox" aria-checked={task.done}
		title={task.done ? 'Mark as not done' : task.recurrence ? 'Complete this occurrence' : 'Complete'}
		onclick={(e) => { e.stopPropagation(); ontoggle(); }}>
		{#if task.done}<Check size={11} strokeWidth={3.2} />{/if}
	</button>
	<div class="body">
		<span class="title" class:faint={!task.title}>{task.title || 'Untitled task'}</span>
		<div class="meta">
			{#if task.due}<span class:overdue>{fmtDue(task.due, today)}</span>{/if}
			{#if task.recurrence}<Repeat size={11} />{/if}
			{#if task.priority}<span class="prio" data-c={PRIORITY_COLOR[task.priority]}><Flag size={11} /></span>{/if}
			{#each task.tags as t (t)}{#if ws.tagMap[t]}<span class="chip" data-c={ws.tagMap[t].color || undefined}>#{ws.tagMap[t].name}</span>{/if}{/each}
			{#if where && ws.docs[where]}
				<a class="doc" href="/doc/{where}" onclick={(e) => { e.preventDefault(); e.stopPropagation(); open(`/doc/${where}${task.block && where === task.document ? '#' + task.block : ''}`, e); }}>
					<FileText size={11} />{ws.docs[where].title || 'Untitled'}
				</a>
			{/if}
			{#if task.description}<span class="faint truncate desc">{task.description.split('\n')[0]}</span>{/if}
		</div>
	</div>
</div>

<style>
	.task { display: flex; gap: 10px; padding: 7px 10px; border-bottom: 1px solid var(--border); cursor: pointer; }
	.task:hover { background: var(--hover); }
	.task.active { background: var(--active); }
	.box { flex: none; width: 16px; height: 16px; margin-top: 2px; display: grid; place-items: center; border: 1.5px solid var(--chip, var(--text-3)); border-radius: 50%; color: #17130c; transition: background 0.1s; }
	.box:hover { background: color-mix(in srgb, var(--chip, var(--accent)) 25%, transparent); }
	.box[aria-checked='true'] { background: var(--accent); border-color: var(--accent); }
	.body { flex: 1; min-width: 0; }
	.title { display: block; line-height: 1.4; overflow-wrap: anywhere; }
	.done .title { color: var(--text-3); text-decoration: line-through; }
	.meta { display: flex; align-items: center; gap: 8px; margin-top: 2px; font-size: 12px; color: var(--text-3); flex-wrap: wrap; }
	.meta:empty { display: none; }
	.overdue { color: var(--danger); }
	.prio { color: var(--chip); display: grid; }
	.doc { display: inline-flex; align-items: center; gap: 3px; text-decoration: none; color: var(--text-3); max-width: 200px; overflow: hidden; white-space: nowrap; }
	.doc:hover { color: var(--accent); }
	.desc { max-width: 260px; }
</style>
