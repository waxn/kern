<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { goto } from '$app/navigation';
  import { api } from '../api.svelte.js';
  import {
    contextFolder, current, info, list, loadAgenda, loadFolders, loadThread, mailbox, threadAction, toast, ui,
  } from '../state.svelte.js';
  import { SHORTCUTS } from '../shortcuts.js';
  import { trapFocus } from '../focus.js';
  import { schedulePresets, snoozePresets } from '../format.js';
  import { describeWhen, parseWhen } from '../when.js';
  import Icon from './Icon.svelte';

  const d = $derived(ui.dialog);
  let busy = $state(false);
  let error = $state('');

  // Shared form fields (reset when a dialog opens).
  let text = $state('');
  let text2 = $state('');
  let date = $state('');
  let filter = $state('');
  let blockChoice = $state('none');
  let check = $state(null);
  let sender = $state('');
  let presets = $state([]);

  const LABEL_COLORS = ['', '#c4441b', '#c98a0b', '#5d8a3a', '#0e6f68', '#3a6ea5', '#7a4f9a', '#a8476e', '#6b6b66'];

  let headersText = $state(null);
  $effect(() => {
    const dd = ui.dialog;
    if (dd?.type !== 'headers') return;
    headersText = null;
    api.get(`/messages/${dd.messageId}/headers`).then((r) => (headersText = r.headers)).catch((e) => (headersText = `Couldn't load headers: ${e.message}`));
  });

  let whenText = $state('');
  // "Make a task" (a Kern task linked to this email).
  let taskTitle = $state('');
  let taskDue = $state('');
  let taskPrio = $state(0);
  function isoDay(offset) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  function nextMonday() {
    const dow = new Date().getDay();
    return isoDay(((8 - dow) % 7) || 7);
  }
  async function createTask() {
    const tid = d.threadId;
    await run(async () => {
      const task = await api.post(`/threads/${tid}/task`, { title: taskTitle.trim(), due: taskDue || null, priority: taskPrio });
      toast('Task created', { action: { label: 'Open', run: () => goto(`/tasks?view=open&task=${task.id}`) } });
      if (current.thread?.id === tid) loadThread(tid, { quiet: true });
    });
  }
  let nudgePresets = $state([]);
  const whenParsed = $derived.by(() => {
    const p = parseWhen(whenText);
    return p && p > new Date() ? p : null;
  });
  function pick(at) {
    if (!at || Number.isNaN(at.getTime())) return;
    if (d.type === 'schedule') {
      run(() => d.submit(at));
      return;
    }
    if (d.type === 'nudge') {
      run(async () => {
        await api.post('/followups', { threadId: d.threadId, until: at.toISOString() });
        toast(`I'll nudge you ${describeWhen(at)} if nobody replies`);
        loadAgenda();
        if (current.thread?.id === d.threadId) loadThread(d.threadId, { quiet: true });
      });
      return;
    }
    run(async () => {
      await threadAction(d.ids, 'snooze', { until: at.toISOString(), silent: true });
      toast(`Snoozed until ${describeWhen(at)}`, { action: { label: 'Undo', run: () => threadAction(d.ids, 'unsnooze', { silent: true }) } });
    });
  }

  $effect(() => {
    const dd = ui.dialog;
    error = '';
    busy = false;
    filter = '';
    blockChoice = 'none';
    check = null;
    if (!dd) return;
    text = '';
    whenText = '';
    if (dd.type === 'snooze') presets = snoozePresets();
    if (dd.type === 'schedule') presets = schedulePresets();
    if (dd.type === 'nudge') {
      const now = new Date();
      const day = (n, h = 8) => new Date(now.getFullYear(), now.getMonth(), now.getDate() + n, h, 0);
      nudgePresets = [
        { id: '1d', label: 'Tomorrow morning', at: day(1) },
        { id: '3d', label: 'In 3 days', at: day(3, 9) },
        { id: '1w', label: 'In a week', at: day(7, 9) },
        { id: '2w', label: 'In two weeks', at: day(14, 9) },
      ];
    }
    text2 = '';
    date = '';
    if (dd.type === 'task') {
      taskTitle = dd.subject || '';
      taskDue = '';
      taskPrio = 0;
    }
    if (dd.type === 'spam') {
      sender = dd.sender || findSender(dd.ids);
      if (sender) api.get('/blocklist/check', { addr: sender }).then((r) => (check = r)).catch(() => {});
    }
  });

  function findSender(ids) {
    if (ids.length !== 1) return '';
    if (current.thread && current.thread.id === ids[0]) {
      const theirs = current.messages.filter((m) => !m.fromMe);
      return theirs.length ? theirs[theirs.length - 1].from.addr : '';
    }
    const t = list.threads.find((x) => x.id === ids[0]);
    const p = (t?.participants || []).filter((x) => x.addr !== info.address);
    return p.length ? p[p.length - 1].addr : '';
  }

  function close() {
    ui.dialog = null;
  }

  async function run(fn) {
    busy = true;
    error = '';
    try {
      await fn();
      close();
    } catch (e) {
      error = e.message;
    } finally {
      busy = false;
    }
  }

  const moveTargets = $derived(
    mailbox.folders.filter((f) => f.id !== contextFolder() && f.role !== 'drafts' && f.role !== 'sent'
      && f.displayName.toLowerCase().includes(filter.toLowerCase())),
  );

  function threadLabels(ids) {
    const sets = ids.map((id) => {
      const t = list.threads.find((x) => x.id === id) || (current.thread?.id === id ? current.thread : null);
      return new Set(t?.labels || []);
    });
    return (lid) => sets.length && sets.every((s) => s.has(lid));
  }
  const hasLabel = $derived(d && d.type === 'label' ? threadLabels(d.ids) : () => false);

  async function toggleLabel(l) {
    const on = hasLabel(l.id);
    await threadAction(d.ids, on ? 'label_remove' : 'label_add', { label: l.id, silent: true }).catch(() => {});
    const set = new Set(d.ids);
    for (const t of list.threads) {
      if (set.has(t.id)) t.labels = on ? t.labels.filter((x) => x !== l.id) : [...new Set([...t.labels, l.id])];
    }
    if (current.thread && set.has(current.thread.id)) {
      current.thread.labels = on ? current.thread.labels.filter((x) => x !== l.id) : [...new Set([...current.thread.labels, l.id])];
    }
  }
  async function createLabel() {
    const name = filter.trim();
    if (!name) return;
    try {
      const l = await api.post('/labels', { name });
      await loadFolders();
      filter = '';
      await toggleLabel(l);
    } catch (e) {
      error = e.message;
    }
  }

  function onKey(e) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  }
