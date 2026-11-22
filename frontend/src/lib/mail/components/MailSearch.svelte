<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // Mail search, opened from the sidebar's Search row (same place as Notes' search), Ctrl+K or /.
  // Results arrive as you type: people, labels, folders and the best conversations with the
  // words that matched; Enter shows every result. Operators complete with Tab.
  import { untrack } from 'svelte';
  import { goto } from '$app/navigation';
  import { CornerDownLeft, Clock, Folder, Mail, Search, Tag, User, X } from '@lucide/svelte';
  import { api } from '../api.svelte.js';
  import { ui } from '../state.svelte.js';
  import { shortDate } from '../format.js';
  import { href } from '../router.svelte.js';
  import { modKey } from '#lib/util.ts';
  import { addToken, hasToken, hitParts, lastToken, OPERATORS, operatorCompletions, removeToken, replaceLastToken } from '../searchQuery.js';

  const RECENT_KEY = 'kern:mail.recentSearches';
  let q = $state('');
  let rows = $state([]);
  let total = $state(null);
  let sel = $state(0);
  let busy = $state(false);
  let help = $state(false);
  let input = $state();
  let list = $state();
  let seq = 0;
  let timer;

  function recent() {
    try {
      return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]').slice(0, 6);
    } catch {
      return [];
    }
  }
  function remember(v) {
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify([v, ...recent().filter((x) => x !== v)].slice(0, 8)));
    } catch {
      /* storage unavailable */
    }
  }

  $effect(() => {
    if (ui.search.open) {
      q = ui.search.q || '';
      help = false;
      queueMicrotask(() => input?.select());
    }
  });

  $effect(() => {
    if (!ui.search.open) return;
    const query = q;
    clearTimeout(timer);
    if (!query.trim()) {
      rows = idle();
      total = null;
      sel = 0;
      return;
    }
    // Keep the last answer on screen while the next one loads, so the list doesn't flicker.
    const prev = untrack(() => rows.filter((r) => r.type === 'thread' || r.type === 'person'));
    rows = [submitRow(query, untrack(() => total)), ...opRows(query), ...prev];
    timer = setTimeout(() => run(query), 120);
  });

  const FILTERS = [
    ['is:unread', 'Unread'], ['is:starred', 'Starred'], ['has:attachment', 'Attachments'],
    ['newer_than:7d', 'Last 7 days'], ['newer_than:30d', 'Last 30 days'], ['in:anywhere', 'Include Trash & Junk'],
  ];
  function toggle(tok) {
    q = hasToken(q, tok) ? removeToken(q, tok) : addToken(q, tok);
    input?.focus();
  }

  function idle() {
    const out = recent().map((r) => ({ key: 'h' + r, type: 'history', group: 'Recent searches', title: r, query: r }));
    for (const [op, label] of [['from:', 'From someone'], ['has:pdf', 'With a PDF'], ['older_than:1y', 'Older than a year'], ['larger:5M', 'Bigger than 5 MB']])
      out.push({ key: 'o' + op, type: 'op', group: 'Try', title: op, sub: label, insert: op });
    return out;
  }
  function submitRow(query, n) {
    return { key: 'go', type: 'submit', group: '', title: query.trim(), sub: n == null ? 'All results' : `${n.toLocaleString()} conversation${n === 1 ? '' : 's'}` };
  }
  function opRows(query) {
    return operatorCompletions(query).map((c) => ({ key: 'c' + c.text, type: 'op', group: 'Operators', title: c.text, sub: c.label, insert: c.text }));
  }

  async function run(query) {
    const mine = ++seq;
    busy = true;
    try {
      const r = await api.get('/search/suggest', { q: query });
      if (mine !== seq) return;
      total = r.total;
      const out = [submitRow(query, r.total), ...opRows(query)];
      for (const p of r.people) out.push({ key: 'p' + p.addr, type: 'person', group: 'People', title: p.name || p.addr, sub: p.name ? p.addr : '', addr: p.addr });
      for (const l of r.labels) out.push({ key: 'l' + l.id, type: 'label', group: 'Labels', title: l.name, color: l.color, insert: 'label:' + quote(l.name) });
      for (const f of r.folders) out.push({ key: 'f' + f.id, type: 'folder', group: 'Folders', title: f.displayName, insert: 'in:' + quote(f.name) });
      for (const t of r.threads)
        out.push({ key: 't' + t.id, type: 'thread', group: 'Conversations', title: t.subject || '(no subject)', who: t.who, date: t.lastDate,
          unread: t.unread > 0, hit: t.hit, snippet: t.snippet, id: t.id });
      rows = out;
      if (sel >= rows.length) sel = 0;
    } catch {
      if (mine === seq) rows = [submitRow(query, null)];
    } finally {
      if (mine === seq) busy = false;
    }
  }

  function quote(v) {
    return /\s/.test(v) ? `"${v}"` : v;
  }
  function close() {
    ui.search.open = false;
  }
  function submit(query = q) {
    const v = query.trim();
    if (!v) return;
    remember(v);
    close();
    goto(href({ page: 'mail', view: 'search', q: v }));
  }
  function choose(row, e) {
    if (!row) return;
    if (row.type === 'submit') return submit();
    if (row.type === 'history') {
      q = row.query;
      input?.focus();
      return;
    }
    if (row.type === 'op' || row.type === 'label' || row.type === 'folder') {
      q = replaceLastToken(q, row.insert, { keepOperatorValue: row.type === 'op' && !row.insert.endsWith(':') });
      input?.focus();
      return;
    }
    if (row.type === 'person') {
      const typing = lastToken(q);
      const op = /^-?(to|cc|bcc|from):/i.exec(typing)?.[0] || 'from:';
      q = replaceLastToken(q, op + row.addr);
      input?.focus();
      return;
    }
    if (row.type === 'thread') {
      const v = q.trim();
      remember(v);
      close();
      const url = href({ page: 'mail', view: 'search', q: v, threadId: row.id });
      if (e && (e.metaKey || e.ctrlKey)) window.open(url, '_blank');
      else goto(url);
    }
  }

  function key(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!rows.length) return;
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
      queueMicrotask(() => list?.querySelector('.row.active')?.scrollIntoView({ block: 'nearest' }));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (e.metaKey || e.ctrlKey || !q.trim()) return choose(rows[sel], e);
      choose(rows[sel] && rows[sel].type !== 'submit' ? rows[sel] : rows[0], e);
    } else if (e.key === 'Tab' && !e.shiftKey) {
      const c = rows.find((r) => r.type === 'op' || r.type === 'person');
      if (c && q.trim()) {
        e.preventDefault();
        choose(c);
      }
    }
  }
