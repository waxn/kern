<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { navLink, navigate, route } from '../router.svelte.js';
  import {
    agenda, clearedToday, contextFolder, syncProgress, errorToast, folderById, info, labelById, list, loadAgenda, loadFolders, loadThreads,
    threadAction, toast, ui, viewTitle,
  parcels, } from '../state.svelte.js';
  import { displayName, highlight, participantsLabel, searchWords, shortDate, snoozeLabel, timeGroup } from '../format.js';
  import { ago } from '../when.js';
  import { packageSummary } from '../packages.js';
  import { swipe } from '../swipe.js';
  import { startDrag } from '../dnd.js';
  import { api } from '../api.svelte.js';
  import { openDraft } from '../compose.svelte.js';
  import Icon from './Icon.svelte';

  let { wide } = $props();
  let sentinel = $state();

  const ctx = $derived(folderById(contextFolder()));
  const role = $derived(ctx?.role || '');
  const selecting = $derived(list.selected.size > 0);
  const allSelected = $derived(list.threads.length > 0 && list.selected.size === list.threads.length);
  const unreadHere = $derived(list.threads.filter((t) => t.unread > 0).length);

  // Infinite scroll.
  $effect(() => {
    if (!sentinel) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && list.next && !list.loading) loadThreads({ more: true });
    }, { rootMargin: '400px' });
    io.observe(sentinel);
    return () => io.disconnect();
  });

  async function open(t) {
    list.focusIndex = list.threads.indexOf(t);
    if (role === 'drafts') {
      // A draft opens straight in the composer.
      try {
        const d = await api.get(`/threads/${t.id}`);
        const draft = [...d.messages].reverse().find((m) => m.isDraft && m.folder.role === 'drafts');
        if (draft) {
          openDraft(draft.draftId ?? draft);
          return;
        }
      } catch (e) {
        errorToast(e);
        return;
      }
    }
    navigate({ threadId: t.id });
  }
  async function markAllRead() {
    try {
      const r = await api.post(`/folders/${ctx.id}/read-all`);
      for (const t of list.threads) t.unread = 0;
      toast(r.count ? `Marked ${r.count} message${r.count === 1 ? '' : 's'} as read` : 'Nothing unread');
      loadFolders();
    } catch (e) {
      errorToast(e);
    }
  }
  function toggle(t, e) {
    e.stopPropagation();
    const s = new Set(list.selected);
    s.has(t.id) ? s.delete(t.id) : s.add(t.id);
    list.selected = s;
  }
  function toggleAll() {
    list.selected = allSelected ? new Set() : new Set(list.threads.map((t) => t.id));
  }
  function star(t, e) {
    e.stopPropagation();
    threadAction([t.id], t.starred ? 'unstar' : 'star', { silent: true }).catch(() => {});
  }
  function quick(t, action, e) {
    e.stopPropagation();
    threadAction([t.id], action).catch(() => {});
  }
  function bulk(action, extra) {
    threadAction([...list.selected], action, extra).catch(() => {});
  }
  function folderChips(t) {
    if (route.view !== 'search' && route.view !== 'all' && route.view !== 'starred' && !route.view.startsWith('l')) return [];
    return (t.folders || []).map(folderById).filter((f) => f && f.role !== 'sent' && f.role !== 'archive');
  }
  const isTrash = $derived(role === 'trash' || role === 'junk');
  const EMPTY = {
    drafts: ['No drafts', 'Unfinished messages are saved here, and on your server.'],
    sent: ['Nothing sent yet', ''],
    archive: ['Nothing archived', 'Press e on a conversation to file it away here.'],
    junk: ['No junk', 'Reported and blocked mail lands here.'],
    trash: ['Trash is empty', ''],
    starred: ['No stars', 'Press s on anything you want to find again quickly.'],
    all: ['No mail yet', 'If this is a fresh setup, the first sync may still be running.'],
    label: ['Nothing with this label', 'Press l on a conversation to label it.'],
    '': ['Empty folder', ''],
  };

  // The ledger line under the title: what's here and what's coming back.
  const subtitle = $derived.by(() => {
    if (route.view === 'search') return [`${list.threads.length}${list.next ? '+' : ''} results`];
    if (role === 'snoozed') {
      const next = agenda.snoozes[0];
      return [`${list.threads.length} snoozed`, next ? `next back ${snoozeLabel(next.until)}` : ''].filter(Boolean);
    }
    if (role === 'inbox') {
      const today = new Date().toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
      const parts = [today, unreadHere ? `${unreadHere} unread` : 'all read'];
      const soon = agenda.snoozes.filter((s) => new Date(s.until) - Date.now() < 36 * 3600e3);
      if (soon.length) parts.push(`${soon.length} back ${snoozeLabel(soon[0].until).toLowerCase()}`);
      const waiting = agenda.followups.filter((f) => f.status === 'waiting').length;
      if (waiting) parts.push(`waiting on ${waiting} ${waiting === 1 ? 'reply' : 'replies'}`);
      parts.push(...packageSummary(parcels.active, new Date(), { short: true }).map((text) => ({ text, href: '/packages' })));
      return parts;
    }
    if (role === '') return [unreadHere ? `${unreadHere} unread` : 'all read'];
    return [`${list.threads.length}${list.next ? '+' : ''} conversations`];
  });
  const hits = $derived(route.view === 'search' ? searchWords(route.q) : []);
  const nudges = $derived(role === 'inbox' ? agenda.followups.filter((f) => f.status === 'nudged') : []);
  const grouped = $derived(role !== 'snoozed' && !selecting);
  const cleared = $derived(list.threads.length === 0 ? clearedToday() : 0);

  async function nudgeDone(f) {
    try {
      await api.post(`/followups/${f.id}`, { action: 'done' });
      loadAgenda();
    } catch (e) {
      errorToast(e);
    }
  }
  function swipeOpts(t) {
    return {
      onRight: () => threadAction([t.id], role === 'archive' || isTrash ? 'inbox' : 'archive').catch(() => {}),
      onLeft: () => (ui.dialog = { type: 'snooze', ids: [t.id] }),
    };
  }
