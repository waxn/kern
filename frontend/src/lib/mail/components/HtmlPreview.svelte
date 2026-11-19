<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // SECURITY: an HTML attachment is never loaded from its own URL. The server
  // runs it through the email sanitizer (…/attachments/<id>/html) and it is
  // shown exactly like an email body: srcdoc, no allow-scripts, strict CSP
  // (see emailFrame.js). Remote images stay blocked until you load them.
  import { api } from '../api.svelte.js';
  import { buildSrcdoc, SANDBOX } from '../emailFrame.js';
  import Icon from './Icon.svelte';

  let { messageId, id, risky = false } = $props();
  let body = $state(null);
  let error = $state('');

  async function load(images = false) {
    error = '';
    try {
      body = await api.get(`/messages/${messageId}/attachments/${id}/html`, images ? { images: 1 } : {});
    } catch (e) {
      error = e.message;
    }
  }
  $effect(() => {
    void [messageId, id];
    body = null;
    load();
  });
  // A page margin of our own around the (already sanitized) markup.
  const srcdoc = $derived(body ? buildSrcdoc(`<div style="padding:14px 22px">${body.html}</div>`, location.origin) : null);
</script>

<div class="html">
  {#if body && body.remoteImages > 0 && !body.imagesLoaded}
    <div class="bar">
      <Icon name="image" size={14} />
      <span>{body.remoteImages} remote image{body.remoteImages === 1 ? '' : 's'} blocked.</span>
      <button class="btn small" onclick={() => load(true)}>{risky ? 'Load anyway' : 'Load images'}</button>
    </div>
  {/if}
  {#if error}<p class="msg">{error}</p>
  {:else if !srcdoc}<p class="msg faint">Loading…</p>
  {:else}<iframe title="HTML attachment" sandbox={SANDBOX} {srcdoc} referrerpolicy="no-referrer"></iframe>{/if}
</div>

<style>
  .html { height: 100%; display: flex; flex-direction: column; background: #fff; }
  .bar {
    display: flex; align-items: center; gap: 8px; padding: 7px 12px; font-size: 12.5px;
    background: var(--bg-sunken); color: var(--text-2); border-bottom: 1px solid var(--line);
  }
  .bar span { flex: 1; }
  iframe { flex: 1; width: 100%; border: 0; background: #fff; }
  .msg { text-align: center; margin-top: 40px; color: var(--text-2); }
</style>
