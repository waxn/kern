// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { parseTime, parseWhen } from './when.js';

const now = new Date(2026, 10, 18, 9, 30); // Wednesday 18 Nov 2026, 09:30
const fmt = (d) => d && `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;

describe('parseWhen', () => {
  const cases = [
    ['in 2 hours', '2026-11-18 11:30'],
    ['2h', '2026-11-18 11:30'],
    ['30m', '2026-11-18 10:00'],
    ['in a week', '2026-11-25 9:30'],
    ['3d', '2026-11-21 9:30'],
    ['tomorrow', '2026-11-19 8:00'],
    ['tom 2pm', '2026-11-19 14:00'],
    ['tomorrow at 14:30', '2026-11-19 14:30'],
    ['tonight', '2026-11-18 20:00'],
    ['this evening', '2026-11-18 18:00'],
    ['fri', '2026-11-20 8:00'],
    ['friday 3pm', '2026-11-20 15:00'],
    ['next mon', '2026-11-23 8:00'],
    ['wed', '2026-11-25 8:00'],
    ['weekend', '2026-11-21 9:00'],
    ['next week', '2026-11-23 8:00'],
    ['next month', '2026-12-1 8:00'],
    ['dec 24', '2026-12-24 8:00'],
    ['dec 9', '2026-12-9 8:00'],
    ['24 dec 9am', '2026-12-24 9:00'],
    ['2027-01-05', '2027-1-5 8:00'],
    ['24/12', '2026-12-24 8:00'],
    ['nov 1', '2027-11-1 8:00'],
    ['5pm', '2026-11-18 17:00'],
    ['9am', '2026-11-19 9:00'],
    ['noon', '2026-11-18 12:00'],
    ['until mon at 9', '2026-11-23 9:00'],
  ];
  for (const [input, want] of cases) {
    it(input, () => expect(fmt(parseWhen(input, now))).toBe(want));
  }
  it('rejects nonsense', () => {
    for (const bad of ['', 'banana', '31 feb', '25:00', 'in pizza']) expect(parseWhen(bad, now)).toBe(null);
  });
  it('parses times', () => {
    expect(parseTime('12am')).toEqual([0, 0]);
    expect(parseTime('9.30pm')).toEqual([21, 30]);
    expect(parseTime('13pm')).toBe(null);
  });
});

import { ago } from './when.js';

describe('ago', () => {
  const now = new Date(2026, 10, 18, 12);
  it('formats the past', () => {
    expect(ago(new Date(2026, 10, 18, 11, 59), now)).toBe('just now');
    expect(ago(new Date(2026, 10, 18, 9), now)).toBe('3 hours ago');
    expect(ago(new Date(2026, 10, 17, 12), now)).toBe('yesterday');
    expect(ago(new Date(2026, 10, 14, 12), now)).toBe('4 days ago');
  });
});
