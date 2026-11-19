<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Viewer for attachments: images full-size; PDFs (pdf.js), HTML (sanitized,
  // script-less frame), text/CSV and Word files on a sheet. ← → or the arrows
  // move between files, Esc closes. Audio and video don't come here: they play
  // in Kern's app-wide player (see ../preview.js).
  import DocxViewer from '#lib/files/DocxViewer.svelte';
  import PdfViewer from '#lib/files/PdfViewer.svelte';
  import { ui } from '../state.svelte.js';
  import { bytes } from '../format.js';
  import { trapFocus } from '../focus.js';
  import HtmlPreview from './HtmlPreview.svelte';
  import TextPreview from './TextPreview.svelte';
  import Icon from './Icon.svelte';

  const v = $derived(ui.viewer);
  const item = $derived(v ? v.items[v.index] : null);
  const sheet = $derived(item && item.preview !== 'image');
  const risky = $derived(item && (item.risk === 'high' || item.risk === 'medium'));
  const file = $derived(item ? { url: item.href, name: item.name, mime: item.mime || '', size: item.size } : null);

  function close() {
    ui.viewer = null;
  }
  function step(d) {
    if (!v || v.items.length < 2) return;
    ui.viewer = { ...v, index: (v.index + d + v.items.length) % v.items.length };
  }
  function onKey(e) {
    if (!v) return;
    if (e.key === 'Escape') {
      // The PDF viewer closes its own popovers and search first; it marks the event.
      setTimeout(() => !e.defaultPrevented && ui.viewer === v && close());
      return;
    }
    // Inside a document (PDF, text, page) the arrows scroll it instead.
    if (e.target.closest?.('.panel') || e.target.matches?.('input, textarea, select')) return;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      step(1);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      step(-1);
    }
  }
</script>

{#if v && item}
  <div class="viewer" class:sheet role="dialog" aria-modal="true" aria-label={item.name} tabindex="-1" onkeydown={onKey} use:trapFocus>
    <button class="scrim" aria-label="Close preview" tabindex="-1" onclick={close}></button>
    <header>
      <span class="name">{item.name}</span>
      <span class="meta num">{bytes(item.size)}{v.items.length > 1 ? ` · ${v.index + 1} / ${v.items.length}` : ''}</span>
      {#if v.items.length > 1}
        <button class="icon-btn" aria-label="Previous file" title="Previous (←)" onclick={() => step(-1)}><Icon name="back" size={16} /></button>
        <button class="icon-btn" aria-label="Next file" title="Next (→)" onclick={() => step(1)}><Icon name="chevronRight" size={16} /></button>
      {/if}
      <a class="btn small" href={item.href} download={item.name} aria-label="Download"><Icon name="download" size={14} /><span class="lbl">Download</span></a>
      <button class="icon-btn" aria-label="Close" title="Close (Esc)" onclick={close}><Icon name="close" /></button>
    </header>
    {#if risky}
      <div class="warn" role="note">
        <Icon name="shieldAlert" size={15} />
        This file came in a message flagged as a possible phishing attempt. The preview can't run code, but don't trust what it says or open links in it.
      </div>
    {/if}
    {#key item.key}
      {#if item.preview === 'image'}
        <img src={item.src} alt={item.name} />
      {:else}
        <div class="panel">
          {#if item.preview === 'pdf'}<PdfViewer {file} />
          {:else if item.preview === 'html'}<HtmlPreview messageId={item.messageId} id={item.id} risky={item.risk === 'high'} />
          {:else if item.preview === 'docx'}<DocxViewer {file} />
          {:else}<TextPreview url={item.href} name={item.name} />{/if}
        </div>
      {/if}
    {/key}
    {#if item.preview === 'image' && v.items.length > 1}
      <button class="nav prev" aria-label="Previous file" tabindex="-1" onclick={() => step(-1)}><Icon name="back" size={22} /></button>
      <button class="nav next" aria-label="Next file" tabindex="-1" onclick={() => step(1)}><Icon name="chevronRight" size={22} /></button>
    {/if}
  </div>
{/if}

<style>
  .viewer {
    position: fixed; inset: 0; z-index: 400; display: grid; grid-template-rows: auto auto 1fr; place-items: center;
    animation: fade-in .15s; outline: none;
  }
  .scrim { position: absolute; inset: 0; border: 0; background: rgb(8 8 8 / .88); cursor: zoom-out; }
  .sheet .scrim { cursor: default; }
  header {
    position: relative; z-index: 1; width: 100%; display: flex; align-items: center; gap: 8px; padding: 10px 14px;
    color: #eee; font-size: 13px;
  }
  header .icon-btn { color: #ccc; }
  header .icon-btn:hover { background: rgb(255 255 255 / .1); color: #fff; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
  .meta { color: #aaa; font-size: 12px; margin-right: 4px; }
  .warn {
    position: relative; z-index: 1; display: flex; align-items: center; gap: 8px; max-width: 900px; margin: 0 14px 8px;
    padding: 7px 12px; border-radius: 8px; font-size: 12.5px; background: var(--danger-soft, #fde8e8); color: var(--danger, #b42318);
  }
  img {
    position: relative; z-index: 1; max-width: calc(100vw - 120px); max-height: calc(100vh - 90px); object-fit: contain;
    background: #fff; box-shadow: 0 20px 60px rgb(0 0 0 / .5); border-radius: 2px;
  }
  .panel {
    position: relative; z-index: 1; align-self: stretch; justify-self: stretch; min-height: 0; overflow: hidden;
    width: min(1200px, calc(100vw - 28px)); margin: 0 auto 14px; border-radius: 10px;
    background: var(--bg-elev); color: var(--text); box-shadow: 0 20px 60px rgb(0 0 0 / .5);
  }
  .nav {
    position: absolute; z-index: 2; top: 50%; transform: translateY(-50%); width: 46px; height: 46px; border-radius: 50%;
    border: 0; background: rgb(255 255 255 / .12); color: #fff; cursor: pointer; display: grid; place-items: center;
  }
  .nav:hover { background: rgb(255 255 255 / .22); }
  .prev { left: 16px; }
  .next { right: 16px; }
  @media (max-width: 640px) {
    img { max-width: 100vw; max-height: calc(100vh - 70px); }
    .nav { top: auto; bottom: 18px; transform: none; }
    .panel { width: 100vw; margin: 0; border-radius: 0; }
    header .lbl { display: none; }
  }
</style>
