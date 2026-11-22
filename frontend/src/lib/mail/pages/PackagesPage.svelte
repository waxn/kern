<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onMount } from 'svelte';
  import { loadPackages, parcels } from '../state.svelte.js';
  import { daysUntil, packageSummary } from '../packages.js';
  import PackageCard from '../components/PackageCard.svelte';
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
  const ledger = $derived.by(() => {
    const n = parcels.active.length;
    const parts = [n ? `${n} on the way` : 'nothing on the way', ...packageSummary(parcels.active)];
    if (parcels.delivered.length) parts.push(`${parcels.delivered.length} delivered in the last two weeks`);
    return parts;
  });
</script>

<div class="mail-page scroll">
  <div class="inner">
    <h1 class="display">Packages</h1>
    <p class="ledger sub">{ledger.join(' · ')}</p>

    {#if parcels.loaded && !active.length && !parcels.delivered.length}
      <div class="empty">
        <span class="big"><Icon name="package" size={30} stroke={1.4} /></span>
        <p><b>No packages yet.</b></p>
        <p class="faint">When a shipping email with a tracking number arrives, it shows up here with its status and expected
          day. Detection runs on your server from the email itself. Kern never contacts the carrier; “Track” just opens
          their page when you click it.</p>
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
  .inner { max-width: 820px; margin: 0 auto; padding: 18px 20px 80px; }
  h1 { font-size: 36px; margin: 6px 0 4px; }
  .sub { color: var(--text-3); margin: 0 0 22px; }
  section { margin-top: 18px; }
  h2 { color: var(--text-3); margin: 0 0 10px; font-size: inherit; }
  .grid { display: grid; gap: 10px; }
  .empty { text-align: center; padding: 50px 20px; max-width: 460px; margin: 0 auto; }
  .empty .big {
    display: inline-grid; place-items: center; width: 64px; height: 64px; border-radius: 18px;
    background: var(--bg-sunken); color: var(--text-3); margin-bottom: 10px;
  }
  .empty p { margin: 6px 0; line-height: 1.5; }
</style>
