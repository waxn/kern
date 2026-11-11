<script lang="ts">
	import { goto } from '$app/navigation';
	import { LayoutTemplate } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { releaseDoc } from '#lib/editor/doc.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Doc } from '#lib/types.ts';

	let { id }: { id: string } = $props();
	let t = $state<Doc | null>(null);

	$effect(() => {
		api.get<{ document: Doc }>(`/documents/${id}`).then((p) => (t = p.document)).catch(() => {});
	});

	async function bind(patch: Record<string, string | null>) {
		try {
			t = await api.patch<Doc>(`/templates/${id}`, patch);
		} catch (e) {
			ui.error(e);
		}
	}

	async function use() {
		try {
			await releaseDoc(id, true);
			const doc = t?.template_db
				? await api.post<Doc>(`/databases/${t.template_db}/entries`, { template: id })
				: await api.post<Doc>('/documents', { template: id });
			ws.docs[doc.id] = doc;
			goto(`/doc/${doc.id}`);
		} catch (e) {
			ui.error(e);
		}
	}
</script>

<div class="tbar">
	<LayoutTemplate size={15} />
	<b>Template</b>
	<span class="muted">Edits here change future pages, not ones already made.</span>
	{#if t}
		<label>For
			<select class="input" value={t.template_db ?? ''} onchange={(e) => bind({ template_db: e.currentTarget.value || null })}>
				<option value="">New pages</option>
				{#each ws.databases as d (d.id)}<option value={d.database}>Entries of {d.title || 'Untitled'}</option>{/each}
			</select>
		</label>
		<label>Apply when tagged
			<select class="input" value={t.template_tag ?? ''} onchange={(e) => bind({ template_tag: e.currentTarget.value || null })}>
				<option value="">—</option>
				{#each ws.tags as tag (tag.id)}<option value={tag.id}>#{tag.name}</option>{/each}
			</select>
		</label>
	{/if}
	<button class="btn primary" onclick={use}>Use template</button>
</div>

<style>
	.tbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 16px; background: color-mix(in srgb, var(--c-purple) 14%, transparent); border-bottom: 1px solid var(--border); font-size: 13px; }
	.tbar :global(svg) { color: var(--c-purple); }
	.muted { flex: 1; min-width: 160px; }
	label { display: flex; align-items: center; gap: 6px; color: var(--text-2); }
	select { max-width: 180px; }
</style>
