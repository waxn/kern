<script lang="ts">
	import { page } from '$app/state';
	import DocView from '#lib/components/DocView.svelte';
</script>

{#key page.params.id}
	<DocView id={page.params.id!} />
{/key}
