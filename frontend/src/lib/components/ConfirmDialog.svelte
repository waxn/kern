<script lang="ts">
	import { ui } from '#lib/state/ui.svelte.ts';

	let okBtn = $state<HTMLButtonElement>();
	$effect(() => {
		if (ui.confirmState) okBtn?.focus();
	});

	function answer(ok: boolean) {
		ui.confirmState?.resolve(ok);
		ui.confirmState = null;
	}
</script>

{#if ui.confirmState}
	{@const c = ui.confirmState}
	<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
	<div class="overlay" onclick={(e) => e.target === e.currentTarget && answer(false)}
		onkeydown={(e) => e.key === 'Escape' && answer(false)}>
		<div class="dialog popover" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
			<h2 id="confirm-title">{c.title}</h2>
			{#if c.message}<p>{c.message}</p>{/if}
			<div class="actions">
				<button class="btn ghost" onclick={() => answer(false)}>Cancel</button>
				<button class="btn" class:danger={c.danger} class:primary={!c.danger} bind:this={okBtn} onclick={() => answer(true)}>
					{c.confirmLabel ?? 'Confirm'}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay { position: fixed; inset: 0; z-index: 950; display: grid; place-items: center; background: rgba(0, 0, 0, 0.45); animation: fade 0.12s; }
	.dialog { width: min(400px, calc(100vw - 32px)); padding: 18px; }
	h2 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
	p { margin: 0; color: var(--text-2); }
	.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
