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
