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
  import { account as prefsSrv, dropMailCache, loadAccountPrefs, loadPackages, prefs, saveAccountPrefs, savePrefs } from './state.svelte.js';
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
  // Send mail as (mail/identities.py) and live package tracking (mail/tracking.py).
  let idents = $state([]);
  const blankIdent = { address: '', name: '', via: 'gmail', smtpHost: 'smtp.gmail.com', smtpPort: 465, smtpSecurity: 'ssl', login: '', password: '' };
  let ident = $state(null); // the add form, or null
  let identBusy = $state('');
  let identMsg = $state(null); // {ok, text}
  let tracking = $state(null);
  let trackKey = $state('');
  let countryPick = $state('');
  let mapInfo = $state(null);
  let mapKey = $state('');
  let mapBusy = $state(false);
  let mapMsg = $state(null);
  // The map source being set up (may differ from the one in use until it's saved).
  let mapPick = $state('');
  let customTiles = $state({ light: '', dark: '', attribution: '' });
  const mapSource = $derived((mapInfo?.sources || []).find((x) => x.id === (mapPick || mapInfo?.chosen || 'osm')));
  async function saveMap(provider, key) {
    mapBusy = true;
    mapMsg = null;
    try {
      mapInfo = await api.post('/packages/map', { provider, ...(key !== undefined ? { key } : {}),
        ...(provider === 'custom' ? { custom: customTiles } : {}) });
      mapKey = '';
      mapPick = '';
      const name = mapInfo.sources.find((x) => x.id === mapInfo.provider)?.name || mapInfo.provider;
      mapMsg = { ok: true, text: `The map uses ${name}.` };
      loadPackages();
    } catch (e) {
      mapMsg = { ok: false, text: e.message };
    } finally {
      mapBusy = false;
    }
  }
  // Default country for numbers Parcels can't place without one: from the browser's region.
  let trackCountry = $state((() => { try { return new Intl.Locale(navigator.language).maximize().region || ''; } catch { return ''; } })());
  const COUNTRIES = (() => {
    const codes = 'AD AE AR AT AU BA BE BG BR BY CA CH CL CN CO CY CZ DE DK EE EG ES FI FR GB GR HK HR HU ID IE IL IN IS IT JP KR KZ LI LT LU LV MA MD ME MK MT MX MY NG NL NO NZ PE PH PK PL PT RO RS RU SA SE SG SI SK TH TR TW UA US UY VN ZA'.split(' ');
    let names;
    try { names = new Intl.DisplayNames([navigator.language || 'en'], { type: 'region' }); } catch { names = null; }
    return codes.map((c) => [c, names?.of(c) || c]).sort((a, b) => a[1].localeCompare(b[1]));
  })();
  let trackBusy = $state(false);
  let trackMsg = $state(null);

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
      [trusted, rules, failed, idents, tracking] = await Promise.all([api.get('/trusted-senders'), api.get('/risk/rules'), api.get('/ops/failed'),
        api.get('/identities'), api.get('/packages/tracking')]);
      mapInfo = await api.get('/packages/map').catch(() => null);
      loadPrivate(); // not awaited: an off PC takes a few seconds to say so
    } catch {
      /* not connected yet */
    }
  }
  onMount(loadAll);

  function identVia(v) {
    ident.via = v;
    if (v === 'gmail') Object.assign(ident, { smtpHost: 'smtp.gmail.com', smtpPort: 465, smtpSecurity: 'ssl' });
    if (v === 'account') Object.assign(ident, { smtpHost: '', password: '' });
    if (v === 'other') Object.assign(ident, { smtpHost: '', smtpPort: 465, smtpSecurity: 'ssl' });
  }
  async function addIdent() {
    identBusy = 'save';
    identMsg = null;
    try {
      const { via, ...data } = ident;
      const saved = await api.post('/identities', data);
      if (saved.ownServer) await api.post(`/identities/${saved.id}/test`);
      idents = await api.get('/identities');
      identMsg = { ok: true, text: saved.ownServer ? `Signed in to ${saved.smtpHost}. You can send as ${saved.address}.` : `You can send as ${saved.address}.` };
      ident = null;
    } catch (e) {
      identMsg = { ok: false, text: e.message };
      idents = await api.get('/identities').catch(() => idents);
    } finally {
      identBusy = '';
    }
  }
  async function testIdent(i) {
    identBusy = 't' + i.id;
    identMsg = null;
    try {
      await api.post(`/identities/${i.id}/test`);
      identMsg = { ok: true, text: `Signed in to ${i.smtpHost}.` };
    } catch (e) {
      identMsg = { ok: false, text: e.message };
    } finally {
      identBusy = '';
    }
  }
  async function removeIdent(i) {
    if (!(await ui.confirm({ title: `Stop sending as ${i.address}?`, message: 'Mail you already sent is not affected.', confirmLabel: 'Remove' }))) return;
    await api.del(`/identities/${i.id}`);
    idents = idents.filter((x) => x.id !== i.id);
  }

  // The tracking service being set up (may differ from the one in use until it's saved).
  let trackPick = $state('');
  let scraperUrl = $state(null);
  let scraperFallbacks = $state(null);
  const FALLBACKS = ['UPU', 'ParcelsApp', 'Ship24', '17TRACK', 'Ordertracker', 'Postal Ninja', 'Track718'];
  const service = $derived(trackPick || tracking?.provider || '');
  const serviceInfo = $derived((tracking?.services || []).find((x) => x.id === service));
  const isOn = $derived(!!tracking?.provider && service === tracking.provider);
  async function saveTracking(provider, extra = {}) {
    trackBusy = true;
    trackMsg = null;
    try {
      const body = { provider };
      if (provider) {
        if (trackKey) body.key = trackKey;
        body.country = countryPick || tracking?.country || trackCountry || '';
        if (provider === 'scraper') body.scraper = { url: scraperUrl ?? tracking?.scraper?.url ?? '', fallbacks: scraperFallbacks ?? tracking?.scraper?.fallbacks ?? ['UPU'] };
      }
      tracking = await api.post('/packages/tracking', { ...body, ...extra });
      trackKey = '';
      trackPick = '';
      scraperUrl = scraperFallbacks = null;
      trackMsg = provider ? (tracking.lastError ? { ok: false, text: tracking.lastError }
        : { ok: true, text: 'On. Your packages are being checked now and update over the next minute or two.' }) : null;
    } catch (e) {
      trackMsg = { ok: false, text: e.message };
    } finally {
      trackBusy = false;
    }
  }
  // The private model (mail/private_ai.py): an endpoint on your own machine, apart from Intelligence.
  let priv = $state(null);
  let privForm = $state({ baseUrl: '', model: '', timeout: 120, key: '' });
  let privBusy = $state(false);
  let privMsg = $state(null);
  function privFill(d) {
    priv = d;
    privForm = { baseUrl: d.baseUrl, model: d.model, timeout: d.timeout, key: '' };
  }
  async function loadPrivate() {
    try {
      privFill(await api.get('/private-ai'));
    } catch {
      /* leave the section out */
    }
  }
  async function savePrivate(extra = {}) {
    privBusy = true;
    privMsg = null;
    try {
      const { key, ...rest } = privForm;
      privFill(await api.post('/private-ai', { ...rest, ...(key ? { key } : {}), ...extra }));
    } catch (e) {
      privMsg = { ok: false, text: e.message };
    } finally {
      privBusy = false;
    }
  }
  function toggleFallback(f) {
    const cur = scraperFallbacks ?? tracking?.scraper?.fallbacks ?? ['UPU'];
    scraperFallbacks = cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f];
  }

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
    dropMailCache();
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
      dropMailCache();
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

  {#if st.connected}
    <div class="section-title">Send mail as</div>
    <div class="group">
      <div class="item col">
        <div><b>Other addresses you send from</b><span>For example a Gmail address that forwards to this mailbox: add it with Gmail's own server and
          an app password. Mail then leaves through Gmail (so it's signed by Gmail and doesn't land in spam), one copy is
          saved in Sent here, and replies come back through the forward. Nothing arrives twice. Replies are sent from the
          address the email was written to.</span></div>
        {#if idents.length}
          <ul class="list">
            {#each idents as i (i.id)}
              <li><span><b class="inline">{i.name ? `${i.name} <${i.address}>` : i.address}</b><span class="faint"> · {i.ownServer ? `through ${i.smtpHost}` : `through ${acct?.address || 'this account'}`}</span></span>
                {#if i.ownServer}<button class="btn ghost" disabled={!!identBusy} onclick={() => testIdent(i)}>{identBusy === 't' + i.id ? 'Testing…' : 'Test'}</button>{/if}
                <button class="btn ghost" onclick={() => removeIdent(i)}>Remove</button></li>
            {/each}
          </ul>
        {/if}
        {#if identMsg}<span class="test" class:good={identMsg.ok} class:bad={!identMsg.ok}>{#if identMsg.ok}<CircleCheck size={13} />{:else}<CircleAlert size={13} />{/if} {identMsg.text}</span>{/if}
        {#if ident}
          <div class="identform">
            <div class="providers">
              {#each [['gmail', 'Gmail'], ['account', 'This account’s server (an alias)'], ['other', 'Other server']] as [v, label] (v)}
                <button class="prov" class:on={ident.via === v} onclick={() => identVia(v)}>{label}</button>
              {/each}
            </div>
            <div class="row"><input class="input wide" type="email" bind:value={ident.address} placeholder={ident.via === 'gmail' ? 'you@gmail.com' : 'you@example.com'} aria-label="Address" />
              <input class="input wide" bind:value={ident.name} placeholder="Name (optional)" aria-label="Name" /></div>
            {#if ident.via !== 'account'}
              {#if ident.via === 'other'}
                <div class="row"><input class="input wide" bind:value={ident.smtpHost} placeholder="smtp.example.com" aria-label="SMTP server" /><input class="input port" type="number" bind:value={ident.smtpPort} aria-label="Port" />
                  <select class="input sel" bind:value={ident.smtpSecurity} aria-label="Security"><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></div>
                <input class="input wide" bind:value={ident.login} placeholder="Username (if not the address)" aria-label="Username" />
              {/if}
              <input class="input wide" type="password" bind:value={ident.password} autocomplete="new-password" placeholder={ident.via === 'gmail' ? 'Gmail app password' : 'Password'} aria-label="Password" />
              {#if ident.via === 'gmail'}<p class="hint">Google Account → Security → 2-Step Verification → App passwords. Make one called “Kern” and paste it here.</p>{/if}
            {:else}
              <p class="hint">Your provider must let you send as this address (Purelymail: add it as an alias or a custom domain).</p>
            {/if}
            <div class="row">
              <button class="btn primary" disabled={!!identBusy || !ident.address || (ident.via !== 'account' && (!ident.password || !ident.smtpHost))} onclick={addIdent}>{identBusy === 'save' ? 'Checking…' : 'Add address'}</button>
              <button class="btn ghost" onclick={() => { ident = null; identMsg = null; }}>Cancel</button>
            </div>
          </div>
        {:else}
          <div><button class="btn" onclick={() => { ident = { ...blankIdent }; identMsg = null; }}>Add an address</button></div>
        {/if}
      </div>
    </div>

    <div class="section-title" id="tracking">Package tracking</div>
    <div class="group">
      <div class="item col">
        <div><b>Live tracking</b><span>Shipping emails only say what the shop knew when it wrote them, so a package delivered without a
          “delivered” email would stay on the way. With live tracking, the mail service checks each package with the carrier about
          every 90 minutes (more often on delivery day) for its real status, scans and a map. Only tracking numbers are sent, and
          your country for numbers that need one.</span></div>
        <div class="providers" role="radiogroup" aria-label="Tracking service">
          {#each [['', 'Off'], ...((tracking?.services || []).map((x) => [x.id, x.name]))] as [id, name] (id)}
            <button class="prov" class:on={service === id} role="radio" aria-checked={service === id}
                    onclick={() => { trackPick = id; trackMsg = null; if (!id && tracking?.provider) saveTracking(''); }}>{name}{#if id && tracking?.provider === id} ✓{/if}</button>
          {/each}
        </div>
        {#if service === 'parcels'}
          <p class="hint">Parcels' free plan covers 300 packages a month; each package counts once a month however often it's
            checked. Sign up at <a href="https://parcelsapp.com/dashboard" target="_blank" rel="noopener noreferrer">parcelsapp.com</a> and copy the API key.</p>
        {:else if service === 'trackingmore'}
          <p class="hint">TrackingMore charges one credit when a package is first added; checking it again is free. Get a key at
            <a href="https://www.trackingmore.com/signup.html" target="_blank" rel="noopener noreferrer">trackingmore.com</a> (Developer → API key).</p>
        {:else if service === 'scraper'}
          <p class="hint">Peek's open-source <a href="https://github.com/plhery/universal-parcel-scraper" target="_blank" rel="noopener noreferrer">Universal
            Parcel Scraper</a> reads each carrier's own tracking site: no account, no key, no limit. {tracking?.scraper?.builtIn
              ? (tracking.scraper.trawl ? 'It\'s built into this Kern, without a browser service, so USPS, FedEx and other browser-only carriers need Parcels or TrackingMore.'
                : 'It\'s built into this Kern, but it has no browser service, so USPS, FedEx and other carriers that only answer a browser can\'t be checked.')
              : 'This Kern has no built-in copy (rebuild the Docker image), so enter the address of one you run.'}
            Amazon Logistics can't be tracked live (only in your Amazon account).</p>
        {/if}
        {#if isOn}
          {@const a = tracking.allowance}
          <div class="allow">
            <span class="test" class:good={!tracking.lastError} class:bad={!!tracking.lastError}>{#if tracking.lastError}<CircleAlert size={13} /> {tracking.lastError}{:else}<CircleCheck size={13} /> On{#if tracking.lastChecked} · checked {when(tracking.lastChecked)}{/if}{/if}</span>
            {#if a}
              <div class="meter" role="meter" aria-valuemin="0" aria-valuemax={a.limit} aria-valuenow={a.used} aria-label="Packages tracked this month">
                <span style:width="{Math.min(100, (a.used / a.limit) * 100)}%" class:low={a.left < a.limit * 0.1}></span>
              </div>
              <span class="faint"><b class="inline">{a.left.toLocaleString()}</b> of {a.limit.toLocaleString()} left this month{a.exact ? ' (from the service)' : ' (counted here)'}</span>
            {/if}
          </div>
        {/if}
        {#if service}
          <div class="row">
            {#if serviceInfo?.needsKey}
              <input class="input wide" type="password" bind:value={trackKey} autocomplete="off"
                     placeholder={tracking?.keys?.[service] ? 'Key saved. Paste a new one to replace it.' : `${serviceInfo.name} API key`} aria-label="{serviceInfo.name} API key" />
            {/if}
            {#if service === 'parcels'}
              <select class="input sel" value={countryPick || tracking?.country || trackCountry} onchange={(e) => (countryPick = e.currentTarget.value)} aria-label="Your country" title="Where your packages are delivered">
                <option value="">Country…</option>
                {#each COUNTRIES as [code, name] (code)}<option value={code}>{name}</option>{/each}
              </select>
            {/if}
            {#if service === 'scraper'}
              <input class="input wide" value={scraperUrl ?? tracking?.scraper?.url ?? ''} oninput={(e) => (scraperUrl = e.currentTarget.value)}
                     placeholder={tracking?.scraper?.builtIn ? 'Built in (or your scraper, https://…)' : 'https://parcels.example.com:8080'} aria-label="Scraper address" />
              <input class="input" type="password" bind:value={trackKey} autocomplete="off" placeholder="Token (optional)" aria-label="Scraper token" style="width:150px" />
            {/if}
            <button class="btn primary" disabled={trackBusy || (serviceInfo?.needsKey && !trackKey && !tracking?.keys?.[service])}
                    onclick={() => saveTracking(service)}>{trackBusy ? 'Checking…' : isOn ? 'Save' : 'Turn on'}</button>
          </div>
          {#if service === 'scraper'}
            <div class="fallbacks"><span class="faint">When the carrier's own site has nothing, also ask:</span>
              {#each FALLBACKS as f (f)}
                {@const on = (scraperFallbacks ?? tracking?.scraper?.fallbacks ?? ['UPU']).includes(f)}
                <label class="fb"><input type="checkbox" checked={on} onchange={() => toggleFallback(f)} /> {f}</label>
              {/each}
              <span class="faint small">Each one you tick receives the tracking number.</span>
            </div>
          {/if}
          {#if isOn && serviceInfo?.metered}
            <div class="row lim"><span class="faint">Packages a month on your plan</span><input class="input port" type="number" min="1" value={tracking.allowance?.limit}
              onchange={(e) => saveTracking(service, { limit: Number(e.currentTarget.value) || undefined })} aria-label="Packages a month on your plan" /></div>
          {/if}
        {/if}
        {#if trackMsg}<span class="test" class:good={trackMsg.ok} class:bad={!trackMsg.ok}>{#if trackMsg.ok}<CircleCheck size={13} />{:else}<CircleAlert size={13} />{/if} {trackMsg.text}</span>{/if}
      </div>
      <div class="item col">
        <div><b>Package map</b><span>Each package shows a line through its scans. Places are looked up on OpenStreetMap, and map tiles
          are fetched by your Kern server, so your browser never contacts the map service.</span></div>
        <div class="providers" role="radiogroup" aria-label="Map source">
          {#each mapInfo?.sources || [] as x (x.id)}
            <button class="prov" class:on={(mapPick || mapInfo.chosen) === x.id} role="radio" aria-checked={(mapPick || mapInfo.chosen) === x.id}
                    onclick={() => { mapPick = x.id; mapMsg = null; if (!x.needsKey && x.id !== 'custom') saveMap(x.id); }}>{x.name}{#if mapInfo.provider === x.id} ✓{/if}</button>
          {/each}
        </div>
        {#if mapSource?.id === 'osm'}
          <p class="hint">OpenStreetMap's own map, greyed down to fit the theme. No key.</p>
        {:else if mapSource?.id === 'esri'}
          <p class="hint">Esri's quiet grey canvas, with a dark and a light version that match the theme. No key.</p>
        {:else if mapSource?.needsKey}
          <p class="hint">{mapSource.name} has dark and light maps that match the theme, and a free plan. Get a key at
            <a href={mapSource.signup} target="_blank" rel="noopener noreferrer">{new URL(mapSource.signup).hostname}</a>.</p>
          <div class="row">
            <input class="input wide" type="password" bind:value={mapKey} autocomplete="off"
                   placeholder={mapInfo?.keys?.[mapSource.id] ? 'Key saved. Paste a new one to replace it.' : `${mapSource.name} key`} aria-label="{mapSource.name} key" />
            <button class="btn" disabled={mapBusy || (!mapKey && !mapInfo?.keys?.[mapSource.id])} onclick={() => saveMap(mapSource.id, mapKey || undefined)}>{mapBusy ? 'Checking…' : 'Use ' + mapSource.name}</button>
          </div>
        {:else if mapSource?.id === 'custom'}
          <p class="hint">Any tile server: an address with {'{z}'}, {'{x}'} and {'{y}'} in it, over https. Add a second one for the dark theme if it has one.</p>
          <div class="row"><input class="input wide" value={customTiles.light || mapInfo?.custom?.light || ''} oninput={(e) => (customTiles.light = e.currentTarget.value)} placeholder="https://tiles.example.com/{'{z}'}/{'{x}'}/{'{y}'}.png" aria-label="Tile address" /></div>
          <div class="row"><input class="input wide" value={customTiles.dark || mapInfo?.custom?.dark || ''} oninput={(e) => (customTiles.dark = e.currentTarget.value)} placeholder="Dark theme tiles (optional)" aria-label="Dark tile address" />
            <input class="input wide" value={customTiles.attribution || mapInfo?.custom?.attribution || ''} oninput={(e) => (customTiles.attribution = e.currentTarget.value)} placeholder="Credit line, e.g. © OpenStreetMap contributors" aria-label="Map credit line" /></div>
          <div class="row"><button class="btn" disabled={mapBusy} onclick={() => saveMap('custom')}>{mapBusy ? 'Checking…' : 'Use these tiles'}</button></div>
        {/if}
        {#if mapMsg}<span class="test" class:good={mapMsg.ok} class:bad={!mapMsg.ok}>{#if mapMsg.ok}<CircleCheck size={13} />{:else}<CircleAlert size={13} />{/if} {mapMsg.text}</span>{/if}
      </div>
    </div>

    <div class="section-title" id="private">Private model</div>
    <div class="group">
      <div class="item col">
        <div><b>Your own AI endpoint</b><span>An OpenAI-compatible server you run yourself, such as LM Studio, Ollama or llama.cpp. It is kept apart from
          Intelligence: mail is only ever shown to this one, never to a hosted model. Plain http:// works, and Kern waits a good while for
          an answer. If it's switched off, nothing happens and mail is sorted the normal way. Kern runs on a server, so “localhost” means
          that server: use your PC's address on the network (in Docker, host.docker.internal also reaches the machine it runs on).</span></div>
        <div class="row">
          <input class="input wide" bind:value={privForm.baseUrl} placeholder="http://192.168.1.20:1234/v1" aria-label="Private model address" />
          {#if priv?.configured}
            <span class="test" class:good={priv.online} class:bad={priv.online === false} aria-live="polite">
              {#if priv.online}<CircleCheck size={13} /> Online{:else if priv.online === false}<CircleAlert size={13} /> Offline{/if}</span>
          {/if}
        </div>
        <div class="row">
          <input class="input wide" bind:value={privForm.model} list="priv-models" placeholder="Model (empty: whichever is loaded)" aria-label="Private model name" />
          <datalist id="priv-models">{#each priv?.models || [] as m (m)}<option value={m}></option>{/each}</datalist>
          <input class="input" type="password" bind:value={privForm.key} autocomplete="off" style="width:170px"
                 placeholder={priv?.hasKey ? 'Key saved' : 'API key (optional)'} aria-label="Private model API key" />
        </div>
        <div class="row lim"><span class="faint">Wait up to</span><input class="input port" type="number" min="10" max="900" bind:value={privForm.timeout} aria-label="Seconds to wait for an answer" /><span class="faint">seconds for an answer</span>
          <button class="btn primary" disabled={privBusy || !privForm.baseUrl} onclick={() => savePrivate()}>{privBusy ? 'Checking…' : 'Save'}</button>
          {#if priv?.configured}<button class="btn ghost" disabled={privBusy} onclick={() => { privForm.baseUrl = ''; privForm.key = ''; savePrivate({ baseUrl: '', key: '' }); }}>Remove</button>{/if}</div>
        {#if privMsg}<span class="test bad"><CircleAlert size={13} /> {privMsg.text}</span>{/if}
      </div>
      {#if priv?.configured}
        <div class="item"><div><b>Sort incoming mail</b><span>New mail is shown to the private model, which decides Inbox or Junk. People you've written to are never judged.</span></div>
          <input type="checkbox" checked={priv.sortMail} onchange={(e) => savePrivate({ sortMail: e.currentTarget.checked })} /></div>
      {/if}
    </div>
  {/if}

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
      <div class="item"><div><b>Layout</b><span>This browser. Split shows the conversation next to the list; full width lets the inbox fill the window and opens a conversation over it, like Gmail.</span></div>
        {@render seg(prefs.readingPane ? 'split' : 'full', [['split', 'Split'], ['full', 'Full width']], (v) => setLocal('readingPane', v === 'split'))}</div>
      <div class="item"><div><b>Fit emails to the theme</b><span>This browser. Emails sit on Kern's background instead of a white sheet; in the dark theme their colors are darkened to match (mail that's dark already keeps its colors). Any email can be shown in its original colors from the message.</span></div><input type="checkbox" checked={prefs.darkEmails} onchange={() => setLocal('darkEmails', !prefs.darkEmails)} /></div>
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
  .allow { display: grid; gap: 6px; }
  .meter { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; max-width: 360px; }
  .meter span { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
  .meter span.low { background: var(--danger); }
  .lim { align-items: center; }
  .fallbacks { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; font-size: 12.5px; }
  .fb { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2) !important; }
  .small { font-size: 12px; width: 100%; }
  .identform { display: grid; gap: 8px; padding: 10px; border: 1px dashed var(--border-strong); border-radius: var(--radius); }
  .inline { display: inline !important; }
</style>
