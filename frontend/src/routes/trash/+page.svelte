<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import DocList from '#lib/components/DocList.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Doc } from '#lib/types.ts';
	import { relTime } from '#lib/util.ts';

	let docs = $state<Doc[]>([]);
	let loaded = $state(false);

	async function load() {
		try {
			docs = await api.get<Doc[]>('/trash');
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);

	async function restore(d: Doc) {
		await ws.restoreDoc(d.id).catch((e) => ui.error(e));
		load();
	}

	async function destroy(d: Doc) {
		const ok = await ui.confirm({
			title: `Delete “${d.title || 'Untitled'}” forever?`,
			message: 'The page, its sub-pages and all their content will be permanently deleted. This cannot be undone.',
			confirmLabel: 'Delete forever', danger: true
		});
		if (!ok) return;
		await api.del(`/documents/${d.id}`).catch((e) => ui.error(e));
		load();
	}

	async function emptyTrash() {
		const ok = await ui.confirm({
			title: `Permanently delete ${docs.length} ${docs.length === 1 ? 'page' : 'pages'}?`,
			message: 'Everything in the trash will be permanently deleted. This cannot be undone.',
			confirmLabel: 'Empty trash', danger: true
		});
		if (!ok) return;
		for (const d of docs) await api.del(`/documents/${d.id}`).catch((e) => ui.error(e));
		load();
	}
</script>

<div class="page-scroll">
	<div class="page">
		<div class="titlebar">
			<h1>Trash</h1>
			{#if docs.length}<button class="btn" onclick={emptyTrash}>Empty trash</button>{/if}
		</div>
		<p class="lede">Deleted pages stay here until you remove them for good.</p>
		{#if docs.length}
			<DocList {docs} link={false} sub={(d) => 'Deleted ' + relTime(d.trashed_at)}>
				{#snippet actions(d)}
					<button class="btn" onclick={() => restore(d)}>Restore</button>
					<button class="btn ghost" onclick={() => destroy(d)}>Delete forever</button>
				{/snippet}
			</DocList>
		{:else if loaded}
			<div class="empty"><b>Trash is empty</b>Pages you delete will show up here.</div>
		{/if}
	</div>
</div>

<style>
	.titlebar { display: flex; align-items: center; justify-content: space-between; }
</style>
