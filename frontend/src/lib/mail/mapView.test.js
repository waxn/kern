// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { mapView, mapViewRoutes, project } from './mapView.js';

describe('package map', () => {
  it('projects like every web map', () => {
    const p = project(0, 0, 0);
    expect(p.x).toBeCloseTo(128);
    expect(p.y).toBeCloseTo(128);
  });
  it('fits the route inside the box with room around it', () => {
    const v = mapView([[45.52, -122.68, 'Portland'], [30.27, -97.74, 'Austin']], 400, 150);
    expect(v.pts).toHaveLength(2);
    for (const p of v.pts) {
      expect(p.x).toBeGreaterThanOrEqual(22 - 1);
      expect(p.x).toBeLessThanOrEqual(400 - 22 + 1);
      expect(p.y).toBeGreaterThanOrEqual(22 - 1);
      expect(p.y).toBeLessThanOrEqual(150 - 22 + 1);
    }
    // Tiles cover the whole box.
    expect(Math.min(...v.tiles.map((t) => t.left))).toBeLessThanOrEqual(0);
    expect(Math.max(...v.tiles.map((t) => t.left + v.tileSize))).toBeGreaterThanOrEqual(400);
    expect(v.tiles[0].z).toBe(v.z + 1);
  });
  it('shows a single place at city zoom, centred', () => {
    const v = mapView([[55.6, 13.0]], 300, 150);
    expect(v.z).toBe(9);
    expect(v.pts[0].x).toBeCloseTo(150);
    expect(v.pts[0].y).toBeCloseTo(75);
  });
  it('draws nothing without places', () => {
    expect(mapView([], 300, 150)).toBeNull();
    expect(mapView([[null, 1]], 300, 150)).toBeNull();
  });
});

describe('all packages on one map', () => {
  it('fits every route', () => {
    const v = mapViewRoutes([{ id: 1, points: [[45.5, -122.7], [30.3, -97.7]] }, { id: 2, points: [[40.7, -74.0]] }], 600, 220);
    expect(v.routes.map((r) => r.pts.length)).toEqual([2, 1]);
    for (const p of v.routes.flatMap((r) => r.pts)) {
      expect(p.x).toBeGreaterThanOrEqual(21);
      expect(p.x).toBeLessThanOrEqual(600 - 21);
    }
  });
  it('shows the world when nothing has a place yet', () => {
    const v = mapViewRoutes([{ id: 1, points: [] }], 600, 220);
    expect(v.tiles.length).toBeGreaterThan(0);
    expect(v.routes[0].pts).toEqual([]);
  });
});
