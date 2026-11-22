<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { href, navLink, navigate, route } from '../router.svelte.js';
  import { contextFolder, info, loadFolders, mailbox, parcels, scheduled, syncProgress, threadAction, ui } from '../state.svelte.js';
    import { api } from '../api.svelte.js';
  import Icon from './Icon.svelte';
  import { dropTarget } from '../dnd.js';

  import { ui as kernUi } from '#lib/state/ui.svelte.ts';

  // embedded: inside Kern's sidebar slot in Mail mode (MailSide.svelte), which
  // also does the phone drawer.
  let { wide, embedded = false } = $props();

  const ROLE_ICON = { inbox: 'inbox', snoozed: 'clock', drafts: 'file', sent: 'send', archive: 'archive', junk: 'spam', trash: 'trash' };
  const system = $derived(mailbox.folders.filter((f) => f.role && f.role !== 'all'));
  const custom = $derived(mailbox.folders.filter((f) => !f.role));
  const open = $derived(wide || ui.sidebarOpen);

  function viewKey(f) {
    return f.role && f.role !== 'all' ? f.role : 'f' + f.id;
  }
  function active(view) {
    return route.page === 'mail' && route.view === view;
  }
  function close() {
    ui.sidebarOpen = false;
    kernUi.mobileNav = false;
  }
  // What dropping conversations on a folder does.
  function folderDrop(f) {
    if (f.role === 'drafts' || f.role === 'sent' || f.role === 'snoozed') return null;
    if (f.id === contextFolder()) return null;
    return {
      onDrop: (ids) => {
        if (f.role === 'junk') ui.dialog = { type: 'spam', ids };
        else if (f.role === 'trash') threadAction(ids, 'trash').catch(() => {});
        else if (f.role === 'archive') threadAction(ids, 'archive').catch(() => {});
        else threadAction(ids, 'move', { dest: f.id }).catch(() => {});
      },
    };
  }
  function labelDrop(l) {
    return { onDrop: (ids) => threadAction(ids, 'label_add', { label: l.id }).catch(() => {}) };
  }
  function newFolder() {
    ui.dialog = {
      type: 'prompt', title: 'New folder', label: 'Folder name', action: 'Create',
      submit: async (name) => {
        await api.post('/folders', { name });
        await loadFolders();
      },
    };
  }
  function newLabel() {
    ui.dialog = {
      type: 'prompt', title: 'New label', label: 'Label name', action: 'Create',
      submit: async (name) => {
        await api.post('/labels', { name });
        await loadFolders();
      },
    };
  }
  const firstSync = $derived.by(() => {
    const all = Object.values(syncProgress);
    if (!all.length) return null;
    const done = all.reduce((n, p) => n + p.done, 0);
    const total = all.reduce((n, p) => n + p.total, 0);
    return total ? { done, total, pct: Math.min(100, Math.round((done / total) * 100)) } : null;
  });
  function syncLabel() {
    if (firstSync) return `Downloading mail · ${firstSync.done.toLocaleString()} / ${firstSync.total.toLocaleString()}`;
    const s = info.worker?.state;
    if (s === 'idle') return 'In sync';
    if (s === 'syncing' || s === 'working' || s === 'connecting') return info.worker.detail || 'Syncing…';
    if (s === 'error') return 'Connection problem';
    if (s === 'unconfigured') return 'Not configured';
    return 'Sync offline';
  }
  function badge(f) {
    if (f.role === 'drafts') return f.total;
    if (f.role === 'snoozed') return f.total;
    if (f.role === 'sent' || f.role === 'trash' || f.role === 'archive') return 0;
    return f.unread;
  }
</script>

