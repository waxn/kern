<script lang="ts">
	import { ArrowUpRight, Trash2, X } from '@lucide/svelte';
	import { api } from '../api.ts';
	import { fmtRecurrence, PRIORITY } from '../learn/util.svelte.ts';
	import { open } from '../state/tabs.ts';
	import { ui } from '../state/ui.svelte.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { Recurrence, Task } from '../types.ts';

	let { task, onchange, onclose, ondelete }: { task: Task; onchange: (patch: Partial<Task>) => void; onclose: () => void; ondelete: () => void } = $props();

	let tagFilter = $state('');
	let docs = $derived(Object.values(ws.docs).sort((a, b) => (a.title || '').localeCompare(b.title || '')));
	let freq = $derived(task.recurrence?.freq ?? '');

	function setRecurrence(f: string, interval = task.recurrence?.interval ?? 1) {
		onchange({ recurrence: f ? ({ freq: f, interval } as Recurrence) : null });
	}

	async function addTag(name: string) {
		const n = name.trim().replace(/^#/, '');
		if (!n) return;
		try {
			const t = ws.tags.find((x) => x.name.toLowerCase() === n.toLowerCase()) ?? (await ws.createTag(n));
			if (!task.tags.includes(t.id)) onchange({ tags: [...task.tags, t.id] });
			tagFilter = '';
		} catch (e) {
			ui.error(e);
		}
	}
</script>

<aside class="detail">
	<div class="head">
		<span class="faint">Task</span>
		<span class="grow"></span>
		<button class="icon-btn" title="Delete task" onclick={ondelete}><Trash2 size={14} /></button>
		<button class="icon-btn" title="Close" onclick={onclose}><X size={15} /></button>
	</div>
	<textarea class="title" rows="1" value={task.title} placeholder="Task name" disabled={!!task.block && false}
		onchange={(e) => onchange({ title: e.currentTarget.value.replace(/\n/g, ' ') })}
		onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur(); } }}></textarea>
	{#if task.block && task.document}
		<a class="src" href="/doc/{task.document}#{task.block}" onclick={(e) => { e.preventDefault(); open(`/doc/${task.document}#${task.block}`, e); }}>
			Checklist item in {ws.docs[task.document]?.title || 'Untitled'} <ArrowUpRight size={12} />
		</a>
	{/if}

	<div class="grid">
		<label for="t-due">Due</label>
		<span class="pair"><input id="t-due" class="input" type="date" value={task.due ?? ''} onchange={(e) => onchange({ due: e.currentTarget.value || null })} />
			{#if task.due}<button class="icon-btn" title="Clear" onclick={() => onchange({ due: null })}><X size={12} /></button>{/if}</span>
		<label for="t-start">Start</label>
		<span class="pair"><input id="t-start" class="input" type="date" value={task.start ?? ''} onchange={(e) => onchange({ start: e.currentTarget.value || null })} />
			{#if task.start}<button class="icon-btn" title="Clear" onclick={() => onchange({ start: null })}><X size={12} /></button>{/if}</span>
		<label for="t-rep">Repeat</label>
		<span class="pair">
			<select id="t-rep" class="input" value={freq} onchange={(e) => setRecurrence(e.currentTarget.value)}>
				<option value="">Never</option><option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option><option value="year">Yearly</option>
			</select>
			{#if task.recurrence}
				<input class="input n" type="number" min="1" max="365" value={task.recurrence.interval} title="Every N"
					onchange={(e) => setRecurrence(freq, Math.max(1, Number(e.currentTarget.value) || 1))} />
			{/if}
		</span>
		{#if task.recurrence}<span></span><span class="faint small">{fmtRecurrence(task.recurrence)} · completing moves it to the next date</span>{/if}
		<label for="t-prio">Priority</label>
		<select id="t-prio" class="input" value={task.priority} onchange={(e) => onchange({ priority: Number(e.currentTarget.value) })}>
			{#each PRIORITY as p, i (i)}<option value={i}>{p}</option>{/each}
		</select>
		<label for="t-proj">Project</label>
		<select id="t-proj" class="input" value={task.project ?? ''} onchange={(e) => onchange({ project: e.currentTarget.value || null })}>
			<option value="">None</option>
			{#each docs as d (d.id)}<option value={d.id}>{d.icon} {d.title || 'Untitled'}</option>{/each}
		</select>
		{#if !task.block}
			<label for="t-doc">Page</label>
			<span class="pair">
				<select id="t-doc" class="input" value={task.document ?? ''} onchange={(e) => onchange({ document: e.currentTarget.value || null })}>
					<option value="">None</option>
					{#each docs as d (d.id)}<option value={d.id}>{d.icon} {d.title || 'Untitled'}{d.entry_of ? ' (entry)' : ''}</option>{/each}
				</select>
				{#if task.document}<a class="icon-btn" href="/doc/{task.document}" title="Open page" onclick={(e) => { e.preventDefault(); open(`/doc/${task.document}`, e); }}><ArrowUpRight size={13} /></a>{/if}
			</span>
			{#if task.document && ws.docs[task.document]?.entry_of}<span></span><span class="faint small">Completing the task marks this entry done.</span>{/if}
		{/if}
		<span class="lbl">Tags</span>
		<div class="tags">
			{#each task.tags as id (id)}
				{#if ws.tagMap[id]}
					<span class="chip" data-c={ws.tagMap[id].color || undefined}>#{ws.tagMap[id].name}
						<button title="Remove" onclick={() => onchange({ tags: task.tags.filter((t) => t !== id) })}><X size={10} /></button></span>
				{/if}
			{/each}
			<input class="input tagin" list="task-tags" bind:value={tagFilter} placeholder="Add tag…"
				onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(tagFilter); } }} onchange={(e) => addTag(e.currentTarget.value)} />
			<datalist id="task-tags">{#each ws.tags as t (t.id)}<option value={t.name}></option>{/each}</datalist>
		</div>
	</div>

	<div class="lbl">Notes</div>
	<textarea class="input desc" rows="6" value={task.description} placeholder="Details, links, sub-steps…"
		onchange={(e) => onchange({ description: e.currentTarget.value })}></textarea>
	<p class="faint small">Created {new Date(task.created_at).toLocaleString()}{#if task.completed_at} · last completed {new Date(task.completed_at).toLocaleString()}{/if}</p>
</aside>

<style>
	.detail { flex: none; width: 360px; display: flex; flex-direction: column; gap: 8px; padding: 10px 14px 20px; border-left: 1px solid var(--border); background: var(--bg-side); overflow-y: auto; }
	.head { display: flex; align-items: center; gap: 2px; }
	.grow { flex: 1; }
	.title { width: 100%; border: 0; outline: 0; background: none; resize: none; font-size: 17px; font-weight: 600; padding: 2px 0; field-sizing: content; }
	.src { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; color: var(--text-3); text-decoration: none; }
	.src:hover { color: var(--accent); }
	.grid { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 6px 10px; align-items: center; margin-top: 4px; }
	.grid label, .lbl { color: var(--text-3); font-size: 12.5px; }
	.pair { display: flex; align-items: center; gap: 4px; }
	.pair .input { flex: 1; min-width: 0; }
	.n { flex: none !important; width: 64px; }
	.tags { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
	.tags .chip button { display: grid; color: inherit; opacity: 0.6; }
	.tagin { width: 110px; }
	.desc { width: 100%; resize: vertical; font: inherit; }
	.small { font-size: 12px; margin: 0; }
	@media (max-width: 900px) { .detail { position: absolute; z-index: 40; right: 0; top: 0; bottom: 0; width: min(380px, 94vw); box-shadow: var(--shadow); } }
</style>
