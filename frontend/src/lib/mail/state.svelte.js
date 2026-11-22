// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Application state (Svelte 5 runes) and the actions that change it.

import { api, ApiError } from './api.svelte.js';
import { ui as kernUi } from '#lib/state/ui.svelte.ts';
import { route, navigate } from './router.svelte.js';
import { inverseOf as undoInverse } from './undo.js';

export const info = $state({ address: '', fromName: '', undoSeconds: 8, worker: { state: 'offline' }, pendingOps: 0, failedOps: 0, maxAttachmentBytes: 0 });
export const mailbox = $state({ folders: [], labels: [], starred: 0, loaded: false });
// selectedAll: every conversation in the view is selected, not only the loaded ones.
export const list = $state({ key: '', threads: [], next: null, loading: false, error: '', selected: new Set(), selectedAll: false, focusIndex: -1, unreadOnly: false, checkedAt: 0 });
export const current = $state({ thread: null, messages: [], packages: [], scheduled: [], tasks: [], loading: false, error: '' });
// First-sync progress per folder id: {done, total}. Fed by SSE events.
export const syncProgress = $state({});

// Connection health: browser online state and the live-update stream.
export const net = $state({ online: typeof navigator === 'undefined' ? true : navigator.onLine, live: true });
if (typeof window !== 'undefined') {
  addEventListener('online', () => (net.online = true));
  addEventListener('offline', () => (net.online = false));
}

// Preferences stored on the server (shared by all your devices).
export const account = $state({
  from_name: '', signature: '', signature_on_replies: true, undo_seconds: null,
  after_action: 'next', mark_read: 'open', loaded: false,
});

export async function loadAccountPrefs() {
  try {
    Object.assign(account, await api.get('/preferences'), { loaded: true });
  } catch {
    /* defaults */
  }
}

export async function saveAccountPrefs(changes) {
  const data = await api.patch('/preferences', changes);
  Object.assign(account, data);
  loadInfo().catch(() => {});
  return data;
}

// Things scheduled to come back to you: snoozes and "nudge if no reply".
export const agenda = $state({ snoozes: [], followups: [], loaded: false });
// Shipments found in shipping emails (mail/packages.py on the server).
export const parcels = $state({ active: [], delivered: [], loaded: false });
// Messages waiting to be sent later ("send later").
export const scheduled = $state({ items: [], loaded: false });
export const ui = $state({
  sidebarOpen: false,
  composers: [],
  dialog: null, // {type: 'spam'|'move'|'label'|'help'|'snooze'|'prompt'|'confirm', ...}
  searchFocusTick: 0,
  senderCard: null, // {addr, name, x, y}
  viewer: null, // {items: [{src, href, name, size}], index}
});

// Side-by-side list + conversation only when both get enough room.
export const READING_MIN = 960; // of the mail area (Kern's sidebar is outside it)

// Per-browser mail settings (Settings → Mail → This browser). Looks come from Kern.
const SETTINGS_KEY = 'kern:mail.v1';
function loadSettings() {
  try {
    return { notifications: false, readingPane: true, darkEmails: true, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
  } catch {
    return { notifications: false, readingPane: true, darkEmails: true };
  }
}
export const prefs = $state(loadSettings());
export function savePrefs() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify($state.snapshot(prefs)));
  } catch {
    /* storage unavailable: settings last for this visit only */
  }
}

// --- toasts: Kern's (#lib/state/ui) so mail and the rest of Kern share one stack ---
export function toast(message, opts = {}) {
  return kernUi.toast(message, { kind: opts.kind || 'info', action: opts.action || undefined, timeout: opts.timeout ?? 5000 });
}
export function dismissToast(id) {
  kernUi.dismiss(id);
}
export function updateToast(id, patch) {
  kernUi.update(id, patch);
}
export function errorToast(e) {
  toast(e instanceof ApiError || e instanceof Error ? e.message : String(e), { kind: 'error', timeout: 7000 });
}

