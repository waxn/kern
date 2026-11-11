<script lang="ts" module>
	export interface TipState { x: number; y: number; title: string; sub?: string }
</script>

<script lang="ts">
	let { tip }: { tip: TipState | null } = $props();
</script>

{#if tip}
	<div class="tip" style:left="{tip.x}px" style:top="{tip.y}px" role="tooltip">
		<b>{tip.title}</b>{#if tip.sub}<span>{tip.sub}</span>{/if}
	</div>
{/if}

<style>
	.tip {
		position: fixed; z-index: 900; pointer-events: none; transform: translate(-50%, calc(-100% - 10px));
		display: flex; flex-direction: column; gap: 1px; padding: 5px 8px; border-radius: var(--radius);
		background: var(--surface); box-shadow: var(--shadow); font-size: 12px; white-space: nowrap;
	}
	b { font-weight: 600; color: var(--text); }
	span { color: var(--text-2); }
</style>
