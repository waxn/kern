// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Reply templates: what gets saved from a compose window, and where.

import { api } from './api.svelte.js';

export const templates = $state({ items: [], loaded: false });

export async function loadTemplates() {
  try {
    templates.items = await api.get('/templates');
    templates.loaded = true;
  } catch {
    /* non-essential */
  }
}

// The part of a message worth reusing: no quoted history, no "On … wrote:"
// line, no signature (the composer adds your current one).
const squash = (s) => (s || '').replace(/\s+/g, '');

export function templateBody(html, signature = '') {
  const sig = squash(`-- ${signature}`);
  const div = document.createElement('div');
  div.innerHTML = html || ''; // detached: nothing renders or loads
  div.querySelectorAll('blockquote').forEach((q) => q.remove());
  div.querySelectorAll('div, p').forEach((el) => {
    const t = (el.textContent || '').trim();
    // Only a block that is exactly your signature: text typed into it stays.
    if (/^On .+ wrote:$/s.test(t) || t === '--' || (signature && squash(t) === sig)) el.remove();
  });
  // Trailing empty paragraphs.
  let last = div.lastElementChild;
  while (last && !(last.textContent || '').trim() && !last.querySelector('img')) {
    last.remove();
    last = div.lastElementChild;
  }
  return div.innerHTML.trim();
}

// Where a template goes: at the caret, unless the caret is in or after the
// signature, or inside quoted history; then just above the signature (or
// above the "On … wrote:" line). Returns a collapsed Range.
export function insertPoint(editor, range) {
  const top = [...editor.children];
  const sig = top.find((el) => /^--(\s|$)/.test((el.textContent || '').trim()));
  const attribution = top.find((el) => /^On .+ wrote:$/s.test((el.textContent || '').trim()));
  const quote = editor.querySelector('blockquote');
  let anchor = sig || attribution || null;
  if (anchor && anchor.previousElementSibling && !(anchor.previousElementSibling.textContent || '').trim()) {
    anchor = anchor.previousElementSibling; // the blank line above the signature
  }
  const inside = (el) => el && range && (el === range.startContainer || el.contains(range.startContainer));
  const after = (el) => el && range && (el.compareDocumentPosition(range.startContainer) & Node.DOCUMENT_POSITION_FOLLOWING);
  const misplaced = !range || !editor.contains(range.startContainer) || inside(sig) || after(sig) || inside(quote) || inside(attribution);
  if (!misplaced) return range;
  const r = document.createRange();
  if (anchor) r.setStartBefore(anchor);
  else r.setStart(editor, 0);
  r.collapse(true);
  return r;
}

export function isEmptyBody(html) {
  const div = document.createElement('div');
  div.innerHTML = html || '';
  return !(div.textContent || '').trim();
}