export function resetMail() {
  dropMailCache();
  mailbox.folders = [];
  mailbox.loaded = false;
  list.threads = [];
  list.key = '';
  current.thread = null;
  current.messages = [];
}

// --- mailbox ----------------------------------------------------------------
export async function loadInfo() {
  Object.assign(info, await api.get('/info'));
}

export async function loadAgenda() {
  try {
    const [snoozes, followups] = await Promise.all([api.get('/snoozes'), api.get('/followups')]);
    agenda.snoozes = snoozes;
    agenda.followups = followups;
    agenda.loaded = true;
  } catch {
    /* non-essential */
  }
}

export async function loadScheduled() {
  try {
    scheduled.items = await api.get('/scheduled');
    scheduled.loaded = true;
  } catch {
    /* non-essential */
  }
}

export async function loadPackages() {
  try {
    const r = await api.get('/packages');
    parcels.active = r.active;
    parcels.delivered = r.delivered;
    parcels.loaded = true;
  } catch {
    /* non-essential */
  }
}

export async function packageAction(p, action) {
  const r = await api.post(`/packages/${p.id}`, { action });
  await loadPackages();
  if (current.packages.some((x) => x.id === p.id)) {
    current.packages = r.hidden ? current.packages.filter((x) => x.id !== p.id) : current.packages.map((x) => (x.id === p.id ? r : x));
  }
  return r;
}

