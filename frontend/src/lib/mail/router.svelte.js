// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Mail's view of the URL, on top of SvelteKit routing (src/routes/mail/[...path]).
//   /mail/<view>[/t/<threadId>]   view: inbox | f<id> | starred | all | l<id> | search (?q=) | <role>
//   /mail/packages  /mail/scheduled  /mail/files  /mail/blocklist
// Settings live in Kern: /settings?s=mail.

import { goto } from '$app/navigation';

export const PAGES = ['packages', 'scheduled', 'files', 'blocklist', 'stats'];
export const route = $state({ page: 'mail', view: 'inbox', threadId: null, q: '' });

export function parse(pathname, search) {
  const parts = pathname.split('/').filter(Boolean);
  const q = new URLSearchParams(search).get('q') || '';
  if (parts[0] !== 'mail' || !parts[1]) return { page: 'mail', view: 'inbox', threadId: null, q: '' };
  if (PAGES.includes(parts[1])) return { page: parts[1], view: 'inbox', threadId: null, q: '' };
  const view = parts[1];
  const threadId = parts[2] === 't' && /^\d+$/.test(parts[3] || '') ? Number(parts[3]) : null;
  return { page: 'mail', view, threadId, q: view === 'search' ? q : '' };
}

export function href(r) {
  if (r.page === 'settings') return '/settings?s=mail';
  if (r.page && r.page !== 'mail') return '/mail/' + r.page;
  let p = '/mail/' + (r.view || 'inbox');
  if (r.threadId) p += '/t/' + r.threadId;
  if (r.view === 'search' && r.q) p += '?q=' + encodeURIComponent(r.q);
  return p;
}

/** Called by the mail page whenever SvelteKit's URL changes. */
export function sync(url) {
  Object.assign(route, parse(url.pathname, url.search));
}

export function navigate(next, { replace = false } = {}) {
  const merged = { ...route, ...next };
  if (merged.page !== 'mail') merged.threadId = null;
  const url = href(merged);
  if (url !== location.pathname + location.search) {
    goto(url, { replace, reset: false });
  }
  if (merged.page !== 'settings') Object.assign(route, parse(new URL(url, location.href).pathname, new URL(url, location.href).search));
}

// <a href> inside mail: SvelteKit already routes same-origin links; this keeps
// focus and scroll where they are (the list shouldn't jump to the top).
export function navLink(node) {
  const onClick = (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const url = new URL(node.href, location.href);
    if (url.origin !== location.origin) return;
    e.preventDefault();
    goto(url.pathname + url.search, { reset: false });
  };
  node.addEventListener('click', onClick);
  return { destroy: () => node.removeEventListener('click', onClick) };
}
