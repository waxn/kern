// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { buildSrcdoc, frameCsp, SANDBOX } from './emailFrame.js';

describe('email frame', () => {
  it('never allows scripts in the sandbox', () => {
    expect(SANDBOX).not.toContain('allow-scripts');
    expect(SANDBOX).not.toContain('allow-forms');
    expect(SANDBOX).not.toContain('allow-top-navigation');
  });
  it('locks the frame down with a CSP', () => {
    const csp = frameCsp('https://mail.example');
    expect(csp).toContain("script-src 'none'");
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain('img-src https://mail.example data:');
    expect(csp).not.toMatch(/img-src[^;]*\*/);
  });
  it('puts the CSP before the content', () => {
    const doc = buildSrcdoc('<p>hello</p>', 'https://mail.example');
    expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('<p>hello</p>'));
  });
});

import { collapseQuotes } from './emailFrame.js';

function doc(html) {
  return new DOMParser().parseFromString(`<!doctype html><html><head></head><body>${html}</body></html>`, 'text/html');
}

describe('collapseQuotes', () => {
  it('hides a trailing Gmail quote', () => {
    const d = doc('<p>Sounds good!</p><div class="gmail_quote"><div class="gmail_attr">On Mon, Bob wrote:</div><blockquote>old stuff</blockquote></div>');
    expect(collapseQuotes(d)).toBe(true);
    expect(d.body.classList.contains('mf-collapsed')).toBe(true);
    expect(d.querySelectorAll('.mf-quote').length).toBeGreaterThan(0);
    expect(d.querySelector('p').classList.contains('mf-quote')).toBe(false);
  });
  it('keeps quotes that are answered inline', () => {
    const d = doc('<blockquote type="cite">Are you coming?</blockquote><p>Yes, and I will bring cake for everyone.</p>');
    expect(collapseQuotes(d)).toBe(false);
  });
  it('hides an Outlook reply header and what follows', () => {
    const d = doc('<p>Thanks!</p><hr><div id="m-divRplyFwdMsg">From: X Sent: Y</div><div>old message body</div>');
    expect(collapseQuotes(d)).toBe(true);
    expect(d.querySelector('p').classList.contains('mf-quote')).toBe(false);
  });
  it('keeps a reply written below a wrapped quote', () => {
    const d = doc('<p>See below.</p><div><div class="gmail_attr">On Mon, Bob wrote:</div><blockquote>' + 'old '.repeat(100)
      + '</blockquote></div><p>And here is my actual long answer, which must stay visible no matter what.</p>');
    expect(collapseQuotes(d)).toBe(false);
  });
  it('never hides the whole message', () => {
    const d = doc('<blockquote type="cite">only a quote</blockquote>');
    expect(collapseQuotes(d)).toBe(false);
  });
});

import { looksDark, parseColor } from './emailFrame.js';

describe('dark emails', () => {
  it('marks the page for dark mode only when asked', () => {
    expect(buildSrcdoc('<p>x</p>', 'https://m.example', { dark: true })).toContain('<html class="kern-dark">');
    expect(buildSrcdoc('<p>x</p>', 'https://m.example')).toContain('<html>');
  });
  it('parses colors', () => {
    expect(parseColor('#fff')).toEqual([255, 255, 255]);
    expect(parseColor('#102030')).toEqual([16, 32, 48]);
    expect(parseColor('rgb(1, 2, 3)')).toEqual([1, 2, 3]);
    expect(parseColor('rgba(1, 2, 3, 0)')).toBeNull();
    expect(parseColor('transparent')).toBeNull();
  });
  it('leaves already-dark emails alone', () => {
    expect(looksDark('<table bgcolor="#111111"><tr><td>Hi</td></tr></table>')).toBe(true);
    expect(looksDark('<div style="background-color: rgb(10, 10, 10)">Hi</div>')).toBe(true);
    expect(looksDark('<style>body { background: #000; }</style><p>Hi</p>')).toBe(true);
    expect(looksDark('<table bgcolor="#ffffff"><tr><td>Hi</td></tr></table>')).toBe(false);
    expect(looksDark('<p>Plain</p>')).toBe(false);
  });
});
