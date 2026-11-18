// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { bytes, initials, linkTokens, participantsLabel, quoteBlocks, relativeDue, shortDate } from './format.js';

describe('linkTokens', () => {
  it('splits URLs out of text without producing HTML', () => {
    const t = linkTokens('see https://x.example/a?b=1. and <b>bold</b>');
    expect(t).toEqual([
      { type: 'text', value: 'see ' },
      { type: 'link', value: 'https://x.example/a?b=1' },
      { type: 'text', value: '. and <b>bold</b>' },
    ]);
  });
  it('ignores javascript: and other schemes', () => {
    expect(linkTokens('javascript:alert(1)').every((t) => t.type === 'text')).toBe(true);
  });
});

describe('quoteBlocks', () => {
  it('groups quoted lines and attaches the "wrote:" line', () => {
    const b = quoteBlocks('Hi\nOn Mon, Alice wrote:\n> old\n> older\nBye');
    expect(b.map((x) => x.quoted)).toEqual([false, true, false]);
    expect(b[1].text).toContain('wrote:');
  });
});

describe('formatting', () => {
  it('formats sizes', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(2048)).toBe('2.0 KB');
    expect(bytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
  it('makes initials', () => {
    expect(initials({ name: 'Jörg Müller', addr: 'j@x' })).toBe('JM');
    expect(initials({ name: '', addr: 'alice@x' })).toBe('A');
  });
  it('labels participants without me', () => {
    const p = [{ name: 'Me', addr: 'me@x' }, { name: 'Alice Ex', addr: 'a@x' }];
    expect(participantsLabel(p, 'me@x')).toBe('Alice Ex');
    const mine = [{ name: 'Me', addr: 'me@x' }, { name: 'Bob B', addr: 'b@x', to: true }];
    expect(participantsLabel(mine, 'me@x')).toBe('To: Bob');
  });
  it('short dates', () => {
    const now = new Date(2026, 10, 17, 15, 0);
    expect(shortDate(new Date(2026, 10, 17, 9, 5).toISOString(), now)).toMatch(/9|09/);
    expect(shortDate(new Date(2026, 10, 16, 9, 5).toISOString(), now)).toBe('Yesterday');
  });
  it('relative due dates', () => {
    const now = new Date(2026, 10, 17, 12);
    expect(relativeDue('2026-11-17', now)).toBe('Today');
    expect(relativeDue('2026-11-18', now)).toBe('Tomorrow');
    expect(relativeDue('2026-11-14', now)).toBe('3 days overdue');
  });
});

import { snoozeLabel, snoozePresets } from './format.js';

describe('snooze helpers', () => {
  it('builds sensible presets on a Wednesday morning', () => {
    const now = new Date(2026, 10, 18, 9, 30); // Wed
    const p = Object.fromEntries(snoozePresets(now).map((x) => [x.id, x.at]));
    expect(p.later.getHours()).toBe(12);
    expect(p.evening.getHours()).toBe(18);
    expect(p.tomorrow.getDate()).toBe(19);
    expect(p.weekend.getDay()).toBe(6);
    expect(p.nextweek.getDay()).toBe(1);
    expect(p.nextweek > now).toBe(true);
  });
  it('skips "this weekend" on Saturday and "later" late at night', () => {
    const p = snoozePresets(new Date(2026, 10, 21, 22, 0)).map((x) => x.id); // Sat 22:00
    expect(p).not.toContain('weekend');
    expect(p).not.toContain('later');
    expect(p).toContain('nextweek');
  });
  it('labels times', () => {
    const now = new Date(2026, 10, 18, 9, 0);
    expect(snoozeLabel(new Date(2026, 10, 19, 8, 0).toISOString(), now)).toMatch(/^Tomorrow/);
  });
});

import { timeGroup } from './format.js';

describe('timeGroup', () => {
  const now = new Date(2026, 10, 18, 12);
  it('groups by recency', () => {
    expect(timeGroup(new Date(2026, 10, 18, 8).toISOString(), now)).toBe('Today');
    expect(timeGroup(new Date(2026, 10, 17, 23).toISOString(), now)).toBe('Yesterday');
    expect(timeGroup(new Date(2026, 10, 14).toISOString(), now)).toBe('Earlier this week');
    expect(timeGroup(new Date(2026, 10, 8).toISOString(), now)).toBe('Last week');
    expect(timeGroup(new Date(2026, 9, 2).toISOString(), now)).toMatch(/Oct/);
    expect(timeGroup(new Date(2025, 2, 2).toISOString(), now)).toBe('2025');
  });
});

import { highlight, searchWords } from './format.js';

describe('search highlighting', () => {
  it('extracts free-text words', () => {
    expect(searchWords('from:alice lisbon "tram 28" -spam is:unread')).toEqual(['lisbon', 'tram 28']);
  });
  it('splits text into hits without HTML', () => {
    expect(highlight('Lisbon is lovely, LISBON!', ['lisbon'])).toEqual([
      { text: 'Lisbon', hit: true }, { text: ' is lovely, ', hit: false }, { text: 'LISBON', hit: true }, { text: '!', hit: false },
    ]);
    expect(highlight('<b>x</b>', ['b'])[0].text).toBe('<');
    expect(highlight('a (b)', ['(b)'])[1]).toEqual({ text: '(b)', hit: true });
  });
});

describe('schedulePresets', () => {
  it('offers working-day mornings', async () => {
    const { schedulePresets } = await import('./format.js');
    const fri = schedulePresets(new Date(2026, 10, 20, 15, 0)); // Fri 15:00
    expect(fri.map((p) => p.id)).toEqual(['evening', 'morning', 'afternoon', 'monday']);
    expect(fri.find((p) => p.id === 'monday').at).toEqual(new Date(2026, 10, 23, 8, 0));
    const sun = schedulePresets(new Date(2026, 10, 22, 20, 0)); // Sun evening: tomorrow is Monday
    expect(sun.map((p) => p.id)).toEqual(['morning', 'afternoon']);
  });
});
