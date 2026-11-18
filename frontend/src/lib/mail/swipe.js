// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Touch swipe on list rows: drag right past the threshold -> onRight, left ->
// onLeft. Vertical scrolling is left alone (rows use touch-action: pan-y).

const THRESHOLD = 90;

export function swipe(node, opts) {
  let o = opts;
  let x0 = 0;
  let y0 = 0;
  let dx = 0;
  let tracking = false;
  let horizontal = null;

  function set(x, animate) {
    node.style.transition = animate ? 'transform .22s cubic-bezier(.2,.7,.2,1)' : 'none';
    node.style.transform = x ? `translateX(${x}px)` : '';
    const wrap = node.parentElement;
    if (wrap) {
      wrap.dataset.swipe = x > 0 ? 'right' : x < 0 ? 'left' : '';
      wrap.dataset.armed = Math.abs(x) > THRESHOLD ? '1' : '';
    }
  }

  function down(e) {
    if (e.pointerType !== 'touch') return;
    tracking = true;
    horizontal = null;
    x0 = e.clientX;
    y0 = e.clientY;
    dx = 0;
  }
  function move(e) {
    if (!tracking) return;
    const mx = e.clientX - x0;
    const my = e.clientY - y0;
    if (horizontal === null && (Math.abs(mx) > 8 || Math.abs(my) > 8)) {
      horizontal = Math.abs(mx) > Math.abs(my) * 1.4;
      if (horizontal) node.setPointerCapture?.(e.pointerId);
    }
    if (!horizontal) return;
    dx = mx;
    set(dx * 0.9, false);
  }
  function up() {
    if (!tracking) return;
    tracking = false;
    if (horizontal && Math.abs(dx) > THRESHOLD) {
      const dir = dx > 0 ? 'right' : 'left';
      set(dir === 'right' ? node.offsetWidth : -node.offsetWidth, true);
      setTimeout(() => {
        (dir === 'right' ? o.onRight : o.onLeft)?.();
        set(0, false);
      }, 180);
    } else {
      set(0, true);
    }
  }
  function click(e) {
    // Swallow the click that ends a swipe.
    if (horizontal && Math.abs(dx) > 8) {
      e.preventDefault();
      e.stopPropagation();
    }
  }

  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', up);
  node.addEventListener('click', click, true);
  return {
    update(next) {
      o = next;
    },
    destroy() {
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', up);
      node.removeEventListener('click', click, true);
    },
  };
}