{#if !wide && ui.sidebarOpen}
  <button class="scrim" aria-label="Close menu" onclick={close}></button>
{/if}

<nav class="sidebar mail-sidebar" class:open class:drawer={!wide && !embedded} class:embedded aria-label="Mailboxes">
  <div class="scroll body">
    <ul>
      {#each system as f (f.id)}
        <li>
          <a href={href({ page: 'mail', view: viewKey(f) })} use:navLink onclick={close} use:dropTarget={folderDrop(f)}
             class:active={active(viewKey(f))} aria-current={active(viewKey(f)) ? 'page' : undefined}>
            <Icon name={ROLE_ICON[f.role] || 'folder'} size={16} />
            <span class="name">{f.displayName}</span>
            {#if f.syncing}
              {@const p = syncProgress[f.id]}
              <span class="spinner tiny" title={p ? `Syncing ${p.done} of ${p.total}` : 'Syncing'}></span>
            {/if}
            {#if badge(f)}<span class="count num" class:strong={f.role === 'inbox'}>{badge(f)}</span>{/if}
          </a>
        </li>
        {#if f.role === 'inbox'}
          <li>
            <a href={href({ page: 'mail', view: 'starred' })} use:navLink onclick={close} class:active={active('starred')}>
              <Icon name="star" size={16} /><span class="name">Starred</span>
              {#if mailbox.starred}<span class="count num">{mailbox.starred}</span>{/if}
            </a>
          </li>
        {/if}
      {/each}
      <li>
        <a href={href({ page: 'mail', view: 'all' })} use:navLink onclick={close} class:active={active('all')}>
          <Icon name="all" size={16} /><span class="name">All mail</span>
        </a>
      </li>
      <li>
        <a href="/mail/files" use:navLink onclick={close} class:active={route.page === 'files'}
           aria-current={route.page === 'files' ? 'page' : undefined}>
          <Icon name="clip" size={16} /><span class="name">Files</span>
        </a>
      </li>
      {#if scheduled.items.length || route.page === 'scheduled'}
        <li>
          <a href="/mail/scheduled" use:navLink onclick={close} class:active={route.page === 'scheduled'}
             aria-current={route.page === 'scheduled' ? 'page' : undefined}>
            <Icon name="clock" size={16} /><span class="name">Scheduled</span>
            {#if scheduled.items.length}<span class="count num">{scheduled.items.length}</span>{/if}
          </a>
        </li>
      {/if}
      <li>
        <a href="/mail/stats" use:navLink onclick={close} class:active={route.page === 'stats'}
           aria-current={route.page === 'stats' ? 'page' : undefined}>
          <Icon name="stats" size={16} /><span class="name">Stats</span>
        </a>
      </li>
      <li>
          <a href="/mail/packages" use:navLink onclick={close} class:active={route.page === 'packages'}
             aria-current={route.page === 'packages' ? 'page' : undefined}>
            <Icon name="package" size={16} /><span class="name">Packages</span>
            {#if parcels.active.length}<span class="count num" title="On the way">{parcels.active.length}</span>{/if}
          </a>
        </li>
    </ul>

    <div class="section">
      <span class="ledger">Folders</span>
      <button class="icon-btn small" title="New folder" aria-label="New folder" onclick={newFolder}><Icon name="plus" size={14} /></button>
    </div>
    <ul>
      {#each custom as f (f.id)}
        <li>
          <a href={href({ page: 'mail', view: 'f' + f.id })} use:navLink onclick={close} class:active={active('f' + f.id)} use:dropTarget={folderDrop(f)}
             style:padding-left={`${14 + Math.min(4, (f.name.split(f.delimiter || '/').length - 1)) * 12}px`}>
            <Icon name="folder" size={16} />
            <span class="name">{f.displayName}</span>
            {#if f.unread}<span class="count num">{f.unread}</span>{/if}
          </a>
        </li>
      {:else}
        <li class="none">None yet</li>
      {/each}
    </ul>

    <div class="section">
      <span class="ledger">Labels</span>
      <button class="icon-btn small" title="New label" aria-label="New label" onclick={newLabel}><Icon name="plus" size={14} /></button>
    </div>
    <ul>
      {#each mailbox.labels as l (l.id)}
        <li>
          <a href={href({ page: 'mail', view: 'l' + l.id })} use:navLink onclick={close} class:active={active('l' + l.id)} use:dropTarget={labelDrop(l)}>
            <span class="tag" style:--c={l.color || 'var(--text-3)'}></span>
            <span class="name">{l.name}</span>
          </a>
          <button class="edit" title="Edit label" aria-label={`Edit label ${l.name}`}
                  onclick={() => (ui.dialog = { type: 'label-edit', label: l })}>
            <Icon name="more" size={14} />
          </button>
        </li>
      {:else}
        <li class="none">None yet</li>
      {/each}
    </ul>

    <div class="section"><span class="ledger">System</span></div>
    <ul>
      <li><a href="/mail/blocklist" use:navLink onclick={close} class:active={route.page === 'blocklist'}><Icon name="block" size={16} /><span class="name">Blocked senders</span></a></li>
      <li><a href="/settings?s=mail" onclick={close}><Icon name="settings" size={16} /><span class="name">Mail settings</span></a></li>
    </ul>
  </div>

  <div class="foot">
    <div class="account">
      <div class="addr num" title={info.address}>{info.address || 'not configured'}</div>
      <div class="sync" class:bad={['error', 'offline', 'unconfigured'].includes(info.worker?.state)}>
        <span class="led"></span>{syncLabel()}
      </div>
      {#if firstSync}
        <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={firstSync.pct} aria-label="First sync progress">
          <span style:width={`${firstSync.pct}%`}></span>
        </div>
      {/if}
    </div>
  </div>
</nav>

<style>
  .sidebar {
    width: var(--sidebar-w);
    flex: none;
    display: flex;
    flex-direction: column;
    height: 100%;
    border-right: 1px solid var(--line);
    background: var(--bg-side);
  }
  .sidebar.embedded { background: transparent; }
  .sidebar.drawer {
    position: absolute;
    z-index: 80;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(300px, 86vw);
    transform: translateX(-102%);
    transition: transform .24s var(--ease);
    box-shadow: var(--shadow-lg);
    background-color: var(--bg-side);
  }
  .sidebar.drawer.open { transform: none; }
  .scrim {
    position: absolute;
    inset: 0;
    background: rgb(0 0 0 / .38);
    border: 0;
    z-index: 79;
    animation: fade-in .2s;
  }
  .body { flex: 1; padding: 0 6px 12px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li a {
    position: relative;
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--row-h, 28px);
    padding: 0 8px;
    border-radius: var(--radius-sm);
    color: var(--text-2);
    text-decoration: none;
    font-size: 13.5px;
  }
  li a:hover { background: var(--bg-hover); color: var(--text); }
  li a:global(.drop-hover) { background: var(--accent-soft); color: var(--text); box-shadow: inset 0 0 0 1.5px var(--accent); }
  li a.active { background: var(--active); color: var(--text); font-weight: 550; }
  li a :global(svg) { flex: none; opacity: .85; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count { font-size: 11.5px; color: var(--text-3); }
  .count.strong { color: var(--accent); font-weight: 600; }
  li { position: relative; }
  .edit {
    position: absolute; right: 6px; top: 6px;
    border: 0; background: none; color: var(--text-3); cursor: pointer; display: grid; place-items: center;
    width: 22px; height: 22px; border-radius: 4px; opacity: 0;
  }
  li:hover .edit, .edit:focus-visible { opacity: 1; }
  .edit:hover { background: var(--bg-active); color: var(--text); }
  .tag {
    width: 11px; height: 11px; flex: none; margin: 0 3px;
    background: var(--c); clip-path: polygon(0 0, 70% 0, 100% 50%, 70% 100%, 0 100%);
  }
  .section { display: flex; align-items: center; justify-content: space-between; margin: 14px 4px 2px 8px; }
  .none { padding: 3px 14px 6px; font-size: 12.5px; color: var(--text-3); font-style: italic; }
  .foot { display: flex; align-items: center; gap: 8px; padding: 10px 12px 12px 14px; border-top: 1px solid var(--line); }
  .account { flex: 1; min-width: 0; }
  .addr { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
  .sync { font-size: 11.5px; color: var(--text-3); display: flex; align-items: center; gap: 6px; margin-top: 2px; }
  .led { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 20%, transparent); }
  .sync.bad .led { background: var(--warn); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 20%, transparent); }
  .spinner.tiny { width: 12px; height: 12px; border-width: 1.5px; }
  .progress { height: 3px; margin-top: 6px; border-radius: 2px; background: var(--bg-sunken); overflow: hidden; }
  .progress span { display: block; height: 100%; background: var(--accent); transition: width .4s var(--ease); }
</style>
