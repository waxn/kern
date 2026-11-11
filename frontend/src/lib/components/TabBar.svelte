<script lang="ts">
	import { FileText, Menu, PanelLeft, Plus, X } from '@lucide/svelte';
	import { goto } from '$app/navigation';
	import { newPage } from '#lib/actions.ts';
	import { prefs } from '#lib/state/prefs.svelte.ts';
	import { closeTab, tabInfo } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { modKey } from '#lib/util.ts';
</script>

<div class="tabbar">
	<button class="icon-btn mobile-only" title="Menu" onclick={() => (ui.mobileNav = true)}><Menu size={16} /></button>
	{#if !prefs.sidebarOpen}
		<button class="icon-btn desktop-only" title="Show sidebar ({modKey}+\)" onclick={() => (prefs.sidebarOpen = true)}>
			<PanelLeft size={15} />
		</button>
	{/if}
	<div class="tabs" role="tablist">
		{#each prefs.tabs as path, i (path)}
			{@const info = tabInfo(path)}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div class="tab" class:active={i === prefs.activeTab} role="tab" tabindex="0" aria-selected={i === prefs.activeTab}
				title={info.title}
				onclick={() => { prefs.activeTab = i; goto(path); }}
				onauxclick={(e) => { if (e.button === 1) { e.preventDefault(); closeTab(i); } }}>
				{#if info.icon}<span class="ico">{info.icon}</span>{:else if path.startsWith('/doc/')}<FileText size={13} strokeWidth={1.75} />{/if}
				<span class="truncate">{info.title}</span>
				<button class="close" title="Close tab (Alt+W)" onclick={(e) => { e.stopPropagation(); closeTab(i); }}><X size={12} /></button>
			</div>
		{/each}
		<button class="icon-btn new" title="New page in new tab" onclick={() => newPage(null, true)}><Plus size={14} /></button>
	</div>
</div>

<style>
	.tabbar { flex: none; display: flex; align-items: center; gap: 4px; height: 36px; padding: 0 8px; border-bottom: 1px solid var(--border); background: var(--bg-side); user-select: none; }
	.tabs { flex: 1; min-width: 0; display: flex; align-items: center; gap: 2px; height: 100%; overflow-x: auto; scrollbar-width: none; }
	.tab { flex: 0 1 190px; min-width: 76px; display: flex; align-items: center; gap: 6px; height: 27px; padding: 0 4px 0 9px; border-radius: var(--radius); color: var(--text-3); cursor: pointer; transition: background 0.12s var(--ease), color 0.12s var(--ease); }
	.tab:hover { background: var(--hover); color: var(--text-2); }
	.tab.active { background: var(--bg); color: var(--text); box-shadow: inset 0 0 0 1px var(--border); }
	.tab .truncate { flex: 1; }
	.ico { font-size: 13px; line-height: 1; }
	.close { flex: none; width: 18px; height: 18px; display: grid; place-items: center; border-radius: 3px; color: var(--text-3); opacity: 0; }
	.tab:hover .close, .tab.active .close { opacity: 1; }
	.close:hover { background: var(--active); color: var(--text); }
	.new { flex: none; margin-left: 2px; }
	.mobile-only { display: none; }
	@media (max-width: 760px) {
		.mobile-only { display: inline-grid; }
		.desktop-only { display: none; }
		.tab { flex-basis: 140px; }
	}
</style>
