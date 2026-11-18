<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Full-size viewer for image attachments: ← → between images, Esc closes.
  import { ui } from '../state.svelte.js';
  import { bytes } from '../format.js';
  import { trapFocus } from '../focus.js';
  import Icon from './Icon.svelte';

  const v = $derived(ui.viewer);
  const item = $derived(v ? v.items[v.index] : null);

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
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      step(1);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      step(-1);
    }
  }
</script>

{#if v && item}
  <div class="viewer" role="dialog" aria-modal="true" aria-label={`Image: ${item.name}`} tabindex="-1" onkeydown={onKey} use:trapFocus>
    <button class="scrim" aria-label="Close image" onclick={close}></button>
    <header>
      <span class="name">{item.name}</span>
      <span class="meta num">{bytes(item.size)}{#if v.items.length > 1} · {v.index + 1} / {v.items.length}{/if}</span>
      <a class="btn small" href={item.href} download={item.name}><Icon name="download" size={14} /> Download</a>
      <button class="icon-btn" aria-label="Close" onclick={close}><Icon name="close" /></button>
    </header>
    <img src={item.src} alt={item.name} />
    {#if v.items.length > 1}
      <button class="nav prev" aria-label="Previous image" onclick={() => step(-1)}><Icon name="back" size={22} /></button>
      <button class="nav next" aria-label="Next image" onclick={() => step(1)}><Icon name="chevronRight" size={22} /></button>
    {/if}
  </div>
{/if}

<style>
  .viewer {
    position: fixed; inset: 0; z-index: 400; display: grid; grid-template-rows: auto 1fr; place-items: center;
    animation: fade-in .15s; outline: none;
  }
  .scrim { position: absolute; inset: 0; border: 0; background: rgb(8 8 8 / .88); cursor: zoom-out; }
  header {
    position: relative; z-index: 1; width: 100%; display: flex; align-items: center; gap: 12px; padding: 10px 14px;
    color: #eee; font-size: 13px;
  }
  header .icon-btn { color: #ccc; }
  header .icon-btn:hover { background: rgb(255 255 255 / .1); color: #fff; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
  .meta { color: #aaa; font-size: 12px; }
  img {
    position: relative; z-index: 1; max-width: calc(100vw - 120px); max-height: calc(100vh - 90px); object-fit: contain;
    background: #fff; box-shadow: 0 20px 60px rgb(0 0 0 / .5); border-radius: 2px;
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
  }
</style>
