<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Every attachment in your mail, newest first. Downloads go through the
  // same endpoint as in a message: only plain raster images are ever shown
  // inline; everything else (PDF, HTML, SVG, Office) is a download.
  import { onMount } from 'svelte';
  import { api } from '../api.svelte.js';
  import { errorToast, ui } from '../state.svelte.js';
  import { navigate } from '../router.svelte.js';
  import { bytes, shortDate } from '../format.js';
  import Icon from '../components/Icon.svelte';

  const KINDS = [['', 'All'], ['image', 'Images'], ['pdf', 'PDFs'], ['doc', 'Documents'], ['archive', 'Archives'], ['other', 'Other']];
  let kind = $state('');
  let q = $state('');
  let files = $state([]);
  let next = $state(null);
  let loading = $state(true);
  let seq = 0;
  let timer;

  const url = (f, inline = false) => `/api/messages/${f.messageId}/attachments/${f.id}${inline ? '?inline=1' : ''}`;

  async function load(more = false) {
    const mine = ++seq;
    loading = true;
    try {
      const r = await api.get('/attachments', { kind, q, ...(more && next ? { before: next } : {}) });
      if (mine !== seq) return;
      files = more ? [...files, ...r.files] : r.files;
      next = r.next;
    } catch (e) {
      errorToast(e);
    } finally {
      if (mine === seq) loading = false;
    }
  }
  onMount(() => load());

  function setKind(k) {
    kind = k;
    load();
  }
  function onSearch() {
    clearTimeout(timer);
    timer = setTimeout(() => load(), 250);
  }
  function view(f) {
    const imgs = files.filter((x) => x.previewable);
    ui.viewer = {
      items: imgs.map((x) => ({ name: x.filename, src: url(x, true), href: url(x) })),
      index: Math.max(0, imgs.indexOf(f)),
    };
  }
  const ICON = { image: 'image', pdf: 'file', doc: 'file', archive: 'archive', other: 'clip' };
</script>

<div class="page scroll">
  <div class="inner">
    <h1 class="display">Files</h1>
    <p class="ledger sub">Every attachment in your mail, newest first · Trash and Junk left out</p>

    <div class="bar">
      <div class="kinds" role="radiogroup" aria-label="File type">
        {#each KINDS as [k, label]}
          <button role="radio" aria-checked={kind === k} class:on={kind === k} onclick={() => setKind(k)}>{label}</button>
        {/each}
      </div>
      <label class="search">
        <Icon name="search" size={15} />
        <input class="input" bind:value={q} oninput={onSearch} placeholder="File name, sender or subject" aria-label="Search files" />
      </label>
    </div>

    {#if !loading && !files.length}
      <div class="empty faint">{q || kind ? 'No files match.' : 'No attachments yet.'}</div>
    {:else}
      <ul>
        {#each files as f (f.id)}
          <li>
            {#if f.previewable}
              <button class="thumb" onclick={() => view(f)} aria-label={`View ${f.filename}`}>
                <img src={url(f, true)} alt="" loading="lazy" />
              </button>
            {:else}
              <span class="thumb kind-{f.kind}"><Icon name={ICON[f.kind]} size={20} /></span>
            {/if}
            <div class="meta">
              <div class="name" title={f.filename}>{f.filename}</div>
              <div class="sub2 faint">
                <span class="num">{bytes(f.size)}</span> · {f.from.name || f.from.addr} · <span class="num">{shortDate(f.date)}</span>
              </div>
              <div class="subj faint">{f.subject || '(no subject)'}</div>
            </div>
            {#if f.risk === 'high' || f.risk === 'medium'}
              <span class="risk" title="This file came in a message flagged as a possible phishing attempt. Open the email first.">
                <Icon name="shieldAlert" size={15} />
              </span>
            {/if}
            <div class="acts">
              <a class="icon-btn small" href={url(f)} download={f.filename} title="Download" aria-label={`Download ${f.filename}`}><Icon name="download" size={15} /></a>
              {#if f.threadId}
                <button class="btn small ghost" onclick={() => navigate({ page: 'mail', view: 'all', threadId: f.threadId })}>Open email</button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
      {#if next}
        <div class="more"><button class="btn" disabled={loading} onclick={() => load(true)}>{loading ? 'Loading…' : 'Show older files'}</button></div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .page { flex: 1; }
  .inner { max-width: 860px; margin: 0 auto; padding: 18px 20px 80px; }
  h1 { font-size: 36px; margin: 6px 0 4px; }
  .sub { color: var(--text-3); margin: 0 0 18px; }
  .bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
  .kinds { display: flex; flex-wrap: wrap; gap: 4px; }
  .kinds button {
    border: 1px solid var(--line); background: transparent; color: var(--text-2); border-radius: 999px;
    padding: 4px 11px; font-size: 12.5px; cursor: pointer;
  }
  .kinds button:hover { background: var(--bg-hover); }
  .kinds button.on { background: var(--text); color: var(--bg); border-color: var(--text); }
  .search { flex: 1; min-width: 200px; display: flex; align-items: center; gap: 6px; color: var(--text-3); }
  .search input { flex: 1; }
  ul { list-style: none; margin: 0; padding: 0; background: var(--bg-elev); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  li { display: flex; align-items: center; gap: 12px; padding: 9px 12px; border-bottom: 1px solid var(--line); }
  li:last-child { border-bottom: 0; }
  .thumb {
    flex: none; width: 44px; height: 44px; border-radius: 8px; overflow: hidden; display: grid; place-items: center;
    background: var(--bg-sunken); color: var(--text-3); border: 0; padding: 0;
  }
  button.thumb { cursor: zoom-in; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; }
  .kind-pdf { color: var(--danger); }
  .kind-doc { color: var(--accent-ink); }
  .meta { flex: 1; min-width: 0; }
  .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sub2, .subj { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .risk { color: var(--danger); flex: none; display: grid; }
  .acts { display: flex; align-items: center; gap: 4px; flex: none; }
  .more { text-align: center; margin-top: 14px; }
  .empty { padding: 40px 0; text-align: center; }
  @media (max-width: 560px) { .acts .btn { display: none; } }
</style>
