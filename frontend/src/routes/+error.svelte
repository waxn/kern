<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import LostNode from '#lib/components/LostNode.svelte';
	import { House, ArrowLeft } from '@lucide/svelte';

	let missing = $derived(page.status === 404);
	let code = $derived(String(page.status).padStart(3, '0').split(''));
	const LAYERS = 14;
</script>

<svelte:head><title>{missing ? 'Not found' : 'Error'} · Kern</title></svelte:head>

<div class="stage">
	<LostNode />
	<div class="content">
		<div class="digits" role="img" aria-label={String(page.status)}>
			{#each code as ch, i}
				<span class="digit" class:core={ch === '0'} style="--i:{i}">
					{#each Array(LAYERS) as _, l}
						<i style="--l:{l}" aria-hidden="true">{ch}</i>
					{/each}
					<b aria-hidden="true">{ch}</b>
				</span>
			{/each}
		</div>
		<h1>{missing ? 'This node isn’t in the graph' : 'Something went wrong'}</h1>
		<p>
			{#if missing}
				Nothing links to <code>{page.url.pathname}</code>. It may have been moved, deleted, or never written.
			{:else}
				{page.error?.message ?? 'An unexpected error occurred.'}
			{/if}
		</p>
		<div class="actions">
			<button class="btn primary" onclick={() => goto('/')}><House size={15} /> Back to Kern</button>
			<button class="btn" onclick={() => history.length > 1 ? history.back() : goto('/')}><ArrowLeft size={15} /> Go back</button>
		</div>
	</div>
</div>

<style>
	.stage {
		position: relative; flex: 1; min-height: 100%; height: 100%; overflow: hidden;
		display: grid; place-items: center; --mx: 0; --my: 0; perspective: 900px;
		background: radial-gradient(ellipse at 50% 40%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 65%);
	}
	.content { position: relative; text-align: center; padding: 24px; max-width: 560px; transform-style: preserve-3d; }
	/* A soft pool of background keeps the copy legible over the graph. */
	.content::before {
		content: ''; position: absolute; inset: 30% -10% -8%; z-index: -1; pointer-events: none;
		background: radial-gradient(ellipse at center, color-mix(in srgb, var(--bg) 88%, transparent) 30%, transparent 72%);
	}
	.digits {
		display: flex; justify-content: center; gap: clamp(6px, 2vw, 18px); margin-bottom: 18px;
		transform-style: preserve-3d;
		transform: rotateY(calc(var(--mx) * 16deg)) rotateX(calc(var(--my) * -10deg));
		transition: transform 0.25s var(--ease);
		animation: float 7s ease-in-out infinite;
	}
	.digit {
		position: relative; display: block; transform-style: preserve-3d;
		font: 800 clamp(96px, 20vw, 190px)/1 var(--font-sans); letter-spacing: -0.04em;
		animation: sway 9s ease-in-out infinite; animation-delay: calc(var(--i) * -1.3s);
	}
	.digit i, .digit b { font-style: normal; font-weight: inherit; display: block; }
	.digit i {
		position: absolute; inset: 0; color: color-mix(in srgb, var(--accent) calc(18% + var(--l) * 3%), var(--bg));
		transform: translateZ(calc(var(--l) * -4px));
	}
	.digit b {
		position: relative; transform: translateZ(2px); color: var(--text);
		text-shadow: 0 0 40px color-mix(in srgb, var(--accent) 35%, transparent);
	}
	/* The zero is the kernel: an amber core that breathes. */
	.digit.core b { color: var(--accent); animation: glow 3.2s ease-in-out infinite; }
	@keyframes glow {
		0%, 100% { text-shadow: 0 0 18px color-mix(in srgb, var(--accent) 40%, transparent); }
		50% { text-shadow: 0 0 56px color-mix(in srgb, var(--accent) 85%, transparent), 0 0 12px var(--accent); }
	}
	@keyframes float { 0%, 100% { translate: 0 -6px; } 50% { translate: 0 8px; } }
	@keyframes sway { 0%, 100% { rotate: y -7deg; } 50% { rotate: y 7deg; } }
	h1 { margin: 0 0 8px; font-size: 22px; font-weight: 650; letter-spacing: -0.01em; }
	p { margin: 0 auto 22px; color: var(--text-2); line-height: 1.55; max-width: 44ch; }
	code {
		font: 12.5px var(--font-mono); background: var(--code-bg); padding: 2px 6px; border-radius: var(--radius-sm);
		color: var(--text); word-break: break-all;
	}
	.actions { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
	.actions :global(.btn) { display: inline-flex; align-items: center; gap: 6px; }
	h1, p, .actions { animation: rise 0.7s var(--ease) both; }
	p { animation-delay: 0.08s; } .actions { animation-delay: 0.16s; }
	@keyframes rise { from { opacity: 0; transform: translateY(12px); } }
	@media (prefers-reduced-motion: reduce) {
		.digits, .digit, .digit.core b, h1, p, .actions { animation: none; }
	}
</style>
