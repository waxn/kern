// @ts-nocheck: plain JavaScript; covered by searchQuery.test.js.
// Editing a mail search query: filter toggles, operator completion, match snippets.

export const OPERATORS = [
  { text: 'from:', label: 'Sender (from:me works)' },
  { text: 'to:', label: 'Recipient (to:me works)' },
  { text: 'cc:', label: 'Copied' },
  { text: 'subject:', label: 'Words in the subject' },
  { text: 'domain:', label: "Sender's domain" },
  { text: 'in:inbox', label: 'Folder (in:anywhere for all)' },
  { text: 'label:', label: 'Label' },
  { text: 'is:unread', label: 'Unread' },
  { text: 'is:read', label: 'Read' },
  { text: 'is:starred', label: 'Starred' },
  { text: 'is:snoozed', label: 'Snoozed' },
  { text: 'is:muted', label: 'Muted' },
  { text: 'is:answered', label: 'You replied' },
  { text: 'has:attachment', label: 'Any file' },
  { text: 'has:pdf', label: 'PDF' },
  { text: 'has:image', label: 'Pictures' },
  { text: 'has:document', label: 'Documents' },
  { text: 'has:spreadsheet', label: 'Spreadsheets' },
  { text: 'has:presentation', label: 'Slides' },
  { text: 'has:calendar', label: 'Invitations' },
  { text: 'has:link', label: 'Links' },
  { text: 'filename:', label: 'Attachment name' },
  { text: 'newer_than:7d', label: 'Last 7 days (d w m y)' },
  { text: 'older_than:1y', label: 'Older than a year' },
  { text: 'after:2026-01-01', label: 'On or after a date' },
  { text: 'before:2026-01-01', label: 'Before a date' },
  { text: 'larger:5M', label: 'Bigger than (K, M)' },
  { text: 'smaller:100K', label: 'Smaller than' },
  { text: 'list:', label: 'Mailing list' },
  { text: 'risk:high', label: 'Possible phishing' },
  { text: '"exact words"', label: 'Phrase' },
  { text: '-word', label: 'Leave out' },
  { text: 'a OR b', label: 'Either word' },
];

// Split on spaces outside quotes.
export function tokens(q) {
  return (q || '').match(/-?\w+:"[^"]*"?|-?"[^"]*"?|\S+/g) || [];
}

export function hasToken(q, tok) {
  return tokens(q).some((t) => t.toLowerCase() === tok.toLowerCase());
}

export function removeToken(q, tok) {
  return tokens(q).filter((t) => t.toLowerCase() !== tok.toLowerCase()).join(' ');
}

// Adds a filter. A filter of the same kind (newer_than:7d vs newer_than:30d) is replaced.
export function addToken(q, tok, { raw = false } = {}) {
  let parts = tokens(q);
  if (!raw) {
    const m = /^(is|has|in|newer_than|older_than):/i.exec(tok);
    const exclusive = m && ['newer_than', 'older_than'].includes(m[1].toLowerCase());
    if (exclusive) parts = parts.filter((t) => !t.toLowerCase().startsWith(m[1].toLowerCase() + ':'));
    if (/^in:/i.test(tok)) parts = parts.filter((t) => !/^in:/i.test(t));
  }
  if (!parts.some((t) => t.toLowerCase() === tok.toLowerCase())) parts.push(tok);
  return parts.join(' ');
}

// The word being typed at the end (nothing when the query ends with a space).
export function lastToken(q) {
  if (!q || /\s$/.test(q)) return '';
  const t = tokens(q);
  return t[t.length - 1] || '';
}

// Put `value` where the word being typed is. An operator that still needs its value keeps the
// cursor right after the colon; a complete one gets a space.
export function replaceLastToken(q, value, { keepOperatorValue = false } = {}) {
  const last = lastToken(q);
  const head = last ? q.slice(0, q.length - last.length) : q && !/\s$/.test(q) ? q + ' ' : q || '';
  const done = !value.endsWith(':') || keepOperatorValue;
  return head + value + (done && !value.endsWith(':') ? ' ' : '');
}

// Operators that fit what's being typed ("ha" -> has:..., "has:p" -> has:pdf, has:presentation).
export function operatorCompletions(q, limit = 4) {
  const last = lastToken(q).replace(/^-/, '').toLowerCase();
  if (!last || last.length < 2 || last.startsWith('"')) return [];
  return OPERATORS.filter((o) => /^[a-z_]+:/.test(o.text))
    .filter((o) => o.text.startsWith(last) && o.text !== last)
    .slice(0, limit);
}

// "…the \x02invoice\x03 for March…" -> [{text, hit}], safe to render as text.
export function hitParts(s) {
  const out = [];
  for (const piece of (s || '').split('\x02')) {
    const [a, b] = piece.split('\x03');
    if (b === undefined) {
      if (a) out.push({ text: a, hit: false });
    } else {
      if (a) out.push({ text: a, hit: true });
      if (b) out.push({ text: b, hit: false });
    }
  }
  return out;
}
