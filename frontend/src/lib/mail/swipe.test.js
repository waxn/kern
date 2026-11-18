// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { swipe } from './swipe.js';

function pointer(type, x, y, pointerType = 'touch') {
  const e = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(e, 'pointerType', { value: pointerType });
  Object.defineProperty(e, 'pointerId', { value: 1 });
  return e;
}

function setup(opts) {
  const wrap = document.createElement('div');
  const row = document.createElement('div');
  Object.defineProperty(row, 'offsetWidth', { value: 300 });
  wrap.append(row);
  document.body.append(wrap);
  const action = swipe(row, opts);
  return { wrap, row, action };
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('swipe', () => {
  it('swiping right past the threshold archives', () => {
    vi.useFakeTimers();
    const onRight = vi.fn();
    const onLeft = vi.fn();
    const { row, wrap } = setup({ onRight, onLeft });
    row.dispatchEvent(pointer('pointerdown', 10, 100));
    row.dispatchEvent(pointer('pointermove', 60, 102));
    expect(wrap.dataset.swipe).toBe('right');
    row.dispatchEvent(pointer('pointermove', 160, 103));
    expect(wrap.dataset.armed).toBe('1');
    row.dispatchEvent(pointer('pointerup', 160, 103));
    vi.runAllTimers();
    expect(onRight).toHaveBeenCalledOnce();
    expect(onLeft).not.toHaveBeenCalled();
    expect(row.style.transform).toBe('');
  });

  it('a short swipe snaps back without acting', () => {
    const onRight = vi.fn();
    const { row } = setup({ onRight });
    row.dispatchEvent(pointer('pointerdown', 10, 100));
    row.dispatchEvent(pointer('pointermove', 50, 100));
    row.dispatchEvent(pointer('pointerup', 50, 100));
    expect(onRight).not.toHaveBeenCalled();
  });

  it('vertical scrolling is left alone', () => {
    const onLeft = vi.fn();
    const { row, wrap } = setup({ onLeft });
    row.dispatchEvent(pointer('pointerdown', 200, 100));
    row.dispatchEvent(pointer('pointermove', 190, 200));
    row.dispatchEvent(pointer('pointermove', 60, 300));
    row.dispatchEvent(pointer('pointerup', 60, 300));
    expect(onLeft).not.toHaveBeenCalled();
    expect(wrap.dataset.swipe || '').toBe('');
  });

  it('ignores the mouse', () => {
    const onRight = vi.fn();
    const { row } = setup({ onRight });
    row.dispatchEvent(pointer('pointerdown', 10, 100, 'mouse'));
    row.dispatchEvent(pointer('pointermove', 200, 100, 'mouse'));
    row.dispatchEvent(pointer('pointerup', 200, 100, 'mouse'));
    expect(onRight).not.toHaveBeenCalled();
  });

  it('swiping left past the threshold snoozes', () => {
    vi.useFakeTimers();
    const onLeft = vi.fn();
    const { row } = setup({ onLeft });
    row.dispatchEvent(pointer('pointerdown', 250, 100));
    row.dispatchEvent(pointer('pointermove', 200, 100));
    row.dispatchEvent(pointer('pointermove', 100, 101));
    row.dispatchEvent(pointer('pointerup', 100, 101));
    vi.runAllTimers();
    expect(onLeft).toHaveBeenCalledOnce();
  });
});
