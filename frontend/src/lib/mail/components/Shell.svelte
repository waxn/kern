<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onDestroy, onMount, untrack } from 'svelte';
  import { navigate, route } from '../router.svelte.js';
  import {
    current, folderByRole, info, list, net, loadAccountPrefs, loadAgenda, loadFolders, loadPackages, loadScheduled, loadInfo, loadThread, loadThreads, mailbox, prefs,
    READING_MIN, threadAction, ui, unreadInbox,
  } from '../state.svelte.js';
  import { startLive, stopLive, updateTitle } from '../live.js';
  import { installShortcuts } from '../shortcuts.js';
  import { closeCompose, openCompose, openReply, saveDraft } from '../compose.svelte.js';
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import ThreadList from './ThreadList.svelte';
  import ThreadView from './ThreadView.svelte';
  import Composer from './Composer.svelte';
  import Dialogs from './Dialogs.svelte';
  import SenderCard from './SenderCard.svelte';
  import ImageViewer from './ImageViewer.svelte';
  import BlocklistPage from '../pages/BlocklistPage.svelte';
  import PackagesPage from '../pages/PackagesPage.svelte';
  import ScheduledPage from '../pages/ScheduledPage.svelte';
  import FilesPage from '../pages/FilesPage.svelte';
  import { loadTemplates } from '../templates.svelte.js';
  import Icon from './Icon.svelte';

  // The mail area's own width (Kern's sidebar and panels take the rest).
  let width = $state(typeof innerWidth === 'number' ? innerWidth : 1200);
  const wide = $derived(width >= 860);
  const reading = $derived(width >= READING_MIN && prefs.readingPane);
  const showList = $derived(route.page === 'mail' && (reading ? true : !route.threadId));
  const showThread = $derived(route.page === 'mail' && !!route.threadId);

  onMount(async () => {
    await Promise.all([loadInfo().catch(() => {}), loadFolders().catch(() => {}), loadAgenda(), loadAccountPrefs(), loadPackages(), loadScheduled(), loadTemplates()]);
    startLive();
  });
  onDestroy(stopLive);

  // Reload the list when the view changes.
  $effect(() => {
    const key = route.page + '|' + route.view + '|' + route.q + '|' + mailbox.loaded;
    if (route.page === 'mail' && mailbox.loaded) {
      void key;
      untrack(() => loadThreads());
    }
  });

  // Load the open conversation.
  $effect(() => {
    const id = route.page === 'mail' ? route.threadId : null;
    untrack(() => {
      if (id) loadThread(id);
      else {
        current.thread = null;
        current.messages = [];
      }
    });
  });

  $effect(() => {
    void unreadInbox();
    updateTitle();
  });

  function focused() {
    if (list.focusIndex >= 0 && list.threads[list.focusIndex]) return list.threads[list.focusIndex];
    return null;
  }
  function targets() {
    if (list.selected.size) return [...list.selected];
    if (route.threadId) return [route.threadId];
    const f = focused();
    return f ? [f.id] : [];
  }
  function moveFocus(delta) {
    if (!list.threads.length) return;
    if (route.threadId) {
      const idx = list.threads.findIndex((t) => t.id === route.threadId);
      const next = list.threads[Math.max(0, Math.min(list.threads.length - 1, (idx < 0 ? 0 : idx) + delta))];
      if (next) {
        list.focusIndex = list.threads.indexOf(next);
        navigate({ threadId: next.id });
      }
      return;
    }
    list.focusIndex = Math.max(0, Math.min(list.threads.length - 1, list.focusIndex + delta));
    document.querySelector(`[data-thread-row="${list.threads[list.focusIndex].id}"]`)?.scrollIntoView({ block: 'nearest' });
  }
  function lastMessage() {
    if (!current.thread || current.thread.id !== route.threadId) return null;
    const m = current.messages;
    return m.length ? m[m.length - 1] : null;
  }

  const go = {
    'g i': () => navigate({ page: 'mail', view: 'inbox', threadId: null }),
    'g s': () => navigate({ page: 'mail', view: 'starred', threadId: null }),
    'g a': () => navigate({ page: 'mail', view: 'all', threadId: null }),
    'g d': () => navigate({ page: 'mail', view: folderByRole('drafts') ? 'drafts' : 'inbox', threadId: null }),
    'g p': () => navigate({ page: 'packages' }),
    'g f': () => navigate({ page: 'files' }),
    'g z': () => navigate({ page: 'mail', view: folderByRole('snoozed') ? 'snoozed' : 'inbox', threadId: null }),
  };

  function handle(key) {
    if (ui.viewer) return false;
    if (key === 'escape') {
      if (ui.senderCard) ui.senderCard = null;
      else if (ui.dialog) ui.dialog = null;
      else if (ui.composers.some((c) => !c.minimized)) {
        const c = ui.composers.findLast((c) => !c.minimized);
        closeCompose(c);
      } else if (route.threadId && !reading) navigate({ threadId: null });
      else if (list.selected.size) list.selected = new Set();
      return;
    }
    if (ui.dialog) return false;
    if (go[key]) return go[key]();
    if (key === '?') return (ui.dialog = { type: 'help' });
    if (key === 'c') return openCompose();
    if (key === '/') return (ui.searchFocusTick += 1);
    if (route.page !== 'mail') return false;
    switch (key) {
      case 'j': return moveFocus(1);
      case 'k': return moveFocus(-1);
      case 'o':
      case 'Enter': {
        if (route.threadId) {
          dispatchEvent(new CustomEvent('kern-mail:thread-key', { detail: 'toggle' }));
          return;
        }
        const f = focused();
        if (f) navigate({ threadId: f.id });
        return;
      }
      case 'n':
      case 'p':
        if (!route.threadId) return false;
        dispatchEvent(new CustomEvent('kern-mail:thread-key', { detail: key === 'n' ? 'next' : 'prev' }));
        return;
      case 'u': return navigate({ threadId: null });
      case 'x': {
        const f = focused() || (route.threadId && { id: route.threadId });
        if (!f) return;
        const s = new Set(list.selected);
        s.has(f.id) ? s.delete(f.id) : s.add(f.id);
        list.selected = s;
        return;
      }
      case 'e': return threadAction(targets(), 'archive').catch(() => {});
      case '#': return threadAction(targets(), 'trash').catch(() => {});
      case '!': {
        const ids = targets();
        if (ids.length) ui.dialog = { type: 'spam', ids };
        return;
      }
      case 's': {
        const ids = targets();
        if (!ids.length) return;
        const t = list.threads.find((x) => x.id === ids[0]) || current.thread;
        return threadAction(ids, t?.starred ? 'unstar' : 'star', { silent: true }).catch(() => {});
      }
      case 'shift+i': return threadAction(targets(), 'read', { silent: true }).catch(() => {});
      case 'shift+u': return threadAction(targets(), 'unread').catch(() => {});
      case 'v': {
        const ids = targets();
        if (ids.length) ui.dialog = { type: 'move', ids };
        return;
      }
      case 'l': {
        const ids = targets();
        if (ids.length) ui.dialog = { type: 'label', ids };
        return;
      }
      case 'r':
      case 'a':
      case 'f': {
        const m = lastMessage();
        if (m && route.threadId) openReply(m, key === 'r' ? 'reply' : key === 'a' ? 'reply_all' : 'forward');
        return;
      }
      case 'm': {
        const ids = targets();
        if (!ids.length) return;
        const t = list.threads.find((x) => x.id === ids[0]) || current.thread;
        return threadAction(ids, t?.muted ? 'unmute' : 'mute').catch(() => {});
      }
      case 'b': {
        const ids = targets();
        if (ids.length) ui.dialog = { type: 'snooze', ids };
        return;
      }
      case 't': {
        const ids = targets();
        if (!ids.length) return;
        const th = list.threads.find((x) => x.id === ids[0]) || current.thread;
        ui.dialog = { type: 'task', threadId: ids[0], subject: th?.subject || '' };
        return;
      }
      default:
        return false;
    }
  }

  let uninstall;
  // Leaving the tab (switching apps on a phone, closing a laptop lid):
  // push unsaved drafts to the server right away.
  function onVisibility() {
    if (document.visibilityState !== 'hidden') return;
    for (const c of ui.composers) {
      if (c.dirty && c.status === 'editing') saveDraft(c, { toServer: true });
    }
  }

  // Don't lose a message that hasn't reached the server yet.
  function onBeforeUnload(e) {
    if (ui.composers.some((c) => c.dirty || c.saving || c.status === 'sending')) {
      e.preventDefault();
      e.returnValue = '';
    }
  }
  onMount(() => {
    uninstall = installShortcuts(handle);
    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('visibilitychange', onVisibility);
  });
  onDestroy(() => {
    uninstall?.();
    window.removeEventListener('beforeunload', onBeforeUnload);
    document.removeEventListener('visibilitychange', onVisibility);
  });

  const workerBad = $derived(['offline', 'error', 'unconfigured'].includes(info.worker?.state));