</script>

{#if d}
  <div class="backdrop" role="presentation" onclick={close}></div>
  <div class="dialog" class:wide={d.type === 'help' || d.type === 'headers'} role="dialog" aria-modal="true" tabindex="-1" onkeydown={onKey} use:trapFocus>
    {#if d.type === 'help'}
      <header><h2>Keyboard shortcuts</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <div class="help-grid">
        {#each SHORTCUTS as [group, items]}
          <section>
            <h3>{group}</h3>
            {#each items as [keys, label]}
              <div class="sc"><span>{label}</span><span class="keys">{#each keys.split(' ') as k}{#if ['then', 'or', '/', '+'].includes(k)}<span class="faint"> {k} </span>{:else}<span class="kbd">{k}</span>{/if}{/each}</span></div>
            {/each}
          </section>
        {/each}
      </div>

    {:else if d.type === 'spam'}
      <header><h2>Report spam</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <p class="muted">
        {d.ids.length > 1 ? `${d.ids.length} conversations` : 'This conversation'} will move to Junk, on your mail server too,
        so your provider's spam filter can learn from it.
      </p>
      {#if sender || d.ids.length > 1}
        <fieldset>
          <legend>Also block future mail?</legend>
          <label class="opt"><input type="radio" bind:group={blockChoice} value="none" /> <span>Just report it</span></label>
          <label class="opt"><input type="radio" bind:group={blockChoice} value="address" />
            <span>Block the sender {#if sender}<b>{sender}</b>{/if}</span></label>
          <label class="opt" class:disabled={check && !check.domainBlockAllowed}>
            <input type="radio" bind:group={blockChoice} value="domain" disabled={check && !check.domainBlockAllowed} />
            <span>
              Block everyone at {#if check}<b>{check.domain}</b>{:else}the sender's domain{/if}
              {#if check && !check.domainBlockAllowed}
                <span class="hint">{check.domain} is a shared email provider used by many people, so only the single address can be blocked.</span>
              {/if}
            </span>
          </label>
        </fieldset>
      {/if}
      {#if error}<p class="error">{error}</p>{/if}
      <footer>
        <button class="btn ghost" onclick={close}>Cancel</button>
        <button class="btn primary" disabled={busy} onclick={() => run(() => threadAction(d.ids, 'spam', { block: blockChoice === 'none' ? '' : blockChoice }))}>Report spam</button>
      </footer>

    {:else if d.type === 'move'}
      <header><h2>Move to…</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <input class="input" placeholder="Filter folders" bind:value={filter} autofocus />
      <ul class="pick">
        {#each moveTargets as f (f.id)}
          <li><button onclick={() => run(() => threadAction(d.ids, 'move', { dest: f.id }))}><Icon name="folder" size={16} /> {f.name}</button></li>
        {:else}
          <li class="faint pad">No matching folder.</li>
        {/each}
      </ul>

    {:else if d.type === 'label'}
      <header><h2>Labels</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <input class="input" placeholder="Find or create a label" bind:value={filter} autofocus
             onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); createLabel(); } }} />
      <ul class="pick">
        {#each mailbox.labels.filter((l) => l.name.toLowerCase().includes(filter.toLowerCase())) as l (l.id)}
          <li><label class="check"><input type="checkbox" checked={hasLabel(l.id)} onchange={() => toggleLabel(l)} />
            <span class="dot" style:background={l.color || 'var(--text-3)'}></span>{l.name}</label></li>
        {/each}
        {#if filter.trim() && !mailbox.labels.some((l) => l.name.toLowerCase() === filter.trim().toLowerCase())}
          <li><button onclick={createLabel}><Icon name="plus" size={16} /> Create “{filter.trim()}”</button></li>
        {/if}
      </ul>
      {#if error}<p class="error">{error}</p>{/if}
      <footer><button class="btn" onclick={close}>Done</button></footer>

    {:else if d.type === 'snooze' || d.type === 'nudge' || d.type === 'schedule'}
      {@const nudge = d.type === 'nudge'}
      {@const sched = d.type === 'schedule'}
      <header>
        <h2 class="display">{nudge ? 'Nudge me if nobody replies' : sched ? 'Send later' : 'Snooze until…'}</h2>
        <button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button>
      </header>
      <p class="muted small-p">
        {#if sched}
          Kern sends it at that time, as long as the mail service is running. Until then it waits under Scheduled, where you can
          edit, cancel or send it straight away.
        {:else if nudge}
          If nobody else writes in this conversation by then, it comes back to you with a reminder. A reply cancels it.
        {:else}
          It leaves your Inbox (on your phone too) and comes back unread, with a notification. A new reply brings it back early.
        {/if}
      </p>
      <form class="typed" onsubmit={(e) => { e.preventDefault(); if (whenParsed) pick(whenParsed); }}>
        <Icon name={nudge ? 'bell' : sched ? 'send' : 'clock'} size={17} />
        <input bind:value={whenText} placeholder={nudge ? 'in 3 days, next mon, dec 1…' : sched ? 'mon 9am, tomorrow 8:30, dec 1…' : 'fri 2pm, in 3 hours, tomorrow…'} aria-label="When" autofocus />
        {#if whenText.trim()}
          <span class="parsed num" class:bad={!whenParsed}>{whenParsed ? describeWhen(whenParsed) : '?'}</span>
        {/if}
      </form>
      <ul class="presets">
        {#each (nudge ? nudgePresets : presets) as p (p.id)}
          <li>
            <button disabled={busy} onclick={() => pick(p.at)}>
              <span>{p.label}</span>
              <span class="when num">{describeWhen(p.at)}</span>
            </button>
          </li>
        {/each}
      </ul>
      {#if error}<p class="error">{error}</p>{/if}

    {:else if d.type === 'task'}
      <header>
        <h2 class="display">Make a task</h2>
        <button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button>
      </header>
      <p class="muted small-p">It goes to your Kern tasks and links back to this email.</p>
      <form class="form" onsubmit={(e) => { e.preventDefault(); createTask(); }}>
        <label><span>Task</span><input class="input" bind:value={taskTitle} required autofocus /></label>
        <div class="taskrow">
          <span class="ledger">Due</span>
          <div class="seg">
            {#each [['', 'No date'], [isoDay(0), 'Today'], [isoDay(1), 'Tomorrow'], [nextMonday(), 'Next week']] as [v, label] (label)}
              <button type="button" class:on={taskDue === v} onclick={() => (taskDue = v)}>{label}</button>
            {/each}
          </div>
          <input class="input date" type="date" bind:value={taskDue} aria-label="Due date" />
        </div>
        <div class="taskrow">
          <span class="ledger">Priority</span>
          <div class="seg">
            {#each [[0, 'None'], [1, 'Low'], [2, 'Medium'], [3, 'High']] as [v, label] (v)}
              <button type="button" class:on={taskPrio === v} onclick={() => (taskPrio = v)}>{label}</button>
            {/each}
          </div>
        </div>
        {#if error}<p class="error">{error}</p>{/if}
        <footer><button type="button" class="btn ghost" onclick={close}>Cancel</button><button class="btn primary" disabled={busy || !taskTitle.trim()}>Create task</button></footer>
      </form>

    {:else if d.type === 'label-edit'}
      <header><h2 class="display">Label: {d.label.name}</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <span class="ledger">Colour</span>
      <div class="swatches" role="radiogroup" aria-label="Label colour">
        {#each LABEL_COLORS as c}
          <button class="sw" role="radio" aria-checked={(d.label.color || '') === c} aria-label={c || 'No colour'}
                  class:on={(d.label.color || '') === c} style:--c={c || 'var(--text-3)'}
                  onclick={() => run(async () => { await api.patch(`/labels/${d.label.id}`, { color: c }); await loadFolders(); })}></button>
        {/each}
      </div>
      <p class="muted small-p">Labels are stored on your mail server as IMAP keywords, so they survive a reinstall.</p>
      {#if error}<p class="error">{error}</p>{/if}
      <footer>
        <button class="btn danger" onclick={() => (ui.dialog = { type: 'confirm', title: `Delete label “${d.label.name}”?`, body: 'The label is removed from every conversation. The mail itself stays where it is.', action: 'Delete label', danger: true, submit: async () => { await api.del(`/labels/${d.label.id}`); await loadFolders(); toast('Label deleted'); } })}>
          Delete label
        </button>
        <button class="btn" onclick={close}>Done</button>
      </footer>

    {:else if d.type === 'headers'}
      <header><h2 class="display">Message headers</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      {#if headersText === null}
        <div class="skel" style="height:200px"></div>
      {:else}
        <pre class="headers">{headersText}</pre>
        <footer>
          <button class="btn" onclick={() => navigator.clipboard?.writeText(headersText).then(() => toast('Headers copied'))}>Copy</button>
          <button class="btn primary" onclick={close}>Done</button>
        </footer>
      {/if}

    {:else if d.type === 'prompt'}
      <header><h2>{d.title}</h2><button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button></header>
      <form class="form" onsubmit={(e) => { e.preventDefault(); if (text.trim()) run(() => d.submit(text.trim())); }}>
        <label><span>{d.label}</span><input class="input" bind:value={text} required autofocus /></label>
        {#if error}<p class="error">{error}</p>{/if}
        <footer><button type="button" class="btn ghost" onclick={close}>Cancel</button><button class="btn primary" disabled={busy}>{d.action || 'OK'}</button></footer>
      </form>

    {:else if d.type === 'confirm'}
      <header><h2>{d.title}</h2></header>
      <p class="muted">{d.body}</p>
      {#if error}<p class="error">{error}</p>{/if}
      <footer>
        <button class="btn ghost" onclick={close} autofocus>Cancel</button>
        <button class="btn primary" class:danger-btn={d.danger} disabled={busy} onclick={() => run(async () => { await d.submit(); })}>{d.action}</button>
      </footer>
    {/if}
  </div>
{/if}

<style>
  .taskrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .taskrow .ledger { width: 64px; }
  .taskrow .date { width: 150px; }
  .seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); flex-wrap: wrap; }
  .seg button { padding: 3px 10px; border-radius: 4px; color: var(--text-2); border: 0; background: none; cursor: pointer; font-size: 12.5px; }
  .seg button.on { background: var(--surface); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
  .backdrop { position: fixed; inset: 0; background: rgb(10 10 20 / .36); z-index: 200; animation: fade-in .15s; }
  .dialog {
    position: fixed; z-index: 201; left: 50%; top: 12vh; transform: translateX(-50%);
    width: min(440px, calc(100vw - 24px)); max-height: 76vh; overflow: auto;
    background: var(--bg-elev); border: var(--card-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg);
    padding: 20px 22px; animation: rise .18s var(--ease);
  }
  .dialog.wide { width: min(780px, calc(100vw - 24px)); }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  h2 { font-size: 22px; margin: 0; }
  h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-3); margin: 0 0 8px; }
  p { margin: 6px 0 12px; }
  .small { font-size: 12.5px; display: flex; align-items: center; gap: 6px; }
  fieldset { border: 0; padding: 0; margin: 8px 0 4px; display: grid; gap: 6px; }
  legend { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .opt { display: flex; gap: 10px; align-items: flex-start; padding: 9px 11px; border: 1px solid var(--line); border-radius: 9px; cursor: pointer; }
  .opt:has(input:checked) { border-color: var(--accent); background: var(--accent-soft); }
  .opt { border-radius: var(--radius-sm); }
  .opt.disabled { opacity: .7; cursor: default; }
  .opt input { margin-top: 3px; accent-color: var(--accent); }
  .opt b { overflow-wrap: anywhere; }
  .hint { display: block; font-size: 12px; color: var(--text-2); margin-top: 3px; }
  footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .error { color: var(--danger); background: var(--danger-soft); padding: 7px 10px; border-radius: 8px; font-size: 13px; }
  .pick { list-style: none; margin: 10px 0 0; padding: 0; max-height: 320px; overflow: auto; }
  .pick button, .pick .check {
    display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; background: none;
    border-radius: 7px; cursor: pointer; text-align: left; font-size: 13.5px; color: var(--text);
  }
  .pick button:hover, .pick .check:hover { background: var(--bg-hover); }
  .pick .check input { accent-color: var(--accent); }
  .pad { padding: 8px 10px; }
  .dot { width: 10px; height: 10px; border-radius: 3px; }
  .form { display: grid; gap: 12px; }
  .form label { display: grid; gap: 5px; font-size: 12.5px; font-weight: 600; color: var(--text-2); }
  .help-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 18px 28px; margin-top: 8px; }
  .sc { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 4px 0; font-size: 13px; border-bottom: 1px solid var(--line); }
  .keys { white-space: nowrap; }
  .danger-btn { background: var(--danger); border-color: var(--danger); color: #fff; box-shadow: none; }
  .small-p { font-size: 13px; margin: 4px 0 14px; }
  .headers {
    margin: 6px 0 0; max-height: 56vh; overflow: auto; padding: 12px; border-radius: var(--radius-sm);
    background: var(--bg-sunken); font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere;
  }
  .swatches { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }
  .sw { width: 30px; height: 30px; border-radius: 50%; border: 2px solid var(--bg-elev); background: var(--c); cursor: pointer; box-shadow: 0 0 0 1px var(--line-strong); }
  .sw.on { box-shadow: 0 0 0 2px var(--text); }
  .presets { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
  .presets li + li { border-top: 1px solid var(--line); }
  .presets button {
    display: flex; justify-content: space-between; align-items: center; width: 100%; gap: 12px; padding: 11px 14px;
    border: 0; background: none; cursor: pointer; text-align: left; font-size: 14px; color: var(--text);
  }
  .presets button:hover { background: var(--bg-hover); }
  .presets .when { font-size: 12px; color: var(--text-3); }
  .presets button:hover .when { color: var(--accent-ink); }
  .typed {
    display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding: 0 12px; height: 46px;
    border: 1px solid var(--line-strong); border-radius: var(--radius); background: var(--bg); color: var(--text-3);
  }
  .typed:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .typed input { flex: 1; min-width: 0; border: 0; background: none; outline: none; font-size: 15px; color: var(--text); }
  .parsed { font-size: 12px; color: var(--accent-ink); white-space: nowrap; }
  .parsed.bad { color: var(--text-3); }
  @media (max-width: 640px) {
    .dialog { top: auto; bottom: 0; transform: translateX(-50%); width: 100vw; border-radius: 16px 16px 0 0; max-height: 88vh; }
  }
</style>
