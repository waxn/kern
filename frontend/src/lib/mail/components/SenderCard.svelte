<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Click a sender's name: who is this, really, and what's our history?
  import { api } from '../api.svelte.js';
  import { navigate } from '../router.svelte.js';
  import { errorToast, toast, ui } from '../state.svelte.js';
  import { openCompose } from '../compose.svelte.js';
  import { hue, initials } from '../format.js';
  import Icon from './Icon.svelte';
  import { trapFocus } from '../focus.js';

  let data = $state(null);
  let error = $state('');
  let loadedFor = '';

  const card = $derived(ui.senderCard);
  $effect(() => {
    if (!card || card.addr === loadedFor) return;
    loadedFor = card.addr;
    data = null;
    error = '';
    api.get('/senders', { addr: card.addr }).then((d) => (data = d)).catch((e) => (error = e.message));
  });
  $effect(() => {
    if (!card) loadedFor = '';
  });

  function since(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString([], { month: 'long', year: 'numeric' });
  }
  function close() {
    ui.senderCard = null;
  }
  async function block() {
    try {
      await api.post('/blocklist', { kind: 'address', value: card.addr, note: 'Blocked from sender card' });
      toast(`Blocked ${card.addr}. Future mail goes to Junk.`);
      data.blocked = { kind: 'address', value: card.addr };
    } catch (e) {
      errorToast(e);
    }
  }
  async function trust() {
    try {
      await api.post('/trusted-senders', { address: card.addr });
      data.trustedImages = true;
      toast('Images from this sender will load automatically');
    } catch (e) {
      errorToast(e);
    }
  }
  const pos = $derived.by(() => {
    if (!card) return '';
    const w = 320;
    const left = Math.max(12, Math.min(card.x - 20, innerWidth - w - 12));
    const top = Math.min(card.y + 10, innerHeight - 300);
    return `left:${left}px;top:${top}px;width:${w}px`;
  });
  const relationship = $derived.by(() => {
    if (!data) return '';
    if (!data.received && !data.sent) return 'You have no history with this sender.';
    if (data.sent && data.received) return `You've written to each other: ${data.received} from them, ${data.sent} from you.`;
    if (data.sent) return `You've written to them ${data.sent} time${data.sent === 1 ? '' : 's'}.`;
    if (data.received === 1) return 'This is the only message you have from them.';
    return `${data.received} messages from them.`;
  });
</script>

{#if card}
  <button class="scrim" aria-label="Close sender card" onclick={close}></button>
  <div class="card" style={pos} role="dialog" aria-label={`About ${card.addr}`} tabindex="-1" use:trapFocus>
    <div class="top">
      <div class="avatar display" style:background={`var(--tint-${(hue(card.addr) % 6) + 1})`}>{initials({ name: card.name, addr: card.addr })}</div>
      <div class="who">
        <div class="name">{card.name || card.addr.split('@')[0]}</div>
        <div class="addr num">{card.addr}</div>
      </div>
    </div>
    {#if error}
      <p class="err">{error}</p>
    {:else if !data}
      <div class="loading"><div class="spinner"></div></div>
    {:else}
      {#if data.domain !== data.domainAscii}
        <p class="warn"><Icon name="shieldAlert" size={14} /> International domain: really <b class="num">{data.domainAscii}</b></p>
      {/if}
      <dl>
        <dt class="ledger">History</dt><dd>{relationship}</dd>
        {#if data.firstSeen}<dt class="ledger">First seen</dt><dd>{since(data.firstSeen)}</dd>{/if}
        {#if data.blocked}<dt class="ledger">Status</dt><dd class="blocked">Blocked ({data.blocked.kind} {data.blocked.value})</dd>{/if}
      </dl>
      <div class="acts">
        <button class="btn small" onclick={() => { close(); navigate({ page: 'mail', view: 'search', q: `from:${card.addr} in:anywhere`, threadId: null }); }}>
          <Icon name="search" size={14} /> All their mail
        </button>
        <button class="btn small" onclick={() => { close(); openCompose({ to: [{ name: card.name || '', addr: card.addr }] }); }}>
          <Icon name="pencil" size={14} /> Write
        </button>
        {#if !data.trustedImages}
          <button class="btn small ghost" onclick={trust}><Icon name="image" size={14} /> Trust images</button>
        {/if}
        {#if !data.blocked}
          <button class="btn small ghost danger" onclick={block}><Icon name="block" size={14} /> Block</button>
        {/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; border: 0; background: transparent; z-index: 250; cursor: default; }
  .card {
    position: fixed; z-index: 251; background: var(--bg-elev); border: var(--card-border); border-radius: var(--radius);
    box-shadow: var(--shadow-lg); padding: 14px; animation: rise .14s var(--ease);
  }
  .top { display: flex; gap: 12px; align-items: center; }
  .avatar { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; font-size: 17px; flex: none; }
  .who { min-width: 0; }
  .name { font-weight: 600; font-size: 15px; }
  .addr { font-size: 12px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 12px; margin: 14px 0 12px; font-size: 13px; align-items: baseline; }
  dd { margin: 0; color: var(--text-2); }
  .blocked { color: var(--danger); }
  .warn { display: flex; gap: 6px; align-items: center; margin: 12px 0 0; padding: 7px 10px; border-radius: var(--radius-sm); background: var(--warn-soft); color: var(--warn); font-size: 12.5px; }
  .acts { display: flex; flex-wrap: wrap; gap: 6px; }
  .loading { display: grid; place-items: center; padding: 18px; }
  .err { color: var(--danger); font-size: 13px; }
</style>
