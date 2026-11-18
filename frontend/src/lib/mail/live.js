// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Live updates: polls /api/mail/changes (Kern serves threaded WSGI, so no
// held-open event stream). Every 4 s while the page is visible, 30 s when hidden.

import { api } from './api.svelte.js';
import { loadInfo, net, prefs, scheduleRefresh, syncProgress, toast } from './state.svelte.js';

const PACKAGE_NEWS = {
  out_for_delivery: 'A package is out for delivery.',
  delivered: 'A package was delivered.',
  ready_for_pickup: 'A package is ready to pick up.',
  exception: 'A package needs attention. Check with the carrier.',
};
import { navigate, route } from './router.svelte.js';

let timer = null;
let infoTimer = null;
let last = null;
let running = false;
let failures = 0;

function notify(kind, data) {
  const pkg = kind === 'package' && PACKAGE_NEWS[data.status];
  if (!((kind === 'message' && data.new) || kind === 'snooze_wake' || kind === 'nudge' || pkg)) return;
  if (!prefs.notifications || !('Notification' in window) || Notification.permission !== 'granted') return;
  if (document.visibilityState === 'visible') return;
  try {
    // Deliberately generic: no sender or subject on the lock screen.
    const n = pkg
      ? new Notification('Package update', { body: pkg, tag: 'kern-mail-package' })
      : kind === 'nudge'
      ? new Notification('No reply yet', { body: 'A conversation you were waiting on has had no reply.', tag: 'kern-mail-nudge' })
      : kind === 'snooze_wake'
      ? new Notification('Snoozed mail is back', { body: 'A conversation you snoozed is back in your Inbox.', tag: 'kern-mail-snooze' })
      : new Notification('New mail', { body: 'You have new mail in Kern.', tag: 'kern-mail-new', silent: false });
    n.onclick = () => window.focus();
  } catch {
    /* notifications unavailable */
  }
}

function handle(data) {
    const kind = data.kind;
    if (kind === 'sync_progress' && data.folder) {
      syncProgress[data.folder] = { done: data.done, total: data.total };
    }
    if (kind === 'folder_synced' && data.folder) delete syncProgress[data.folder];
    if (kind === 'op_failed') {
      toast("A change couldn't be saved to your mail server, so it was undone.", {
        kind: 'error',
        timeout: 12000,
        action: { label: 'Review', run: () => navigate({ page: 'settings' }) },
      });
    }
    if (kind === 'nudge') {
      toast('Nobody has replied yet. Time to follow up?', {
        timeout: 12000,
        action: data.thread ? { label: 'Open', run: () => navigate({ page: 'mail', view: 'all', threadId: data.thread }) } : null,
      });
    }
    if (kind === 'snooze_wake' && data.thread) {
      toast(data.reason === 'reply' ? 'New reply in a snoozed conversation. It\'s back in your Inbox.' : 'A snoozed conversation is back in your Inbox.', {
        timeout: 12000,
        action: { label: 'Open', run: () => navigate({ page: 'mail', view: 'inbox', threadId: data.thread }) },
      });
    }
    if (kind === 'package' && PACKAGE_NEWS[data.status]) {
      toast(PACKAGE_NEWS[data.status], {
        kind: data.status === 'exception' ? 'error' : 'info',
        timeout: 10000,
        action: { label: 'Packages', run: () => navigate({ page: 'packages' }) },
      });
    }
    if (kind === 'draft' && data.status === 'sent' && data.scheduled) {
      toast('Your scheduled message was sent.', { timeout: 6000 });
    }
    if (kind === 'draft' && data.status === 'failed') {
      toast('Sending failed. Your message is back in Drafts.', { kind: 'error', timeout: 10000 });
    }
    const touchesThread = route.threadId && (data.thread === route.threadId || (data.threads || []).includes(route.threadId));
    scheduleRefresh({ thread: touchesThread || kind === 'sent' });
    notify(kind, data);
}


async function poll() {
  if (!running) return;
  try {
    const r = await api.get('/changes', last === null ? {} : { since: last });
    if (failures && !net.live) scheduleRefresh({ thread: true }); // catch up after a gap
    failures = 0;
    net.live = true;
    if (r.reset) scheduleRefresh({ thread: true });
    const first = last === null;
    last = r.last;
    if (!first) for (const e of r.events) handle(e);
    if (r.more) {
      timer = setTimeout(poll, 50);
      return;
    }
  } catch {
    failures += 1;
    if (failures >= 2) net.live = false;
  }
  timer = setTimeout(poll, document.visibilityState === 'visible' ? 4000 : 30000);
}

function onVisible() {
  if (document.visibilityState === 'visible' && running) {
    clearTimeout(timer);
    poll();
  }
}

export function startLive() {
  stopLive();
  running = true;
  last = null;
  poll();
  document.addEventListener('visibilitychange', onVisible);
  infoTimer = setInterval(() => loadInfo().catch(() => {}), 30000);
}

export function stopLive() {
  running = false;
  clearTimeout(timer);
  clearInterval(infoTimer);
  document.removeEventListener('visibilitychange', onVisible);
}

// The tab title is set by the mail page (<svelte:head>); Kern keeps its own icon.
export function updateTitle() {}
