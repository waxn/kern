<script lang="ts">
	// The top of the sidebar, identical in Notes and Mail so nothing moves when you switch:
	// hide-sidebar on the left, then Kern, then the Notes | Mail switch.
	import { goto } from '$app/navigation';
	import { PanelLeft } from '@lucide/svelte';
	import Logo from './Logo.svelte';
	import ModeSwitch from './ModeSwitch.svelte';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { modKey } from '#lib/util.ts';
	import type { Mode } from '#lib/state/mode.ts';

	let { mode }: { mode: Mode } = $props();

	function home(e: MouseEvent) {
		if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
		e.preventDefault();
		ui.mobileNav = false;
		goto('/');
	}
</script>

<div class="head">
	<button class="icon-btn hide" title="Hide sidebar ({modKey}+\)" aria-label="Hide sidebar"
		onclick={() => { prefs.sidebarOpen = false; ui.mobileNav = false; }}>
		<PanelLeft size={15} />
	</button>
	<a class="brand" href="/" onclick={home}><Logo size={20} /> Kern</a>
	<span class="grow"></span>
	<ModeSwitch {mode} />
</div>

<style>
	/* Fixed geometry (not inherited from the mode's own styles) so the two sidebars line up exactly. */
	.head { display: flex; align-items: center; gap: 6px; height: 40px; padding: 0 8px 0 6px; flex: none; font-size: 13.5px; }
	.hide { width: 26px; height: 26px; }
	.grow { flex: 1; }
	.brand { display: flex; align-items: center; gap: 7px; font-weight: 650; letter-spacing: -0.01em; text-decoration: none; color: var(--text) !important; }
</style>
