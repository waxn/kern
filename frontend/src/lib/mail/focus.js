// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Modal focus handling: keep Tab inside the dialog, focus something sensible
// on open, and put focus back where it was on close.

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

export function trapFocus(node) {
  const previous = document.activeElement;

  function focusables() {
    return [...node.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
  }

  queueMicrotask(() => {
    if (node.contains(document.activeElement)) return;
    const preferred = node.querySelector('[autofocus]') || node.querySelector('input, textarea, select') || focusables()[0];
    (preferred || node).focus();
  });

  function onKey(e) {
    if (e.key !== 'Tab') return;
    const els = focusables();
    if (!els.length) {
      e.preventDefault();
      return;
    }
    const first = els[0];
    const last = els[els.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  node.addEventListener('keydown', onKey);
  return {
    destroy() {
      node.removeEventListener('keydown', onKey);
      if (previous && previous instanceof HTMLElement && document.contains(previous)) {
        previous.focus({ preventScroll: true });
      }
    },
  };
}
