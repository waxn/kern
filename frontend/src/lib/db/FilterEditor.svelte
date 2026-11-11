<script lang="ts">
	import { Plus, Trash2 } from '@lucide/svelte';
	import type { FilterGroup, FilterRule } from '../types.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import { opsFor, type Col } from './query.ts';
	import Self from './FilterEditor.svelte';

	let { group, cols, onchange, nested = false, onremove }: {
		group: FilterGroup; cols: Col[]; onchange: () => void; nested?: boolean; onremove?: () => void;
	} = $props();

	const colOf = (id: string) => cols.find((c) => c.id === id);
	const noValue = new Set(['empty', 'not_empty', 'past_week', 'next_week']);

	function addRule() {
		const c = cols[0];
		group.rules.push({ prop: c.id, op: opsFor(c.type)[0][0], value: c.type === 'boolean' ? true : '' });
		onchange();
	}

	function addGroup() {
		group.rules.push({ op: group.op === 'and' ? 'or' : 'and', rules: [] });
		onchange();
	}

	function setProp(rule: FilterRule, id: string) {
		const c = colOf(id)!;
		rule.prop = id;
		rule.op = opsFor(c.type)[0][0];
		rule.value = c.type === 'boolean' ? true : '';
		onchange();
	}

	const isGroup = (r: FilterRule | FilterGroup): r is FilterGroup => 'rules' in r;
</script>

<div class="group" class:nested>
	{#each group.rules as rule, i (i)}
		<div class="rule">
			<span class="conj">
				{#if i === 0}Where{:else if i === 1}
					<select class="input sm" bind:value={group.op} onchange={onchange}><option value="and">And</option><option value="or">Or</option></select>
				{:else}{group.op === 'and' ? 'And' : 'Or'}{/if}
			</span>
			{#if isGroup(rule)}
				<Self group={rule} {cols} {onchange} nested onremove={() => { group.rules.splice(i, 1); onchange(); }} />
			{:else}
				{@const c = colOf(rule.prop)}
				<select class="input" value={rule.prop} onchange={(e) => setProp(rule, e.currentTarget.value)}>
					{#each cols as col (col.id)}<option value={col.id}>{col.name}</option>{/each}
				</select>
				{#if c}
					<select class="input" bind:value={rule.op} onchange={onchange}>
						{#each opsFor(c.type) as [v, label] (v)}<option value={v}>{label}</option>{/each}
					</select>
					{#if !noValue.has(rule.op)}
						{#if c.type === 'boolean'}
							<select class="input" bind:value={rule.value} onchange={onchange}><option value={true}>Checked</option><option value={false}>Unchecked</option></select>
						{:else if c.type === 'select' || c.type === 'status' || c.type === 'multi_select'}
							<select class="input" bind:value={rule.value} onchange={onchange}>
								<option value="">Choose…</option>
								{#each c.def?.options ?? [] as o (o.id)}<option value={o.id}>{o.name}</option>{/each}
							</select>
						{:else if c.type === 'relation'}
							<select class="input" bind:value={rule.value} onchange={onchange}>
								<option value="">Choose…</option>
								{#each Object.values(ws.docs).filter((d) => !c.def?.config.target || d.entry_of === c.def.config.target) as d (d.id)}
									<option value={d.id}>{d.title || 'Untitled'}</option>
								{/each}
							</select>
						{:else if c.type === 'date' || c.type === 'created_time' || c.type === 'last_edited_time'}
							<span class="datepick">
								<select class="input" value={['today', 'tomorrow', 'yesterday'].includes(rule.value) ? rule.value : 'exact'}
									onchange={(e) => { rule.value = e.currentTarget.value === 'exact' ? '' : e.currentTarget.value; onchange(); }}>
									<option value="today">Today</option><option value="tomorrow">Tomorrow</option><option value="yesterday">Yesterday</option><option value="exact">Exact date</option>
								</select>
								{#if !['today', 'tomorrow', 'yesterday'].includes(rule.value)}
									<input class="input" type="date" bind:value={rule.value} onchange={onchange} />
								{/if}
							</span>
						{:else}
							<input class="input" type={c.type === 'number' || c.type === 'rating' ? 'number' : 'text'} bind:value={rule.value} oninput={onchange} placeholder="Value" />
						{/if}
					{/if}
				{/if}
				<button class="icon-btn" title="Remove filter" onclick={() => { group.rules.splice(i, 1); onchange(); }}><Trash2 size={13} /></button>
			{/if}
		</div>
	{/each}
	<div class="adds">
		<button class="btn ghost" onclick={addRule}><Plus size={13} />Add filter</button>
		{#if !nested}<button class="btn ghost" onclick={addGroup}><Plus size={13} />Add filter group</button>{/if}
		{#if nested && onremove}<button class="btn ghost" onclick={onremove}><Trash2 size={13} />Remove group</button>{/if}
	</div>
</div>

<style>
	.group { display: flex; flex-direction: column; gap: 5px; }
	.group.nested { flex: 1; padding: 6px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2); }
	.rule { display: flex; align-items: flex-start; gap: 5px; flex-wrap: wrap; }
	.rule > .input { flex: 1; min-width: 92px; }
	.conj { flex: none; width: 60px; height: 28px; display: flex; align-items: center; color: var(--text-3); font-size: 12.5px; }
	.sm { width: 60px; padding: 0 2px; }
	.datepick { display: flex; gap: 4px; flex: 1; }
	.datepick .input { flex: 1; min-width: 0; }
	.adds { display: flex; gap: 2px; }
</style>
