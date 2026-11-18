<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { api } from '../api.svelte.js';
  import { buildSrcdoc, collapseQuotes, SANDBOX } from '../emailFrame.js';
  import { linkTokens, quoteBlocks } from '../format.js';
  import Icon from './Icon.svelte';

  let { m } = $props();
  let body = $state(null);
  let error = $state('');
  let frame = $state();
  let height = $state(120);
  let showQuoted = $state(false);
  let loadedFor = null;

  async function load(images = false) {
    error = '';
    try {
      body = await api.get(`/messages/${m.id}/body`, images ? { images: 1 } : {});
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    if (loadedFor === m.id) return;
    loadedFor = m.id;
    body = null;
    load();
  });

  const srcdoc = $derived(body && body.html != null ? buildSrcdoc(body.html, location.origin) : null);

  // Size the iframe to its content. The frame is same-origin (no scripts), so
  // the parent can observe its document.
  function measure() {
    const doc = frame?.contentDocument;
    if (!doc || !doc.documentElement) return;
    const h = Math.max(doc.documentElement.scrollHeight, doc.body ? doc.body.scrollHeight : 0);
    height = Math.min(Math.max(h + 2, 40), 40000);
  }
  let frameQuote = $state(false);
  let quoteOpen = $state(false);
  function toggleQuote() {
    quoteOpen = !quoteOpen;
    frame?.contentDocument?.body?.classList.toggle('mf-collapsed', !quoteOpen);
    requestAnimationFrame(measure);
  }

  function onLoad() {
    const doc = frame?.contentDocument;
    if (doc) {
      try {
        frameQuote = collapseQuotes(doc);
        quoteOpen = false;
      } catch {
        frameQuote = false;
      }
    }
    measure();
    if (!doc) return;
    try {
      const ro = new ResizeObserver(measure);
      ro.observe(doc.documentElement);
      for (const img of doc.images) img.addEventListener('load', measure, { once: true });
      frame._ro?.disconnect();
      frame._ro = ro;
    } catch {
      /* ResizeObserver unavailable */
    }
  }
  $effect(() => () => frame?._ro?.disconnect());

  const blocks = $derived(body && body.text != null ? quoteBlocks(body.text) : []);
  const hasQuote = $derived(blocks.some((b) => b.quoted));
</script>

{#if error}
  <div class="err">Couldn't load this message: {error} <button class="btn small" onclick={() => load()}>Retry</button></div>
{:else if !body}
  <div class="loading" aria-busy="true">
    <span class="skel" style="width:88%;height:10px"></span>
    <span class="skel" style="width:75%;height:10px"></span>
    <span class="skel" style="width:52%;height:10px"></span>
  </div>
{:else}
  {#if body.remoteImages > 0 && !body.imagesLoaded}
    <div class="images-bar">
      <Icon name="image" size={15} />
      <span>{body.remoteImages} remote image{body.remoteImages === 1 ? '' : 's'} blocked to protect your privacy.</span>
      <button class="btn small" onclick={() => load(true)}>Load images</button>
    </div>
  {/if}
  {#if srcdoc != null}
    <div class="paper">
      <iframe
        bind:this={frame}
        title="Message content"
        sandbox={SANDBOX}
        referrerpolicy="no-referrer"
        {srcdoc}
        style:height={height + 'px'}
        onload={onLoad}
      ></iframe>
      {#if frameQuote}
        <button class="dots frame-dots" title={quoteOpen ? 'Hide quoted text' : 'Show quoted text'}
                aria-label={quoteOpen ? 'Hide quoted text' : 'Show quoted text'} aria-expanded={quoteOpen} onclick={toggleQuote}>•••</button>
      {/if}
    </div>
  {:else}
    <div class="text">
      {#each blocks as b, i}
        {#if !b.quoted || showQuoted}
          <div class:quote={b.quoted}>{#each linkTokens(b.text) as tok}{#if tok.type === 'link'}<a href={tok.value} target="_blank" rel="noopener noreferrer nofollow">{tok.value}</a>{:else}{tok.value}{/if}{/each}</div>
        {:else if i === blocks.findIndex((x) => x.quoted)}
          <button class="dots" title="Show quoted text" aria-label="Show quoted text" onclick={() => (showQuoted = true)}>•••</button>
        {/if}
      {/each}
      {#if !body.text.trim()}<p class="faint">(This message has no text.)</p>{/if}
      {#if hasQuote && showQuoted}
        <button class="dots" aria-label="Hide quoted text" onclick={() => (showQuoted = false)}>•••</button>
      {/if}
    </div>
  {/if}
{/if}

<style>
  .loading { padding: 4px 18px 18px 62px; display: grid; gap: 9px; }
  .err { margin: 0 14px 12px 62px; color: var(--danger); font-size: 13px; }
  .images-bar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin: 0 14px 10px 62px; padding: 7px 8px 7px 12px; border-radius: 8px;
    background: var(--bg-sunken); color: var(--text-2); font-size: 12.5px;
  }
  .images-bar span { flex: 1; min-width: 180px; }
  .paper {
    margin: 0 14px 12px 62px;
    background: #fff;
    border-radius: 8px;
    padding: 6px 10px;
    border: 1px solid var(--line);
  }
  iframe { width: 100%; border: 0; display: block; background: #fff; color-scheme: light; }
  .text {
    margin: 0 18px 14px 62px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font-size: 14.5px;
    line-height: 1.6;
  }
  .quote { color: var(--text-3); border-left: 2px solid var(--line-strong); padding-left: 10px; margin: 4px 0; }
  .dots {
    border: 1px solid var(--line-strong); background: var(--bg-sunken); color: var(--text-2);
    border-radius: 6px; padding: 0 8px; height: 18px; line-height: 14px; font-size: 11px; cursor: pointer; letter-spacing: .1em;
  }
  .dots:hover { background: var(--bg-hover); }
  .frame-dots { margin: 2px 0 6px; background: #f1f1ef; border-color: #d6d6d0; color: #555; }
  @media (max-width: 640px) {
    .paper, .images-bar, .err { margin-left: 8px; margin-right: 8px; padding-left: 6px; padding-right: 6px; }
    .text { margin-left: 14px; margin-right: 14px; }
  }
</style>
