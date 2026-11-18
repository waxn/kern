// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Formatting helpers (dates, sizes, names) and safe text tokenizing.

const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export function shortDate(iso, now = new Date()) {
  if (!iso) return '';
  const d = new Date(iso);
  if (sameDay(d, now)) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, yesterday)) return 'Yesterday';
  if (now - d < 6 * 86400000 && d < now) return d.toLocaleDateString([], { weekday: 'short' });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  return d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}

export function longDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString([], {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function relativeDue(isoDate, now = new Date()) {
  if (!isoDate) return '';
  const [y, m, d] = isoDate.split('-').map(Number);
  const due = new Date(y, m - 1, d);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((due - today) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days === -1) return 'Yesterday';
  if (days < 0) return `${-days} days overdue`;
  if (days < 7) return due.toLocaleDateString([], { weekday: 'long' });
  return due.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export function bytes(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function displayName(p) {
  if (!p) return '';
  if (p.name) return p.name;
  return p.addr ? p.addr.split('@')[0] : '';
}

export function firstName(p) {
  const n = displayName(p);
  return n.split(/[\s,]+/)[0] || n;
}

export function initials(p) {
  const n = displayName(p).replace(/[^\p{L}\p{N}\s]/gu, '').trim();
  if (!n) return '?';
  const parts = n.split(/\s+/);
  return ((parts[0][0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

// Deterministic, calm avatar hue from an address.
export function hue(addr = '') {
  let h = 0;
  for (const ch of addr) h = (h * 31 + ch.codePointAt(0)) % 360;
  return h;
}

export function participantsLabel(participants, me) {
  const all = participants || [];
  const senders = all.filter((p) => !p.to && p.addr !== me);
  if (!senders.length) {
    const to = all.filter((p) => p.to);
    if (to.length) return 'To: ' + to.slice(0, 3).map((p) => firstName(p)).join(', ') + (to.length > 3 ? '…' : '');
  }
  const list = senders.length ? senders : all.filter((p) => !p.to);
  if (!list.length) return '(no sender)';
  if (list.length === 1) return displayName(list[0]);
  const a = list[0];
  const b = list[list.length - 1];
  // Use full names when first names alone would be ambiguous.
  const short = firstName(a) !== firstName(b);
  const na = short ? firstName(a) : displayName(a);
  const nb = short ? firstName(b) : displayName(b);
  if (list.length === 2) return `${na}, ${nb}`;
  return `${na} … ${nb}`;
}

const URL_RE = /(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]])/gi;

// Split plain text into [{type:'text'|'link', value}] tokens. Rendered with
// normal Svelte text/attributes, so nothing is ever injected as HTML.
export function linkTokens(text) {
  const out = [];
  let last = 0;
  for (const m of (text || '').matchAll(URL_RE)) {
    if (m.index > last) out.push({ type: 'text', value: text.slice(last, m.index) });
    out.push({ type: 'link', value: m[1] });
    last = m.index + m[1].length;
  }
  if (last < (text || '').length) out.push({ type: 'text', value: text.slice(last) });
  return out;
}

// Group plain-text lines into normal and quoted ("> ...") blocks.
export function quoteBlocks(text) {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  for (const line of lines) {
    const quoted = /^\s*>/.test(line);
    const last = blocks[blocks.length - 1];
    if (last && last.quoted === quoted) last.lines.push(line);
    else blocks.push({ quoted, lines: [line] });
  }
  // Signature-ish trailing "On ... wrote:" line joins the quote below it.
  for (let i = 0; i < blocks.length - 1; i++) {
    const b = blocks[i];
    if (!b.quoted && blocks[i + 1].quoted) {
      const tail = b.lines[b.lines.length - 1];
      if (/wrote:\s*$/i.test(tail)) {
        b.lines.pop();
        blocks[i + 1].lines.unshift(tail);
      }
    }
  }
  return blocks.map((b) => ({ quoted: b.quoted, text: b.lines.join('\n') }));
}

// "Tomorrow 08:00", "Sat 09:00", "12 Dec 08:00" for snooze times.
export function snoozeLabel(iso, now = new Date()) {
  if (!iso) return '';
  const d = new Date(iso);
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((day - today) / 86400000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Tomorrow ${time}`;
  if (days > 1 && days < 7) return `${d.toLocaleDateString([], { weekday: 'short' })} ${time}`;
  return `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${time}`;
}

// Snooze presets in local time. Each: {id, label, at: Date}.
export function snoozePresets(now = new Date()) {
  const at = (days, hour) => {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, hour, 0, 0, 0);
    return d;
  };
  const out = [];
  const later = new Date(now.getTime() + 3 * 3600 * 1000);
  later.setMinutes(0, 0, 0);
  if (later.getDate() === now.getDate() && later.getHours() < 21) out.push({ id: 'later', label: 'Later today', at: later });
  if (now.getHours() < 17) out.push({ id: 'evening', label: 'This evening', at: at(0, 18) });
  out.push({ id: 'tomorrow', label: 'Tomorrow morning', at: at(1, 8) });
  const dow = now.getDay(); // 0 = Sunday
  if (dow >= 1 && dow <= 4) out.push({ id: 'weekend', label: 'This weekend', at: at(6 - dow, 9) });
  out.push({ id: 'nextweek', label: 'Next week', at: at(((8 - dow) % 7) || 7, 8) });
  out.push({ id: 'month', label: 'In a month', at: at(30, 8) });
  return out;
}

// "Send later" choices, like the usual mail apps: next working morning etc.
export function schedulePresets(now = new Date()) {
  const at = (days, hour) => new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, hour, 0, 0, 0);
  const out = [];
  if (now.getHours() < 17) out.push({ id: 'evening', label: 'This evening', at: at(0, 18) });
  out.push({ id: 'morning', label: 'Tomorrow morning', at: at(1, 8) });
  out.push({ id: 'afternoon', label: 'Tomorrow afternoon', at: at(1, 13) });
  const dow = now.getDay();
  const toMonday = ((8 - dow) % 7) || 7;
  if (toMonday > 1) out.push({ id: 'monday', label: 'Monday morning', at: at(toMonday, 8) });
  return out;
}

// Section heading for a conversation in a date-sorted list.
export function timeGroup(iso, now = new Date()) {
  if (!iso) return 'Undated';
  const d = new Date(iso);
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - day) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'Earlier this week';
  if (days < 14) return 'Last week';
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString([], { month: 'long' });
  return String(d.getFullYear());
}

// Free-text words of a search query (operators like from:x and -word excluded).
export function searchWords(q) {
  const out = [];
  for (const m of (q || '').matchAll(/"([^"]+)"|(\S+)/g)) {
    const w = m[1] || m[2];
    if (!w || w.startsWith('-') || /^\w+:/.test(w)) continue;
    if (w.length >= 2) out.push(w.toLowerCase());
  }
  return out;
}

// Split text into [{text, hit}] for highlighting (rendered as text, not HTML).
export function highlight(text, words) {
  text = text || '';
  if (!words || !words.length) return [{ text, hit: false }];
  const esc = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(${esc.join('|')})`, 'gi');
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), hit: false });
    parts.push({ text: m[0], hit: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), hit: false });
  return parts.length ? parts : [{ text, hit: false }];
}
