<script lang="ts">
	// With one tab open there is no tab strip: just where you are, in the corner,
	// and a "+" that opens a new tab (the strip then appears). The menu and
	// "show sidebar" buttons that lived in the strip come along.
	import { FileText, Menu, PanelLeft, Plus } from '@lucide/svelte';
	import { page } from '$app/state';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { newTab, tabInfo } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { modKey } from '#lib/util.ts';

	/** location: show the page title (pages with their own breadcrumbs pass false). */
	let { location = true, plus = true, menu = true }: { location?: boolean; plus?: boolean; menu?: boolean } = $props();
	const path = $derived(page.url.pathname);
	const info = $derived(tabInfo(path));
</script>

<div class="corner">
	{#if menu}<button class="icon-btn mobile-only" title="Menu" aria-label="Menu" onclick={() => (ui.mobileNav = true)}><Menu size={16} /></button>{/if}
	{#if menu && !prefs.sidebarOpen}
		<button class="icon-btn desktop-only" title="Show sidebar ({modKey}+\)" aria-label="Show sidebar" onclick={() => (prefs.sidebarOpen = true)}><PanelLeft size={15} /></button>
	{/if}
	{#if location}
		<span class="where truncate" title={info.title}>
			{#if info.icon}<span class="ico">{info.icon}</span>{:else if path.startsWith('/doc/')}<FileText size={13} strokeWidth={1.75} />{/if}
			{info.title}
		</span>
	{/if}
	{#if plus}
		<button class="icon-btn plus" title="New tab" aria-label="New tab" onclick={() => newTab(path)}><Plus size={14} /></button>
	{/if}
</div>

<style>
	.corner { display: inline-flex; align-items: center; gap: 2px; min-width: 0; color: var(--text-2); }
	.where { display: inline-flex; align-items: center; gap: 6px; max-width: 260px; padding: 2px 6px; font-size: 13px; color: var(--text-2); }
	.ico { font-size: 13px; line-height: 1; }
	.plus { width: 24px; height: 24px; color: var(--text-3); }
	.plus:hover { color: var(--text); }
	.mobile-only { display: none; }
	@media (max-width: 560px) { .where { display: none; } }
	@media (max-width: 760px) {
		.mobile-only { display: inline-grid; }
		.desktop-only { display: none; }
	}
</style>
