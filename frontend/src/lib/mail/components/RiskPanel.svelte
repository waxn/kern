<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import Icon from './Icon.svelte';

  let { risk, expanded = false } = $props();
  let open = $state(false);
  $effect(() => {
    open = expanded;
  });
  const LABEL = { high: 'High phishing risk', medium: 'This message looks suspicious', low: 'Low risk' };
  const positive = $derived(risk.findings.filter((f) => f.weight > 0).sort((a, b) => b.weight - a.weight));
  let showAll = $state(false);
  const shown = $derived(showAll ? positive : positive.slice(0, 3));
  const negative = $derived(risk.findings.filter((f) => f.weight <= 0));
</script>

<div class="risk {risk.level || 'low'}">
  <button class="head" onclick={() => (open = !open)} aria-expanded={open}>
    <Icon name={risk.level === 'low' ? 'shield' : 'shieldAlert'} size={16} />
    <span class="title">{LABEL[risk.level] || 'Risk check'}</span>
    {#if risk.level !== 'low' && positive[0]}<span class="lead">{positive[0].reason}</span>{/if}
    <span class="why">{open ? 'Hide' : 'Why?'}</span>
  </button>
  {#if open}
    <ul>
      {#each shown as f}
        <li>
          <span class="rule">{f.title}</span>
          <span class="reason">{f.reason}</span>
          <span class="weight" title="Score added by this rule">+{f.weight}</span>
        </li>
      {/each}
      {#if positive.length > shown.length}
        <li class="more"><button onclick={() => (showAll = true)}>+ {positive.length - shown.length} more reason{positive.length - shown.length === 1 ? '' : 's'}</button></li>
      {/if}
      {#each negative as f}
        <li class="good">
          <span class="rule">{f.title}</span>
          <span class="reason">{f.reason}</span>
          <span class="weight">{f.weight}</span>
        </li>
      {/each}
    </ul>
    <p class="foot">
      Score {risk.score}. Rules only look at headers, sender details, link targets and attachment names, never at the
      text with AI. You can tune them in <code>rules.yaml</code>; see Settings.
    </p>
  {/if}
</div>

<style>
  .risk { margin: 0 14px 10px 62px; border-radius: var(--radius-sm); font-size: 13px; border: 1px solid transparent; }
  .risk.high { background: var(--danger-soft); color: var(--danger); border-color: color-mix(in srgb, var(--danger) 25%, transparent); }
  .risk.medium { background: var(--warn-soft); color: var(--warn); border-color: color-mix(in srgb, var(--warn) 25%, transparent); }
  .risk.low { background: var(--bg-sunken); color: var(--text-2); }
  .head {
    display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 12px; border: 0; background: none;
    color: inherit; cursor: pointer; text-align: left; font-size: 13px;
  }
  .title { font-family: var(--mono); font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; white-space: nowrap; }
  .lead { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; opacity: .9; }
  .why { margin-left: auto; font-weight: 600; font-size: 12px; text-decoration: underline; text-underline-offset: 2px; }
  ul { list-style: none; margin: 0; padding: 0 12px 4px 36px; display: grid; gap: 6px; }
  li { display: grid; grid-template-columns: 1fr auto; gap: 0 12px; color: var(--text); }
  .rule { font-weight: 600; font-size: 12.5px; }
  .reason { grid-column: 1; color: var(--text-2); font-size: 12.5px; }
  .weight { grid-row: 1 / span 2; grid-column: 2; align-self: center; font: 600 12px var(--mono); color: inherit; opacity: .8; }
  li.good .weight { color: var(--ok); }
  li.more button { border: 0; background: none; padding: 0; color: inherit; font-weight: 600; font-size: 12.5px; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
  .foot { margin: 6px 12px 0 36px; padding: 0 0 10px; font-size: 11.5px; color: var(--text-3); }
  @media (max-width: 640px) {
    .risk { margin-left: 8px; margin-right: 8px; }
    .lead { display: none; }
  }
</style>
