<script lang="ts">
	import { goto } from '$app/navigation';
	import { Copy, LayoutTemplate, Pencil, Plus, Trash2 } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import AiButton from '#lib/ai/AiButton.svelte';
	import AiTemplateDialog from '#lib/ai/AiTemplateDialog.svelte';
	import { releaseDoc } from '#lib/editor/doc.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Doc } from '#lib/types.ts';

	let list = $state<Doc[]>([]);
	let aiOpen = $state(false);
	let loaded = $state(false);

	async function load() {
		try {
			list = await api.get<Doc[]>('/templates');
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);

	async function create() {
		try {
			const t = await api.post<Doc>('/templates', { title: 'New template' });
			goto(`/doc/${t.id}`);
		} catch (e) {
			ui.error(e);
		}
	}

	async function use(t: Doc) {
		try {
			await releaseDoc(t.id, true);
			const doc = t.template_db
				? await api.post<Doc>(`/databases/${t.template_db}/entries`, { template: t.id })
				: await api.post<Doc>('/documents', { template: t.id });
			ws.docs[doc.id] = doc;
			goto(`/doc/${doc.id}`);
		} catch (e) {
			ui.error(e);
		}
	}

	async function duplicate(t: Doc) {
		await api.post(`/templates/${t.id}/duplicate`).catch((e) => ui.error(e));
		load();
	}

	async function remove(t: Doc) {
		const ok = await ui.confirm({
			title: `Delete template “${t.title || 'Untitled'}”?`,
			message: 'Pages already created from it are not affected. This cannot be undone.',
			confirmLabel: 'Delete template', danger: true
		});
		if (!ok) return;
		await api.del(`/templates/${t.id}`).catch((e) => ui.error(e));
		load();
	}

	function scope(t: Doc): string {
		const parts = [];
		if (t.template_db) parts.push(`Entries of ${ws.dbPages[t.template_db]?.title || 'a database'}`);
		else parts.push('New pages');
		if (t.template_tag) parts.push(`applied on #${ws.tagMap[t.template_tag]?.name ?? 'tag'}`);
		return parts.join(' · ');
	}
</script>

<div class="page-scroll">
	<div class="page">
		<div class="titlebar">
			<h1>Templates</h1>
			<span class="acts">
				<AiButton title="Generate a template with AI" onclick={() => (aiOpen = true)} />
				<button class="btn primary" onclick={create}><Plus size={14} />New template</button>
			</span>
		</div>
		<p class="lede">Reusable pages with a title, icon, tags, properties and blocks. Bind one to a tag and its structure is added whenever the tag is applied. You can also save any page as a template from its menu.</p>
		{#if list.length}
			<div class="list">
				{#each list as t (t.id)}
					<div class="row">
						<a class="main" href="/doc/{t.id}" onclick={(e) => { e.preventDefault(); open(`/doc/${t.id}`, e); }}>
							<span class="ico">{#if t.icon}{t.icon}{:else}<LayoutTemplate size={15} strokeWidth={1.75} />{/if}</span>
							<span class="name truncate">{t.title || 'Untitled'}</span>
							<span class="sub truncate">{scope(t)} · {t.block_count ?? 0} blocks</span>
						</a>
						<button class="btn" onclick={() => use(t)}>Use</button>
						<button class="icon-btn" title="Edit" onclick={() => goto(`/doc/${t.id}`)}><Pencil size={14} /></button>
						<button class="icon-btn" title="Duplicate" onclick={() => duplicate(t)}><Copy size={14} /></button>
						<button class="icon-btn" title="Delete" onclick={() => remove(t)}><Trash2 size={14} /></button>
					</div>
				{/each}
			</div>
		{:else if loaded}
			<div class="empty"><b>No templates yet</b>Create one, or use “Save as template” in any page's menu.</div>
		{/if}
	</div>
</div>

{#if aiOpen}<AiTemplateDialog onclose={() => (aiOpen = false)} />{/if}

<style>
	.acts { display: flex; align-items: center; gap: 6px; }
	.titlebar { display: flex; align-items: center; justify-content: space-between; }
	.list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	.row { display: flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 8px 0 12px; border-top: 1px solid var(--border); }
	.row:first-child { border-top: 0; }
	.row:hover { background: var(--hover); }
	.main { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; height: 40px; text-decoration: none; }
	.ico { width: 20px; display: grid; place-items: center; color: var(--text-2); }
	.name { font-weight: 550; flex: 0 1 auto; }
	.sub { margin-left: auto; padding-left: 12px; color: var(--text-3); font-size: 12.5px; }
</style>