// "Cleared today" counter for the inbox-zero moment (per browser).
function clearedKey() {
  const d = new Date();
  return `kern:mail.cleared.${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}
export function clearedToday() {
  try {
    return Number(localStorage.getItem(clearedKey()) || 0);
  } catch {
    return 0;
  }
}
function bumpCleared(n) {
  try {
    localStorage.setItem(clearedKey(), String(clearedToday() + n));
  } catch {
    /* ignore */
  }
}

// --- instant start: the last folder list and first page of each view are kept
// on this device (cleared on sign-out with every other kern* key) and shown at
// once, then refreshed from the server.
const CACHE = 'kern:mail.cache.';
const CACHE_VIEWS = 8;
const memo = new Map();
function readCache(key) {
  if (memo.has(key)) return memo.get(key);
  try {
    const v = JSON.parse(localStorage.getItem(CACHE + key) || 'null');
    if (v && v.v === 1) {
      memo.set(key, v);
      return v;
    }
  } catch {
    /* unavailable or corrupt */
  }
  return null;
}
function writeCache(key, data) {
  const v = { v: 1, at: Date.now(), ...data };
  memo.set(key, v);
  try {
    localStorage.setItem(CACHE + key, JSON.stringify(v));
    const views = Object.keys(localStorage).filter((k) => k.startsWith(CACHE + 'view:'));
    if (views.length > CACHE_VIEWS) {
      views.map((k) => [k, JSON.parse(localStorage.getItem(k) || '{}').at || 0]).sort((a, b) => a[1] - b[1])
        .slice(0, views.length - CACHE_VIEWS).forEach(([k]) => localStorage.removeItem(k));
    }
  } catch {
    /* storage full or unavailable: the in-memory copy still helps */
  }
}
export function dropMailCache() {
  memo.clear();
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith(CACHE)) localStorage.removeItem(k);
  } catch {
    /* ignore */
  }
}

function applyFolders(data) {
  mailbox.folders = data.folders;
  mailbox.labels = data.labels;
  mailbox.starred = data.starred;
  mailbox.loaded = true;
}
if (typeof window !== 'undefined') {
  const f = readCache('folders');
  if (f) applyFolders(f);
}

export async function loadFolders() {
  const data = await api.get('/folders');
  applyFolders(data);
  writeCache('folders', { folders: data.folders, labels: data.labels, starred: data.starred });
}

export function folderByRole(role) {
  return mailbox.folders.find((f) => f.role === role);
}

export function folderById(id) {
  return mailbox.folders.find((f) => f.id === id);
}

export function labelById(id) {
  return mailbox.labels.find((l) => l.id === id);
}

// Folder roles the server resolves itself (?view=inbox), so the list can load
// before (or without) the folder list.
const ROLE_VIEWS = new Set(['inbox', 'snoozed', 'drafts', 'sent', 'archive', 'junk', 'trash']);

// The view to ask /threads for: a role name when it is one, else the folder/label id.
export function listView(view = route.view) {
  if (ROLE_VIEWS.has(view)) return view;
  return apiView(view);
}

// Resolve the route's view key ("inbox", "f12", "starred", ...) for the API.
export function apiView(view = route.view) {
  if (view === 'starred' || view === 'all') return view;
  if (/^f\d+$/.test(view)) return 'folder:' + view.slice(1);
  if (/^l\d+$/.test(view)) return 'label:' + view.slice(1);
  const f = folderByRole(view);
  return f ? 'folder:' + f.id : null;
}

// Folder that actions apply to ("context"), or null for virtual views.
export function contextFolder(view = route.view) {
  const v = apiView(view);
  return v && v.startsWith('folder:') ? Number(v.slice(7)) : null;
}

export function viewTitle(view = route.view) {
  if (view === 'search') return route.q ? `Search: ${route.q}` : 'Search';
  if (view === 'starred') return 'Starred';
  if (view === 'all') return 'All mail';
  if (/^l\d+$/.test(view)) return labelById(Number(view.slice(1)))?.name || 'Label';
  const fid = contextFolder(view);
  return folderById(fid)?.displayName || (view[0]?.toUpperCase() + view.slice(1));
}

function listKey() {
  return route.view === 'search' ? 'search:' + route.q : 'view:' + route.view + (list.unreadOnly ? ':unread' : '');
}

let listSeq = 0;
export async function loadThreads({ more = false, quiet = false } = {}) {
  const key = listKey();
  const view = route.view === 'search' ? null : listView();
  if (route.view !== 'search' && !view) return;
  const seq = ++listSeq;
  if (!more && key !== list.key && route.view !== 'search') {
    // Show what this device saw last time right away; the server answer replaces it.
    const cached = readCache(key);
    if (cached) {
      list.threads = cached.threads;
      list.next = cached.next;
      list.key = key;
      list.selected = new Set();
      list.selectedAll = false;
      list.focusIndex = -1;
      quiet = true;
    }
  }
  if (!quiet) list.loading = true;
  list.error = '';
  try {
    const params = route.view === 'search' ? { q: route.q } : { view, unread: list.unreadOnly ? 1 : undefined };
    if (more && list.next) params.cursor = list.next;
    const data = await api.get('/threads', params);
    if (seq !== listSeq) return;
    if (more) {
      const seen = new Set(list.threads.map((t) => t.id));
      list.threads.push(...data.threads.filter((t) => !seen.has(t.id)));
    } else {
      if (key !== list.key) {
        list.selected = new Set();
        list.selectedAll = false;
        list.focusIndex = -1;
      }
      if (route.view !== 'search') writeCache(key, { threads: data.threads, next: data.next });
      // Quiet refresh keeps already-loaded extra pages (only when the fresh
      // first page isn't the whole list; otherwise it is the truth).
      if (quiet && key === list.key && data.next && list.threads.length > data.threads.length) {
        const fresh = new Map(data.threads.map((t) => [t.id, t]));
        const tail = list.threads.slice(data.threads.length).filter((t) => !fresh.has(t.id));
        list.threads = [...data.threads, ...tail];
      } else {
        list.threads = data.threads;
        list.next = data.next;
      }
      list.key = key;
    }
    if (more) list.next = data.next;
  } catch (e) {
    if (seq === listSeq) list.error = e.message;
  } finally {
    if (seq === listSeq) list.loading = false;
  }
}

let threadSeq = 0;
export async function loadThread(id, { quiet = false } = {}) {
  const seq = ++threadSeq;
  if (!quiet) {
    current.loading = true;
    current.error = '';
  }
  try {
    const data = await api.get(`/threads/${id}`);
    if (seq !== threadSeq) return;
    current.thread = data.thread;
    current.messages = data.messages;
    current.packages = data.packages || [];
    current.scheduled = data.scheduled || [];
    current.tasks = data.tasks || [];
    if (!quiet && data.thread.unread > 0 && account.mark_read !== 'manual') {
      if (account.mark_read === 'delay') {
        setTimeout(() => {
          if (route.threadId === id) threadAction([id], 'read', { silent: true }).catch(() => {});
        }, 2000);
      } else {
        threadAction([id], 'read', { silent: true }).catch(() => {});
      }
    }
  } catch (e) {
    if (seq !== threadSeq) return;
    if (e.status === 404) {
      current.thread = null;
      if (route.threadId === id) navigate({ threadId: null }, { replace: true });
    } else current.error = e.message;
  } finally {
    if (seq === threadSeq) current.loading = false;
  }
}

// --- actions ----------------------------------------------------------------
const REMOVES_FROM_VIEW = new Set(['archive', 'trash', 'move', 'spam', 'not_spam', 'delete_forever', 'inbox', 'snooze', 'unsnooze', 'mute']);

function patchListLocal(ids, action) {
  const set = new Set(ids);
  for (const t of list.threads) {
    if (!set.has(t.id)) continue;
    if (action === 'read') t.unread = 0;
    if (action === 'unread') t.unread = Math.max(1, t.unread);
    if (action === 'star') t.starred = true;
    if (action === 'unstar') t.starred = false;
    if (action === 'mute') t.muted = true;
    if (action === 'unmute') t.muted = false;
  }
  if (current.thread && set.has(current.thread.id)) {
    if (action === 'star') current.thread.starred = true;
    if (action === 'unstar') current.thread.starred = false;
    if (action === 'mute') current.thread.muted = true;
    if (action === 'unmute') current.thread.muted = false;
  }
}

// "Select all N conversations in <view>": the server applies it to the whole view.
export async function viewAction(action) {
  const scope = route.view === 'search' ? { view: 'all', q: route.q } : { view: listView(), unread: list.unreadOnly };
  const ids = list.threads.map((t) => t.id);
  patchListLocal(ids, action);
  list.selected = new Set();
  list.selectedAll = false;
  try {
    const res = await api.post('/threads/actions', { all: scope, action, context: contextFolder() });
    const n = res.count === 1 ? '1 conversation' : `${(res.count || 0).toLocaleString()} conversations`;
    toast({ read: `Marked ${n} as read`, unread: `Marked ${n} as unread`, archive: `${n} archived`, trash: `${n} moved to Trash`,
      star: `Starred ${n}`, unstar: `Unstarred ${n}` }[action] || 'Done');
    loadFolders().catch(() => {});
    loadThreads({ quiet: true });
    return res;
  } catch (e) {
    errorToast(e);
    loadThreads({ quiet: true });
    throw e;
  }
}

// The refresh button: ask the server to check for new mail now, and reload.
// Resolves when the worker reports back (or after a few seconds).
let checkWaiters = [];
export function noteChecked() {
  list.checkedAt = Date.now();
  const w = checkWaiters;
  checkWaiters = [];
  w.forEach((f) => f());
}
export async function checkNow() {
  const folder = contextFolder();
  const done = new Promise((resolve) => {
    checkWaiters.push(resolve);
    setTimeout(resolve, info.worker?.state === 'idle' ? 6000 : 2500);
  });
  await Promise.all([
    api.post('/check', folder ? { folder } : {}).catch(() => {}),
    loadThreads({ quiet: true }),
    loadFolders().catch(() => {}),
  ]);
  await done;
  await loadThreads({ quiet: true });
}

export async function threadAction(ids, action, extra = {}) {
  const { silent, ...payload } = extra;
  ids = [...ids];
  if (!ids.length) throw new Error('Nothing selected.');
  const context = contextFolder();
  patchListLocal(ids, action);
  const removing = REMOVES_FROM_VIEW.has(action) && route.view !== 'search' && route.view !== 'all'
    && !(action === 'archive' && route.view === 'starred')
    && !(action === 'snooze' && route.view === 'snoozed')
    && !(action === 'unsnooze' && route.view !== 'snoozed')
    && !(action === 'mute' && route.view !== 'inbox');
  let snapshot = null;
  if (removing) {
    snapshot = list.threads.slice();
    const set = new Set(ids);
    const idx = list.threads.findIndex((t) => set.has(t.id));
    list.threads = list.threads.filter((t) => !set.has(t.id));
    list.selected = new Set([...list.selected].filter((x) => !set.has(x)));
    if (route.threadId && set.has(route.threadId)) {
      // Move on to the next conversation like Gmail (or back to the list).
      const next = list.threads[Math.min(idx, list.threads.length - 1)];
      const goNext = account.after_action !== 'list' && prefs.readingPane && innerWidth >= READING_MIN;
      navigate({ threadId: next && goNext ? next.id : null }, { replace: true });
    }
  }
  try {
    const res = await api.post('/threads/actions', { ids, action, context, ...payload });
    const undo = inverseOf(ids, action, context, payload);
    if (removing && route.view === 'inbox' && ['archive', 'trash', 'move', 'spam', 'snooze'].includes(action)) {
      bumpCleared(ids.length);
    }
    if (!silent) {
      const n = ids.length > 1 ? `${ids.length} conversations` : 'Conversation';
      const msg = {
        archive: `${n} archived`, trash: `${n} moved to Trash`, spam: `${n} reported as spam`,
        not_spam: `${n} moved to Inbox`, delete_forever: `${n} deleted forever`, move: `${n} moved`,
        inbox: `${n} moved to Inbox`, label_add: 'Label added', label_remove: 'Label removed',
        unread: 'Marked as unread', unsnooze: 'Back in your Inbox',
        mute: `${n} muted. New replies will skip your Inbox`, unmute: `${n} unmuted`,
      }[action];
      let extraMsg = '';
      if (res.blocked) extraMsg = ` · ${res.blocked.kind === 'domain' ? 'Domain' : 'Sender'} ${res.blocked.value} blocked`;
      if (res.unblocked && res.unblocked.length) extraMsg = ' · Block removed';
      if (msg) {
        toast(msg + extraMsg, undo ? {
          timeout: 7000,
          action: { label: 'Undo', run: () => runUndo(undo) },
        } : {});
      }
    }
    if (['snooze', 'unsnooze'].includes(action)) loadAgenda();
    loadFolders();
    if (route.threadId && ids.includes(route.threadId) && !removing) loadThread(route.threadId, { quiet: true });
    return res;
  } catch (e) {
    if (snapshot) list.threads = snapshot;
    errorToast(e);
    loadThreads({ quiet: true });
    throw e;
  }
}

function inverseOf(ids, action, context, payload) {
  const role = (r) => folderByRole(r)?.id;
  return undoInverse(ids, action, context, payload, {
    inbox: role('inbox'), archive: role('archive'), trash: role('trash'), junk: role('junk'),
  });
}

async function runUndo(u) {
  try {
    const { ids, action, ...rest } = u;
    await api.post('/threads/actions', { ids, action, ...rest });
    toast('Undone');
    loadThreads({ quiet: true });
    loadFolders();
    loadAgenda();
  } catch (e) {
    errorToast(e);
  }
}

export async function messageAction(ids, action) {
  try {
    await api.post('/messages/actions', { ids, action });
    if (route.threadId) loadThread(route.threadId, { quiet: true });
    loadThreads({ quiet: true });
    loadFolders();
  } catch (e) {
    errorToast(e);
  }
}

// --- live updates -----------------------------------------------------------
let refreshTimer = null;
export function scheduleRefresh({ thread = false } = {}) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    loadFolders().catch(() => {});
    loadAgenda();
    loadPackages();
    loadScheduled();
    if (route.page === 'mail') loadThreads({ quiet: true });
    if (thread && route.threadId) loadThread(route.threadId, { quiet: true });
  }, 400);
}

export function unreadInbox() {
  return folderByRole('inbox')?.unread || 0;
}
