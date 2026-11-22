<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onMount } from 'svelte';
  import { errorToast, loadScheduled, scheduled } from '../state.svelte.js';
  import { sendScheduledNow, unscheduleDraft } from '../compose.svelte.js';
  import { navigate } from '../router.svelte.js';
  import { describeWhen } from '../when.js';
  import Icon from '../components/Icon.svelte';

  onMount(loadScheduled);

  function who(d) {
    const all = [...d.to, ...d.cc, ...d.bcc];
    if (!all.length) return 'No recipients';
    const first = all[0].name || all[0].addr;
    return all.length > 1 ? `${first} and ${all.length - 1} more` : first;
  }
  function preview(html) {
    const div = document.createElement('div');
    div.innerHTML = html || ''; // detached element: nothing renders or loads
    div.querySelectorAll('blockquote').forEach((q) => q.remove());
    // Drop the signature ("-- " block) and the "On …, X wrote:" line above a quote.
    div.querySelectorAll('div, p').forEach((el) => {
      const t = (el.textContent || '').trim();
      if (t.startsWith('-- ') || t === '--' || /^On .+ wrote:$/s.test(t)) el.remove();
    });
    div.querySelectorAll('p, div, li, br').forEach((el) => el.after(' '));
    return (div.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160);
  }
</script>

<div class="mail-page scroll">
  <div class="inner">
    <h1>Scheduled</h1>
    <p class="ledger sub">
      {scheduled.items.length ? `${scheduled.items.length} waiting to be sent` : 'nothing waiting'}{#if scheduled.items.length} · next {describeWhen(new Date(scheduled.items[0].sendAt))}{/if}
    </p>

    {#if scheduled.loaded && !scheduled.items.length}
      <div class="empty">
        <span class="big"><Icon name="clock" size={30} stroke={1.4} /></span>
        <p><b>Nothing scheduled.</b></p>
        <p class="faint">Use the clock button next to Send to write now and send later, e.g. Monday at 8.</p>
      </div>
    {:else}
      <ul>
        {#each scheduled.items as d (d.id)}
          <li>
            <div class="when num"><Icon name="clock" size={14} /> {describeWhen(new Date(d.sendAt))}</div>
            <div class="main">
              <div class="to">To {who(d)}</div>
              <div class="subj">{d.subject || '(no subject)'}</div>
              <div class="pre faint">{preview(d.bodyHtml)}</div>
            </div>
            <div class="acts">
              <button class="btn small" onclick={() => unscheduleDraft(d).catch(errorToast)}><Icon name="pencil" size={13} /> Edit</button>
              <button class="btn small" onclick={() => sendScheduledNow(d).catch(errorToast)}><Icon name="send" size={13} /> Send now</button>
              {#if d.threadId}
                <button class="btn small ghost" onclick={() => navigate({ page: 'mail', view: 'all', threadId: d.threadId })}>Conversation</button>
              {/if}
              <button class="btn small ghost" onclick={() => unscheduleDraft(d, { open: false }).catch(errorToast)} title="Cancel the schedule; it stays in Drafts">Cancel</button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

<style>
  .mail-page { flex: 1; min-height: 0; width: 100%; }
  .inner { max-width: 860px; margin: 0 auto; padding: 36px 40px 80px; }
  @media (max-width: 760px) { .inner { padding: 48px 16px 80px; } }
  h1 { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; margin: 0 0 4px; }
  .sub { color: var(--text-3); margin: 0 0 22px; }
  ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
  li {
    display: grid; grid-template-columns: 170px 1fr; gap: 6px 16px; padding: 14px 16px;
    background: var(--bg-elev); border: 1px solid var(--card-border, var(--line)); border-radius: var(--radius-lg, 12px);
  }
  .when { display: flex; align-items: center; gap: 6px; color: var(--accent-ink); font-weight: 600; font-size: 13px; }
  .main { min-width: 0; }
  .to { font-size: 12.5px; color: var(--text-2); }
  .subj { font-weight: 600; margin: 2px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pre { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .acts { grid-column: 2; display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  .empty { text-align: center; padding: 50px 20px; max-width: 460px; margin: 0 auto; }
  .empty .big {
    display: inline-grid; place-items: center; width: 64px; height: 64px; border-radius: 18px;
    background: var(--bg-sunken); color: var(--text-3); margin-bottom: 10px;
  }
  .empty p { margin: 6px 0; line-height: 1.5; }
  @media (max-width: 560px) {
    li { grid-template-columns: 1fr; }
    .acts { grid-column: 1; }
  }
</style>
