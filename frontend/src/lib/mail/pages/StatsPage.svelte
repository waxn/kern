<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // Mail stats: how much arrives, from whom, when, and how fast you answer (backend/mail/stats.py).
  import { onMount } from 'svelte';
  import { api } from '../api.svelte.js';
  import { bytes } from '../format.js';
  import { href, navigate } from '../router.svelte.js';

  let days = $state(30);
  let s = $state(null);
  let error = $state('');
  let hover = $state(null); // {chart, i}

  async function load() {
    error = '';
    try {
      s = await api.get('/stats', { days });
    } catch (e) {
      error = e.message;
    }
  }
  onMount(load);

  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const maxDay = $derived(s ? Math.max(1, ...s.series.map((d) => d.received)) : 1);
  const maxHour = $derived(s ? Math.max(1, ...s.hours) : 1);
  const maxWeek = $derived(s ? Math.max(1, ...s.weekdays) : 1);
  const maxSender = $derived(s?.topSenders.length ? s.topSenders[0].count : 1);
  const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)}%`);
  function dayLabel(iso) {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
  }
  function replyTime(min) {
    if (min == null) return '–';
    if (min < 60) return `${min} min`;
    if (min < 48 * 60) return `${Math.round(min / 60)} h`;
    return `${Math.round(min / 1440)} days`;
  }
  function hourLabel(h) {
    return new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: 'numeric' });
  }
  function searchFrom(addr) {
    navigate({ page: 'mail', view: 'search', q: `from:${addr}`, threadId: null });
  }
</script>

<div class="mail-page scroll">
  <div class="inner">
    <div class="titlerow">
      <div>
        <h1>Stats</h1>
        <p class="sub">Computed on your server from the mail stored here.</p>
      </div>
      <div class="seg" role="group" aria-label="Period">
        {#each [[7, '7 days'], [30, '30 days'], [90, '90 days'], [365, 'Year']] as [n, label] (n)}
          <button class:on={days === n} aria-pressed={days === n} onclick={() => { days = n; load(); }}>{label}</button>
        {/each}
      </div>
    </div>

    {#if error}
      <p class="err">{error} <button class="btn small" onclick={load}>Retry</button></p>
    {:else if !s}
      <div class="tiles">{#each Array(4) as _}<div class="tile"><span class="skel" style="width:60%;height:22px"></span><span class="skel" style="width:40%;height:10px"></span></div>{/each}</div>
    {:else}
      <div class="tiles">
        <div class="tile"><b class="num">{s.received.toLocaleString()}</b><span>received · {s.perDay}/day</span></div>
        <div class="tile"><b class="num">{s.sent.toLocaleString()}</b><span>sent</span></div>
        <div class="tile"><b class="num">{pct(s.readRate)}</b><span>read</span></div>
        <div class="tile"><b class="num">{replyTime(s.replyMedianMinutes)}</b><span>typical reply time{s.replies ? ` · ${s.replies} replies` : ''}</span></div>
        <div class="tile"><b class="num">{pct(s.newsletterShare)}</b><span>newsletters and lists</span></div>
        <div class="tile"><b class="num">{s.totals.inboxUnread.toLocaleString()}</b><span>unread in Inbox · {s.totals.inbox.toLocaleString()} in all</span></div>
      </div>

      <section>
        <h2>Received per day</h2>
        <div class="readout" aria-live="polite">
          {#if hover?.chart === 'day'}{@const d = s.series[hover.i]}<b>{dayLabel(d.day)}</b> · {d.received} received · {d.sent} sent{:else}&nbsp;{/if}
        </div>
        <div class="bars" class:dense={s.series.length > 60} role="img" aria-label="Emails received per day">
          {#each s.series as d, i (d.day)}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="col" onmouseenter={() => (hover = { chart: 'day', i })} onmouseleave={() => (hover = null)}>
              <span class="bar" class:hl={hover?.chart === 'day' && hover.i === i} style:height="{(d.received / maxDay) * 100}%"></span>
            </div>
          {/each}
        </div>
        <div class="axis"><span>{dayLabel(s.series[0].day)}</span><span>Today</span></div>
      </section>

      <div class="two">
        <section>
          <h2>Time of day</h2>
          <div class="readout">{#if hover?.chart === 'hour'}<b>{hourLabel(hover.i)}</b> · {s.hours[hover.i]} received{:else if s.peakHour != null}Busiest around {hourLabel(s.peakHour)}{:else}&nbsp;{/if}</div>
          <div class="bars short" role="img" aria-label="Emails received by hour of day">
            {#each s.hours as n, h (h)}
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="col" onmouseenter={() => (hover = { chart: 'hour', i: h })} onmouseleave={() => (hover = null)}>
                <span class="bar" class:hl={hover?.chart === 'hour' && hover.i === h} style:height="{(n / maxHour) * 100}%"></span>
              </div>
            {/each}
          </div>
          <div class="axis"><span>{hourLabel(0)}</span><span>{hourLabel(12)}</span><span>{hourLabel(23)}</span></div>
        </section>
        <section>
          <h2>Day of week</h2>
          <div class="readout">{#if hover?.chart === 'week'}<b>{WEEKDAYS[hover.i]}</b> · {s.weekdays[hover.i]} received{:else if s.busiestDay != null}Busiest on {WEEKDAYS[s.busiestDay]}{:else}&nbsp;{/if}</div>
          <div class="bars short" role="img" aria-label="Emails received by day of week">
            {#each s.weekdays as n, i (i)}
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="col" onmouseenter={() => (hover = { chart: 'week', i })} onmouseleave={() => (hover = null)}>
                <span class="bar" class:hl={hover?.chart === 'week' && hover.i === i} style:height="{(n / maxWeek) * 100}%"></span>
              </div>
            {/each}
          </div>
          <div class="axis week">{#each WEEKDAYS as w}<span>{w}</span>{/each}</div>
        </section>
      </div>

      <div class="two">
        <section>
          <h2>Who writes most</h2>
          {#if s.topSenders.length}
            <ol class="rank">
              {#each s.topSenders as p (p.addr)}
                <li>
                  <a href={href({ page: 'mail', view: 'search', q: `from:${p.addr}` })} onclick={(e) => { e.preventDefault(); searchFrom(p.addr); }} title={p.addr}>
                    <span class="nm truncate">{p.label}</span>
                    <span class="meter"><span style:width="{(p.count / maxSender) * 100}%"></span></span>
                    <span class="n num">{p.count}</span>
                  </a>
                </li>
              {/each}
            </ol>
          {:else}<p class="faint">Nothing received in this period.</p>{/if}
        </section>
        <section>
          <h2>Top domains</h2>
          <ol class="rank">
            {#each s.topDomains as d (d.domain)}
              <li><a href={href({ page: 'mail', view: 'search', q: `domain:${d.domain}` })} onclick={(e) => { e.preventDefault(); navigate({ page: 'mail', view: 'search', q: `domain:${d.domain}`, threadId: null }); }}>
                <span class="nm truncate">{d.domain}</span>
                <span class="meter"><span style:width="{(d.count / (s.topDomains[0]?.count || 1)) * 100}%"></span></span>
                <span class="n num">{d.count}</span>
              </a></li>
            {/each}
          </ol>
          <h2 class="gap">Mailbox</h2>
          <dl class="facts">
            <dt>Messages</dt><dd class="num">{s.totals.messages.toLocaleString()} · {bytes(s.totals.bytes)}</dd>
            <dt>Conversations</dt><dd class="num">{s.totals.threads.toLocaleString()}</dd>
            <dt>Attachments</dt><dd class="num">{s.totals.attachments.toLocaleString()} · {bytes(s.totals.attachmentBytes)}</dd>
            <dt>With files ({days} days)</dt><dd class="num">{s.withFiles.toLocaleString()}</dd>
          </dl>
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  .mail-page { flex: 1; min-height: 0; width: 100%; }
  .inner { max-width: 860px; margin: 0 auto; padding: 36px 40px 80px; }
  @media (max-width: 760px) { .inner { padding: 48px 16px 80px; } }
  .titlerow { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  h1 { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; margin: 0 0 4px; }
  .sub { color: var(--text-2); margin: 0 0 18px; }
  .seg { display: inline-flex; background: var(--bg-sunken); border-radius: var(--radius-sm); padding: 2px; }
  .seg button { padding: 3px 10px; border-radius: calc(var(--radius-sm) - 1px); font-size: 12px; color: var(--text-2); }
  .seg button.on { background: var(--bg-elev); color: var(--text); font-weight: 600; }
  .err { color: var(--danger); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; margin-bottom: 8px; }
  .tile { display: grid; gap: 4px; padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--radius); }
  .tile b { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; color: var(--text); }
  .tile span { font-size: 12px; color: var(--text-3); }
  section { margin-top: 22px; min-width: 0; }
  h2 { font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-3); margin: 0 0 6px; }
  h2.gap { margin-top: 20px; }
  .readout { font-size: 12.5px; color: var(--text-2); height: 18px; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .readout b { color: var(--text); font-weight: 600; }
  .bars { height: 140px; display: flex; align-items: flex-end; gap: 2px; border-bottom: 1px solid var(--line); }
  .bars.short { height: 90px; }
  .col { flex: 1; height: 100%; display: flex; align-items: flex-end; min-width: 0; cursor: default; }
  .bar { display: block; width: 100%; min-height: 1px; border-radius: 4px 4px 0 0; background: color-mix(in srgb, var(--accent) 78%, transparent); transition: background .1s; }
  .bars.dense .bar { border-radius: 2px 2px 0 0; }
  .bar.hl { background: var(--accent); }
  .axis { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); margin-top: 4px; }
  .axis.week span { flex: 1; text-align: center; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 28px; }
  @media (max-width: 760px) { .two { grid-template-columns: 1fr; } }
  .rank { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  .rank a { display: grid; grid-template-columns: minmax(0, 1fr) 90px 36px; align-items: center; gap: 10px; padding: 4px 6px; border-radius: var(--radius-sm); color: var(--text) !important; text-decoration: none; font-size: 13px; }
  .rank a:hover { background: var(--bg-hover); }
  .meter { height: 6px; border-radius: 3px; background: var(--bg-sunken); overflow: hidden; }
  .meter span { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
  .n { text-align: right; color: var(--text-2); font-size: 12px; }
  .facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0; font-size: 13px; }
  .facts dt { color: var(--text-3); }
  .facts dd { margin: 0; }
</style>
