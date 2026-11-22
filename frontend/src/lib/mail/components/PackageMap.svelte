<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // A small map of where a package has been: a line through its scans, oldest to newest, and a
  // marker where it is now. Tiles come through Kern's server (backend/mail/geo.py), dark or light
  // with the theme; a source with one colourful style (OpenStreetMap) is toned down here. The math
  // is plain Web Mercator, so there's no map library to load.
  import { resolvedTheme } from '#lib/state/prefs.svelte.ts';
  import { mapView } from '../mapView.js';

  let { points = [], delivered = false, height = 170, map = null } = $props();
  let width = $state(0);

  const theme = $derived(resolvedTheme() === 'dark' ? 'dark' : 'light');
  const view = $derived(width ? mapView(points, width, height) : null);
</script>

<div class="map" class:light={theme === 'light'} class:osm={map ? map.tone : true} style:height="{height}px" bind:clientWidth={width} aria-hidden="true">
  {#if view}
    {#each view.tiles as t (t.key)}
      <img src="/api/mail/maptiles/{theme}/{t.z}/{t.x}/{t.y}.png?v={map?.version || ''}" alt="" draggable="false"
           style:left="{t.left}px" style:top="{t.top}px" style:width="{view.tileSize}px" style:height="{view.tileSize}px" />
    {/each}
    <svg width={width} height={height} viewBox="0 0 {width} {height}">
      {#if view.pts.length > 1}
        <polyline class="halo" points={view.pts.map((p) => `${p.x},${p.y}`).join(' ')} />
        <polyline class="route" points={view.pts.map((p) => `${p.x},${p.y}`).join(' ')} />
      {/if}
      {#each view.pts.slice(0, -1) as p, i (i)}
        <circle class="stop" cx={p.x} cy={p.y} r="3.5" />
      {/each}
      {#if view.pts.length}
        {@const now = view.pts[view.pts.length - 1]}
        {#if !delivered}<circle class="pulse" cx={now.x} cy={now.y} r="7" />{/if}
        <circle class="here" class:done={delivered} cx={now.x} cy={now.y} r="6" />
      {/if}
    </svg>
    <span class="attr">{map?.attribution || '© OpenStreetMap contributors'}</span>
  {/if}
</div>

<style>
  .map {
    position: relative; overflow: hidden; border-radius: var(--radius); background: #1b1b1d;
    border: 1px solid var(--line); user-select: none;
  }
  .map.light { background: #f2f1ee; }
  /* Pulled toward Kern's own greys so the map reads as part of the page. */
  img { position: absolute; max-width: none; filter: saturate(0.7) brightness(0.95); }
  .map.light img { filter: saturate(0.7); }
  /* OpenStreetMap's colourful map: grey it down, and turn it dark in the dark theme. */
  .map.osm img { filter: grayscale(1) invert(1) brightness(0.78) contrast(0.92); }
  .map.osm.light img { filter: grayscale(0.85) contrast(0.9) brightness(1.03); }
  svg { position: absolute; inset: 0; }
  .route { fill: none; stroke: var(--accent); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  .halo { fill: none; stroke: var(--bg); stroke-width: 6; stroke-linecap: round; stroke-linejoin: round; opacity: .7; }
  .stop { fill: var(--bg); stroke: var(--accent); stroke-width: 2; }
  .here { fill: var(--accent); stroke: var(--bg); stroke-width: 2.5; }
  .here.done { fill: var(--ok, #7fbf8f); }
  .pulse { fill: var(--accent); opacity: .35; transform-box: fill-box; transform-origin: center; animation: pkg-pulse 1.8s ease-out infinite; }
  @keyframes pkg-pulse { from { transform: scale(1); opacity: .45; } to { transform: scale(2.6); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  .attr { position: absolute; right: 4px; bottom: 2px; font-size: 9px; color: var(--text-3); background: color-mix(in srgb, var(--bg) 70%, transparent); padding: 0 4px; border-radius: 3px; }
</style>
