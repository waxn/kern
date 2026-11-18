<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // One shipment: where it is, when it arrives, and a link to the carrier's
  // own tracking page. Nothing is fetched from the carrier; the link only
  // opens when you click it.
  import { navigate } from '../router.svelte.js';
  import { errorToast, packageAction, toast } from '../state.svelte.js';
  import { STEPS, arrivalLabel, groupNumber, isLate } from '../packages.js';
  import Icon from './Icon.svelte';

  let { p, compact = false, inThread = false } = $props();

  const late = $derived(isLate(p));
  const tone = $derived(p.status === 'exception' || late ? 'warn' : p.status === 'delivered' ? 'ok' : p.step >= 2 ? 'hot' : '');

  async function copy() {
    try {
      await navigator.clipboard.writeText(p.number);
      toast('Tracking number copied');
    } catch {
      toast("Couldn't copy. Select the number and copy it by hand.", { kind: 'error' });
    }
  }
  async function act(action) {
    try {
      await packageAction(p, action);
      if (action === 'hide') {
        toast('Package hidden', { action: { label: 'Undo', run: () => packageAction(p, 'unhide').catch(errorToast) } });
      } else toast('Marked as delivered');
    } catch (e) {
      errorToast(e);
    }
  }
</script>

<article class="pkg {tone}" class:compact aria-label={`${p.carrierName} package ${p.number}: ${p.statusLabel}`}>
  <div class="top">
    <span class="ico"><Icon name={p.status === 'delivered' ? 'check' : p.step >= 2 ? 'truck' : 'package'} size={compact ? 16 : 18} /></span>
    <div class="what">
      <div class="ledger who">{p.carrierName}{#if p.merchant}<span class="sep">·</span>{p.merchant}{/if}</div>
      <div class="when display">{arrivalLabel(p)}</div>
      {#if !compact && p.subject}<div class="subj faint">{p.subject}</div>{/if}
    </div>
    <span class="status">{late ? 'Running late' : p.statusLabel}</span>
  </div>

  <ol class="track" aria-label={`Progress: ${STEPS[p.step]}`}>
    {#each STEPS as s, i}
      <li class:done={i <= p.step} class:now={i === p.step}><span class="bar"></span>{#if !compact}<span class="lbl">{s}</span>{/if}</li>
    {/each}
  </ol>

  <div class="foot">
    <span class="num mono" title="Tracking number">{groupNumber(p.number)}</span>
    <button class="icon-btn small" title="Copy tracking number" aria-label="Copy tracking number" onclick={copy}><Icon name="copy" size={14} /></button>
    <span class="grow"></span>
    {#if p.trackUrl}
      <a class="btn small" href={p.trackUrl} target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"
         title={`Opens ${p.carrierName}'s tracking page in a new tab`}>Track <Icon name="external" size={13} /></a>
    {/if}
    {#if !inThread && p.threadId}
      <button class="btn small ghost" onclick={() => navigate({ page: 'mail', view: 'all', threadId: p.threadId })}>Open email</button>
    {/if}
    {#if p.status !== 'delivered' && !compact}
      <button class="btn small ghost" title="Mark as delivered" onclick={() => act('delivered')}>Got it</button>
    {/if}
    <button class="icon-btn small" title="Hide this package" aria-label="Hide this package" onclick={() => act('hide')}><Icon name="close" size={14} /></button>
  </div>
</article>

<style>
  .pkg {
    --tone: var(--accent-ink);
    position: relative;
    background: var(--bg-elev);
    border: 1px solid var(--card-border, var(--line));
    border-radius: var(--radius-lg, 12px);
    padding: 14px 16px 12px;
    display: grid;
    gap: 12px;
  }
  .pkg.ok { --tone: var(--ok); }
  .pkg.warn { --tone: var(--warn); }
  .pkg.compact { padding: 10px 12px 8px; gap: 8px; border-radius: var(--radius, 10px); }
  .top { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
  .ico {
    flex: none; width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center;
    background: color-mix(in srgb, var(--tone) 14%, transparent); color: var(--tone);
  }
  .compact .ico { width: 28px; height: 28px; border-radius: 8px; }
  .what { flex: 1; min-width: 0; }
  .who { color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sep { margin: 0 6px; opacity: .6; }
  .when { font-size: 22px; line-height: 1.15; margin-top: 2px; }
  .compact .when { font-size: 16px; }
  .subj { font-size: 12.5px; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .status {
    flex: none; font-size: 11.5px; font-weight: 600; padding: 3px 8px; border-radius: 999px;
    color: var(--tone); background: color-mix(in srgb, var(--tone) 12%, transparent);
  }
  .track { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
  .track li { display: grid; gap: 5px; min-width: 0; }
  .bar { height: 4px; border-radius: 2px; background: var(--line-strong, var(--line)); }
  .done .bar { background: var(--tone); }
  .now .bar { box-shadow: 0 0 0 2px color-mix(in srgb, var(--tone) 22%, transparent); }
  .lbl { font-size: 11px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .done .lbl { color: var(--text-2); }
  .now .lbl { color: var(--text); font-weight: 600; }
  .foot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .mono { font-family: var(--mono); font-size: 12.5px; color: var(--text-2); letter-spacing: .02em; user-select: all; }
  .grow { flex: 1; }
  a.btn { text-decoration: none; display: inline-flex; align-items: center; gap: 4px; }
  @media (max-width: 560px) {
    .when { font-size: 19px; }
    .pkg:not(.warn) .status { display: none; }
    .lbl { font-size: 10px; }
  }
</style>
