// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { inverseOf } from './undo.js';

const roles = { inbox: 1, archive: 2, trash: 3, junk: 4 };

describe('undo', () => {
  it('puts archived and trashed mail back where it came from', () => {
    expect(inverseOf([9], 'archive', 1, {}, roles)).toEqual({ ids: [9], action: 'move', context: 2, dest: 1 });
    expect(inverseOf([9], 'trash', 7, {}, roles)).toEqual({ ids: [9], action: 'move', context: 3, dest: 7 });
    // From a virtual view (Starred, search) "back" means the Inbox.
    expect(inverseOf([9], 'archive', null, {}, roles).dest).toBe(1);
  });
  it('reverses moves, spam, snooze, labels and unread', () => {
    expect(inverseOf([9], 'move', 1, { dest: 5 }, roles)).toEqual({ ids: [9], action: 'move', context: 5, dest: 1 });
    expect(inverseOf([9], 'spam', 1, {}, roles).action).toBe('not_spam');
    expect(inverseOf([9], 'snooze', 1, { until: 'x' }, roles)).toEqual({ ids: [9], action: 'unsnooze' });
    expect(inverseOf([9], 'label_add', 1, { label: 3 }, roles)).toEqual({ ids: [9], action: 'label_remove', label: 3 });
    expect(inverseOf([9], 'unread', 1, {}, roles).action).toBe('read');
    expect(inverseOf([9], 'mute', 1, {}, roles).action).toBe('unmute');
  });
  it('has no undo for permanent deletion', () => {
    expect(inverseOf([9], 'delete_forever', 3, {}, roles)).toBe(null);
  });
});

