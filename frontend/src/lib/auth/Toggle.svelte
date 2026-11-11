<script lang="ts">
	let { checked = $bindable(false), label = '', disabled = false, onchange }: { checked?: boolean; label?: string; disabled?: boolean; onchange?: (v: boolean) => void } = $props();
</script>

<button type="button" class="sw" class:on={checked} role="switch" aria-checked={checked} aria-label={label} {disabled} onclick={() => { checked = !checked; onchange?.(checked); }}>
	<i></i>
</button>

<style>
	.sw { flex: none; width: 36px; height: 20px; border-radius: 10px; padding: 2px; background: var(--border-strong); transition: background 0.15s var(--ease); }
	.sw i { display: block; width: 16px; height: 16px; border-radius: 50%; background: var(--text-2); transition: transform 0.15s var(--ease), background 0.15s; }
	.sw.on { background: color-mix(in srgb, var(--accent) 80%, var(--bg)); }
	.sw.on i { transform: translateX(16px); background: #17130c; }
	.sw:disabled { opacity: 0.5; }
</style>
