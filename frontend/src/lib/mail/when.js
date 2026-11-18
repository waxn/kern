// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Natural-language times for snooze and nudges, in local time.
//
//   "in 2 hours" "in 30 min" "3d" "2h" "a week"
//   "tonight" "this evening" "tomorrow" "tom 9" "tomorrow 2:30pm" "noon"
//   "fri" "friday 3pm" "next mon" "weekend" "next week" "next month"
//   "dec 24" "24 dec 9am" "2026-12-24" "24/12"
//   "9am" "21:00" (today, or tomorrow if already past)
//
// parseWhen(text, now) -> Date | null. Dates without a time get 08:00.

const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
const DEFAULT_HOUR = 8;

function dayIndex(word) {
  if (!word || word.length < 2) return -1;
  return DAYS.findIndex((d) => d.startsWith(word) && (word.length >= 3 || ['mo', 'tu', 'we', 'th', 'fr', 'sa', 'su'].includes(word)));
}

function monthIndex(word) {
  if (!word || word.length < 3) return -1;
  return MONTHS.findIndex((m) => m.startsWith(word));
}

// "9", "9am", "9:30", "21:00", "9.30pm", "noon", "midnight" -> [h, m] or null
export function parseTime(s) {
  s = s.trim();
  if (!s) return null;
  if (s === 'noon' || s === 'midday') return [12, 0];
  if (s === 'midnight') return [0, 0];
  const m = s.match(/^(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a|p)?$/);
  if (!m) return null;
  let h = Number(m[1]);
  const min = m[2] ? Number(m[2]) : 0;
  const ap = m[3];
  if (min > 59) return null;
  if (ap) {
    if (h < 1 || h > 12) return null;
    if (ap.startsWith('p') && h !== 12) h += 12;
    if (ap.startsWith('a') && h === 12) h = 0;
  } else if (h > 23) {
    return null;
  }
  return [h, min];
}

function at(base, days, h, m) {
  return new Date(base.getFullYear(), base.getMonth(), base.getDate() + days, h, m, 0, 0);
}

export function parseWhen(input, now = new Date()) {
  let s = (input || '').toLowerCase().trim().replace(/\s+/g, ' ').replace(/^(until|till|at|on)\s+/, '');
  if (!s) return null;

  // Relative: "in 2 hours", "2h", "in a week", "30 min"
  let m = s.match(/^(?:in\s+)?(an?|\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?|w|wk|weeks?|mo|months?)$/);
  if (m) {
    const n = m[1].startsWith('a') ? 1 : Number(m[1]);
    const u = m[2];
    if (u.startsWith('mo')) return at(new Date(now.getFullYear(), now.getMonth() + n, now.getDate()), 0, DEFAULT_HOUR, 0);
    const ms = u.startsWith('m') ? 60e3 : u.startsWith('h') ? 3600e3 : u.startsWith('d') ? 86400e3 : 7 * 86400e3;
    return new Date(now.getTime() + n * ms);
  }

  // Split off a trailing time: "tomorrow 9am", "fri at 3pm". If the rest
  // doesn't parse ("dec 9" is a date, not "dec" at 9:00), try it whole.
  const tm = s.match(/^(.*?)(?:\s+at)?\s+(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a|p)?|noon|midnight)$/);
  if (tm && tm[1] && parseTime(tm[2])) {
    const r = parseDay(tm[1].trim(), parseTime(tm[2]), now);
    if (r) return r;
  }
  return parseDay(s, null, now);
}

function parseDay(s, time, now) {
  let m;
  const [h, mi] = time || [DEFAULT_HOUR, 0];

  // A bare time: today if still ahead, else tomorrow.
  if (!time) {
    const only = parseTime(s);
    if (only && /\d|noon|midnight/.test(s)) {
      const d = at(now, 0, only[0], only[1]);
      return d > now ? d : at(now, 1, only[0], only[1]);
    }
  }

  const words = s.split(' ');
  switch (s) {
    case 'today': { const d = at(now, 0, time ? h : 18, time ? mi : 0); return d > now ? d : null; }
    case 'tonight': return at(now, 0, time ? h : 20, time ? mi : 0);
    case 'this evening':
    case 'evening': return at(now, 0, time ? h : 18, time ? mi : 0);
    case 'this afternoon':
    case 'afternoon': return at(now, 0, time ? h : 14, time ? mi : 0);
    case 'morning':
    case 'tomorrow morning': return at(now, 1, time ? h : 8, time ? mi : 0);
    case 'tomorrow':
    case 'tom':
    case 'tmrw':
    case 'tmr': return at(now, 1, h, mi);
    case 'weekend':
    case 'this weekend': { const dow = now.getDay(); const add = dow === 6 ? 7 : (6 - dow); return at(now, add, time ? h : 9, time ? mi : 0); }
    case 'next week': { const add = ((8 - now.getDay()) % 7) || 7; return at(now, add, h, mi); }
    case 'next month': return new Date(now.getFullYear(), now.getMonth() + 1, 1, h, mi);
    default: break;
  }

  // "fri", "next friday", "this fri"
  let w = words;
  if (w[0] === 'next' || w[0] === 'this') w = w.slice(1);
  if (w.length === 1) {
    const di = dayIndex(w[0]);
    if (di >= 0) {
      let add = (di - now.getDay() + 7) % 7;
      if (add === 0) add = 7; // "fri" on a Friday means next Friday
      return at(now, add, h, mi);
    }
  }

  // ISO date
  m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), h, mi);
  // "24/12" or "24/12/2026" (day first)
  m = s.match(/^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$/);
  if (m) return futureDate(now, Number(m[2]) - 1, Number(m[1]), m[3], h, mi);
  // "dec 24", "24 dec", "december 24th"
  m = s.match(/^([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?$/) || null;
  if (m && monthIndex(m[1]) >= 0) return futureDate(now, monthIndex(m[1]), Number(m[2]), null, h, mi);
  m = s.match(/^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)$/);
  if (m && monthIndex(m[2]) >= 0) return futureDate(now, monthIndex(m[2]), Number(m[1]), null, h, mi);
  return null;
}

function futureDate(now, month, day, year, h, mi) {
  if (day < 1 || day > 31 || month < 0 || month > 11) return null;
  let y = year ? Number(year.length === 2 ? '20' + year : year) : now.getFullYear();
  let d = new Date(y, month, day, h, mi);
  if (d.getMonth() !== month) return null; // e.g. 31 feb
  if (!year && d <= now) d = new Date(y + 1, month, day, h, mi);
  return d;
}

// "Fri 21 Nov, 14:00" / "in 3 hours"
export function describeWhen(d, now = new Date()) {
  if (!d) return '';
  const mins = Math.round((d - now) / 60000);
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (mins < 60) return `in ${mins} min`;
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((day - today) / 86400000);
  if (days === 0) return `today at ${time}`;
  if (days === 1) return `tomorrow at ${time}`;
  const date = d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() !== now.getFullYear() ? 'numeric' : undefined });
  return `${date}, ${time}`;
}

// "just now", "20 min ago", "3 hours ago", "yesterday", "4 days ago", "12 Oct"
export function ago(d, now = new Date()) {
  const mins = Math.round((now - d) / 60000);
  if (mins < 2) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}
