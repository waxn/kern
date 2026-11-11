<script lang="ts">
	import { ArrowDown, ArrowUp, EyeOff, GripVertical, Plus, Trash2, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { COMPUTED, DB_PROP_TYPES, PROP_ICONS, ROLLUP_FNS } from '../propTypes.ts';
	import { ws } from '../state/workspace.svelte.ts';
	import type { PropDef, PropOption, PropType } from '../types.ts';
	import { TAG_COLORS, uid } from '../util.ts';
	import { getDb, type DbState } from './state.svelte.ts';

	let { db, def, onclose, onhide }: { db: DbState; def?: PropDef; onclose: () => void; onhide?: () => void } = $props();

	// svelte-ignore state_referenced_locally
	const creating = !def;
	// svelte-ignore state_referenced_locally
	let name = $state(def?.name ?? '');
	// svelte-ignore state_referenced_locally
	let type = $state<PropType>(def?.type ?? 'text');
	// svelte-ignore state_referenced_locally
	let options = $state<PropOption[]>(structuredClone($state.snapshot(def?.options ?? [])));
	// svelte-ignore state_referenced_locally
	let config = $state<Record<string, any>>(structuredClone($state.snapshot(def?.config ?? {})));
	let newOption = $state('');
	let nameInput = $state<HTMLInputElement>();
	if (creating) config.two_way = true;

	onMount(() => nameInput?.select());

	let relations = $derived((db.data?.properties ?? []).filter((p) => p.type === 'relation' && p.id !== def?.id));
	let rollupRel = $derived(relations.find((r) => r.id === config.relation));
	let relatedDb = $derived(rollupRel?.config.target ? getDbOnce(rollupRel.config.target) : null);

	const dbCache = new Map<string, DbState>();
	function getDbOnce(id: string) {
		if (!dbCache.has(id)) dbCache.set(id, getDb(id));
		return dbCache.get(id)!;
	}

	function addOption() {
		const n = newOption.trim();
		if (!n || options.some((o) => o.name.toLowerCase() === n.toLowerCase())) return;
		options.push({ id: uid(), name: n, color: TAG_COLORS[options.length % TAG_COLORS.length], ...(type === 'status' ? { group: 'todo' } : {}) });
		newOption = '';
	}

	function moveOption(i: number, d: number) {
		const j = i + d;
		if (j < 0 || j >= options.length) return;
		[options[i], options[j]] = [options[j], options[i]];
	}

	async function save() {
		const n = name.trim() || DB_PROP_TYPES.find((t) => t[0] === type)?.[1] || 'Property';
		const cfg = $state.snapshot(config);
		const opts = $state.snapshot(options);
		if (creating) {
			await db.addProperty({ name: n, type, options: opts, config: cfg } as any);
		} else if (def) {
			const patch: Partial<PropDef> = {};
			if (n !== def.name) patch.name = n;
			if (type !== def.type) {
				patch.type = type;
				if (type === 'relation') patch.config = cfg;
			}
			if (JSON.stringify(opts) !== JSON.stringify(def.options)) patch.options = opts;
			if (type !== 'relation' && JSON.stringify(cfg) !== JSON.stringify(def.config)) patch.config = cfg;
			if (Object.keys(patch).length) await db.updateProperty(def.id, patch);
		}
		onclose();
	}

	let hasOptions = $derived(type === 'select' || type === 'multi_select' || type === 'status');
	let typeChangeWarn = $derived(!creating && def && type !== def.type);
	let targetName = $derived(config.target ? (ws.dbPages[config.target]?.title || 'Untitled') : 'Any page');
</script>

<form class="pe" onsubmit={(e) => { e.preventDefault(); save(); }}>
	<label class="field"><span>Name</span><input class="input" bind:this={nameInput} bind:value={name} placeholder="Property name" /></label>
	<label class="field"><span>Type</span>
		<select class="input" bind:value={type}>
			{#each DB_PROP_TYPES as [v, label] (v)}<option value={v}>{label}</option>{/each}
		</select>
	</label>
	{#if typeChangeWarn}<p class="warn">Changing the type clears existing values of this property.</p>{/if}

	{#if hasOptions}
		<div class="sub">Options</div>
		<div class="options">
			{#each options as o, i (o.id)}
				<div class="opt">
					<GripVertical size={12} class="faint" />
					<select class="color" bind:value={o.color} data-c={o.color} title="Color">
						{#each TAG_COLORS as c (c)}<option value={c}>{c}</option>{/each}
					</select>
					<input class="input grow" bind:value={o.name} />
					{#if type === 'status'}
						<select class="input grp" bind:value={o.group} title="Group">
							<option value="todo">To-do</option><option value="in_progress">In progress</option><option value="done">Complete</option>
						</select>
					{/if}
					<button type="button" class="icon-btn" title="Move up" onclick={() => moveOption(i, -1)}><ArrowUp size={12} /></button>
					<button type="button" class="icon-btn" title="Move down" onclick={() => moveOption(i, 1)}><ArrowDown size={12} /></button>
					<button type="button" class="icon-btn" title="Delete option" onclick={() => options.splice(i, 1)}><X size={12} /></button>
				</div>
			{/each}
			<div class="opt">
				<input class="input grow" bind:value={newOption} placeholder="Add an option…"
					onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addOption(); } }} />
				<button type="button" class="btn" onclick={addOption}><Plus size={13} />Add</button>
			</div>
		</div>
	{:else if type === 'number'}
		<label class="field"><span>Format</span>
			<select class="input" bind:value={config.format}>
				<option value="number">Number</option><option value="percent">Percent</option>
				<option value="USD">US dollar</option><option value="EUR">Euro</option><option value="GBP">Pound</option>
				<option value="SEK">Krona</option><option value="JPY">Yen</option>
			</select>
		</label>
	{:else if type === 'relation'}
		{#if creating || type !== def?.type}
			<label class="field"><span>Related to</span>
				<select class="input" bind:value={config.target}>
					<option value={null}>Any page</option>
					{#each ws.databases as d (d.id)}<option value={d.database}>{d.icon} {d.title || 'Untitled'}{d.database === db.id ? ' (this database)' : ''}</option>{/each}
				</select>
			</label>
			{#if config.target}
				<label class="check"><input type="checkbox" bind:checked={config.two_way} /> Show on {config.target === db.id ? 'this database too' : targetName} (two-way)</label>
				{#if config.two_way}<label class="field"><span>Name there</span><input class="input" bind:value={config.reverse_name} placeholder={ws.dbPages[db.id]?.title || 'Related'} /></label>{/if}
			{/if}
		{:else}
			<p class="muted small">Related to <b>{targetName}</b>{config.reverse ? ' · two-way' : ' · one-way'}</p>
		{/if}
	{:else if type === 'rollup'}
		<label class="field"><span>Relation</span>
			<select class="input" bind:value={config.relation}>
				<option value={undefined}>Choose…</option>
				{#each relations as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
			</select>
		</label>
		{#if !relations.length}<p class="warn">Add a relation property first.</p>{/if}
		{#if rollupRel}
			<label class="field"><span>Property</span>
				<select class="input" bind:value={config.target}>
					<option value="title">Name</option>
					{#each relatedDb?.data?.properties ?? [] as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
				</select>
			</label>
			{#if !rollupRel.config.target}<p class="warn small">This relation is not tied to a database; only page names are available.</p>{/if}
		{/if}
		<label class="field"><span>Calculate</span>
			<select class="input" bind:value={config.fn}>
				{#each ROLLUP_FNS as [v, label] (v)}<option value={v}>{label}</option>{/each}
			</select>
		</label>
	{:else if type === 'formula'}
		<label class="field col"><span>Formula</span>
			<textarea class="input mono" rows="4" bind:value={config.expr} spellcheck="false"
				placeholder={'prop("Price") * prop("Quantity")'}></textarea>
		</label>
		<details class="help">
			<summary>Formula reference</summary>
			<p><code>prop("Name")</code> reads a property. Operators: <code>+ - * / % ^</code>, <code>== != &lt; &gt; &lt;= &gt;=</code>, <code>and or not</code>, <code>cond ? a : b</code>.</p>
			<p>Functions: if, ifs, concat, join, length, lower, upper, trim, contains, replace, slice, format, toNumber, empty, abs, round, floor, ceil, sqrt, pow, min, max, sum, mean, now, today, dateAdd, dateSubtract, dateBetween, formatDate, year, month, date, day.</p>
		</details>
	{/if}

	{#if !creating && def && !COMPUTED.has(type)}
		<label class="check"><input type="checkbox" bind:checked={config.hidden_in_page} /> Hide on entry pages</label>
	{/if}

	<div class="actions">
		{#if def}
			<button type="button" class="btn ghost danger-text" onclick={() => { onclose(); db.deleteProperty(def.id); }}><Trash2 size={13} />Delete</button>
			{#if onhide}<button type="button" class="btn ghost" onclick={() => { onhide?.(); onclose(); }}><EyeOff size={13} />Hide</button>{/if}
		{/if}
		<span class="grow"></span>
		<button type="button" class="btn ghost" onclick={onclose}>Cancel</button>
		<button type="submit" class="btn primary">{creating ? 'Add property' : 'Save'}</button>
	</div>
</form>

<style>
	.pe { display: flex; flex-direction: column; gap: 8px; }
	.field { display: flex; align-items: center; gap: 8px; }
	.field.col { flex-direction: column; align-items: stretch; }
	.field > span { flex: none; width: 78px; color: var(--text-3); font-size: 12.5px; }
	.field .input { flex: 1; min-width: 0; }
	.sub { margin-top: 2px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); }
	.options { display: flex; flex-direction: column; gap: 4px; }
	.opt { display: flex; align-items: center; gap: 4px; }
	.opt .icon-btn { width: 22px; height: 22px; }
	.grow { flex: 1; min-width: 0; }
	.grp { width: 104px; flex: none; }
	.color { width: 20px; height: 20px; flex: none; border-radius: 50%; border: 0; appearance: none; background: var(--chip); color: transparent; cursor: pointer; }
	.color option { color: var(--text); background: var(--surface); }
	.mono { font-family: var(--font-mono); font-size: 12.5px; }
	.check { display: flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 12.5px; }
	.check input { accent-color: var(--accent); }
	.warn { margin: 0; color: var(--c-orange); font-size: 12px; }
	.small { margin: 0; font-size: 12.5px; }
	.help { font-size: 12px; color: var(--text-2); }
	.help summary { cursor: pointer; color: var(--text-3); }
	.help p { margin: 6px 0; }
	.help code { font-family: var(--font-mono); font-size: 11.5px; background: var(--code-bg); padding: 0 3px; border-radius: 3px; }
	.actions { display: flex; gap: 6px; margin-top: 4px; padding-top: 8px; border-top: 1px solid var(--border); }
	.danger-text { color: var(--danger); }
</style>
