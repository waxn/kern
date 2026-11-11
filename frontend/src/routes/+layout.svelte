<script lang="ts">
	import '../app.css';
	import 'katex/dist/katex.min.css';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { newPage } from '#lib/actions.ts';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ContextMenu from '#lib/components/ContextMenu.svelte';
	import SearchModal from '#lib/components/SearchModal.svelte';
	import Sidebar from '#lib/components/Sidebar.svelte';
	import TabBar from '#lib/components/TabBar.svelte';
	import Toasts from '#lib/components/Toasts.svelte';
	import CardEditor from '#lib/learn/CardEditor.svelte';
	import { ai } from '#lib/ai/ai.svelte.ts';
	import IntelPopup from '#lib/ai/IntelPopup.svelte';
	import MediaPlayer from '#lib/files/MediaPlayer.svelte';
	import { flushAll, syncPending } from '#lib/editor/doc.svelte.ts';
	import { CloudOff } from '@lucide/svelte';
	import { counts } from '#lib/learn/util.svelte.ts';
	import { comboOf, loadRemotePrefs, persistPrefs, prefs, resolvedTheme, shortcut } from '#lib/state/prefs.svelte.ts';
	import { closeTab, syncTabs } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import { mod } from '#lib/util.ts';
	import { goto } from '$app/navigation';

	let { children } = $props();
	let systemLight = $state(false);

	onMount(() => {
		loadRemotePrefs();
		ws.load().catch(() => {});
		counts.load();
		syncPending();
		const onFocus = () => counts.refresh();
		const onOnline = () => {
			ws.offline = false;
			ws.load().catch(() => {});
			syncPending();
			counts.refresh();
		};
		const onOffline = () => (ws.offline = true);
		// Save before the tab closes; edits also stay on this device until confirmed.
		const onHide = () => flushAll(true);
		const onVisibility = () => document.visibilityState === 'hidden' && flushAll(true);
		addEventListener('focus', onFocus);
		addEventListener('online', onOnline);
		addEventListener('offline', onOffline);
		addEventListener('pagehide', onHide);
		addEventListener('beforeunload', onHide);
		document.addEventListener('visibilitychange', onVisibility);
		if (!navigator.onLine) ws.offline = true;
		// While offline, check every few seconds whether the server is reachable again.
		const probe = setInterval(async () => {
			if (!ws.offline) return;
			try {
				const r = await fetch('/api/health', { cache: 'no-store' });
				if (r.ok) onOnline();
			} catch {
				/* still offline */
			}
		}, 4000);
		const mq = matchMedia('(prefers-color-scheme: light)');
		systemLight = mq.matches;
		const onChange = () => (systemLight = mq.matches);
		mq.addEventListener('change', onChange);
		return () => {
			mq.removeEventListener('change', onChange);
			removeEventListener('focus', onFocus);
			removeEventListener('online', onOnline);
			removeEventListener('offline', onOffline);
			removeEventListener('pagehide', onHide);
			removeEventListener('beforeunload', onHide);
			document.removeEventListener('visibilitychange', onVisibility);
			clearInterval(probe);
		};
	});

	$effect(() => persistPrefs());

	$effect(() => {
		void systemLight;
		const root = document.documentElement;
		root.dataset.theme = resolvedTheme();
		root.dataset.density = prefs.density;
		root.dataset.font = prefs.font;
		root.dataset.size = prefs.editorSize;
		if (prefs.accent) root.style.setProperty('--accent', prefs.accent);
		else root.style.removeProperty('--accent');
	});

	afterNavigate(() => syncTabs(page.url.pathname));

	function hasTextSelection(): boolean {
		const s = getSelection();
		return !!s && !s.isCollapsed && !!(s.anchorNode?.parentElement?.closest('[contenteditable]'));
	}

	function keydown(e: KeyboardEvent) {
		if (e.defaultPrevented || ui.capturingShortcut) return;
		const combo = comboOf(e);
		const inText = !!(e.target as HTMLElement)?.closest?.('input, textarea, [contenteditable]');
		const is = (action: string) => shortcut(action) === combo;
		const run = (fn: () => void) => {
			e.preventDefault();
			fn();
		};
		if (is('search') && !(combo === 'Mod+K' && hasTextSelection())) return run(() => (ui.searchOpen ? (ui.searchOpen = false) : ui.openSearch()));
		if (combo === 'Mod+P') return run(() => (ui.searchOpen ? (ui.searchOpen = false) : ui.openSearch()));
		// Works while typing too: it is meant to be summoned from inside a page.
		if (is('intelligence')) return run(() => (ai.popupOpen = !ai.popupOpen));
		if (is('toggleSidebar')) return run(() => (prefs.sidebarOpen = !prefs.sidebarOpen));
		if (is('togglePanel')) return run(() => (prefs.panelOpen = !prefs.panelOpen));
		if (is('newPage')) return run(() => newPage());
		if (is('closeTab')) return run(() => closeTab(prefs.activeTab));
		if ((is('nextTab') || is('prevTab')) && prefs.tabs.length > 1)
			return run(() => {
				const n = prefs.tabs.length;
				prefs.activeTab = (prefs.activeTab + (is('nextTab') ? 1 : n - 1)) % n;
				goto(prefs.tabs[prefs.activeTab]);
			});
		if (inText) return; // the rest would clash with typing
		if (is('tasks')) return run(() => goto('/tasks'));
		if (is('review')) return run(() => goto('/review'));
		if (is('home')) return run(() => goto('/'));
	}
