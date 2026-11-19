<script lang="ts">
	// A small status icon for a CI run, a job or a commit. With `href` it links to that run.
	import { Ban, CircleAlert, CircleCheck, CircleDashed, CircleMinus, CircleX, Clock, LoaderCircle } from '@lucide/svelte';
	import { STATUS_LABEL } from './ci.ts';

	let { status, size = 15, href = '' }: { status: string; size?: number; href?: string } = $props();
	const title = $derived(STATUS_LABEL[status] ?? status);
</script>

{#snippet icon()}
	<span class="dot {status}" {title} role="img" aria-label={title}>
		{#if status === 'success'}<CircleCheck {size} />
		{:else if status === 'failed'}<CircleX {size} />
		{:else if status === 'running'}<LoaderCircle {size} class="spin" />
		{:else if status === 'queued'}<Clock {size} />
		{:else if status === 'cancelled'}<Ban {size} />
		{:else if status === 'error'}<CircleAlert {size} />
		{:else if status === 'skipped'}<CircleMinus {size} />
		{:else}<CircleDashed {size} />{/if}
	</span>
{/snippet}

{#if href}<a class="dl" {href}>{@render icon()}</a>{:else}{@render icon()}{/if}

<style>
	.dot { display: inline-flex; flex: none; color: var(--text-3); }
	.dot.success { color: var(--c-green); }
	.dot.failed { color: var(--c-red); }
	.dot.running { color: var(--c-blue); }
	.dot.error { color: var(--c-orange); }
	.dl { display: inline-flex; text-decoration: none; }
	.dot :global(.spin) { animation: ci-spin 1.1s linear infinite; }
	@keyframes ci-spin { to { transform: rotate(360deg); } }
	@media (prefers-reduced-motion: reduce) { .dot :global(.spin) { animation-duration: 3s; } }
</style>
