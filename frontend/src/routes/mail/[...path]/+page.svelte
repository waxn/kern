<script lang="ts">
	import { page } from '$app/state';
	import MailApp from '#lib/mail/MailApp.svelte';
</script>

<MailApp url={page.url} />
