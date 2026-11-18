// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Whether this user can use mail right now (GET /api/mail/account/status, which
// answers even before two-factor). Shared by the mail page, Settings → Mail,
// Home and the sidebar badge.

/** @type {{ data: any, error: string }} */
export const mailStatus = $state({ data: null, error: '' });

export async function loadMailStatus() {
  try {
    const r = await fetch('/api/mail/account/status', { cache: 'no-store', credentials: 'same-origin' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    mailStatus.data = await r.json();
    mailStatus.error = '';
  } catch (e) {
    mailStatus.error = e instanceof Error ? e.message : String(e);
  }
  return mailStatus.data;
}

/** Mail is usable in this browser: two-factor passed and an account connected. */
export function mailReady() {
  const s = mailStatus.data;
  return !!(s && s.two_factor?.enabled && s.two_factor?.session_verified && (s.connected || s.account?.address));
}
