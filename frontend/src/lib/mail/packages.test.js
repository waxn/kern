// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { arrivalLabel, arrivingToday, daysUntil, groupNumber, isLate, packageSummary } from './packages.js';

const NOW = new Date(2026, 10, 16, 10, 0); // Mon 16 Nov 2026, local

describe('packages', () => {
  it('counts calendar days in local time', () => {
    expect(daysUntil('2026-11-16', NOW)).toBe(0);
    expect(daysUntil('2026-11-17', NOW)).toBe(1);
    expect(daysUntil('2026-11-14', NOW)).toBe(-2);
    expect(daysUntil(null, NOW)).toBe(null);
  });

  it('labels arrival', () => {
    expect(arrivalLabel({ status: 'in_transit', expected: '2026-11-17' }, NOW)).toBe('Arriving tomorrow');
    expect(arrivalLabel({ status: 'in_transit', expected: '2026-11-16' }, NOW)).toBe('Arriving today');
    expect(arrivalLabel({ status: 'out_for_delivery', expected: null }, NOW)).toBe('Arriving today');
    expect(arrivalLabel({ status: 'out_for_delivery', statusAt: new Date(2026, 10, 16, 7).toISOString() }, NOW)).toBe('Arriving today');
    expect(arrivalLabel({ status: 'out_for_delivery', statusAt: new Date(2026, 10, 12, 7).toISOString() }, NOW)).toMatch(/^Out for delivery since /);
    expect(arrivalLabel({ status: 'in_transit', expected: '2026-11-15' }, NOW)).toBe('Expected yesterday');
    expect(arrivalLabel({ status: 'in_transit', expected: null }, NOW)).toBe('No delivery date yet');
    expect(arrivalLabel({ status: 'exception', expected: null }, NOW)).toBe('Check with the carrier');
    expect(arrivalLabel({ status: 'ready_for_pickup' }, NOW)).toBe('Waiting for you to pick it up');
    expect(arrivalLabel({ status: 'delivered', statusAt: new Date(2026, 10, 16, 8).toISOString() }, NOW)).toBe('Delivered today');
    expect(arrivalLabel({ status: 'delivered', statusAt: new Date(2026, 10, 15, 23).toISOString() }, NOW)).toBe('Delivered yesterday');
    expect(arrivalLabel({ status: 'in_transit', expected: '2026-11-19' }, NOW)).toMatch(/^Arriving \w+day$/);
  });

  it('flags late packages but not delivered ones', () => {
    expect(isLate({ status: 'in_transit', expected: '2026-11-10' }, NOW)).toBe(true);
    expect(isLate({ status: 'delivered', expected: '2026-11-10' }, NOW)).toBe(false);
    expect(isLate({ status: 'in_transit', expected: null }, NOW)).toBe(false);
    expect(isLate({ status: 'out_for_delivery', statusAt: new Date(2026, 10, 12).toISOString() }, NOW)).toBe(true);
    expect(isLate({ status: 'out_for_delivery', statusAt: new Date(2026, 10, 16, 7).toISOString() }, NOW)).toBe(false);
  });

  it('summarises the day', () => {
    const active = [
      { status: 'out_for_delivery' },
      { status: 'out_for_delivery', statusAt: new Date(2026, 10, 10).toISOString(), expected: '2026-11-16' },
      { status: 'in_transit', expected: '2026-11-16' },
      { status: 'in_transit', expected: '2026-11-20' },
      { status: 'ready_for_pickup' },
    ];
    expect(arrivingToday(active, NOW)).toHaveLength(2);
    expect(packageSummary(active, NOW)).toEqual(['2 packages arriving today', '1 to pick up']);
    expect(packageSummary([], NOW)).toEqual([]);
    expect(packageSummary(active, NOW, { short: true })).toEqual(['2 parcels today', '1 to collect']);
  });

  it('groups numbers for reading', () => {
    expect(groupNumber('1Z999AA10123456784')).toBe('1Z99 9AA1 0123 4567 84');
    expect(groupNumber('')).toBe('');
    expect(groupNumber('RR123456785SE')).toBe('RR 123 456 785 SE');
  });
});
