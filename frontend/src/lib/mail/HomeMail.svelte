<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Mail on Kern's Home: what's new, what comes back today, what's arriving.
  import { onMount } from 'svelte';
  import { BellRing, Clock, Mail, Package, Send } from '@lucide/svelte';
  import { open } from '#lib/state/tabs.ts';
  import { mailToday, watchMailToday } from './badge.svelte.js';

  onMount(() => watchMailToday());
  const d = $derived(mailToday.data);

  function go(e, href) {
    e.preventDefault();
    open(href, e);
  }
  function when(iso) {
    const t = new Date(iso);
    const today = new Date().toDateString() === t.toDateString();
    return today ? t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : t.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }
  const pkgLabel = (p) => (p.status === 'ready_for_pickup' ? 'ready to pick up' : p.status === 'out_for_delivery' ? 'out for delivery' : 'arriving today');
</script>

{#if d?.connected}
  <section class="mail">
    <div class="head">
      <div class="section-title">Mail · {d.unread ? `${d.unread} unread` : 'all read'}</div>
      <a class="more" href="/mail/inbox" onclick={(e) => go(e, '/mail/inbox')}>Open inbox →</a>
    </div>
    {#if d.latest.length}
      <div class="list">
        {#each d.latest as m (m.threadId)}
          <a class="row" href="/mail/inbox/t/{m.threadId}" onclick={(e) => go(e, `/mail/inbox/t/${m.threadId}`)}>
            <span class="ico"><Mail size={14} strokeWidth={1.75} /></span>
            <span class="who truncate">{m.from}</span>
            <span class="subj truncate">{m.subject || '(no subject)'}</span>
            <span class="time">{when(m.date)}</span>
          </a>
        {/each}
      </div>
    {/if}
    {#if d.snoozes.length || d.nudged.length || d.packages.length || d.scheduledToday}
      <div class="chips">
        {#each d.nudged as f (f.id)}
          <a class="pill hot" href="/mail/all/t/{f.threadId}" onclick={(e) => go(e, `/mail/all/t/${f.threadId}`)}><BellRing size={13} /> No reply yet: {f.subject}</a>
        {/each}
        {#each d.snoozes as s (s.threadId + s.until)}
          <a class="pill" href="/mail/snoozed" onclick={(e) => go(e, '/mail/snoozed')}><Clock size={13} /> Back at {when(s.until)}: {s.subject}</a>
        {/each}
        {#each d.packages as p (p.id)}
          <a class="pill" href="/mail/packages" onclick={(e) => go(e, '/mail/packages')}><Package size={13} /> {p.merchant || p.carrierName} {pkgLabel(p)}</a>
        {/each}
        {#if d.scheduledToday}
          <a class="pill" href="/mail/scheduled" onclick={(e) => go(e, '/mail/scheduled')}><Send size={13} /> {d.scheduledToday} scheduled to send today</a>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  .mail { margin-top: 22px; }
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  .more { font-size: 12.5px; color: var(--text-3); text-decoration: none; }
  .list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .row { display: grid; grid-template-columns: 22px minmax(0, 0.8fr) minmax(0, 1.6fr) auto; align-items: center; gap: 8px; height: 34px; padding: 0 12px; text-decoration: none; border-top: 1px solid var(--border); color: var(--text); }
  .row:first-child { border-top: 0; }
  .row:hover { background: var(--hover); }
  .ico { display: grid; place-items: center; color: var(--text-2); }
  .who { font-weight: 550; }
  .subj, .time { color: var(--text-2); font-size: 13px; }
  .time { color: var(--text-3); font-size: 12.5px; white-space: nowrap; text-align: right; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .pill { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 4px 10px; border-radius: 14px; font-size: 12.5px; color: var(--text-2); text-decoration: none; background: var(--surface-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill:hover { color: var(--text); background: var(--hover); }
  .pill.hot { color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
  @media (max-width: 760px) { .row { grid-template-columns: 22px 1fr auto; } .who { display: none; } }
</style>
