<script lang="ts">
	import { FileText } from '@lucide/svelte';
	import { ws } from '../state/workspace.svelte.ts';
	import type { PropDef } from '../types.ts';
	import { fullDate } from '../util.ts';

	let { def, value }: { def: PropDef; value: any } = $props();

	function fmt(v: any): string {
		if (v === null || v === undefined || v === '') return '';
		if (Array.isArray(v)) return v.map(fmt).filter(Boolean).join(', ');
		if (typeof v === 'number') {
			const f = def.config?.format;
			if (f === 'percent') return `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
			if (f && /^[A-Z]{3}$/.test(f)) return v.toLocaleString(undefined, { style: 'currency', currency: f });
			return v.toLocaleString(undefined, { maximumFractionDigits: 6 });
		}
		if (typeof v === 'boolean') return v ? '✓' : '';
		if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fullDate(v);
		if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v))
			return new Date(v + 'T00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
		if (typeof v === 'object' && 'error' in v) return '⚠';
		return String(v);
	}

	const opt = (id: string) => def.options.find((o) => o.id === id);
	let empty = $derived(value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length) || (def.type === 'boolean' && !value));
</script>

{#if !empty}
	{#if def.type === 'select' || def.type === 'status'}
		{@const o = opt(value)}
		{#if o}<span class="chip" data-c={o.color}>{o.name}</span>{/if}
	{:else if def.type === 'multi_select'}
		{#each value as id (id)}{@const o = opt(id)}{#if o}<span class="chip" data-c={o.color}>{o.name}</span>{/if}{/each}
	{:else if def.type === 'relation'}
		{#each value as id (id)}
			{@const d = ws.docs[id]}
			{#if d}<span class="rel">{#if d.icon}{d.icon}{:else}<FileText size={11} />{/if}{d.title || 'Untitled'}</span>{/if}
		{/each}
	{:else if def.type === 'boolean'}
		<span class="chip">✓ {def.name}</span>
	{:else if def.type === 'rating'}
		<span class="stars">{'★'.repeat(value)}<span class="faint">{'★'.repeat(5 - value)}</span></span>
	{:else if def.type === 'url'}
		<span class="txt link truncate">{value}</span>
	{:else}
		<span class="txt truncate" title={def.name}>{fmt(value)}</span>
	{/if}
{/if}

<style>
	.rel { display: inline-flex; align-items: center; gap: 3px; padding: 0 5px; border-radius: 4px; background: var(--active); font-size: 12px; height: 19px; max-width: 180px; overflow: hidden; white-space: nowrap; }
	.txt { font-size: 12.5px; color: var(--text-2); }
	.link { color: var(--accent); }
	.stars { color: var(--accent); font-size: 12px; letter-spacing: 1px; }
</style>
