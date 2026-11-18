<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { navigate, route } from '../router.svelte.js';
  import { ui } from '../state.svelte.js';
  import Icon from './Icon.svelte';

  let { wide } = $props();
  let q = $state(route.q || '');
  let input;
  let showHelp = $state(false);

  $effect(() => {
    if (ui.searchFocusTick) input?.focus();
  });
  $effect(() => {
    if (route.view === 'search') q = route.q;
  });

  const RECENT_KEY = 'kern:mail.recentSearches';
  function loadRecent() {
    try {
      return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]').slice(0, 8);
    } catch {
      return [];
    }
  }
  let recent = $state(loadRecent());
  function remember(v) {
    recent = [v, ...recent.filter((x) => x !== v)].slice(0, 8);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* ignore */
    }
  }
  function forget(v) {
    recent = recent.filter((x) => x !== v);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* ignore */
    }
  }
  function runRecent(v) {
    q = v;
    navigate({ page: 'mail', view: 'search', q: v, threadId: null });
    input.blur();
  }

  function submit(e) {
    e.preventDefault();
    const v = q.trim();
    if (!v) return;
    remember(v);
    navigate({ page: 'mail', view: 'search', q: v, threadId: null });
    input.blur();
  }
  function clear() {
    q = '';
    if (route.view === 'search') navigate({ page: 'mail', view: 'inbox', threadId: null });
  }
  function onKey(e) {
    if (e.key === 'Escape') {
      input.blur();
      e.stopPropagation();
    }
  }
  const OPS = [
    ['from:alice', 'Sender'], ['to:bob', 'Recipient'], ['subject:invoice', 'Subject'], ['has:attachment', 'With files'],
    ['is:unread', 'Unread'], ['is:starred', 'Starred'], ['in:sent', 'Folder (or in:anywhere)'], ['label:work', 'Label'],
    ['after:2026-01-31', 'Date'], ['risk:high', 'Phishing risk'], ['"exact words"', 'Phrase'], ['-word', 'Exclude'],
  ];
</script>

<header class="topbar">
  {#if !wide}
    <button class="icon-btn" aria-label="Open menu" onclick={() => (ui.sidebarOpen = true)}><Icon name="menu" /></button>
  {/if}
  <form class="search" role="search" onsubmit={submit}>
    <Icon name="search" size={17} />
    <input bind:this={input} bind:value={q} onkeydown={onKey} onfocus={() => (showHelp = true)}
           onblur={() => setTimeout(() => (showHelp = false), 150)}
           placeholder="Search mail" aria-label="Search mail" autocomplete="off" spellcheck="false" />
    {#if q}
      <button type="button" class="icon-btn small" aria-label="Clear search" onclick={clear}><Icon name="close" size={15} /></button>
    {:else if wide}
      <span class="kbd">/</span>
    {/if}
    {#if showHelp && !q}
      <div class="help" role="note">
        {#if recent.length}
          <div class="recent">
            <span class="ledger">Recent</span>
            {#each recent as r (r)}
              <div class="rec">
                <button type="button" class="rq" onmousedown={(e) => { e.preventDefault(); runRecent(r); }}><Icon name="clock" size={13} /> {r}</button>
                <button type="button" class="rx" aria-label={`Forget ${r}`} onmousedown={(e) => { e.preventDefault(); forget(r); }}>×</button>
              </div>
            {/each}
          </div>
          <span class="ledger ops-title">Search operators</span>
        {/if}
        {#each OPS as [op, label]}
          <button type="button" class="op" onmousedown={(e) => { e.preventDefault(); q = (q ? q + ' ' : '') + op.replace(/(alice|bob|invoice|work|2026-01-31|exact words|word)/, ''); input.focus(); }}>
            <code>{op}</code><span>{label}</span>
          </button>
        {/each}
      </div>
    {/if}
  </form>
</header>

<style>
  .topbar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 48px;
    padding: 0 12px;
    flex: none;
  }
  .cmd {
    display: inline-flex; align-items: center; gap: 4px; height: 40px; padding: 0 12px; flex: none;
    border: 1px solid var(--line-strong); border-radius: var(--radius); background: var(--bg-elev); color: var(--text-2); cursor: pointer;
    font-size: 12px;
  }
  .cmd:hover { color: var(--text); border-color: var(--text-3); }
  .search {
    position: relative;
    flex: 1;
    max-width: 720px;
    display: flex;
    align-items: center;
    gap: 10px;
    height: 40px;
    padding: 0 8px 0 14px;
    border-radius: var(--radius);
    background: var(--bg-sunken);
    border: 1px solid transparent;
    color: var(--text-3);
    transition: background .15s, border-color .15s, box-shadow .15s;
  }
  .search:focus-within {
    background: var(--bg-elev);
    border-color: var(--line-strong);
    box-shadow: var(--shadow);
    color: var(--text-2);
  }
  input {
    flex: 1;
    min-width: 0;
    border: 0;
    background: transparent;
    outline: none;
    font-size: 14px;
    color: var(--text);
  }
  input::placeholder { color: var(--text-3); }
  .help {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    background: var(--bg-elev);
    border: var(--card-border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-lg);
    padding: 8px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 2px;
    z-index: 30;
    animation: rise .15s var(--ease);
  }
  .recent { grid-column: 1 / -1; display: grid; gap: 1px; padding-bottom: 6px; margin-bottom: 4px; border-bottom: 1px solid var(--line); }
  .recent .ledger, .ops-title { padding: 4px 8px; grid-column: 1 / -1; }
  .rec { display: flex; align-items: center; border-radius: var(--radius-sm); }
  .rec:hover { background: var(--bg-hover); }
  .rq { flex: 1; display: flex; align-items: center; gap: 8px; border: 0; background: none; padding: 6px 8px; cursor: pointer; text-align: left; color: var(--text); font-size: 13px; }
  .rq :global(svg) { color: var(--text-3); }
  .rx { border: 0; background: none; color: var(--text-3); cursor: pointer; padding: 0 10px; font-size: 16px; }
  .rx:hover { color: var(--text); }
  .op {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    border: 0; background: none; padding: 6px 8px; border-radius: 6px; cursor: pointer; text-align: left; color: var(--text-2);
    font-size: 12.5px;
  }
  .op:hover { background: var(--bg-hover); }
  .op code { font-family: var(--mono); font-size: 12px; color: var(--accent-ink); }
</style>