</script>

<div class="shell" class:wide class:reading bind:clientWidth={width}>
  <Sidebar {wide} />
  <div class="main">
    <TopBar {wide} />
    {#if !net.online}
      <div class="banner off" role="status">You're offline. Mail will catch up as soon as you're back.</div>
    {:else if !net.live}
      <div class="banner off" role="status"><span class="spinner tiny"></span> Reconnecting…</div>
    {:else if workerBad}
      <div class="banner" role="status">
        {#if info.worker.state === 'unconfigured'}
          Your mail account isn't connected. Showing what's stored here. <a href="/settings?s=mail">Settings → Mail</a>
        {:else if info.worker.state === 'error'}
          Can't reach the mail server right now. Retrying… <span class="faint">{info.worker.lastError}</span>
        {:else}
          The mail service isn't running, so new mail won't arrive. Changes are saved when it's back.
        {/if}
      </div>
    {/if}
    {#if route.page === 'mail'}
      <div class="panes">
        {#if showList}
          <section class="list-pane" aria-label="Conversations"><ThreadList {wide} /></section>
        {/if}
        {#if showThread}
          <section class="thread-pane" aria-label="Conversation"><ThreadView {reading} /></section>
        {:else if reading}
          <section class="thread-pane empty">
            <div class="empty-state">
              <div class="seal" aria-hidden="true"><Icon name="mailOpen" size={40} stroke={1.3} /></div>
              <p class="display big">Nothing open</p>
              <p class="faint">Pick a conversation, or press <span class="kbd">j</span> <span class="kbd">k</span> to move and <span class="kbd">?</span> for every shortcut.</p>
            </div>
          </section>
        {/if}
      </div>
    {:else if route.page === 'blocklist'}
      <BlocklistPage />
    {:else if route.page === 'packages'}
      <PackagesPage />
    {:else if route.page === 'scheduled'}
      <ScheduledPage />
    {:else if route.page === 'files'}
      <FilesPage />
    {/if}
  </div>
</div>

{#if !wide && route.page === 'mail' && !route.threadId && !ui.composers.some((c) => !c.minimized)}
  <button class="fab" aria-label="Compose" onclick={() => openCompose()}><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4" /></svg></button>
{/if}
<div class="composers">
  {#each ui.composers.filter((c) => !(c.docked && route.page === 'mail' && route.threadId === c.threadId && current.thread?.id === c.threadId)) as c (c.key)}
    <Composer {c} {wide} />
  {/each}
</div>
<Dialogs />
<SenderCard />
<ImageViewer />

<style>
  .shell {
    height: 100%;
    display: flex;
    position: relative;
    overflow: hidden; /* the folder drawer slides in from here, not over Kern's sidebar */
  }
  .main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .panes {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .list-pane {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .reading .list-pane {
    flex: 0 0 var(--list-w);
    border-right: 1px solid var(--line);
  }
  .thread-pane {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .banner a { color: inherit; text-decoration: underline; }
  .banner.off { background: var(--bg-sunken); color: var(--text-2); display: flex; align-items: center; gap: 8px; }
  .spinner.tiny { width: 12px; height: 12px; border-width: 1.5px; }
  .thread-pane.empty {
    display: grid;
    place-items: center;
  }
  .empty-state {
    text-align: center;
    color: var(--text-3);
  }
  .empty-state { max-width: 320px; }
  .seal { color: var(--text-3); opacity: .7; display: inline-block; margin-bottom: 8px; }
  .empty-state p { margin: 6px 0; }
  .empty-state .big { font-size: 17px; color: var(--text-2); }
  .banner {
    background: var(--warn-soft);
    color: var(--warn);
    padding: 8px 18px;
    font-size: 12.5px;
    border-bottom: 1px solid var(--line);
  }
  .composers {
    position: fixed;
    right: 16px;
    bottom: 0;
    display: flex;
    align-items: flex-end;
    gap: 12px;
    z-index: 50;
    pointer-events: none;
  }
  .fab {
    position: fixed;
    right: 18px;
    bottom: max(18px, env(safe-area-inset-bottom));
    width: 56px;
    height: 56px;
    border-radius: var(--radius-lg);
    border: var(--cta-border);
    background: var(--cta-bg);
    color: var(--cta-text);
    box-shadow: var(--cta-shadow), var(--shadow-lg);
    display: grid;
    place-items: center;
    z-index: 40;
    cursor: pointer;
  }
  @media (max-width: 1023px) {
    .composers { right: 0; left: 0; }
  }
</style>
