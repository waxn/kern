<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { api } from '../api.svelte.js';
  import { bytes, displayName, hue, initials, longDate, shortDate } from '../format.js';
  import { openCompose, openDraft, openReply } from '../compose.svelte.js';
  import { errorToast, info, messageAction, threadAction, toast, ui } from '../state.svelte.js';
  import EmailBody from './EmailBody.svelte';
  import { ago } from '../when.js';
  import RiskPanel from './RiskPanel.svelte';
  import Icon from './Icon.svelte';

  let { m, open, onToggle, last } = $props();
  let showDetails = $state(false);
  let menu = $state(false);

  const recipients = $derived([...(m.to || []), ...(m.cc || [])]);
  const toLine = $derived(
    recipients.length
      ? 'to ' + recipients.slice(0, 3).map((p) => (p.addr === info.address ? 'me' : displayName(p))).join(', ') +
        (recipients.length > 3 ? ` +${recipients.length - 3}` : '')
      : '',
  );
  const files = $derived(m.attachments.filter((a) => !a.inline));
  const showRisk = $derived(m.risk.level === 'medium' || m.risk.level === 'high');

  function openViewer(a) {
    const imgs = files.filter((x) => x.previewable);
    ui.viewer = {
      index: Math.max(0, imgs.findIndex((x) => x.id === a.id)),
      items: imgs.map((x) => ({
        src: `/api/messages/${m.id}/attachments/${x.id}?inline=1`,
        href: `/api/messages/${m.id}/attachments/${x.id}`,
        name: x.filename,
        size: x.size,
      })),
    };
  }

  async function trustImages() {
    try {
      await api.post('/trusted-senders', { address: m.from.addr });
      toast(`Images from ${m.from.addr} will load automatically`);
    } catch (e) {
      errorToast(e);
    }
  }
  function unsubscribe() {
    const u = m.unsubscribe;
    if (!u) return;
    if (u.oneClick) {
      ui.dialog = {
        type: 'confirm',
        title: `Unsubscribe from ${displayName(m.from)}?`,
        body: `Kern will send a one-click unsubscribe request to ${new URL(u.url).hostname} on your behalf. Nothing else is sent.`,
        action: 'Unsubscribe',
        submit: async () => {
          const r = await api.post(`/messages/${m.id}/unsubscribe`);
          if (r.done) {
            toast(`Unsubscribed from ${displayName(m.from)}`, {
              timeout: 9000,
              action: { label: 'Archive', run: () => threadAction([m.threadId], 'archive').catch(() => {}) },
            });
          } else {
            toast("One-click didn't work, opening their unsubscribe page instead.", { kind: 'error' });
            manualUnsubscribe(u);
          }
        },
      };
    } else {
      manualUnsubscribe(u);
    }
  }
  function manualUnsubscribe(u) {
    if (u.url) {
      window.open(u.url, '_blank', 'noopener,noreferrer');
    } else if (u.mailto) {
      const parsed = new URL(u.mailto);
      openCompose({
        to: [{ name: '', addr: decodeURIComponent(parsed.pathname) }],
        subject: parsed.searchParams.get('subject') || 'unsubscribe',
        bodyHtml: `<p>${(parsed.searchParams.get('body') || 'unsubscribe').replace(/[<>&]/g, '')}</p>`,
      });
    }
  }
</script>

