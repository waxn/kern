<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { untrack } from 'svelte';
  import { resolvedTheme } from '#lib/state/prefs.svelte.ts';
  import { api } from '../api.svelte.js';
  import { prefs } from '../state.svelte.js';
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

  // How the email is drawn: fitted to Kern's theme by the server (no white sheet, no inversion;
  // mail that's dark already keeps its colors), or "original" as sent, on white.
  let original = $state(false);
  const look = $derived(original ? 'original' : resolvedTheme() === 'dark' ? (prefs.darkEmails !== false ? 'dark' : 'original') : 'light');
  let images = false;

  async function load(withImages = images) {
    error = '';
    images = withImages;
    const want = look;
    const params = { colors: want === 'original' ? undefined : want, images: withImages ? 1 : undefined };
    try {
      const b = await api.get(`/messages/${m.id}/body`, params);
      if (want === look) body = { ...b, look: want };
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    const key = m.id + '|' + look;
    if (loadedFor === key) return;
    const sameMessage = loadedFor?.startsWith(m.id + '|');
    loadedFor = key;
    if (!sameMessage) {
      body = null; // a different message; switching looks keeps the old one until the new arrives
      images = false;
    }
    untrack(() => load());
  });

  const adjustable = $derived(!!body?.html && (original || ['adapted', 'dark', 'light'].includes(body.colors)));
  const srcdoc = $derived(body && body.html != null ? buildSrcdoc(body.html, location.origin, { look: body.look }) : null);
  // An HTML part with nothing to see (the server usually catches these).
  let blank = $state(false);
  const hasFiles = $derived((m.attachments || []).some((a) => !a.inline));

  // Size the iframe to its content. The frame is same-origin (no scripts), so
  // the parent can observe its document.
  // Measure the body, not the root: documentElement.scrollHeight is never smaller than the frame
  // itself, so each +2 would grow the frame and re-trigger the observer forever. Emails that size
  // things in vh/100% grow with the frame too, so growth that keeps chasing is cut off.
  let growStreak = 0;
  function measure() {
    const doc = frame?.contentDocument;
    if (!doc || !doc.body) return;
    const b = doc.body;
    const h = Math.ceil(Math.max(b.getBoundingClientRect().height, b.scrollHeight));
    const next = Math.min(Math.max(h + 2, 40), 40000);
    if (next === height) return;
    if (next > height) {
      if (++growStreak > 4) return; // content tracks the frame height: stop chasing it
    } else {
      growStreak = 0;
    }
    height = next;
  }
  let frameQuote = $state(false);
  let quoteOpen = $state(false);
  function toggleQuote() {
    quoteOpen = !quoteOpen;
    frame?.contentDocument?.body?.classList.toggle('mf-collapsed', !quoteOpen);
    growStreak = 0;
    requestAnimationFrame(measure);
  }

  function onLoad() {
    const doc = frame?.contentDocument;
    if (doc) {
      blank = !(doc.body?.innerText || '').replace(/[\s\u200b\u200c\u00a0]/g, '')
        && !doc.querySelector('img, video, svg, picture, hr, [background], [style*="background"]');
      try {
        frameQuote = collapseQuotes(doc);
        quoteOpen = false;
      } catch {
        frameQuote = false;
      }
    }
    growStreak = 0;
    height = 120;
    measure();
    if (!doc) return;
    try {
      const ro = new ResizeObserver(measure);
      ro.observe(doc.body);
      for (const img of doc.images) img.addEventListener('load', () => { growStreak = 0; measure(); }, { once: true });
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
    <div class="paper" class:original={body.look === 'original'} class:blank>
      {#if adjustable}
        <button class="colors" title={original ? 'Fit to theme' : 'Show original colors'} aria-pressed={original}
                aria-label={original ? 'Fit colors to the theme' : 'Show original colors'} onclick={() => (original = !original)}>
          <Icon name={original ? 'moon' : 'sun'} size={14} />
        </button>
      {/if}
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
  {:else if body.text.trim() || !hasFiles}
    <div class="text">
      {#each blocks as b, i}
        {#if !b.quoted || showQuoted}
          <div class:quote={b.quoted}>{#each linkTokens(b.text) as tok}{#if tok.type === 'link'}<a href={tok.value} target="_blank" rel="noopener noreferrer nofollow">{tok.value}</a>{:else}{tok.value}{/if}{/each}</div>
        {:else if i === blocks.findIndex((x) => x.quoted)}
          <button class="dots" title="Show quoted text" aria-label="Show quoted text" onclick={() => (showQuoted = true)}>•••</button>
        {/if}
      {/each}
      {#if !body.text.trim() && !hasFiles}<p class="faint none">No message text.</p>{/if}
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
  /* No sheet of its own: the email sits on the card like the rest of the conversation. */
  .paper {
    position: relative;
    margin: 0 var(--mail-pad, 16px) 12px 62px;
    padding: 0;
    background: transparent;
  }
  iframe { width: 100%; border: 0; display: block; background: transparent; }
  .paper.original { background: #fff; border-radius: 8px; padding: 8px 12px; border: 1px solid var(--line); }
  .paper.original iframe { color-scheme: light; }
  /* Nothing to see: no white box. */
  .paper.blank { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; margin: 0; padding: 0; border: 0; }
  .colors {
    position: absolute; top: 6px; right: 6px; z-index: 2; width: 26px; height: 26px; display: grid; place-items: center;
    border-radius: 7px; border: 1px solid #0000; background: color-mix(in srgb, var(--bg-elev) 85%, transparent);
    color: var(--text-3); cursor: pointer; opacity: 0; transition: opacity .15s, color .15s;
  }
  .paper:hover .colors, .colors:focus-visible, .colors[aria-pressed='true'] { opacity: 1; }
  .colors:hover { color: var(--text); border-color: var(--line); }
  @media (hover: none) { .colors { opacity: .8; } }
  .paper.original .colors { background: #f4f4f2; color: #555; }
  .none { margin: 0; font-size: 13px; }

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
  .frame-dots { margin: 2px 0 6px; }
  .paper.original .frame-dots { background: #f1f1ef; border-color: #d6d6d0; color: #555; }
  @media (max-width: 640px) {
    .paper, .images-bar, .err { margin-left: 8px; margin-right: 8px; padding-left: 6px; padding-right: 6px; }
    .text { margin-left: 14px; margin-right: 14px; }
  }
</style>