</script>

<div class="head">
  {#if selecting}
    <div class="bulk">
      <input type="checkbox" checked={allSelected} indeterminate={!allSelected} onchange={toggleAll} aria-label="Select all" />
      <span class="n num">{list.selected.size} selected</span>
      <div class="acts">
        {#if role !== 'archive' && !isTrash}<button class="icon-btn" title="Archive (e)" aria-label="Archive" onclick={() => bulk('archive')}><Icon name="archive" /></button>{/if}
        {#if role !== 'snoozed' && !isTrash}<button class="icon-btn" title="Snooze (b)" aria-label="Snooze" onclick={() => (ui.dialog = { type: 'snooze', ids: [...list.selected] })}><Icon name="clock" /></button>{/if}
        {#if role === 'junk'}
          <button class="btn small" onclick={() => bulk('not_spam')}>Not spam</button>
        {:else}
          <button class="icon-btn" title="Report spam (!)" aria-label="Report spam" onclick={() => (ui.dialog = { type: 'spam', ids: [...list.selected] })}><Icon name="spam" /></button>
        {/if}
        {#if isTrash}
          <button class="btn small danger" onclick={() => (ui.dialog = { type: 'confirm', title: 'Delete forever?', body: `${list.selected.size} conversation(s) will be permanently deleted from the server. This can't be undone.`, action: 'Delete forever', danger: true, submit: () => bulk('delete_forever') })}>Delete forever</button>
        {:else}
          <button class="icon-btn" title="Trash (#)" aria-label="Move to Trash" onclick={() => bulk('trash')}><Icon name="trash" /></button>
        {/if}
        <button class="icon-btn" title="Mark read" aria-label="Mark read" onclick={() => bulk('read', { silent: true })}><Icon name="mailOpen" /></button>
        <button class="icon-btn" title="Mark unread" aria-label="Mark unread" onclick={() => bulk('unread')}><Icon name="mail" /></button>
        <button class="icon-btn" title="Move (v)" aria-label="Move" onclick={() => (ui.dialog = { type: 'move', ids: [...list.selected] })}><Icon name="move" /></button>
        <button class="icon-btn" title="Label (l)" aria-label="Label" onclick={() => (ui.dialog = { type: 'label', ids: [...list.selected] })}><Icon name="label" /></button>
      </div>
      <button class="icon-btn" aria-label="Clear selection" onclick={() => (list.selected = new Set())}><Icon name="close" /></button>
    </div>
  {:else}
    <div class="titles">
      <h2 class="display">{viewTitle()}</h2>
      <span class="ledger sub">{#each subtitle as part, i}{#if i}<span class="sep">·</span>{/if}{#if part.href}<a class="sublink" href={part.href} use:navLink>{part.text}</a>{:else}<span>{part}</span>{/if}{/each}</span>
    </div>
    {#if route.view !== 'search' && role !== 'snoozed' && role !== 'sent' && role !== 'drafts'}
      <div class="seg" role="group" aria-label="Show">
        <button class:on={!list.unreadOnly} aria-pressed={!list.unreadOnly} onclick={() => { list.unreadOnly = false; loadThreads(); }}>All</button>
        <button class:on={list.unreadOnly} aria-pressed={list.unreadOnly} onclick={() => { list.unreadOnly = true; loadThreads(); }}>Unread</button>
      </div>
    {/if}
    {#if ctx && unreadHere > 0}
      <button class="icon-btn" title="Mark all as read" aria-label="Mark all as read" onclick={markAllRead}><Icon name="mailOpen" size={17} /></button>
    {/if}
    <button class="icon-btn" title="Refresh" aria-label="Refresh" onclick={() => loadThreads()}><Icon name="refresh" size={17} /></button>
  {/if}
</div>

{#if isTrash && list.threads.length && !selecting}
  <div class="notice">
    {role === 'junk' ? 'Junk' : 'Trash'} is emptied by your mail server according to its own rules.
  </div>
{/if}

<div class="scroll rows" role="list">
  {#if nudges.length}
    <div class="nudges" aria-label="Waiting for replies">
      {#each nudges as f (f.id)}
        <div class="nudge">
          <Icon name="bell" size={15} />
          <button class="ntext" onclick={() => f.threadId && navigate({ threadId: f.threadId })}>
            <span class="ledger">No reply · sent {ago(new Date(f.sentAt))}</span>
            <span class="nsub">{f.subject || '(no subject)'}</span>
            <span class="nto">to {(f.recipients || []).map((r) => displayName(r)).join(', ') || 'them'}</span>
          </button>
          <button class="icon-btn small" title="Clear" aria-label="Clear nudge" onclick={() => nudgeDone(f)}><Icon name="check" size={15} /></button>
        </div>
      {/each}
    </div>
  {/if}
  {#if list.error}
    <div class="state error">{list.error} <button class="btn small" onclick={() => loadThreads()}>Retry</button></div>
  {:else if list.loading && !list.threads.length}
    <div aria-hidden="true">
      {#each Array(9) as _, i}
        <div class="row skel-row">
          <div class="content">
            <div class="line1"><span class="skel" style:width={`${30 + ((i * 37) % 30)}%`} style:height="11px"></span><span class="skel" style="width:40px;height:10px;margin-left:auto"></span></div>
            <div class="line2"><span class="skel" style:width={`${55 + ((i * 53) % 35)}%`} style:height="10px"></span></div>
          </div>
        </div>
      {/each}
    </div>
  {:else if !list.loading && !list.threads.length}
    <div class="state">
      {#if route.view === 'search'}
        <p class="display big">No matches</p>
        <p class="faint">Nothing for “{route.q}”. Try fewer words, or <code>in:anywhere</code> to include Trash and Junk.</p>
      {:else if ctx && (ctx.syncing || syncProgress[ctx.id])}
        <div class="spinner" style="margin: 0 auto 14px"></div>
        <p class="display big">Fetching your mail…</p>
        <p class="faint">
          {#if syncProgress[ctx.id]}{syncProgress[ctx.id].done.toLocaleString()} of {syncProgress[ctx.id].total.toLocaleString()} messages so far. Newest first.{:else}The first sync is running. Newest messages arrive first.{/if}
        </p>
      {:else if role === 'inbox'}
        <div class="stamp display" aria-hidden="true">All clear</div>
        {#if cleared}
          <p class="cleared">You cleared <b class="num">{cleared}</b> conversation{cleared === 1 ? '' : 's'} today.</p>
        {/if}
        <p class="faint">Nothing needs you right now.{#if agenda.snoozes.length} {agenda.snoozes.length} snoozed will come back {snoozeLabel(agenda.snoozes[0].until).toLowerCase()}.{/if}</p>
      {:else if role === 'snoozed'}
        <p class="display big">Nothing snoozed</p>
        <p class="faint">Press <span class="kbd">b</span> on a conversation to bring it back later.</p>
      {:else}
        {@const empty = EMPTY[route.view.startsWith('l') ? 'label' : role || route.view] || ['Empty', '']}
        <p class="display big">{empty[0]}</p>
        {#if empty[1]}<p class="faint">{empty[1]}</p>{/if}
      {/if}
    </div>
  {/if}

  {#each list.threads as t, i (t.id)}
    {#if grouped && (i === 0 || timeGroup(list.threads[i - 1].lastDate) !== timeGroup(t.lastDate))}
      <div class="group ledger" role="presentation">{timeGroup(t.lastDate)}</div>
    {/if}
    <div class="swipe-wrap">
    <span class="reveal right"><Icon name={role === 'archive' || isTrash ? 'inbox' : 'archive'} size={18} /> {role === 'archive' || isTrash ? 'Inbox' : 'Archive'}</span>
    <span class="reveal left">Snooze <Icon name="clock" size={18} /></span>
    <div
      use:swipe={swipeOpts(t)}
      draggable={wide ? 'true' : undefined}
      ondragstart={(e) => startDrag(e, list.selected.has(t.id) ? [...list.selected] : [t.id])}
      class="row"
      class:unread={t.unread > 0}
      class:open={route.threadId === t.id}
      class:focus={list.focusIndex === i}
      class:checked={list.selected.has(t.id)}
      data-thread-row={t.id}
      role="listitem"
    >
      <button class="hit" title={t.subject || '(no subject)'}
              aria-label={`${t.unread ? 'Unread: ' : ''}${t.subject || '(no subject)'}, from ${participantsLabel(t.participants, info.address)}, ${shortDate(t.lastDate)}${t.risk === 'high' ? ', high phishing risk' : ''}${t.starred ? ', starred' : ''}`}
              onclick={() => open(t)}></button>
      <span class="dot" aria-hidden="true"></span>
      <input type="checkbox" class="sel" checked={list.selected.has(t.id)} onclick={(e) => toggle(t, e)} aria-label="Select" />
      <div class="content">
        <div class="line1">
          <span class="who">
            {participantsLabel(t.participants, info.address)}
            {#if t.count > 1}<span class="cnt num">{t.count}</span>{/if}
          </span>
          {#if t.risk === 'high' || t.risk === 'medium'}
            <span class="risk {t.risk}" title={t.risk === 'high' ? 'High phishing risk' : 'Medium phishing risk'}>
              <Icon name="shieldAlert" size={14} />
            </span>
          {/if}
          {#if t.hasAttachments}<span class="faint clip"><Icon name="clip" size={14} /></span>{/if}
          {#if t.muted}<span class="faint clip" title="Muted"><Icon name="mute" size={14} /></span>{/if}
          {#if t.followup}
            <span class="fup num" class:hot={t.followup.status === 'nudged'} title={t.followup.status === 'nudged' ? 'No reply yet' : 'Waiting for a reply'}>
              <Icon name="bell" size={12} />{t.followup.status === 'nudged' ? 'no reply' : ''}
            </span>
          {/if}
          {#if t.package}
            <span class="pkg pk-{t.package.status}" title={`Package: ${t.package.label}`}><Icon name={t.package.status === 'delivered' ? 'check' : 'package'} size={12} /> {t.package.label}</span>
          {/if}
          {#if t.snoozeUntil}
            <span class="snz num" title="Snoozed"><Icon name="clock" size={12} /> {snoozeLabel(t.snoozeUntil)}</span>
          {:else}
            <time class="date num" datetime={t.lastDate}>{shortDate(t.lastDate)}</time>
          {/if}
        </div>
        <div class="line2">
          <span class="subject">{#each highlight(t.subject || '(no subject)', hits) as p}{#if p.hit}<mark>{p.text}</mark>{:else}{p.text}{/if}{/each}</span>
          <span class="snippet">{#each highlight(t.snippet, hits) as p}{#if p.hit}<mark>{p.text}</mark>{:else}{p.text}{/if}{/each}</span>
        </div>
        {#if t.labels.length || folderChips(t).length}
          <div class="chips">
            {#each folderChips(t) as f}<span class="chip">{f.displayName}</span>{/each}
            {#each t.labels as lid}
              {@const l = labelById(lid)}
              {#if l}<span class="chip label" style:--c={l.color || 'var(--text-3)'}>{l.name}</span>{/if}
            {/each}
          </div>
        {/if}
      </div>
      <button class="star" class:on={t.starred} aria-label={t.starred ? 'Unstar' : 'Star'} aria-pressed={t.starred} onclick={(e) => star(t, e)}>
        <Icon name="star" size={16} fill={t.starred ? 'currentColor' : 'none'} />
      </button>
      {#if wide}
        <div class="hover-acts">
          {#if role !== 'archive' && !isTrash}
            <button class="icon-btn small" title="Archive" aria-label="Archive" onclick={(e) => quick(t, 'archive', e)}><Icon name="archive" size={16} /></button>
          {/if}
          {#if role === 'snoozed'}
            <button class="icon-btn small" title="Unsnooze" aria-label="Unsnooze" onclick={(e) => quick(t, 'unsnooze', e)}><Icon name="inbox" size={16} /></button>
          {:else if !isTrash}
            <button class="icon-btn small" title="Snooze" aria-label="Snooze" onclick={(e) => { e.stopPropagation(); ui.dialog = { type: 'snooze', ids: [t.id] }; }}><Icon name="clock" size={16} /></button>
          {/if}
          {#if !isTrash}
            <button class="icon-btn small" title="Trash" aria-label="Trash" onclick={(e) => quick(t, 'trash', e)}><Icon name="trash" size={16} /></button>
          {/if}
          <button class="icon-btn small" title={t.unread ? 'Mark read' : 'Mark unread'} aria-label={t.unread ? 'Mark read' : 'Mark unread'}
                  onclick={(e) => { e.stopPropagation(); threadAction([t.id], t.unread ? 'read' : 'unread', { silent: true }).catch(() => {}); }}>
            <Icon name={t.unread ? 'mailOpen' : 'mail'} size={16} />
          </button>
        </div>
      {/if}
    </div>
    </div>
  {/each}
  <div bind:this={sentinel} class="sentinel">
    {#if list.loading}<div class="spinner"></div>{/if}
  </div>
</div>

<style>
  .head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 74px;
    padding: 12px 12px 10px 22px;
    flex: none;
    border-bottom: 1px solid var(--line);
  }
  .seg { display: inline-flex; background: var(--bg-sunken); border-radius: var(--radius-sm); padding: 2px; flex: none; }
  .seg button { border: 0; background: none; padding: 3px 9px; border-radius: calc(var(--radius-sm) - 1px); cursor: pointer; font-size: 12px; color: var(--text-2); }
  .seg button.on { background: var(--bg-elev); color: var(--text); box-shadow: var(--shadow-sm); font-weight: 600; }
  .titles { flex: 1; min-width: 0; display: grid; gap: 3px; }
  h2 { font-size: 28px; line-height: 1.05; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bulk { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; }
  .bulk input { accent-color: var(--accent); }
  .bulk .n { font-size: 12px; white-space: nowrap; }
  .bulk .acts { display: flex; align-items: center; gap: 2px; flex: 1; overflow-x: auto; }
  .notice { font-size: 12px; padding: 8px 22px; border-bottom: 1px dashed var(--line-strong); color: var(--text-3); font-style: italic; }
  .rows { flex: 1; }
  .sub { display: flex; flex-wrap: wrap; gap: 0 6px; }
  .sub .sep { opacity: .5; }
  .group {
    position: sticky; top: 0; z-index: 3; padding: 14px 22px 6px; background-color: var(--bg);
    border-bottom: 1px solid var(--line); font-size: 10px;
  }
  .nudges { padding: 10px 12px 2px; display: grid; gap: 6px; }
  .nudge {
    display: flex; align-items: center; gap: 10px; padding: 8px 6px 8px 12px; border-radius: var(--radius);
    border: 1px solid var(--accent); background: var(--accent-soft);
  }
  .nudge > :global(svg) { color: var(--accent-ink); flex: none; }
  .ntext { flex: 1; min-width: 0; display: grid; gap: 1px; border: 0; background: none; text-align: left; cursor: pointer; color: var(--text); padding: 0; }
  .ntext .ledger { color: var(--accent-ink); font-size: 9.5px; }
  .nsub { font-weight: 600; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nto { font-size: 12px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fup { flex: none; display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; color: var(--text-3); }
  .fup.hot { color: var(--accent-ink); font-weight: 600; }
  .cleared { font-size: 14px; color: var(--text-2); margin: 0 0 4px; }
  .swipe-wrap { position: relative; overflow: hidden; }
  .reveal {
    position: absolute; top: 0; bottom: 0; display: none; align-items: center; gap: 8px; padding: 0 22px;
    font: 600 11px var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--text-2);
  }
  .reveal.right { left: 0; right: 0; background: var(--ok-soft); color: var(--ok); }
  .reveal.left { left: 0; right: 0; justify-content: flex-end; background: var(--accent-soft); color: var(--accent-ink); }
  .swipe-wrap:global([data-swipe='right']) .reveal.right, .swipe-wrap:global([data-swipe='left']) .reveal.left { display: flex; }
  .swipe-wrap:global([data-armed='1']) .reveal { filter: saturate(1.6); font-size: 12px; }
  .row {
    background-color: var(--bg);
    touch-action: pan-y;
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: var(--row-pad) 14px var(--row-pad) 22px;
    border-bottom: 1px solid var(--line);
    transition: background .1s;
  }
  .row:hover { background: var(--bg-hover); }
  .row.open { background: var(--bg-selected); }
  .row.open::after { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
  .row.checked { background: var(--bg-active); }
  .row.focus { box-shadow: inset 0 0 0 1px var(--line-strong); }
  .hit { position: absolute; inset: 0; border: 0; background: transparent; cursor: pointer; z-index: 0; padding: 0; }
  .hit:focus-visible { outline-offset: -2px; }
  .dot {
    position: absolute; left: 9px; top: calc(var(--row-pad) + 7px); width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); opacity: 0; transition: opacity .15s;
  }
  .unread .dot { opacity: 1; }
  .sel { position: relative; z-index: 1; margin: 3px 0 0; accent-color: var(--accent); width: 14px; height: 14px; flex: none; opacity: .35; }
  .row:hover .sel, .row.checked .sel, .sel:focus-visible { opacity: 1; }
  .content { flex: 1; min-width: 0; pointer-events: none; }
  .line1 { display: flex; align-items: center; gap: 6px; }
  .who { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-2); font-size: 13.5px; }
  .unread .who { color: var(--text); font-weight: 600; }
  .cnt { color: var(--text-3); font-weight: 400; font-size: 11px; margin-left: 5px; }
  .date { flex: none; font-size: 11.5px; color: var(--text-3); }
  .unread .date { color: var(--accent-ink); font-weight: 600; }
  .pkg { flex: none; display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--text-3); white-space: nowrap; }
  .pkg.pk-out_for_delivery, .pkg.pk-ready_for_pickup { color: var(--accent-ink); font-weight: 600; }
  .pkg.pk-exception { color: var(--warn); font-weight: 600; }
  .pkg.pk-delivered { color: var(--ok); }
  @media (max-width: 560px) { .pkg { display: none; } }
  .sublink { color: var(--accent-ink); text-decoration: none; }
  .sublink:hover { text-decoration: underline; }
  .snz { flex: none; display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--accent-ink); }
  .line2 { margin-top: 3px; display: flex; gap: 8px; min-width: 0; font-size: 13.5px; }
  .subject { color: var(--text-2); flex: none; max-width: 72%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .unread .subject { color: var(--text); font-weight: 600; }
  .snippet { color: var(--text-3); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  mark { background: color-mix(in srgb, var(--accent) 22%, transparent); color: inherit; border-radius: 2px; padding: 0 1px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .chip.label { background: color-mix(in srgb, var(--c) 18%, transparent); color: color-mix(in srgb, var(--c) 70%, var(--text)); }
  .risk { display: inline-grid; place-items: center; }
  .risk.high { color: var(--danger); }
  .risk.medium { color: var(--warn); }
  .clip { display: inline-grid; place-items: center; }
  .star {
    position: relative; z-index: 1; border: 0; background: none; padding: 2px; margin-top: 1px; cursor: pointer;
    color: var(--text-3); border-radius: 4px; display: grid; place-items: center; opacity: .5;
  }
  .row:hover .star, .star.on { opacity: 1; }
  .star:hover { color: var(--text-2); }
  .star.on { color: var(--star); }
  .hover-acts {
    position: absolute; right: 42px; top: 50%; transform: translateY(-50%); z-index: 2;
    display: none; gap: 1px; padding: 2px; border-radius: var(--radius-sm); background: var(--bg-elev);
    border: 1px solid var(--line); box-shadow: var(--shadow-sm);
  }
  .row:hover .hover-acts { display: flex; }
  .skel-row { pointer-events: none; }
  .skel-row .line1, .skel-row .line2 { gap: 10px; margin: 4px 0; }
  .state { padding: 56px 24px; text-align: center; color: var(--text-2); }
  .state .big { font-size: 26px; margin: 0 0 6px; color: var(--text-2); }
  .state.error { color: var(--danger); }
  .stamp {
    display: inline-block; margin: 6px 0 18px; padding: 8px 18px; font-size: 30px; color: var(--accent);
    border: 3px double var(--accent); border-radius: 6px; transform: rotate(-9deg); animation: stamp .5s var(--ease) both;
    text-transform: uppercase; letter-spacing: .06em;
  }
  .sentinel { height: 60px; display: grid; place-items: center; }
</style>