<section class="card" class:open class:unread={!m.seen} aria-label={`Message from ${displayName(m.from)}`}>
  <header>
    <button class="toggle" onclick={onToggle} aria-expanded={open} aria-label={open ? 'Collapse message' : 'Expand message'}></button>
    <div class="avatar display" style:background={`var(--tint-${(hue(m.from.addr) % 6) + 1})`} aria-hidden="true">{initials(m.from)}</div>
    <div class="who">
      <div class="line">
        <button class="name" title="About this sender"
                onclick={(e) => { const r = e.currentTarget.getBoundingClientRect(); ui.senderCard = { addr: m.from.addr, name: m.from.name, x: r.left, y: r.bottom }; }}>
          {displayName(m.from) || '(unknown sender)'}
        </button>
        {#if open && m.from.name}<span class="addr">&lt;{m.from.addr}&gt;</span>{/if}
        {#if showRisk}
          <span class="risk-pill {m.risk.level}"><Icon name="shieldAlert" size={13} /> {m.risk.level === 'high' ? 'High risk' : 'Suspicious'}</span>
        {/if}
        {#if m.isDraft}<span class="chip draft">Draft</span>{/if}
        {#if m.pending}<span class="chip" title="Waiting to be saved on the server">Syncing</span>{/if}
      </div>
      {#if open}
        <button class="to" onclick={() => (showDetails = !showDetails)}>{toLine} <Icon name="chevronDown" size={13} /></button>
      {:else}
        <div class="snippet">{m.snippet}</div>
      {/if}
    </div>
    <div class="meta">
      {#if files.length && !open}<Icon name="clip" size={14} />{/if}
      <time datetime={m.date} title={`${longDate(m.date)} (${ago(new Date(m.date))})`}>{shortDate(m.date)}</time>
      {#if open}
        <button class="icon-btn small" class:on={m.flagged} aria-label={m.flagged ? 'Unstar message' : 'Star message'}
                onclick={() => messageAction([m.id], m.flagged ? 'unstar' : 'star')}>
          <Icon name="star" size={16} fill={m.flagged ? 'currentColor' : 'none'} />
        </button>
        <button class="icon-btn small" aria-label="Reply" title="Reply" onclick={() => openReply(m, 'reply')}><Icon name="reply" size={16} /></button>
        <div class="menu-wrap">
          <button class="icon-btn small" aria-label="More" aria-haspopup="menu" aria-expanded={menu} onclick={() => (menu = !menu)}><Icon name="more" size={16} /></button>
          {#if menu}
            <button class="menu-scrim" aria-label="Close menu" onclick={() => (menu = false)}></button>
            <div class="menu" role="menu">
              <button role="menuitem" onclick={() => { menu = false; openReply(m, 'reply_all'); }}><Icon name="replyAll" size={15} /> Reply all</button>
              <button role="menuitem" onclick={() => { menu = false; openReply(m, 'forward'); }}><Icon name="forward" size={15} /> Forward</button>
              <button role="menuitem" onclick={() => { menu = false; messageAction([m.id], m.seen ? 'unread' : 'read'); }}><Icon name="mail" size={15} /> Mark {m.seen ? 'unread' : 'read'} from here</button>
              <button role="menuitem" onclick={() => { menu = false; ui.dialog = { type: 'snooze', ids: [m.threadId] }; }}><Icon name="clock" size={15} /> Snooze conversation…</button>
              {#if m.fromMe}
                <button role="menuitem" onclick={() => { menu = false; ui.dialog = { type: 'nudge', threadId: m.threadId }; }}><Icon name="bell" size={15} /> Nudge me if nobody replies…</button>
              {/if}
              {#if !m.fromMe}
                <button role="menuitem" onclick={() => { menu = false; ui.dialog = { type: 'spam', ids: [m.threadId], sender: m.from.addr }; }}><Icon name="spam" size={15} /> Report spam…</button>
              {/if}
              <button role="menuitem" onclick={() => { menu = false; setTimeout(() => print(), 50); }}><Icon name="file" size={15} /> Print conversation</button>
              <button role="menuitem" onclick={() => { menu = false; ui.dialog = { type: 'headers', messageId: m.id, subject: m.subject }; }}><Icon name="code" size={15} /> View headers</button>
              <a role="menuitem" href={`/api/messages/${m.id}/raw`} download onclick={() => (menu = false)}><Icon name="download" size={15} /> Download original (.eml)</a>
              <button role="menuitem" onclick={() => { menu = false; messageAction([m.id], 'trash'); }}><Icon name="trash" size={15} /> Delete this message</button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </header>

  {#if open}
    {#if showDetails}
      <dl class="details">
        <dt>From</dt><dd>{m.from.name} &lt;{m.from.addr}&gt;</dd>
        {#if m.replyTo.length}<dt>Reply-To</dt><dd>{m.replyTo.map((a) => a.addr).join(', ')}</dd>{/if}
        {#if m.to.length}<dt>To</dt><dd>{m.to.map((a) => (a.name ? `${a.name} <${a.addr}>` : a.addr)).join(', ')}</dd>{/if}
        {#if m.cc.length}<dt>Cc</dt><dd>{m.cc.map((a) => a.addr).join(', ')}</dd>{/if}
        {#if m.bcc.length}<dt>Bcc</dt><dd>{m.bcc.map((a) => a.addr).join(', ')}</dd>{/if}
        <dt>Date</dt><dd>{longDate(m.date)} <span class="faint">({ago(new Date(m.date))})</span></dd>
        <dt>Folder</dt><dd>{m.folder.name}</dd>
        {#if m.auth && m.auth.trusted}
          <dt>Security</dt>
          <dd>SPF {m.auth.spf || 'none'} · DKIM {(m.auth.dkim || []).map((d) => d.result).join('/') || 'none'} · DMARC {m.auth.dmarc || 'none'}</dd>
        {/if}
      </dl>
    {/if}

    {#if m.blockedBy}
      <div class="note warn">
        <Icon name="block" size={15} />
        Moved to Junk because {m.blockedBy.kind === 'domain' ? 'the domain' : 'the sender'} <b>{m.blockedBy.value}</b> is blocked.
      </div>
    {/if}
    {#if showRisk}
      <RiskPanel risk={m.risk} expanded={m.risk.level === 'high'} />
    {:else if showDetails && !m.fromMe && m.risk.level}
      <RiskPanel risk={m.risk} />
    {/if}
    {#if m.isDraft}
      <div class="note">
        <Icon name="file" size={15} /> This is a draft.
        <button class="btn small" onclick={() => openDraft(m.draftId ?? m)}>Continue editing</button>
      </div>
    {/if}

    <EmailBody {m} />

    {#if files.length}
      <div class="files">
        {#each files as a (a.id)}
          <a class="file" href={`/api/messages/${m.id}/attachments/${a.id}`} download={a.filename} title={a.filename}
             onclick={(e) => { if (a.previewable) { e.preventDefault(); openViewer(a); } }}>
            {#if a.previewable}
              <img src={`/api/messages/${m.id}/attachments/${a.id}?inline=1`} alt="" loading="lazy" />
            {:else}
              <span class="ext">{(a.filename.split('.').pop() || 'file').slice(0, 4).toUpperCase()}</span>
            {/if}
            <span class="fname">{a.filename}</span>
            <span class="fsize">{bytes(a.size)}</span>
            <span class="dl"><Icon name="download" size={15} /></span>
          </a>
        {/each}
      </div>
    {/if}

    <footer class="foot">
      {#if m.unsubscribe && !m.fromMe}
        <button class="btn ghost small" onclick={unsubscribe} title={m.unsubscribe.oneClick ? 'One-click unsubscribe' : 'Opens their unsubscribe page'}>
          <Icon name="unsubscribe" size={14} /> Unsubscribe
        </button>
      {/if}
      {#if !m.fromMe && m.hasHtml && m.risk.level !== 'high'}
        <button class="btn ghost small" onclick={trustImages} title="Always load remote images from this sender (through the privacy proxy)"><Icon name="image" size={14} /> Always load images from sender</button>
      {/if}
      {#if !last}
        <button class="btn ghost small" onclick={() => openReply(m, 'reply')}><Icon name="reply" size={14} /> Reply</button>
      {/if}
    </footer>
  {/if}
</section>

<style>
  .card {
    background: var(--bg-elev);
    border: var(--card-border);
    border-radius: var(--radius);
    margin-bottom: 10px;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .15s;
  }
  .card:not(.open) { background: color-mix(in srgb, var(--bg-elev) 70%, var(--bg)); }
  header { position: relative; display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; }
  .toggle { position: absolute; inset: 0; border: 0; background: transparent; cursor: pointer; border-radius: var(--radius); }
  .avatar {
    flex: none; width: 38px; height: 38px; border-radius: 50%;
    display: grid; place-items: center; font-size: 15px; color: var(--text);
    position: relative; pointer-events: none; box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--text) 8%, transparent);
  }
  .who { flex: 1 1 140px; min-width: 0; position: relative; pointer-events: none; }
  .line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 8px; min-width: 0; }
  .name {
    font-weight: 600; font-size: 14px; pointer-events: auto; border: 0; background: none; padding: 0; color: var(--text);
    cursor: pointer; text-align: left; text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 3px;
    transition: text-decoration-color .15s;
  }
  .name:hover { text-decoration-color: var(--accent); }
  .unread .name { color: var(--text); }
  .addr { color: var(--text-3); font-size: 12.5px; min-width: 0; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .snippet { color: var(--text-3); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 1px; }
  .to {
    pointer-events: auto; border: 0; background: none; padding: 0; margin-top: 1px; cursor: pointer;
    color: var(--text-3); font-size: 12.5px; display: inline-flex; align-items: center; gap: 2px; text-align: left;
  }
  .to:hover { color: var(--text-2); }
  .meta { display: flex; align-items: center; gap: 2px; color: var(--text-3); font-size: 11.5px; font-family: var(--mono); position: relative; white-space: nowrap; flex: none; }
  .meta time { margin: 0 6px 0 4px; }
  .meta .on { color: var(--star); }
  .risk-pill { display: inline-flex; align-items: center; gap: 4px; font-family: var(--mono); font-size: 10.5px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; padding: 1px 7px 1px 5px; border-radius: var(--radius-sm); }
  .risk-pill.high { background: var(--danger-soft); color: var(--danger); }
  .risk-pill.medium { background: var(--warn-soft); color: var(--warn); }
  .chip.draft { background: var(--danger-soft); color: var(--danger); }
  .menu-wrap { position: relative; }
  .menu-scrim { position: fixed; inset: 0; border: 0; background: transparent; z-index: 20; cursor: default; }
  .menu {
    position: absolute; right: 0; top: calc(100% + 4px); z-index: 21; min-width: 230px;
    background: var(--bg-elev); border: var(--card-border); border-radius: var(--radius); box-shadow: var(--shadow-lg);
    padding: 5px; display: grid; animation: rise .14s var(--ease); font-family: var(--ui);
  }
  .menu button, .menu a {
    display: flex; align-items: center; gap: 10px; border: 0; background: none; text-align: left;
    padding: 7px 10px; border-radius: 7px; cursor: pointer; color: var(--text); font-size: 13px; text-decoration: none;
  }
  .menu button:hover, .menu a:hover { background: var(--bg-hover); }
  .details {
    display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; margin: 0 14px 10px 62px;
    padding: 10px 12px; background: var(--bg-sunken); border-radius: 8px; font-size: 12.5px;
  }
  .details dt { color: var(--text-3); }
  .details dd { margin: 0; overflow-wrap: anywhere; }
  .note {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin: 0 14px 10px 62px; padding: 8px 12px; border-radius: 8px; font-size: 13px;
    background: var(--bg-sunken); color: var(--text-2);
  }
  .note.warn { background: var(--warn-soft); color: var(--warn); }
  .files { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 14px 12px 62px; }
  .file {
    display: grid; grid-template-columns: 40px 1fr auto; grid-template-rows: auto auto; column-gap: 10px; align-items: center;
    width: 240px; padding: 8px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm);
    text-decoration: none; color: var(--text); background: var(--bg);
  }
  .file:hover { border-color: var(--line-strong); background: var(--bg-hover); }
  .file img, .file .ext {
    grid-row: span 2; width: 40px; height: 40px; border-radius: 6px; object-fit: cover; background: var(--bg-sunken);
    display: grid; place-items: center; font: 600 10px var(--mono); color: var(--text-2); letter-spacing: .03em;
  }
  .fname { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fsize { font-size: 11.5px; color: var(--text-3); grid-column: 2; }
  .dl { grid-row: 1 / span 2; grid-column: 3; color: var(--text-3); }
  .foot { display: flex; flex-wrap: wrap; gap: 4px; padding: 0 10px 10px 56px; }
  .foot:empty { display: none; }
  @media (max-width: 640px) {
    .details, .note, .files { margin-left: 14px; }
    .foot { padding-left: 10px; }
    .file { width: 100%; }
    .meta time { display: none; }
  }
</style>
