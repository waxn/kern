<script lang="ts">
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fly } from 'svelte/transition';
</script>

<div class="toasts" aria-live="polite">
	{#each ui.toasts as t (t.id)}
		<div class="toast popover" class:error={t.kind === 'error'} transition:fly={{ y: 12, duration: 160 }}>
			<span>{t.message}</span>
			{#if t.action}
				<button class="act" onclick={() => { t.action!.run(); ui.dismiss(t.id); }}>{t.action.label}</button>
			{/if}
		</div>
	{/each}
</div>

<style>
	.toasts { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 990; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
	.toast { pointer-events: auto; display: flex; gap: 14px; align-items: center; padding: 8px 12px; max-width: min(520px, 92vw); animation: none; }
	.toast.error { box-shadow: var(--shadow), inset 3px 0 0 var(--danger); }
	.act { color: var(--accent); font-weight: 550; }
</style>
