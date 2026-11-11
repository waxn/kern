<script lang="ts">
	import { renderMath } from '../editor/dom.ts';
	import type { Region } from '../types.ts';

	let { html = '', image = '', regions = [], target = -1, reveal = false, size = 'large' }: {
		html?: string; image?: string; regions?: Region[]; target?: number; reveal?: boolean; size?: 'large' | 'small';
	} = $props();

	function math(node: HTMLElement, _v: string) {
		renderMath(node);
		return { update() { renderMath(node); } };
	}
</script>

{#if image}
	<div class="occ">
		<img src={image} alt="" draggable="false" />
		{#each regions as r (r.id)}
			{@const isTarget = r.n === target}
			{#if !(reveal && isTarget)}
				<div class="mask" class:target={isTarget} style:left="{r.x * 100}%" style:top="{r.y * 100}%" style:width="{r.w * 100}%" style:height="{r.h * 100}%">
					{#if isTarget}?{/if}
				</div>
			{:else}
				<div class="shown" style:left="{r.x * 100}%" style:top="{r.y * 100}%" style:width="{r.w * 100}%" style:height="{r.h * 100}%">
					{#if r.label}<span>{r.label}</span>{/if}
				</div>
			{/if}
		{/each}
	</div>
	{#if html}<div class="face rt {size}" use:math={html}>{@html html}</div>{/if}
{:else}
	<div class="face rt {size}" use:math={html}>{@html html}</div>
{/if}

<style>
	.face { overflow-wrap: anywhere; line-height: 1.55; }
	.face.large { font-size: 19px; }
	.face.small { font-size: 13.5px; }
	.face :global(.cloze) { padding: 0 6px; border-radius: 4px; background: color-mix(in srgb, var(--accent) 22%, transparent); color: var(--accent); font-weight: 600; }
	.face :global(.cloze.shown) { color: var(--text); background: color-mix(in srgb, var(--c-green) 26%, transparent); }
	.occ { position: relative; display: inline-block; max-width: 100%; user-select: none; }
	.occ img { display: block; max-width: 100%; max-height: 60vh; border-radius: var(--radius); }
	.mask, .shown { position: absolute; display: grid; place-items: center; border-radius: 3px; }
	.mask { background: color-mix(in srgb, var(--c-blue) 80%, var(--bg)); color: #fff; font-weight: 700; }
	.mask.target { background: var(--accent); color: #17130c; box-shadow: 0 0 0 2px var(--bg); }
	.shown { box-shadow: inset 0 0 0 2px var(--c-green); }
	.shown span { padding: 1px 6px; border-radius: 4px; background: var(--c-green); color: #0e1a10; font-size: 12px; font-weight: 600; transform: translateY(calc(-100% - 4px)); white-space: nowrap; }
</style>
