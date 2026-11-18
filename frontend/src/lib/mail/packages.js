// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Package tracking helpers (pure, tested in packages.test.js).

const DAY = 86400e3;

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

// "2026-11-19" -> local Date at midnight (not UTC: a date is a calendar day).
export function parseDay(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function daysUntil(iso, now = new Date()) {
  const d = parseDay(iso);
  return d ? Math.round((d - startOfDay(now)) / DAY) : null;
}

function sameDay(a, b) {
  return startOfDay(a).getTime() === startOfDay(b).getTime();
}

// "Out for delivery" only means today if the carrier said so today.
function outToday(p, now) {
  return p.status === 'out_for_delivery' && (!p.statusAt || sameDay(new Date(p.statusAt), now));
}

// One short line about when it arrives (or arrived).
export function arrivalLabel(p, now = new Date()) {
  if (p.status === 'delivered') {
    const n = p.statusAt ? Math.round((startOfDay(now) - startOfDay(new Date(p.statusAt))) / DAY) : null;
    if (n === 0) return 'Delivered today';
    if (n === 1) return 'Delivered yesterday';
    return p.statusAt ? `Delivered ${new Date(p.statusAt).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}` : 'Delivered';
  }
  if (p.status === 'ready_for_pickup') return 'Waiting for you to pick it up';
  if (outToday(p, now)) return 'Arriving today';
  if (p.status === 'out_for_delivery') {
    return `Out for delivery since ${new Date(p.statusAt).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}`;
  }
  const n = daysUntil(p.expected, now);
  if (n === null) return p.status === 'exception' ? 'Check with the carrier' : 'No delivery date yet';
  if (n < 0) return `Expected ${-n === 1 ? 'yesterday' : `${-n} days ago`}`;
  if (n === 0) return 'Arriving today';
  if (n === 1) return 'Arriving tomorrow';
  const d = parseDay(p.expected);
  return n < 7
    ? `Arriving ${d.toLocaleDateString([], { weekday: 'long' })}`
    : `Arriving ${d.toLocaleDateString([], { day: 'numeric', month: 'short' })}`;
}

export function isLate(p, now = new Date()) {
  if (p.status === 'delivered' || p.status === 'ready_for_pickup') return false;
  if (p.status === 'out_for_delivery') return !outToday(p, now);
  const n = daysUntil(p.expected, now);
  return n !== null && n < 0;
}

export function arrivingToday(active, now = new Date()) {
  return active.filter((p) => outToday(p, now) || (p.status !== 'out_for_delivery' && daysUntil(p.expected, now) === 0));
}

// Ledger line for the page header and the Inbox subtitle.
export function packageSummary(active, now = new Date(), { short = false } = {}) {
  const today = arrivingToday(active, now).length;
  const pickup = active.filter((p) => p.status === 'ready_for_pickup').length;
  const parts = [];
  if (today) parts.push(short ? `${today} ${today === 1 ? 'parcel' : 'parcels'} today` : `${today} ${today === 1 ? 'package' : 'packages'} arriving today`);
  if (pickup) parts.push(short ? `${pickup} to collect` : `${pickup} to pick up`);
  return parts;
}

export const STEPS = ['Label created', 'On the way', 'Nearly there', 'Delivered'];

// Groups of four so a number can be read out or typed by hand.
export function groupNumber(n) {
  n = n || '';
  const s10 = /^([A-Z]{2})(\d{9})([A-Z]{2})$/.exec(n); // postal: RR 123 456 785 SE
  if (s10) return `${s10[1]} ${s10[2].replace(/(\d{3})(?=\d)/g, '$1 ')} ${s10[3]}`;
  return n.replace(/(.{4})(?=.)/g, '$1 ');
}
