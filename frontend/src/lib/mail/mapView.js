// @ts-nocheck: plain JavaScript; covered by mapView.test.js.
// Fitting a route onto a few Web Mercator map tiles (the same tiling every web map uses).

export const TILE = 256; // pixels per tile at zoom z

export function project(lat, lon, z) {
  const size = TILE * 2 ** z;
  const s = Math.min(Math.max(Math.sin((lat * Math.PI) / 180), -0.9999), 0.9999);
  return { x: ((lon + 180) / 360) * size, y: (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size };
}

// points: [[lat, lon, place?], ...] oldest first. Returns the tiles to draw and the points in
// the box's own pixels, or null when there's nothing to show.
export function mapView(points, width, height, { pad = 22, maxZoom = 11, minZoom = 1, single = 9 } = {}) {
  const ll = (points || []).filter((p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]));
  if (!ll.length || width <= 0 || height <= 0) return null;
  let z = single;
  if (ll.length > 1) {
    for (z = maxZoom; z > minZoom; z--) {
      const xy = ll.map((p) => project(p[0], p[1], z));
      const w = Math.max(...xy.map((p) => p.x)) - Math.min(...xy.map((p) => p.x));
      const h = Math.max(...xy.map((p) => p.y)) - Math.min(...xy.map((p) => p.y));
      if (w <= width - 2 * pad && h <= height - 2 * pad) break;
    }
  }
  const xy = ll.map((p) => project(p[0], p[1], z));
  const cx = (Math.max(...xy.map((p) => p.x)) + Math.min(...xy.map((p) => p.x))) / 2;
  const cy = (Math.max(...xy.map((p) => p.y)) + Math.min(...xy.map((p) => p.y))) / 2;
  const ox = cx - width / 2;
  const oy = cy - height / 2;
  // Tiles one zoom level deeper drawn at half size: sharp on high-density screens.
  const zt = Math.min(z + 1, 18);
  const k = 2 ** (zt - z);
  const size = TILE / k;
  const n = 2 ** zt;
  const tiles = [];
  for (let ty = Math.floor((oy * k) / TILE); ty <= Math.floor(((oy + height) * k) / TILE); ty++) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = Math.floor((ox * k) / TILE); tx <= Math.floor(((ox + width) * k) / TILE); tx++) {
      const x = ((tx % n) + n) % n;
      tiles.push({ key: `${zt}/${tx}/${ty}`, z: zt, x, y: ty, left: Math.round(tx * size - ox), top: Math.round(ty * size - oy) });
    }
  }
  return { z, tiles, tileSize: size, pts: xy.map((p, i) => ({ x: p.x - ox, y: p.y - oy, place: ll[i][2] || '' })) };
}
