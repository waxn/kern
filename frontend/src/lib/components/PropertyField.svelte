<script lang="ts">
	import { AtSign, ExternalLink, FileText, Phone, Plus, Star, X } from '@lucide/svelte';
	import { tick } from 'svelte';
	import { api } from '#lib/api.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { PropDef, PropOption } from '#lib/types.ts';
	import { fullDate, TAG_COLORS, uid } from '#lib/util.ts';

	let { def, value, onchange, ondef, compact = false }: {
		def: PropDef; value: any; onchange: (value: any) => void; ondef?: (def: PropDef) => void; compact?: boolean;
	} = $props();

	let pickerOpen = $state(false);
	let filter = $state('');
	let pos = $state({ x: 0, y: 0 });

	const multi = $derived(def.type === 'multi_select' || def.type === 'relation');
	let selectedIds = $derived<string[]>(multi ? (Array.isArray(value) ? value : []) : value ? [value] : []);
	let options = $derived(def.options.filter((o) => o.name.toLowerCase().includes(filter.toLowerCase())));
	let candidates = $derived.by(() => {
		if (def.type !== 'relation' || !pickerOpen) return [];
		const target = def.config?.target;
		const pool = Object.values(ws.docs).filter((d) => (target ? d.entry_of === target : !d.entry_of || true));
		const q = filter.trim().toLowerCase();
		return pool
			.filter((d) => (d.title || 'Untitled').toLowerCase().includes(q))
			.sort((a, b) => Number(selectedIds.includes(b.id)) - Number(selectedIds.includes(a.id)) || (a.title || '').localeCompare(b.title || ''))
			.slice(0, 30);
	});

	function openPicker(e: MouseEvent) {
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		pos = { x: Math.min(r.left, innerWidth - 276), y: r.bottom + 4 > innerHeight - 280 ? Math.max(8, r.top - 284) : r.bottom + 4 };
		pickerOpen = true;
	}

	function toggle(id: string) {
		if (!multi) {
			onchange(value === id ? null : id);
			pickerOpen = false;
		} else {
			const next = selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id];
			onchange(next.length ? next : null);
		}
		filter = '';
	}

	async function createOption() {
		const name = filter.trim();
		if (!name) return;
		const existing = def.options.find((o) => o.name.toLowerCase() === name.toLowerCase());
		if (existing) return toggle(existing.id);
		const opt: PropOption = { id: uid(), name, color: TAG_COLORS[def.options.length % TAG_COLORS.length] };
		if (def.type === 'status') opt.group = 'todo';
		try {
			const saved = await api.patch<PropDef>(`/properties/${def.id}`, { options: [...def.options, opt] });
			def.options = saved.options;
			ondef?.(saved);
			toggle(opt.id);
		} catch (e) {
			ui.error(e);
		}
	}

	async function createRelated() {
		const target = def.config?.target;
		const title = filter.trim();
		if (!title) return;
		try {
			const doc = target
				? await api.post<any>(`/databases/${target}/entries`, { title })
				: await ws.createDoc({ title });
			ws.docs[doc.id] = doc;
			toggle(doc.id);
		} catch (e) {
			ui.error(e);
		}
	}

	async function removeOption(id: string) {
		try {
			const saved = await api.patch<PropDef>(`/properties/${def.id}`, { options: def.options.filter((o) => o.id !== id) });
			def.options = saved.options;
			ondef?.(saved);
			if (selectedIds.includes(id)) toggle(id);
		} catch (e) {
			ui.error(e);
		}
	}

	const optionOf = (id: string) => def.options.find((o) => o.id === id);

	function fmtNum(n: number): string {
		const f = def.config?.format;
		if (f === 'percent') return `${(n * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
		if (f && f !== 'number' && /^[A-Z]{3}$/.test(f))
			return n.toLocaleString(undefined, { style: 'currency', currency: f });
		return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
	}

	function fmtComputed(v: any): string {
		if (v === null || v === undefined) return '';
		if (Array.isArray(v)) return v.map(fmtComputed).filter(Boolean).join(', ');
		if (typeof v === 'number') return fmtNum(v);
		if (typeof v === 'boolean') return v ? '✓' : '✗';
		if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fullDate(v);
		return String(v);
	}

	let input = $state<HTMLInputElement>();
	let editingNum = $state(false);
</script>

{#if def.type === 'created_time' || def.type === 'last_edited_time'}
	<span class="ro" title={value ?? ''}>{fullDate(value)}</span>
{:else if def.type === 'formula'}
	{#if value && typeof value === 'object' && 'error' in value}
		<span class="ro err" title={value.error}>⚠ {value.error}</span>
	{:else if typeof value === 'boolean'}
		<span class="ro"><input type="checkbox" checked={value} disabled /></span>
	{:else}
		<span class="ro">{fmtComputed(value)}</span>
	{/if}
{:else if def.type === 'rollup'}
	<span class="ro">{fmtComputed(value)}</span>
{:else if def.type === 'text'}
	<input class="plain" value={value ?? ''} placeholder={compact ? '' : 'Empty'} onchange={(e) => onchange(e.currentTarget.value)}
		onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
{:else if def.type === 'url' || def.type === 'email' || def.type === 'phone'}
	{@const href = !value ? '' : def.type === 'email' ? `mailto:${value}` : def.type === 'phone' ? `tel:${value}` : /^[a-z]+:/i.test(value) ? value : `https://${value}`}
	<span class="url">
		<input class="plain" type={def.type === 'email' ? 'email' : def.type === 'phone' ? 'tel' : 'url'} value={value ?? ''}
			placeholder={compact ? '' : 'Empty'} onchange={(e) => onchange(e.currentTarget.value)} onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
		{#if value}
			<a class="icon-btn go" {href} target="_blank" rel="noopener noreferrer" title="Open">
				{#if def.type === 'email'}<AtSign size={12} />{:else if def.type === 'phone'}<Phone size={12} />{:else}<ExternalLink size={12} />{/if}
			</a>
		{/if}
	</span>
{:else if def.type === 'number'}
	{#if !editingNum && value !== null && value !== undefined && def.config?.format && def.config.format !== 'number'}
		<button class="ro num" onclick={async () => { editingNum = true; await tick(); input?.focus(); }}>{fmtNum(value)}</button>
	{:else}
		<input bind:this={input} class="plain" class:num={compact} type="number" step="any" value={value ?? ''} placeholder={compact ? '' : 'Empty'}
			onblur={() => (editingNum = false)}
			onchange={(e) => onchange(e.currentTarget.value === '' ? null : Number(e.currentTarget.value))} onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
	{/if}
{:else if def.type === 'date'}
	<input class="plain date" type="date" value={value ? String(value).slice(0, 10) : ''} onchange={(e) => onchange(e.currentTarget.value || null)} />
{:else if def.type === 'boolean'}
	<label class="check"><input type="checkbox" checked={!!value} onchange={(e) => onchange(e.currentTarget.checked)} /></label>
{:else if def.type === 'rating'}
	<span class="stars">
		{#each [1, 2, 3, 4, 5] as n (n)}
			<button class:on={(value ?? 0) >= n} title="{n} of 5" onclick={() => onchange(value === n ? null : n)}><Star size={14} /></button>
		{/each}
	</span>
{:else}
	<div class="multi">
		<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
		<div class="chips" class:compact onclick={openPicker}>
			{#each selectedIds as id (id)}
				{#if def.type === 'relation'}
					{@const d = ws.docs[id]}
					{#if d}
						<a class="rel" href="/doc/{id}" onclick={(e) => { e.preventDefault(); e.stopPropagation(); open(`/doc/${id}`, e); }}>
							{#if d.icon}{d.icon}{:else}<FileText size={12} />{/if}<span class="truncate">{d.title || 'Untitled'}</span>
						</a>
					{/if}
				{:else}
					{@const o = optionOf(id)}
					{#if o}<span class="chip" data-c={o.color} class:status={def.type === 'status'}>{#if def.type === 'status'}<i></i>{/if}{o.name}</span>{/if}
				{/if}
			{:else}
				{#if !compact}<span class="faint">Empty</span>{/if}
			{/each}
		</div>
		{#if pickerOpen}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="backdrop" onmousedown={() => { pickerOpen = false; filter = ''; }}></div>
			<div class="pop popover" style:left="{pos.x}px" style:top="{pos.y}px">
				<!-- svelte-ignore a11y_autofocus -->
				<input class="input" autofocus bind:value={filter} placeholder={def.type === 'relation' ? 'Find or create an entry…' : 'Find or create an option…'}
					onkeydown={(e) => {
						e.stopPropagation();
						if (e.key === 'Escape') pickerOpen = false;
						if (e.key === 'Enter') def.type === 'relation' ? (candidates[0] && filter.trim() ? toggle(candidates[0].id) : createRelated()) : createOption();
					}} />
				<div class="opts">
					{#if def.type === 'relation'}
						{#each candidates as d (d.id)}
							<button class="menu-item" onclick={() => toggle(d.id)}>
								<span class="truncate">{d.icon} {d.title || 'Untitled'}</span>
								{#if selectedIds.includes(d.id)}<span class="hint">✓</span>{/if}
							</button>
						{:else}<div class="faint pad">{filter.trim() ? 'No matches.' : 'No entries yet.'}</div>{/each}
						{#if filter.trim()}
							<button class="menu-item" onclick={createRelated}><Plus size={14} />Create “{filter.trim()}”</button>
						{/if}
					{:else}
						{#each options as o (o.id)}
							<div class="opt">
								<button class="menu-item" onclick={() => toggle(o.id)}>
									<span class="chip" data-c={o.color}>{o.name}</span>
									{#if selectedIds.includes(o.id)}<span class="hint">✓</span>{/if}
								</button>
								<button class="icon-btn" title="Delete option" onclick={() => removeOption(o.id)}><X size={12} /></button>
							</div>
						{/each}
						{#if filter.trim() && !def.options.some((o) => o.name.toLowerCase() === filter.trim().toLowerCase())}
							<button class="menu-item" onclick={createOption}>Create “{filter.trim()}”</button>
						{:else if !options.length}
							<div class="faint pad">Type to create an option.</div>
						{/if}
						{#if !multi && value}
							<div class="menu-sep"></div>
							<button class="menu-item" onclick={() => { onchange(null); pickerOpen = false; }}>Clear</button>
						{/if}
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	.plain { width: 100%; height: 26px; padding: 0 6px; border: 0; border-radius: var(--radius-sm); background: none; outline: none; }
	.plain:hover, .chips:hover { background: var(--hover); }
	.plain:focus { background: var(--hover); box-shadow: inset 0 0 0 1px var(--border-strong); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.ro { display: flex; align-items: center; min-height: 26px; padding: 0 6px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.ro.num { width: 100%; justify-content: flex-end; color: var(--text); cursor: text; border-radius: var(--radius-sm); }
	.ro.num:hover { background: var(--hover); }
	.ro.err { color: var(--danger); font-size: 12px; }
	.date { width: auto; color-scheme: inherit; }
	.url { display: flex; align-items: center; gap: 2px; }
	.go { width: 22px; height: 22px; flex: none; }
	.check { display: flex; align-items: center; height: 26px; padding: 0 6px; }
	.check input { accent-color: var(--accent); width: 15px; height: 15px; }
	.stars { display: flex; align-items: center; height: 26px; padding: 0 4px; }
	.stars button { color: var(--text-3); padding: 0 1px; display: grid; }
	.stars button.on { color: var(--accent); }
	.stars button.on :global(svg) { fill: currentColor; }
	.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: 26px; padding: 3px 6px; border-radius: var(--radius-sm); cursor: pointer; }
	.chips.compact { flex-wrap: nowrap; overflow: hidden; }
	.chip.status i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
	.rel { display: inline-flex; align-items: center; gap: 4px; max-width: 200px; padding: 0 6px; border-radius: 4px; background: var(--active); text-decoration: none; font-size: 12.5px; height: 20px; }
	.rel:hover { color: var(--accent); }
	.backdrop { position: fixed; inset: 0; z-index: 400; }
	.pop { position: fixed; z-index: 401; width: 268px; padding: 6px; }
	.pop .input { width: 100%; }
	.opts { max-height: 240px; overflow-y: auto; margin-top: 4px; }
	.opt { display: flex; align-items: center; }
	.opt .icon-btn { opacity: 0; }
	.opt:hover .icon-btn { opacity: 1; }
	.pad { padding: 6px 8px; }
</style>
