<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { navigate, route } from '../router.svelte.js';
  import { contextFolder, current, folderById, labelById, threadAction, ui } from '../state.svelte.js';
  import { openReply, sendScheduledNow, unscheduleDraft } from '../compose.svelte.js';
  import { displayName, shortDate, snoozeLabel } from '../format.js';
  import { ago, describeWhen } from '../when.js';
  import { api } from '../api.svelte.js';
  import { errorToast, loadAgenda, loadThread, toast } from '../state.svelte.js';
  import Icon from './Icon.svelte';
  import MessageCard from './MessageCard.svelte';
  import Composer from './Composer.svelte';
  import PackageCard from './PackageCard.svelte';
  import { api as kernApi } from '#lib/api.ts';
  import { goto } from '$app/navigation';

  let { reading } = $props();
  let expanded = $state(new Set());
  let moreOpen = $state(false);
  let lastThread = null;

  const ctx = $derived(folderById(contextFolder()));
  const role = $derived(ctx?.role || '');
  // Only the conversation the URL points at; never the previous one while
  // the next is loading (actions must not hit the wrong thread).
  const t = $derived(current.thread && current.thread.id === route.threadId ? current.thread : null);
  const msgs = $derived(t ? current.messages : []);
  const inJunk = $derived(msgs.some((m) => m.folder.role === 'junk'));
  const inTrash = $derived(role === 'trash' || role === 'junk');

  // Expand unread messages and the latest one when a thread opens.
  $effect(() => {
    if (!t || t.id === lastThread || !msgs.length) return;
    lastThread = t.id;
    const s = new Set(msgs.filter((m) => !m.seen).map((m) => m.id));
    s.add(msgs[msgs.length - 1].id);
    expanded = s;
  });

  // Collapse the middle of very long threads.
  let showAll = $state(false);
  $effect(() => {
    void t?.id;
    showAll = false;
  });
  const visible = $derived.by(() => {
    if (showAll || msgs.length <= 8) return msgs.map((m) => ({ m }));
    const hiddenIdx = msgs.slice(1, -3).filter((m) => !expanded.has(m.id) || m.seen);
    const hidden = new Set(hiddenIdx.map((m) => m.id));
    const out = [];
    let gap = 0;
    for (const m of msgs) {
      if (hidden.has(m.id)) {
        if (!gap) out.push({ gap: true });
        gap += 1;
        out[out.length - 1].count = gap;
      } else {
        gap = 0;
        out.push({ m });
      }
    }
    return out;
  });

  // Keyboard: n / p move between messages, Enter expands or collapses.
  let cursor = $state(-1);
  $effect(() => {
    void t?.id;
    cursor = -1;
  });
  function onThreadKey(e) {
    if (!t || !msgs.length) return;
    if (e.detail === 'next' || e.detail === 'prev') {
      if (!showAll && msgs.length > 8) showAll = true;
      const start = cursor < 0 ? msgs.length - 1 : cursor;
      cursor = Math.max(0, Math.min(msgs.length - 1, start + (e.detail === 'next' ? 1 : -1)));
      queueMicrotask(() => document.querySelector(`[data-msg="${msgs[cursor].id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
    } else if (e.detail === 'toggle') {
      const m = msgs[cursor < 0 ? msgs.length - 1 : cursor];
      if (m) toggle(m.id);
    }
  }
  $effect(() => {
    addEventListener('kern-mail:thread-key', onThreadKey);
    return () => removeEventListener('kern-mail:thread-key', onThreadKey);
  });

  function toggle(id) {
    const s = new Set(expanded);
    s.has(id) ? s.delete(id) : s.add(id);
    expanded = s;
  }
  const wroteHere = $derived(msgs.some((m) => m.fromMe));
  // "3 messages · Alice, Bob and you · Oct 1 – yesterday"
  const summary = $derived.by(() => {
    if (!msgs.length) return [];
    const people = [];
    const seen = new Set();
    for (const m of msgs) {
      if (seen.has(m.from.addr)) continue;
      seen.add(m.from.addr);
      people.push(m.fromMe ? 'you' : (m.from.name || m.from.addr).split(/[\s,]+/)[0]);
    }
    // Others first, you last.
    if (people.includes('you')) people.push(people.splice(people.indexOf('you'), 1)[0]);
    const names = people.length > 3 ? `${people.slice(0, 2).join(', ')} and ${people.length - 2} others` : people.join(', ').replace(/, ([^,]*)$/, ' and $1');
    const first = new Date(msgs[0].date);
    const last = new Date(msgs[msgs.length - 1].date);
    const lastLabel = ago(last);
    const firstLabel = shortDate(msgs[0].date);
    const sameDay = first.toDateString() === last.toDateString();
    const span = msgs.length > 1 && !sameDay ? `${firstLabel} – ${lastLabel}` : lastLabel;
    return [msgs.length === 1 ? '1 message' : `${msgs.length} messages`, names, span];
  });
  const fu = $derived(t?.followup);
  const waitingOn = $derived.by(() => {
    const r = fu?.recipients || [];
    if (!r.length) return 'anyone';
    return r.slice(0, 2).map((p) => displayName(p)).join(' and ') + (r.length > 2 ? ` +${r.length - 2}` : '');
  });
  async function followupAction(action, until) {
    try {
      await api.post(`/followups/${fu.id}`, { action, until: until?.toISOString() });
      toast(action === 'done' ? 'Nudge cleared' : `I'll nudge you again ${describeWhen(until)}`);
      loadAgenda();
      loadThread(t.id, { quiet: true });
    } catch (e) {
      errorToast(e);
    }
  }
  function inDays(n) {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 9, 0);
  }
  function lastFromMe() {
    return [...msgs].reverse().find((m) => m.fromMe) || msgs[msgs.length - 1];
  }

  function act(action, extra) {
    threadAction([t.id], action, extra).catch(() => {});
  }
  function makeTask() {
    ui.dialog = { type: 'task', threadId: t.id, subject: t.subject || '' };
  }
  async function toggleTask(task) {
    try {
      await kernApi.patch(`/tasks/${task.id}`, { done: !task.done });
      loadThread(t.id, { quiet: true });
    } catch (e) {
      errorToast(e);
    }
  }
  function dueLabel(d) {
    if (!d) return '';
    const day = new Date(d + 'T12:00');
    const diff = Math.round((new Date(day.toDateString()) - new Date(new Date().toDateString())) / 864e5);
    return diff === 0 ? 'today' : diff === 1 ? 'tomorrow' : diff === -1 ? 'yesterday' : day.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }
</script>

<div class="bar">
  {#if !reading}
    <button class="icon-btn" aria-label="Back" onclick={() => navigate({ threadId: null })}><Icon name="back" /></button>
  {/if}
  {#if t}
    <div class="acts">
      {#if role === 'junk' || inJunk}
        <button class="btn small" onclick={() => act('not_spam')}><Icon name="inbox" size={15} /> Not spam</button>
      {:else if role !== 'archive' && role !== 'trash'}
        <button class="icon-btn" title="Archive (e)" aria-label="Archive" onclick={() => act('archive')}><Icon name="archive" /></button>
      {/if}
      {#if (role === 'archive' || role === 'trash') && !inJunk}
        <button class="icon-btn" title="Move to Inbox" aria-label="Move to Inbox" onclick={() => act('inbox')}><Icon name="inbox" /></button>
      {/if}
      {#if !inJunk}
        <button class="icon-btn" title="Report spam (!)" aria-label="Report spam" onclick={() => (ui.dialog = { type: 'spam', ids: [t.id] })}><Icon name="spam" /></button>
      {/if}
      {#if inTrash}
        <button class="btn small danger" onclick={() => (ui.dialog = { type: 'confirm', title: 'Delete forever?', body: 'This conversation will be permanently deleted from your mail server. This can\'t be undone.', action: 'Delete forever', danger: true, submit: () => act('delete_forever') })}>Delete forever</button>
      {:else}
        <button class="icon-btn" title="Trash (#)" aria-label="Move to Trash" onclick={() => act('trash')}><Icon name="trash" /></button>
      {/if}
      <span class="sep"></span>
      <span class="wide-only">
      <button class="icon-btn" title="Mark unread (Shift+U)" aria-label="Mark unread" onclick={() => { act('unread'); navigate({ threadId: null }); }}><Icon name="mail" /></button>
      <button class="icon-btn" title="Move (v)" aria-label="Move" onclick={() => (ui.dialog = { type: 'move', ids: [t.id] })}><Icon name="move" /></button>
      <button class="icon-btn" title="Label (l)" aria-label="Label" onclick={() => (ui.dialog = { type: 'label', ids: [t.id] })}><Icon name="label" /></button>
      <button class="icon-btn" class:on={t.muted} title={t.muted ? 'Unmute (m)' : 'Mute: replies skip the Inbox (m)'} aria-label={t.muted ? 'Unmute' : 'Mute'} aria-pressed={t.muted}
              onclick={() => act(t.muted ? 'unmute' : 'mute')}><Icon name="mute" /></button>
      </span>
      <span class="sep"></span>
      {#if wroteHere && !fu}
        <button class="icon-btn" title="Nudge me if nobody replies" aria-label="Nudge me if nobody replies" onclick={() => (ui.dialog = { type: 'nudge', threadId: t.id })}><Icon name="bell" /></button>
      {/if}
      <button class="icon-btn" title="Make a task (t)" aria-label="Make a task" onclick={makeTask}><Icon name="task" /></button>
      {#if t.snoozeUntil}
        <button class="btn small" title="Bring back to Inbox now" onclick={() => act('unsnooze')}><Icon name="inbox" size={15} /> Unsnooze</button>
      {:else if !inTrash}
        <button class="icon-btn" title="Snooze (b)" aria-label="Snooze" onclick={() => (ui.dialog = { type: 'snooze', ids: [t.id] })}><Icon name="clock" /></button>
      {/if}
    </div>
    <div class="more-wrap narrow-only">
      <button class="icon-btn" aria-label="More actions" aria-haspopup="menu" aria-expanded={moreOpen} onclick={() => (moreOpen = !moreOpen)}><Icon name="more" /></button>
      {#if moreOpen}
        <button class="menu-scrim" aria-label="Close menu" onclick={() => (moreOpen = false)}></button>
        <div class="menu" role="menu">
          <button role="menuitem" onclick={() => { moreOpen = false; act('unread'); navigate({ threadId: null }); }}><Icon name="mail" size={16} /> Mark unread</button>
          <button role="menuitem" onclick={() => { moreOpen = false; ui.dialog = { type: 'move', ids: [t.id] }; }}><Icon name="move" size={16} /> Move to…</button>
          <button role="menuitem" onclick={() => { moreOpen = false; ui.dialog = { type: 'label', ids: [t.id] }; }}><Icon name="label" size={16} /> Label…</button>
          <button role="menuitem" onclick={() => { moreOpen = false; act(t.muted ? 'unmute' : 'mute'); }}><Icon name="mute" size={16} /> {t.muted ? 'Unmute' : 'Mute conversation'}</button>
          {#if wroteHere && !fu}<button role="menuitem" onclick={() => { moreOpen = false; ui.dialog = { type: 'nudge', threadId: t.id }; }}><Icon name="bell" size={16} /> Nudge me if no reply…</button>{/if}
          <button role="menuitem" onclick={() => { moreOpen = false; makeTask(); }}><Icon name="task" size={16} /> Make a task…</button>
        </div>
      {/if}
    </div>
    <button class="icon-btn star" class:on={t.starred} aria-pressed={t.starred} aria-label={t.starred ? 'Unstar' : 'Star'}
            onclick={() => act(t.starred ? 'unstar' : 'star', { silent: true })}>
      <Icon name="star" fill={t.starred ? 'currentColor' : 'none'} />
    </button>
  {/if}
</div>

<div class="scroll body">
  {#if !t}
    {#if current.error}
      <div class="center error">{current.error}</div>
    {:else}
      <div class="thread" aria-busy="true" aria-label="Loading conversation">
        <span class="skel" style="width:55%;height:28px;margin:8px 4px 24px"></span>
        {#each [0, 1] as i}
          <div class="skel-card">
            <span class="skel" style="width:38px;height:38px;border-radius:50%"></span>
            <div class="skel-lines">
              <span class="skel" style="width:30%;height:12px"></span>
              <span class="skel" style:width={i ? '70%' : '85%'} style="height:10px"></span>
              <span class="skel" style="width:60%;height:10px"></span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {:else if current.error}
    <div class="center error">{current.error}</div>
  {:else if t}
    <article class="thread">
      <header class="subject-row">
        <h1 class="display">{t.subject || '(no subject)'}</h1>
        {#if summary.length}
          <p class="summary ledger">{#each summary as part, i}{#if i}<span class="sep2">·</span>{/if}<span>{part}</span>{/each}</p>
        {/if}
        <div class="labels">
          {#each t.labels as lid}
            {@const l = labelById(lid)}
            {#if l}
              <span class="chip label" style:--c={l.color || 'var(--text-3)'}>
                {l.name}
                <button aria-label={`Remove label ${l.name}`} onclick={() => act('label_remove', { label: l.id })}><Icon name="close" size={11} /></button>
              </span>
            {/if}
          {/each}
        </div>
      </header>

      {#if t.muted}
        <div class="nudge">
          <Icon name="mute" size={16} />
          <span class="txt">Muted. New replies go straight to Archive, marked as read.</span>
          <span class="nacts"><button class="btn small ghost" onclick={() => act('unmute')}>Unmute</button></span>
        </div>
      {/if}
      {#if fu && fu.status === 'nudged'}
        <div class="nudge hot">
          <Icon name="bell" size={16} />
          <span class="txt">You wrote to <b>{waitingOn}</b> {ago(new Date(fu.sentAt))} and nobody has replied. Follow up?</span>
          <span class="nacts">
            <button class="btn small primary" onclick={() => openReply(lastFromMe(), 'reply')}><Icon name="reply" size={14} /> Write a follow-up</button>
            <button class="btn small" onclick={() => followupAction('later', inDays(3))}>In 3 days</button>
            <button class="btn small ghost" onclick={() => followupAction('done')}>Done</button>
          </span>
        </div>
      {:else if fu}
        <div class="nudge">
          <Icon name="bell" size={16} />
          <span class="txt">Waiting on <b>{waitingOn}</b>. I'll nudge you {describeWhen(new Date(fu.due))} if nobody replies.</span>
          <span class="nacts">
            <button class="btn small ghost" onclick={() => (ui.dialog = { type: 'nudge', threadId: t.id })}>Change</button>
            <button class="btn small ghost" onclick={() => followupAction('done')}>Cancel</button>
          </span>
        </div>
      {/if}
      {#if t.snoozeUntil}
        <button class="snoozed" onclick={() => (ui.dialog = { type: 'snooze', ids: [t.id] })}>
          <Icon name="clock" size={16} />
          <span>Snoozed until <b>{snoozeLabel(t.snoozeUntil)}</b>. It'll come back to your Inbox as unread.</span>
          <span class="change">Change</span>
        </button>
      {/if}

      {#each current.tasks.filter((x) => x.source?.kind === 'mail') as task (task.id)}
        <div class="nudge taskline" class:done={task.done}>
          <input type="checkbox" checked={task.done} onchange={() => toggleTask(task)} aria-label={task.done ? 'Reopen task' : 'Complete task'} />
          <span class="txt"><b>{task.title}</b>{#if task.due} <span class="faint">· due {dueLabel(task.due)}</span>{/if}</span>
          <span class="nacts"><button class="btn small ghost" onclick={() => goto(`/tasks?view=${task.done ? 'completed' : 'open'}&task=${task.id}`)}>Open in Tasks</button></span>
        </div>
      {/each}

      {#each current.scheduled as s (s.id)}
        <div class="nudge">
          <Icon name="clock" size={16} />
          <span class="txt">Your {s.mode === 'forward' ? 'forward' : 'reply'} is scheduled to send <b>{describeWhen(new Date(s.sendAt))}</b>.</span>
          <span class="nacts">
            <button class="btn small" onclick={() => unscheduleDraft({ ...s, threadId: t.id }).catch(errorToast)}>Edit</button>
            <button class="btn small ghost" onclick={() => sendScheduledNow(s).then(() => loadThread(t.id, { quiet: true })).catch(errorToast)}>Send now</button>
          </span>
        </div>
      {/each}

      {#each current.packages as p (p.id)}
        <div class="pkg-wrap"><PackageCard {p} compact inThread /></div>
      {/each}

      {#each visible as item, i (item.m ? item.m.id : 'gap' + i)}
        {#if item.gap}
          <button class="gap" onclick={() => (showAll = true)}>
            <span>{item.count} older message{item.count === 1 ? '' : 's'}</span>
          </button>
        {:else}
          <div class="msg-wrap" class:cursor={msgs[cursor]?.id === item.m.id} data-msg={item.m.id}>
            <MessageCard m={item.m} open={expanded.has(item.m.id)} onToggle={() => toggle(item.m.id)}
                         last={item.m === msgs[msgs.length - 1]} />
          </div>
        {/if}
      {/each}

      {#each ui.composers.filter((c) => c.docked && c.threadId === t.id) as c (c.key)}
        <div class="docked-wrap"><Composer {c} wide={true} docked={true} /></div>
      {/each}
      {#if msgs.length && !ui.composers.some((c) => c.docked && c.threadId === t.id)}
        <div class="reply-bar">
          <button class="btn" onclick={() => openReply(msgs[msgs.length - 1], 'reply')}><Icon name="reply" size={16} /> Reply</button>
          <button class="btn" onclick={() => openReply(msgs[msgs.length - 1], 'reply_all')}><Icon name="replyAll" size={16} /> Reply all</button>
          <button class="btn" onclick={() => openReply(msgs[msgs.length - 1], 'forward')}><Icon name="forward" size={16} /> Forward</button>
        </div>
      {/if}
    </article>
  {/if}
</div>

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 4px;
    height: 46px;
    padding: 0 10px;
    border-bottom: 1px solid var(--line);
    flex: none;
  }
  .acts { flex: 1; display: flex; align-items: center; gap: 2px; overflow-x: auto; scrollbar-width: none; }
  .wide-only { display: contents; }
  .narrow-only { display: none; }
  .more-wrap { position: relative; }
  .menu-scrim { position: fixed; inset: 0; border: 0; background: transparent; z-index: 20; }
  .menu {
    position: absolute; right: 0; top: calc(100% + 4px); z-index: 21; min-width: 220px; display: grid; padding: 5px;
    background: var(--bg-elev); border: var(--card-border); border-radius: var(--radius); box-shadow: var(--shadow-lg);
  }
  .menu button { display: flex; align-items: center; gap: 10px; border: 0; background: none; text-align: left; padding: 9px 10px; border-radius: var(--radius-sm); cursor: pointer; color: var(--text); font-size: 14px; }
  .menu button:hover { background: var(--bg-hover); }
  @media (max-width: 640px) {
    .wide-only, .sep { display: none; }
    .narrow-only { display: block; }
  }
  .sep { width: 1px; height: 20px; background: var(--line); margin: 0 6px; flex: none; }
  .star.on { color: var(--star); }
  .body { flex: 1; }
  .thread { max-width: 880px; margin: 0 auto; padding: 26px 24px 120px; }
  .subject-row { padding: 4px 4px 18px; }
  h1 { font-size: 30px; line-height: 1.15; margin: 0; overflow-wrap: anywhere; }
  .summary { margin: 8px 0 0; display: flex; flex-wrap: wrap; gap: 0 7px; text-transform: none; letter-spacing: .02em; font-size: 11.5px; }
  .summary .sep2 { opacity: .5; }
  .labels { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .labels:empty { display: none; }
  .chip.label { background: color-mix(in srgb, var(--c) 18%, transparent); color: color-mix(in srgb, var(--c) 70%, var(--text)); padding-right: 3px; }
  .chip.label button { border: 0; background: none; color: inherit; cursor: pointer; display: grid; place-items: center; padding: 2px; border-radius: 50%; opacity: .7; }
  .chip.label button:hover { opacity: 1; background: rgb(0 0 0 / .08); }
  .nudge {
    display: flex; align-items: center; flex-wrap: wrap; gap: 8px 10px; margin: 0 0 14px; padding: 9px 12px;
    border: 1px dashed var(--line-strong); border-radius: var(--radius); font-size: 13px; color: var(--text-2);
  }
  .nudge :global(svg) { color: var(--accent-ink); flex: none; }
  .nudge .txt { flex: 1; min-width: 200px; }
  .nudge b { color: var(--text); }
  .nudge.hot { border: 1px solid var(--accent); background: var(--accent-soft); color: var(--text); }
  .nacts { display: flex; gap: 6px; flex-wrap: wrap; }
  .pkg-wrap { margin: 0 0 14px; }
  .taskline input { accent-color: var(--accent); margin: 0; }
  .taskline.done .txt b { text-decoration: line-through; color: var(--text-3); }
  .snoozed {
    display: flex; align-items: center; gap: 10px; width: 100%; margin: 0 0 14px; padding: 10px 14px; text-align: left;
    border: 1px dashed var(--accent); border-radius: var(--radius); background: var(--accent-soft); color: var(--text);
    cursor: pointer; font-size: 13px;
  }
  .snoozed :global(svg) { color: var(--accent-ink); flex: none; }
  .snoozed span:first-of-type { flex: 1; }
  .snoozed .change { font-family: var(--mono); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent-ink); }
  .gap {
    display: flex; align-items: center; justify-content: center; width: 100%; height: 34px; margin: 4px 0;
    border: 0; background: none; cursor: pointer; color: var(--accent-ink); font-weight: 600; font-size: 13px; position: relative;
  }
  .gap::before { content: ''; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px dashed var(--line-strong); }
  .gap span { position: relative; background: var(--bg); padding: 2px 12px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); font-family: var(--mono); font-size: 11.5px; font-weight: 500; }
  .msg-wrap { border-radius: var(--radius); }
  .msg-wrap.cursor { box-shadow: 0 0 0 2px var(--accent); border-radius: calc(var(--radius) + 1px); margin-bottom: 10px; }
  .msg-wrap.cursor :global(.card) { margin-bottom: 0; }
  .docked-wrap { margin-top: 14px; }
  .reply-bar { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 4px 0; }
  .center { display: grid; place-items: center; padding: 60px; }
  .skel-card { display: flex; gap: 12px; padding: 14px; margin-bottom: 10px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--bg-elev); }
  .skel-lines { flex: 1; display: grid; gap: 8px; align-content: start; padding-top: 3px; }
  .error { color: var(--danger); }
  @media (max-width: 640px) {
    .thread { padding: 12px 10px 120px; }
    h1 { font-size: 23px; }
  }
</style>
