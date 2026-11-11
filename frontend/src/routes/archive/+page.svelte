<script lang="ts">
	import { setArchived, trashPage } from '#lib/actions.ts';
	import DocList from '#lib/components/DocList.svelte';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { relTime } from '#lib/util.ts';
</script>

<div class="page-scroll">
	<div class="page">
		<h1>Archive</h1>
		<p class="lede">Archived pages are hidden from the sidebar but stay searchable and linked.</p>
		{#if ws.archived.length}
			<DocList docs={ws.archived} sub={(d) => 'Edited ' + relTime(d.updated_at)}>
				{#snippet actions(d)}
					<button class="btn" onclick={() => setArchived(d.id, false)}>Unarchive</button>
					<button class="btn ghost" onclick={() => trashPage(d.id)}>Move to trash</button>
				{/snippet}
			</DocList>
		{:else}
			<div class="empty"><b>Nothing archived</b>Use a page's menu to archive it.</div>
		{/if}
	</div>
</div>