</script>

<svelte:window onkeydown={keydown} />

<div class="app" class:side-closed={!prefs.sidebarOpen} class:mobile-nav={ui.mobileNav}>
	<div class="side"><Sidebar /></div>
	<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
	<div class="scrim" onclick={() => (ui.mobileNav = false)}></div>
	<main>
		<TabBar />
		{#if ws.offline}
			<div class="offline" role="status"><CloudOff size={14} />You're offline. Pages you've opened before are available, and your edits are kept on this device until you reconnect.</div>
		{/if}
		<div class="content">
			{#if ws.offline && !Object.keys(ws.docs).length}
				<div class="page"><div class="empty"><b>Cannot reach the Kern server</b>Check that the backend container is running, then reload.
					<div style="margin-top:12px"><button class="btn" onclick={() => ws.load().catch(() => {})}>Retry</button></div></div></div>
			{:else}
				{@render children()}
			{/if}
		</div>
	</main>
</div>

<SearchModal />
<ContextMenu />
<ConfirmDialog />
{#if ui.cardEditor}<CardEditor />{/if}
{#if ai.popupOpen}<IntelPopup />{/if}
<MediaPlayer />
<Toasts />

<style>
	.app { display: flex; height: 100dvh; }
	.side { flex: none; height: 100%; transition: margin-left 0.18s var(--ease); }
	.side-closed .side { display: none; }
	main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
	.content { flex: 1; min-height: 0; position: relative; }
	.offline { flex: none; display: flex; align-items: center; gap: 8px; padding: 6px 14px; font-size: 12.5px; color: var(--text); background: color-mix(in srgb, var(--c-orange) 18%, var(--bg)); border-bottom: 1px solid var(--border); }
	.scrim { display: none; }
	@media (max-width: 760px) {
		.side, .side-closed .side { display: block; position: fixed; z-index: 700; inset: 0 auto 0 0; transform: translateX(-102%); transition: transform 0.2s var(--ease); box-shadow: var(--shadow); }
		.side :global(.sidebar) { width: min(300px, 86vw) !important; }
		.mobile-nav .side { transform: none; }
		.mobile-nav .scrim { display: block; position: fixed; inset: 0; z-index: 699; background: rgba(0, 0, 0, 0.45); animation: fade 0.15s; }
	}
</style>
