// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Mail at a glance for the rest of Kern: the sidebar badge and Home.
// GET /api/mail/today (only once mail is usable in this browser).

import { loadMailStatus, mailReady, mailStatus } from './status.svelte.js';

/** @type {{ data: any, loading: boolean }} */
export const mailToday = $state({ data: null, loading: false });
let timer = null;
let users = 0;

export async function refreshMailToday() {
  if (!mailStatus.data) await loadMailStatus();
  if (!mailReady()) {
    mailToday.data = null;
    return null;
  }
  mailToday.loading = true;
  try {
    const r = await fetch('/api/mail/today', { cache: 'no-store', credentials: 'same-origin' });
    mailToday.data = r.ok ? await r.json() : null;
  } catch {
    /* offline: keep the last numbers */
  } finally {
    mailToday.loading = false;
  }
  return mailToday.data;
}

/** Keep the numbers fresh while something shows them (refcounted). */
export function watchMailToday() {
  users += 1;
  if (users === 1) {
    refreshMailToday();
    timer = setInterval(() => document.visibilityState === 'visible' && refreshMailToday(), 60000);
    addEventListener('focus', refreshMailToday);
  }
  return () => {
    users -= 1;
    if (users === 0) {
      clearInterval(timer);
      removeEventListener('focus', refreshMailToday);
    }
  };
}
