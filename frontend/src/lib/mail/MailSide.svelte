<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // The sidebar in Mail mode: Kern's brand and the Notes | Mail switch on top,
  // Home (shared with Notes), then the mailboxes. Replaces Kern's notes sidebar
  // so Mail is three columns (mailboxes, list, conversation), not four.
  import './mail.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { House, PanelLeft } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import Logo from '#lib/components/Logo.svelte';
  import ModeSwitch from '#lib/components/ModeSwitch.svelte';
  import { prefs } from '#lib/state/prefs.svelte.ts';
  import { ui as kernUi } from '#lib/state/ui.svelte.ts';
  import { modKey } from '#lib/util.ts';
  import { loadFolders, loadInfo, loadPackages, loadScheduled } from './state.svelte.js';
  import Sidebar from './components/Sidebar.svelte';

  const path = $derived(page.url.pathname);
  // Inside /mail the mail shell loads all of this itself.
  onMount(() => {
    if (!page.url.pathname.startsWith('/mail')) {
      loadFolders().catch(() => {});
      loadInfo().catch(() => {});
      loadPackages();
      loadScheduled();
    }
  });
  function home(e) {
    e.preventDefault();
    kernUi.mobileNav = false;
    goto('/');
  }
</script>

<div class="mail-app mail-side" style:width="{prefs.sidebarWidth}px">
  <div class="head">
    <a class="brand" href="/" onclick={home}><Logo size={20} /> Kern</a>
    <span class="grow"></span>
    <ModeSwitch mode="mail" />
    <button class="icon-btn" title="Hide sidebar ({modKey}+\)" aria-label="Hide sidebar" onclick={() => { prefs.sidebarOpen = false; kernUi.mobileNav = false; }}>
      <PanelLeft size={15} />
    </button>
  </div>
  <a class="home" class:active={path === '/'} href="/" onclick={home}><House size={15} strokeWidth={1.75} /><span>Home</span></a>
  <Sidebar wide={true} embedded={true} />
</div>

<style>
  .mail-side { height: 100%; display: flex; flex-direction: column; background: var(--bg-side); border-right: 1px solid var(--border); user-select: none; }
  /* Doubled class: beats the shell's phone rule for Kern's own .sidebar. */
  .mail-side.mail-side :global(.mail-sidebar) { flex: 1; min-height: 0; width: 100% !important; border-right: 0; }
  .head { display: flex; align-items: center; gap: 6px; height: 40px; padding: 0 8px 0 12px; flex: none; }
  .grow { flex: 1; }
  .brand { display: flex; align-items: center; gap: 7px; font-weight: 650; letter-spacing: -0.01em; text-decoration: none; color: var(--text) !important; }
  .home { display: flex; align-items: center; gap: 9px; height: var(--row-h, 28px); margin: 2px 6px 0; padding: 0 8px 0 10px; border-radius: var(--radius-sm); color: var(--text-2) !important; text-decoration: none; font-size: 13.5px; flex: none; }
  .home:hover { background: var(--hover); color: var(--text) !important; }
  .home.active { background: var(--active); color: var(--text) !important; font-weight: 550; }
</style>
