// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// SECURITY (review carefully): how sanitized email HTML is displayed.
//
// The HTML arriving here was already cleaned by the server (mail/sanitize.py).
// As two more layers, it is shown inside an <iframe srcdoc> with:
//   * sandbox WITHOUT allow-scripts: no script can ever run in the frame,
//     whatever slipped through. allow-same-origin is granted only so the
//     parent can measure the content height; without allow-scripts that
//     gives the email no capabilities. Never add allow-scripts here.
//   * a <meta> Content-Security-Policy that forbids scripts, forms, plugins,
//     <base>, and any network access except images from our own origin
//     (the signed image proxy and inline attachments).
//   * the app's own CSP, which the srcdoc frame inherits.

export const SANDBOX = 'allow-same-origin allow-popups allow-popups-to-escape-sandbox';

export function frameCsp(origin) {
  return [
    "default-src 'none'",
    `img-src ${origin} data:`,
    "style-src 'unsafe-inline'",
    'font-src data:',
    "script-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
    "frame-src 'none'",
    "object-src 'none'",
  ].join('; ');
}

const BASE_CSS = `
  html, body { margin: 0; padding: 0; background: #ffffff; color: #222222; }
  body { font: 15px/1.5 system-ui, Cantarell, "Noto Sans", Ubuntu, "DejaVu Sans", Arial, sans-serif;
         padding: 4px 2px 12px; overflow-wrap: anywhere; word-break: break-word; }
  img { max-width: 100%; height: auto; }
  table { max-width: 100%; }
  pre { white-space: pre-wrap; }
  blockquote[type=cite] { margin: 0 0 0 .8ex; border-left: 2px solid #c9c9cf; padding-left: 1ex; color: #555; }
  a { color: #2f4ad0; }
`;

export function buildSrcdoc(html, origin) {
  const csp = frameCsp(origin).replace(/"/g, '&quot;');
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    '<meta name="referrer" content="no-referrer">' +
    '<base target="_blank">' +
    `<style>${BASE_CSS}</style></head><body>` +
    html +
    '</body></html>'
  );
}

// Quoted history at the end of HTML mail (the previous messages in the
// thread) is collapsed behind a toggle, like Gmail's "•••". Only trailing
// quotes are hidden, never quotes with your correspondent's reply below them.
const QUOTE_BLOCKS = '.gmail_quote, blockquote[type="cite"], .protonmail_quote, .yahoo_quoted, blockquote.tutanota_quote';
// Markers that start a quote which continues in their following siblings.
const QUOTE_STARTS = '#m-divRplyFwdMsg, .moz-cite-prefix, #m-appendonsend, .gmail_attr';

function textAfter(el, root) {
  let n = 0;
  let node = el;
  while (node && node !== root) {
    let sib = node.nextSibling;
    while (sib) {
      n += (sib.textContent || '').trim().length;
      sib = sib.nextSibling;
    }
    node = node.parentNode;
  }
  return n;
}

export function collapseQuotes(doc) {
  const body = doc.body;
  if (!body) return false;
  const marked = [];
  for (const el of body.querySelectorAll(QUOTE_STARTS)) {
    // Hide the marker and everything after it at its level.
    const group = [el];
    for (let s = el.nextSibling; s; s = s.nextSibling) group.push(s);
    const text = group.reduce((n, x) => n + (x.textContent || '').trim().length, 0);
    // Text after the marker's group: siblings are part of the group when the
    // marker sits directly in <body>; otherwise count what follows its parent.
    const after = el.parentNode === body ? textAfter(el, body) - text : textAfter(el.parentNode, body);
    if (text > 0 && after <= 20) {
      marked.push(...group);
      break;
    }
  }
  if (!marked.length) {
    const blocks = [...body.querySelectorAll(QUOTE_BLOCKS)].filter((el) => !el.parentElement?.closest(QUOTE_BLOCKS));
    const last = blocks[blocks.length - 1];
    if (last && textAfter(last, body) <= 20 && (last.textContent || '').trim().length > 0) marked.push(last);
  }
  // Never hide the whole message.
  const hiddenText = marked.reduce((n, x) => n + (x.textContent || '').trim().length, 0);
  if (!marked.length || hiddenText >= (body.textContent || '').trim().length - 5) return false;
  for (const el of marked) {
    if (el.nodeType === 1) el.classList.add('mf-quote');
    else if (el.nodeType === 3 && el.textContent.trim()) {
      const span = doc.createElement('span');
      span.className = 'mf-quote';
      el.replaceWith(span);
      span.append(el);
    }
  }
  const style = doc.createElement('style');
  style.textContent = 'body.mf-collapsed .mf-quote { display: none !important; }';
  doc.head.append(style);
  body.classList.add('mf-collapsed');
  return true;
}
