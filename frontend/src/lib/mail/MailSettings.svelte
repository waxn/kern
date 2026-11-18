<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Settings → Mail: connect the account, writing and reading preferences,
  // images, templates, block list, phishing rules and changes that failed.
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { CircleAlert, CircleCheck, KeyRound, Plug, Unplug } from '@lucide/svelte';
  import { ui } from '#lib/state/ui.svelte.ts';
  import { api } from './api.svelte.js';
  import { loadMailStatus, mailStatus } from './status.svelte.js';
  import { account as prefsSrv, loadAccountPrefs, prefs, saveAccountPrefs, savePrefs } from './state.svelte.js';
  import { loadTemplates, templates } from './templates.svelte.js';

  const PROVIDERS = [
    { id: 'purelymail', name: 'Purelymail', imap_host: 'imap.purelymail.com', imap_port: 993, smtp_host: 'smtp.purelymail.com', smtp_port: 465, smtp_security: 'ssl', authserv_id: 'purelymail.com' },
    { id: 'fastmail', name: 'Fastmail', imap_host: 'imap.fastmail.com', imap_port: 993, smtp_host: 'smtp.fastmail.com', smtp_port: 465, smtp_security: 'ssl', hint: 'Use an app password (Fastmail → Settings → Privacy & Security).' },
    { id: 'gmail', name: 'Gmail', imap_host: 'imap.gmail.com', imap_port: 993, smtp_host: 'smtp.gmail.com', smtp_port: 465, smtp_security: 'ssl', authserv_id: 'mx.google.com', server_saves_sent: true, hint: 'Use an app password (Google Account → Security → App passwords). IMAP must be on in Gmail settings.' },
    { id: 'icloud', name: 'iCloud', imap_host: 'imap.mail.me.com', imap_port: 993, smtp_host: 'smtp.mail.me.com', smtp_port: 587, smtp_security: 'starttls', hint: 'Use an app-specific password (appleid.apple.com).' },
    { id: 'other', name: 'Other', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 465, smtp_security: 'ssl' },
  ];
  const blank = { address: '', login: '', from_name: '', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 465, smtp_security: 'ssl',
                  tls_verify: true, server_saves_sent: false, authserv_id: '', aliases: [] };

  let form = $state({ ...blank });
  let aliases = $state('');
  let password = $state('');
  let provider = $state('');
  let advanced = $state(false);
  let busy = $state('');
  let test = $state(null); // {ok, text}
  let trusted = $state([]);
  let rules = $state(null);
  let failed = $state([]);
  let filled = false;

  const st = $derived(mailStatus.data);
  const twofa = $derived(st?.two_factor);
  const ready = $derived(!!(twofa?.enabled && twofa?.session_verified));
  const acct = $derived(st?.account);
  const hint = $derived(PROVIDERS.find((p) => p.id === provider)?.hint || '');

  function fill(a) {
    if (!a || filled || !('imap_host' in a)) return;
    filled = true;
    form = { ...blank, ...Object.fromEntries(Object.keys(blank).map((k) => [k, a[k] ?? blank[k]])) };
    aliases = (a.aliases || []).join(', ');
    provider = PROVIDERS.find((p) => p.imap_host && p.imap_host === a.imap_host)?.id || (a.imap_host ? 'other' : '');
  }
  $effect(() => fill(acct));

  async function loadAll() {
    await loadMailStatus();
    if (!ready) return;
    loadAccountPrefs();
    loadTemplates();
    try {
      [trusted, rules, failed] = await Promise.all([api.get('/trusted-senders'), api.get('/risk/rules'), api.get('/ops/failed')]);
    } catch {
      /* not connected yet */
    }
  }
  onMount(loadAll);

  function pick(p) {
    provider = p.id;
    const { id, name, hint: _h, ...cfg } = p;
    form = { ...form, ...cfg, server_saves_sent: !!p.server_saves_sent, authserv_id: p.authserv_id || '' };
    test = null;
  }
  function body() {
    return { ...form, aliases: aliases.split(/[,\s]+/).filter(Boolean), ...(password ? { password } : {}) };
  }
  async function run(kind, fn) {
    busy = kind;
    try {
      await fn();
    } catch (e) {
      if (kind === 'test') test = { ok: false, text: e.message };
      else ui.error(e);
    } finally {
      busy = '';
    }
  }
  const doTest = () => run('test', async () => {
    test = null;
    await api.post('/account/test', body());
    test = { ok: true, text: 'Signed in to both servers.' };
  });
  const save = () => run('save', async () => {
    mailStatus.data = { ...(await api.put('/account', { ...body(), enabled: true })), two_factor: twofa };
    password = '';
    ui.toast('Mail account connected. The first download can take a while for a big mailbox.');
    loadAll();
  });
  async function disconnect() {
    const forget = await ui.confirm({
      title: 'Disconnect this mailbox?',
      message: 'Syncing stops and the password is forgotten. Your mail stays on the mail server.',
      confirmLabel: 'Disconnect',
    });
    if (!forget) return;
    const wipe = await ui.confirm({
      title: 'Also remove the downloaded copy?',
      message: 'Deletes the local copy of your messages from this Kern server (snoozes, follow-ups and labels too). Templates, block rules and preferences stay. Choose Cancel to keep it.',
      confirmLabel: 'Remove local copy',
      danger: true,
    });
    run('off', async () => {
      await api.del('/account' + (wipe ? '?forget=1' : ''));
      filled = false;
      await loadMailStatus();
      ui.toast(wipe ? 'Disconnected and removed the local copy.' : 'Disconnected.');
    });
  }
  async function setPref(changes) {
    try {
      await saveAccountPrefs(changes);
    } catch (e) {
      ui.error(e);
    }
  }
  let sigTimer;
  function sigSoon(v) {
    clearTimeout(sigTimer);
    sigTimer = setTimeout(() => setPref({ signature: v }), 600);
  }
  function setLocal(k, v) {
    prefs[k] = v;
    savePrefs();
  }
  async function toggleNotifications() {
    if (!prefs.notifications && 'Notification' in window) {
      if ((await Notification.requestPermission()) !== 'granted') return;
    }
    setLocal('notifications', !prefs.notifications);
  }
  async function untrust(t) {
    try {
      await api.del(`/trusted-senders/${t.id}`);
      trusted = trusted.filter((x) => x.id !== t.id);
    } catch (e) {
      ui.error(e);
    }
  }
  async function delTemplate(t) {
    if (!(await ui.confirm({ title: `Delete the template “${t.name}”?`, confirmLabel: 'Delete', danger: true }))) return;
    try {
      await api.del(`/templates/${t.id}`);
      loadTemplates();
    } catch (e) {
      ui.error(e);
    }
  }
  async function renameTemplate(t, name) {
    if (!name.trim() || name === t.name) return;
    try {
      await api.patch(`/templates/${t.id}`, { name });
      loadTemplates();
    } catch (e) {
      ui.error(e);
    }
  }
  async function opAction(op, action) {
    try {
      await api.post(`/ops/${op.id}`, { action });
      failed = failed.filter((o) => o.id !== op.id);
      ui.toast(action === 'retry' ? 'Trying again' : 'Dismissed');
    } catch (e) {
      ui.error(e);
    }
  }
  function when(iso) {
    return iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—';
  }
