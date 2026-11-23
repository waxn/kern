<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onMount } from 'svelte';
  import { loadPackages, parcels } from '../state.svelte.js';
  import { daysUntil, packageSummary } from '../packages.js';
  import PackageCard from '../components/PackageCard.svelte';
  import PackageMap from '../components/PackageMap.svelte';
  import Icon from '../components/Icon.svelte';

  onMount(loadPackages);

  // Soonest first; things needing you (pickup, problems) float to the top.
  const RANK = { ready_for_pickup: 0, exception: 1, out_for_delivery: 2 };
  const active = $derived(
    [...parcels.active].sort((a, b) => {
      const ra = RANK[a.status] ?? 3, rb = RANK[b.status] ?? 3;
      if (ra !== rb) return ra - rb;
      const da = daysUntil(a.expected) ?? 999, db = daysUntil(b.expected) ?? 999;
      return da - db;
    }),
  );
  // Every package on one map: on the way first, and today's deliveries.
  const routes = $derived([
    ...active.map((p) => ({ id: p.id, points: p.route?.points || [], delivered: false, label: p.merchant || p.carrierName })),
    ...parcels.delivered.filter((p) => p.route?.points?.length && p.statusAt && new Date(p.statusAt) > new Date(Date.now() - 2 * 86400e3))
      .map((p) => ({ id: p.id, points: p.route.points, delivered: true, label: p.merchant || p.carrierName })),
  ]);
  function pick(id) {
    const el = document.getElementById(`pkg-${id}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el?.classList.add('flash');
    setTimeout(() => el?.classList.remove('flash'), 1200);
  }
  const ledger = $derived.by(() => {
    const n = parcels.active.length;
    const parts = [n ? `${n} on the way` : 'nothing on the way', ...packageSummary(parcels.active)];
    if (parcels.delivered.length) parts.push(`${parcels.delivered.length} delivered in the last two weeks`);
    return parts;
  });
</script>

<div class="mail-page scroll">
  <div class="inner">
    <h1>Packages</h1>
    <p class="sub">{ledger.join(' · ')}</p>

    {#if parcels.loaded && !parcels.tracking?.hasKey}
      <div class="tip">
        <Icon name="truck" size={16} />
        <span>Shops rarely email when something is delivered. Turn on <b>live tracking</b> (built in, no account needed; or
          Parcels or TrackingMore) to get the carrier's real status, a map of where the package is and its latest scans.</span>
        <a class="btn small" href="/settings?s=mail#tracking">Set up</a>
      </div>
    {:else if parcels.tracking?.lastError}
      <div class="tip warn"><Icon name="shieldAlert" size={16} /><span>Live tracking: {parcels.tracking.lastError}</span>
        <a class="btn small" href="/settings?s=mail#tracking">Settings</a></div>
    {/if}

    {#if active.length || parcels.delivered.length}
      <div class="overview"><PackageMap {routes} height={260} map={parcels.map} onpick={pick} /></div>
    {/if}

    {#if parcels.loaded && !active.length && !parcels.delivered.length}
      <div class="empty">
        <span class="big"><Icon name="package" size={30} stroke={1.4} /></span>
        <p><b>No packages yet.</b></p>
        <p class="faint">When a shipping email with a tracking number arrives, it shows up here with its status and expected
          day. Detection runs on your server from the email itself; with live tracking on, the carrier's status is checked
          every hour or so.</p>
      </div>
    {/if}

    {#if active.length}
      <section aria-labelledby="pk-active">
        <h2 id="pk-active" class="ledger">On the way</h2>
        <div class="grid">
          {#each active as p (p.id)}<PackageCard {p} />{/each}
        </div>
      </section>
    {/if}

    {#if parcels.delivered.length}
      <section aria-labelledby="pk-done">
        <h2 id="pk-done" class="ledger">Delivered</h2>
        <div class="grid">
          {#each parcels.delivered as p (p.id)}<PackageCard {p} compact />{/each}
        </div>
      </section>
    {/if}
  </div>
</div>

<style>
  .mail-page { flex: 1; min-height: 0; width: 100%; }
  .inner { max-width: 860px; margin: 0 auto; padding: 36px 40px 80px; }
  h1 { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; margin: 0 0 4px; }
  .sub { color: var(--text-2); margin: 0 0 18px; }
  .tip { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--text-2); font-size: 13px; margin-bottom: 8px; }
  .tip :global(svg) { flex: none; color: var(--accent-ink); }
  .tip span { flex: 1; }
  .tip.warn :global(svg) { color: var(--warn); }
  a.btn { text-decoration: none; color: var(--text); }
  @media (max-width: 760px) { .inner { padding: 48px 16px 80px; } }
  section { margin-top: 18px; }
  .overview { margin: 4px 0 6px; }
  .grid :global(.pkg.flash) { box-shadow: 0 0 0 2px var(--accent); transition: box-shadow .3s; }
  h2 { color: var(--text-3); margin: 0 0 10px; }
  .grid { display: grid; gap: 10px; }
  .empty { text-align: center; padding: 50px 20px; max-width: 460px; margin: 0 auto; }
  .empty .big {
    display: inline-grid; place-items: center; width: 64px; height: 64px; border-radius: 18px;
    background: var(--bg-sunken); color: var(--text-3); margin-bottom: 10px;
  }
  .empty p { margin: 6px 0; line-height: 1.5; }
</style>
