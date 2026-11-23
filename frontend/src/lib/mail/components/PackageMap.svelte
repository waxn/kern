<script>
  // @ts-nocheck: plain JavaScript (like the rest of mail).
  // Where packages have been: a line through each one's scans, oldest to newest, and a marker
  // where it is now. One package (its card) or all of them (the Packages page, with a name by
  // each marker). Tiles come through Kern's server (backend/mail/geo.py), dark or light with the
  // theme; a source with one colourful style (OpenStreetMap) is toned down here. The math is
  // plain Web Mercator (mapView.js), so there's no map library to load.
  import { resolvedTheme } from '#lib/state/prefs.svelte.ts';
  import { mapViewRoutes } from '../mapView.js';

  let {
    points = null, // one package: [[lat, lon, place], ...]
    delivered = false,
    routes = null, // several: [{ id, points, delivered, label }]
    height = 170,
    map = null,
    center = undefined, // [lat, lon] for an empty map
    onpick = null, // (id) => … when a package's marker is clicked
  } = $props();
  let width = $state(0);
  let hover = $state(null);

  const theme = $derived(resolvedTheme() === 'dark' ? 'dark' : 'light');
  const list = $derived(routes ?? [{ id: 0, points: points || [], delivered }]);
  const many = $derived(!!routes);
  const view = $derived(width ? mapViewRoutes(list, width, height, center ? { center } : {}) : null);
  const line = (pts) => pts.map((p) => `${p.x},${p.y}`).join(' ');
</script>

<div class="map" class:light={theme === 'light'} class:osm={map ? map.tone : true} style:height="{height}px" bind:clientWidth={width}
     role={many ? 'group' : undefined} aria-hidden={many ? undefined : 'true'} aria-label={many ? 'Map of your packages' : undefined}>
  {#if view}
    {#each view.tiles as t (t.key)}
      <img src="/api/mail/maptiles/{theme}/{t.z}/{t.x}/{t.y}.png?v={map?.version || ''}" alt="" draggable="false"
           style:left="{t.left}px" style:top="{t.top}px" style:width="{view.tileSize}px" style:height="{view.tileSize}px" />
    {/each}
    <svg width={width} height={height} viewBox="0 0 {width} {height}">
      {#each view.routes as r (r.id)}
        {#if r.pts.length > 1}
          <polyline class="halo" points={line(r.pts)} />
          <polyline class="route" class:done={r.delivered} class:dim={hover != null && hover !== r.id} points={line(r.pts)} />
        {/if}
        {#each r.pts.slice(0, -1) as p, i (i)}
          <circle class="stop" class:done={r.delivered} cx={p.x} cy={p.y} r="3.5" />
        {/each}
      {/each}
      {#each view.routes as r (r.id)}
        {#if r.pts.length}
          {@const now = r.pts[r.pts.length - 1]}
          {#if !r.delivered}<circle class="pulse" cx={now.x} cy={now.y} r="7" />{/if}
          <circle class="here" class:done={r.delivered} cx={now.x} cy={now.y} r="6" />
        {/if}
      {/each}
    </svg>
    {#if many}
      {#each view.routes as r (r.id)}
        {#if r.pts.length && r.label}
          {@const now = r.pts[r.pts.length - 1]}
          <button class="tag" class:hot={hover === r.id} class:done={r.delivered} style:left="{now.x + 10}px" style:top="{now.y - 11}px"
                  onmouseenter={() => (hover = r.id)} onmouseleave={() => (hover = null)} onclick={() => onpick?.(r.id)}>{r.label}</button>
        {/if}
      {/each}
      {#if !view.routes.some((r) => r.pts.length)}
        <div class="empty"><span>Packages appear here once live tracking has their scans.</span></div>
      {/if}
    {/if}
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
  .route { fill: none; stroke: var(--accent); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; transition: opacity .15s; }
  .route.done, .stop.done { stroke: var(--ok, #7fbf8f); }
  .route.dim { opacity: .35; }
  .halo { fill: none; stroke: var(--bg); stroke-width: 6; stroke-linecap: round; stroke-linejoin: round; opacity: .7; }
  .stop { fill: var(--bg); stroke: var(--accent); stroke-width: 2; }
  .here { fill: var(--accent); stroke: var(--bg); stroke-width: 2.5; }
  .here.done { fill: var(--ok, #7fbf8f); }
  .pulse { fill: var(--accent); opacity: .35; transform-box: fill-box; transform-origin: center; animation: pkg-pulse 1.8s ease-out infinite; pointer-events: none; }
  @keyframes pkg-pulse { from { transform: scale(1); opacity: .45; } to { transform: scale(2.6); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  .tag {
    position: absolute; max-width: 150px; padding: 2px 7px; border-radius: 10px; font-size: 11.5px; font-weight: 550;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer;
    color: var(--text); background: color-mix(in srgb, var(--bg) 88%, transparent); border: 1px solid var(--line);
  }
  .tag.hot { border-color: var(--accent); }
  .tag.done { color: var(--text-2); }
  .empty { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
  .empty span { padding: 6px 12px; border-radius: 14px; font-size: 12.5px; color: var(--text-2); background: color-mix(in srgb, var(--bg) 85%, transparent); }
  .attr { position: absolute; right: 4px; bottom: 2px; font-size: 9px; color: var(--text-3); background: color-mix(in srgb, var(--bg) 70%, transparent); padding: 0 4px; border-radius: 3px; }
</style>