</script>

{#snippet seg(value, options, onpick)}
  <div class="seg">{#each options as [v, label] (v)}<button class:on={value === v} onclick={() => onpick(v)}>{label}</button>{/each}</div>
{/snippet}

{#if !st}
  <p class="lede">Loading…</p>
{:else if !st.allowed && !st.connected}
  <p class="lede">An administrator has turned mail off on this server.</p>
{:else if !twofa.enabled || !twofa.session_verified}
  <p class="lede">Read and send your email in Kern, with a local copy for fast search.</p>
  <div class="group">
    <div class="item">
      <div>
        <b class="need"><KeyRound size={15} /> {twofa.enabled ? 'Sign in again with your code' : 'Two-factor sign-in comes first'}</b>
        <span>{twofa.enabled ? 'This browser signed in with your password only. Sign out and back in with your authenticator code to connect or change mail.' : 'Your mailbox will be reachable through Kern, so it needs more than a password. Turn on two-factor sign-in, then come back here.'}</span>
      </div>
      {#if !twofa.enabled}<button class="btn primary" onclick={() => goto('/settings?s=account')}>Set up two-factor</button>{/if}
    </div>
  </div>
{:else}
  <p class="lede">Kern syncs your mailbox over IMAP and sends over SMTP. The mail server stays the source of truth: changes on your phone show up here and the other way round. Your password is encrypted on this server and never sent back to the browser.</p>

  <div class="section-title">Account</div>
  <div class="group">
    {#if st.connected}
      <div class="item">
        <div>
          <b class="ok"><CircleCheck size={15} /> {acct.address}</b>
          <span>
            {#if st.worker?.state === 'error'}Can't reach the server: {st.worker.lastError}
            {:else if st.worker?.state}{st.worker.state === 'idle' ? 'Up to date' : st.worker.detail || st.worker.state}{#if st.worker.heartbeat} · checked {when(st.worker.heartbeat)}{/if}
            {:else}Waiting for the mail service to pick it up…{/if}
          </span>
        </div>
        <div class="row">
          <a class="btn" href="/mail/inbox">Open mail</a>
          <button class="btn ghost" disabled={!!busy} onclick={disconnect}><Unplug size={14} />Disconnect</button>
        </div>
      </div>
    {/if}
    <div class="item col">
      <div><b>{st.connected ? 'Change settings' : 'Connect a mailbox'}</b><span>Pick your provider, or Other for any IMAP/SMTP server.</span></div>
      <div class="providers">
        {#each PROVIDERS as p (p.id)}<button class="prov" class:on={provider === p.id} onclick={() => pick(p)}>{p.name}</button>{/each}
      </div>
      {#if hint}<p class="hint">{hint}</p>{/if}
    </div>
    <div class="item"><div><b>Email address</b><span>Also the From address.</span></div><input class="input wide" type="email" bind:value={form.address} autocomplete="off" placeholder="you@example.com" /></div>
    <div class="item"><div><b>Password</b><span>{acct?.has_password ? 'Saved. Leave empty to keep it.' : 'Or an app password, if your provider uses them.'}</span></div><input class="input wide" type="password" bind:value={password} autocomplete="new-password" placeholder={acct?.has_password ? '••••••••' : ''} /></div>
    <div class="item"><div><b>Your name</b><span>Shown to people you write to.</span></div><input class="input wide" bind:value={form.from_name} placeholder="Your name" /></div>
    {#if provider === 'other' || advanced}
      <div class="item"><div><b>Incoming (IMAP)</b><span>Always encrypted (TLS), usually port 993.</span></div>
        <div class="row"><input class="input wide" bind:value={form.imap_host} placeholder="imap.example.com" /><input class="input port" type="number" bind:value={form.imap_port} /></div></div>
      <div class="item"><div><b>Outgoing (SMTP)</b><span>SSL/TLS on 465, or STARTTLS on 587.</span></div>
        <div class="row"><input class="input wide" bind:value={form.smtp_host} placeholder="smtp.example.com" /><input class="input port" type="number" bind:value={form.smtp_port} />
          <select class="input sel" bind:value={form.smtp_security}><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></div></div>
    {/if}
    {#if advanced}
      <div class="item"><div><b>Username</b><span>Only if your provider's login isn't your email address.</span></div><input class="input wide" bind:value={form.login} placeholder={form.address} /></div>
      <div class="item"><div><b>Other addresses</b><span>Aliases that also count as you (comma separated).</span></div><input class="input wide" bind:value={aliases} placeholder="me@other.example" /></div>
      <div class="item"><div><b>Server keeps a copy of sent mail</b><span>Turn on if sent messages show up twice in Sent.</span></div><input type="checkbox" bind:checked={form.server_saves_sent} /></div>
      <div class="item"><div><b>Authentication-Results name</b><span>The authserv-id your provider writes into Authentication-Results headers. Only those headers are trusted for the phishing check (others can be forged). Look at a received message's raw source.</span></div><input class="input wide" bind:value={form.authserv_id} placeholder="e.g. purelymail.com" /></div>
      <div class="item"><div><b>Check certificates</b><span>Leave on. Off only for a server with a self-signed certificate you trust.</span></div><input type="checkbox" bind:checked={form.tls_verify} /></div>
    {/if}
    <div class="item">
      <div>
        {#if test}<span class="test" class:good={test.ok} class:bad={!test.ok}>{#if test.ok}<CircleCheck size={13} />{:else}<CircleAlert size={13} />{/if} {test.text}</span>
        {:else}<button class="linklike" onclick={() => (advanced = !advanced)}>{advanced ? 'Fewer options' : 'More options'}</button>{/if}
      </div>
      <div class="row">
        <button class="btn" disabled={!!busy || !form.address || !form.imap_host} onclick={doTest}>{busy === 'test' ? 'Testing…' : 'Test'}</button>
        <button class="btn primary" disabled={!!busy || !form.address || !form.imap_host || !form.smtp_host || (!password && !acct?.has_password)} onclick={save}><Plug size={14} />{busy === 'save' ? 'Saving…' : st.connected ? 'Save' : 'Connect'}</button>
      </div>
    </div>
  </div>

  {#if prefsSrv.loaded}
    <div class="section-title">Writing</div>
    <div class="group">
      <div class="item col"><div><b>Signature</b><span>Plain text, added below new messages after a “-- ” line.</span></div>
        <textarea class="input" rows="3" value={prefsSrv.signature} oninput={(e) => sigSoon(e.currentTarget.value)} placeholder="Your name&#10;example.com"></textarea></div>
      <div class="item"><div><b>Sign replies and forwards too</b></div><input type="checkbox" checked={prefsSrv.signature_on_replies} onchange={(e) => setPref({ signature_on_replies: e.currentTarget.checked })} /></div>
      <div class="item"><div><b>Undo send</b><span>How long a message waits before it really goes out.</span></div>
        {@render seg(prefsSrv.undo_seconds ?? 8, [[0, 'Off'], [5, '5 s'], [8, '8 s'], [15, '15 s'], [30, '30 s']], (v) => setPref({ undo_seconds: v }))}</div>
      <div class="item col"><div><b>Reply templates</b><span>Save one from the composer's template button; insert it there too.</span></div>
        {#if templates.items.length}
          <ul class="list">
            {#each templates.items as t (t.id)}
              <li><input class="input plain" value={t.name} onchange={(e) => renameTemplate(t, e.currentTarget.value)} aria-label="Template name" />
                <span class="faint">{t.uses ? `used ${t.uses}×` : 'unused'}</span><button class="btn ghost" onclick={() => delTemplate(t)}>Delete</button></li>
            {/each}
          </ul>
        {:else}<span class="faint">None yet.</span>{/if}
      </div>
    </div>

    <div class="section-title">Reading</div>
    <div class="group">
      <div class="item"><div><b>Mark as read</b></div>{@render seg(prefsSrv.mark_read, [['open', 'When opened'], ['delay', 'After 2 s'], ['manual', 'Manually']], (v) => setPref({ mark_read: v }))}</div>
      <div class="item"><div><b>After archiving or deleting</b></div>{@render seg(prefsSrv.after_action, [['next', 'Open next'], ['list', 'Back to list']], (v) => setPref({ after_action: v }))}</div>
      <div class="item"><div><b>Reading pane</b><span>This browser. Conversation next to the list when there's room.</span></div><input type="checkbox" checked={prefs.readingPane} onchange={() => setLocal('readingPane', !prefs.readingPane)} /></div>
      <div class="item"><div><b>Desktop notifications</b><span>This browser. A generic “New mail” alert while Kern is in the background; never the sender or subject.</span></div><input type="checkbox" checked={prefs.notifications} onchange={toggleNotifications} /></div>
    </div>
  {/if}

  <div class="section-title">Privacy and safety</div>
  <div class="group">
    <div class="item col"><div><b>Images</b><span>Remote images are blocked until you load them. These senders' images load automatically, through Kern's image proxy, so senders never see your address or browser.</span></div>
      {#if trusted.length}
        <ul class="list">{#each trusted as t (t.id)}<li><span>{t.address}</span><button class="btn ghost" onclick={() => untrust(t)}>Remove</button></li>{/each}</ul>
      {:else}<span class="faint">No trusted senders.</span>{/if}
    </div>
    <div class="item"><div><b>Blocked senders</b><span>Mail from them goes straight to Junk, on the mail server too.</span></div><a class="btn" href="/mail/blocklist">Manage</a></div>
    {#if rules}
      <details class="item col rules">
        <summary><b>Phishing checks</b><span>Each message is scored by these rules (headers, sender, link targets, attachment names; never sent anywhere). Medium at {rules.thresholds.medium} points, high at {rules.thresholds.high}.</span></summary>
        <table>
          <tbody>
            {#each rules.rules as r (r.id)}
              <tr class:off={!r.enabled}><td><b>{r.title}</b><span>{r.description}</span></td><td class="w">{r.enabled ? (r.weight > 0 ? '+' : '') + r.weight : 'off'}</td></tr>
            {/each}
          </tbody>
        </table>
        <span class="faint">The weights are in <code>backend/mail/risk/rules.yaml</code> on the server (or the file named by <code>KERN_RISK_RULES_FILE</code>).</span>
      </details>
    {/if}
  </div>

  {#if failed.length}
    <div class="section-title">Changes that couldn't be saved</div>
    <div class="group">
      {#each failed as op (op.id)}
        <div class="item"><div><b>{op.description}</b><span title={op.error}>{op.error.split(':')[0]} · {when(op.failedAt)}</span></div>
          <div class="row"><button class="btn" onclick={() => opAction(op, 'retry')}>Retry</button><button class="btn ghost" onclick={() => opAction(op, 'dismiss')}>Dismiss</button></div></div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
  .item { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
  .item.col { flex-direction: column; align-items: stretch; }
  .item:first-child { border-top: 0; }
  .item > div:first-child { flex: 1; min-width: 220px; }
  .item b { display: block; font-weight: 550; }
  .item span { color: var(--text-3); font-size: 12.5px; }
  a.btn { text-decoration: none; }
  .need, .ok { display: flex !important; align-items: center; gap: 6px; }
  .ok { color: var(--c-green); }
  .row { display: flex; gap: 6px; flex-wrap: wrap; }
  .wide { width: min(280px, 100%); }
  .port { width: 76px; }
  .sel { width: 110px; }
  .seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); flex-wrap: wrap; }
  .seg button { padding: 3px 11px; border-radius: 4px; color: var(--text-2); }
  .seg button.on { background: var(--surface); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
  .providers { display: flex; flex-wrap: wrap; gap: 6px; }
  .prov { padding: 5px 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-2); }
  .prov.on { border-color: var(--accent); color: var(--text); background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .hint { margin: 0; font-size: 12.5px; color: var(--text-2); }
  .test { display: inline-flex !important; align-items: center; gap: 5px; }
  .test.good { color: var(--c-green) !important; }
  .test.bad { color: var(--danger) !important; }
  .linklike { color: var(--accent); font-size: 12.5px; }
  textarea.input { width: 100%; font-family: var(--font-sans); }
  .list { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  .list li { display: flex; align-items: center; gap: 10px; }
  .list li > :first-child { flex: 1; }
  .input.plain { border-color: transparent; background: none; padding-left: 0; }
  .input.plain:focus { border-color: var(--border-strong); background: var(--bg); padding-left: 8px; }
  .rules summary { cursor: pointer; display: grid; gap: 2px; }
  .rules table { width: 100%; border-collapse: collapse; margin: 8px 0; }
  .rules td { padding: 6px 0; border-top: 1px solid var(--border); vertical-align: top; }
  .rules td span { display: block; }
  .rules td.w { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; padding-left: 12px; color: var(--text-2); }
  .rules tr.off { opacity: 0.55; }
</style>
