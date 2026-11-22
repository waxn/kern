<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // The sidebar in Mail mode. Its top is the same as Notes' (SidebarHead, then Search, New and
  // Home on the same rows) so switching modes moves nothing; the mailboxes follow.
  import './mail.css';
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { House, PenSquare, Search } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import SidebarHead from '#lib/components/SidebarHead.svelte';
  import { prefs } from '#lib/state/prefs.svelte.ts';
  import { ui as kernUi } from '#lib/state/ui.svelte.ts';
  import { modKey } from '#lib/util.ts';
  import { loadFolders, loadInfo, loadPackages, loadScheduled, openMailSearch } from './state.svelte.js';
  import { openCompose } from './compose.svelte.js';
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
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    kernUi.mobileNav = false;
    goto('/');
  }
  async function compose() {
    kernUi.mobileNav = false;
    if (!page.url.pathname.startsWith('/mail')) await goto(prefs.lastMailPath?.startsWith('/mail') ? prefs.lastMailPath : '/mail/inbox');
    openCompose();
  }
  function search() {
    kernUi.mobileNav = false;
    openMailSearch();
  }
</script>

<aside class="mail-side" style:width="{prefs.sidebarWidth}px">
  <SidebarHead mode="mail" />
  <div class="top">
    <button class="nav" onclick={search}><Search size={15} strokeWidth={1.75} /><span>Search</span><kbd>{modKey} K</kbd></button>
    <button class="nav" onclick={compose}><PenSquare size={15} strokeWidth={1.75} /><span>Compose</span><kbd>C</kbd></button>
    <a class="nav" class:active={path === '/'} href="/" onclick={home}><House size={15} strokeWidth={1.75} /><span>Home</span></a>
  </div>
  <div class="mail-app boxes"><Sidebar wide={true} embedded={true} /></div>
</aside>

<style>
  .mail-side { height: 100%; display: flex; flex-direction: column; background: var(--bg-side); border-right: 1px solid var(--border); user-select: none; font-size: 13.5px; }
  /* Same rows as Notes' sidebar (components/Sidebar.svelte .top / .nav). */
  .top { padding: 2px 6px; flex: none; }
  .nav { display: flex; align-items: center; gap: 8px; width: 100%; height: var(--row-h); padding: 0 8px; border-radius: var(--radius-sm); color: var(--text-2); text-decoration: none; }
  .nav:hover { background: var(--hover); color: var(--text); }
  .nav.active { background: var(--active); color: var(--text); }
  .nav span { flex: 1; text-align: left; }
  .nav kbd { opacity: 0; border: 0; background: none; transition: opacity 0.12s; }
  .nav:hover kbd { opacity: 1; }
  .boxes { flex: 1; min-height: 0; display: flex; flex-direction: column; height: auto; }
  /* Doubled class: beats the shell's phone rule for Kern's own .sidebar. */
  .boxes.boxes :global(.mail-sidebar) { flex: 1; min-height: 0; width: 100% !important; border-right: 0; }
</style>