</script>

{#if ui.search.open}
  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
  <div class="overlay" onmousedown={(e) => e.target === e.currentTarget && close()}>
    <div class="palette popover" role="dialog" aria-label="Search mail">
      <div class="bar">
        <Search size={16} class="faint" />
        <input bind:this={input} bind:value={q} placeholder="Search mail" onkeydown={key} spellcheck="false" autocomplete="off"
               aria-label="Search mail" aria-controls="mail-search-list" />
        {#if busy}<span class="spin" aria-hidden="true"></span>{/if}
        {#if q}<button class="icon-btn" aria-label="Clear" onclick={() => { q = ''; input?.focus(); }}><X size={14} /></button>{/if}
      </div>
      <div class="filters" role="group" aria-label="Filters">
        {#each FILTERS as [tok, label] (tok)}
          <button class:on={hasToken(q, tok)} aria-pressed={hasToken(q, tok)} onclick={() => toggle(tok)}>{label}</button>
        {/each}
      </div>
      <div class="list" id="mail-search-list" bind:this={list} role="listbox">
        {#if help}
          <div class="help">
            {#each OPERATORS as o (o.text)}
              <button class="op" onclick={() => { q = addToken(q, o.text, { raw: true }); help = false; input?.focus(); }}><code>{o.text}</code><span>{o.label}</span></button>
            {/each}
          </div>
        {:else}
          {#each rows as row, i (row.key)}
            {#if row.group && (i === 0 || rows[i - 1].group !== row.group)}<div class="menu-heading">{row.group}</div>{/if}
            <!-- svelte-ignore a11y_mouse_events_have_key_events -->
            <button class="row" class:active={i === sel} class:thread={row.type === 'thread'} role="option" aria-selected={i === sel}
                    onmousemove={() => (sel = i)} onclick={(e) => choose(row, e)}>
              <span class="ico">
                {#if row.type === 'submit'}<Search size={15} strokeWidth={1.75} />
                {:else if row.type === 'history'}<Clock size={15} strokeWidth={1.75} />
                {:else if row.type === 'person'}<User size={15} strokeWidth={1.75} />
                {:else if row.type === 'label'}<Tag size={15} strokeWidth={1.75} style="color:{row.color || 'currentColor'}" />
                {:else if row.type === 'folder'}<Folder size={15} strokeWidth={1.75} />
                {:else if row.type === 'thread'}<Mail size={15} strokeWidth={1.75} />
                {:else}<code class="opico">:</code>{/if}
              </span>
              {#if row.type === 'thread'}
                <span class="body">
                  <span class="tline"><b class="who truncate" class:unread={row.unread}>{row.who}</b><span class="date">{shortDate(row.date)}</span></span>
                  <span class="title truncate" class:unread={row.unread}>{row.title}</span>
                  <span class="sub truncate">{#if row.hit}{#each hitParts(row.hit) as p}{#if p.hit}<mark>{p.text}</mark>{:else}{p.text}{/if}{/each}{:else}{row.snippet}{/if}</span>
                </span>
              {:else}
                <span class="body">
                  <span class="title truncate">{#if row.type === 'op'}<code>{row.title}</code>{:else}{row.title}{/if}</span>
                  {#if row.sub}<span class="sub truncate">{row.sub}</span>{/if}
                </span>
              {/if}
              <span class="enter">{#if i === sel}<CornerDownLeft size={13} />{/if}</span>
            </button>
          {/each}
          {#if !rows.length}<div class="none">Type to search your mail.</div>{/if}
        {/if}
      </div>
      <div class="foot">
        <span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>Tab</kbd> complete</span>
        <span><kbd>{modKey} ↵</kbd> new tab</span>
        <button class="all" onclick={() => (help = !help)}>{help ? 'Back to results' : 'All operators'}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* Same frame as Notes' search (components/SearchModal.svelte). */
  .overlay { position: fixed; inset: 0; z-index: 800; display: flex; justify-content: center; align-items: flex-start; padding-top: 12vh; background: rgba(0, 0, 0, 0.4); animation: fade 0.1s; }
  .palette { width: min(680px, calc(100vw - 24px)); display: flex; flex-direction: column; height: min(560px, 76vh); overflow: hidden; }
  .bar { display: flex; align-items: center; gap: 10px; padding: 0 10px 0 14px; height: 46px; border-bottom: 1px solid var(--border); flex: none; }
  .bar input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; font-size: 15px; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--border-strong); border-top-color: var(--accent); animation: ms-spin .8s linear infinite; }
  @keyframes ms-spin { to { transform: rotate(360deg); } }
  .filters { display: flex; gap: 4px; padding: 7px 10px; flex: none; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid var(--border); }
  .filters button { flex: none; padding: 3px 10px; border-radius: 12px; color: var(--text-2); font-size: 12.5px; border: 1px solid var(--border); white-space: nowrap; }
  .filters button:hover { background: var(--hover); color: var(--text); }
  .filters button.on { background: color-mix(in srgb, var(--accent) 16%, transparent); border-color: color-mix(in srgb, var(--accent) 45%, transparent); color: var(--text); }
  .list { flex: 1; min-height: 0; overflow-y: auto; padding: 4px 6px 6px; }
  .row { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 34px; padding: 5px 8px; border-radius: var(--radius-sm); text-align: left; }
  .row.thread { align-items: flex-start; padding-top: 7px; padding-bottom: 7px; }
  .row.active { background: var(--hover); }
  .ico { flex: none; width: 20px; display: grid; place-items: center; color: var(--text-2); }
  .row.thread .ico { padding-top: 2px; }
  .opico { font-family: var(--font-mono); font-weight: 700; color: var(--accent); }
  .body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .tline { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .who { flex: 1; min-width: 0; font-weight: 500; color: var(--text-2); }
  .who.unread, .title.unread { color: var(--text); font-weight: 650; }
  .date { flex: none; font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
  .title code, .help code { font-family: var(--font-mono); font-size: 12.5px; color: var(--accent); }
  .sub { font-size: 12px; color: var(--text-3); }
  mark { background: color-mix(in srgb, var(--accent) 26%, transparent); color: var(--text); border-radius: 2px; padding: 0 1px; }
  .enter { flex: none; width: 14px; color: var(--text-3); display: grid; place-items: center; align-self: center; }
  .none { padding: 22px; text-align: center; color: var(--text-3); }
  .help { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 2px; padding: 4px 2px; }
  .op { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px; border-radius: var(--radius-sm); text-align: left; color: var(--text-2); font-size: 12.5px; }
  .op:hover { background: var(--hover); }
  .foot { display: flex; align-items: center; gap: 14px; padding: 7px 14px; border-top: 1px solid var(--border); color: var(--text-3); font-size: 12px; flex: none; }
  .all { margin-left: auto; color: var(--accent); font-size: 12px; }
  @media (max-width: 760px) {
    .overlay { padding-top: 8px; }
    .palette { height: calc(100dvh - 16px); }
    .foot span { display: none; }
  }
</style>
