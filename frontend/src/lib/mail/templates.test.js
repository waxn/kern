// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
import { describe, expect, it } from 'vitest';
import { insertPoint, isEmptyBody, templateBody } from './templates.svelte.js';

describe('templateBody', () => {
  it('keeps your words, drops quote, attribution and signature', () => {
    const html = '<p>Thanks, got it.</p><p>Talk soon</p><div><br></div><div>-- <br>Me</div>'
      + '<p><br></p><div>On Fri, 13 Nov 2026 at 09:00, Alice &lt;a@x.test&gt; wrote:</div><blockquote><p>old</p></blockquote>';
    expect(templateBody(html, 'Me')).toBe('<p>Thanks, got it.</p><p>Talk soon</p>');
  });
  it('matches multi-line signatures (lines joined by <br>)', () => {
    const html = '<p>Hi</p><div><br></div><div>-- <br>Test Me<br>manifest.test</div>';
    expect(templateBody(html, 'Test Me\nmanifest.test')).toBe('<p>Hi</p>');
  });
  it('keeps text typed into the signature block', () => {
    const html = '<p><br></p><div><br></div><div>-- <br>Me<br>Thanks, will reply soon.</div>';
    expect(templateBody(html, 'Me')).toContain('Thanks, will reply soon.');
  });
  it('detects empty bodies', () => {
    expect(isEmptyBody('<p><br></p>')).toBe(true);
    expect(isEmptyBody('<p>x</p>')).toBe(false);
  });
});

describe('insertPoint', () => {
  function editorWith(html) {
    const ed = document.createElement('div');
    ed.innerHTML = html;
    document.body.appendChild(ed);
    return ed;
  }
  const at = (node, offset) => { const r = document.createRange(); r.setStart(node, offset); r.collapse(true); return r; };

  it('keeps a caret in your own text', () => {
    const ed = editorWith('<p>Hello there</p><div><br></div><div>-- <br>Me</div>');
    const r = at(ed.firstChild.firstChild, 5);
    expect(insertPoint(ed, r)).toBe(r);
  });
  it('moves a caret in the signature to just above it', () => {
    const ed = editorWith('<p>Hello</p><div><br></div><div>-- <br>Me</div>');
    const sig = ed.children[2];
    const r = insertPoint(ed, at(sig.lastChild, 2));
    expect(r.startContainer).toBe(ed);
    expect(ed.childNodes[r.startOffset]).toBe(ed.children[1]); // before the blank line
  });
  it('moves a caret in the quote above the attribution', () => {
    const ed = editorWith('<p><br></p><div>On Fri, A wrote:</div><blockquote><p>old</p></blockquote>');
    const q = ed.querySelector('blockquote p');
    const r = insertPoint(ed, at(q.firstChild, 1));
    expect(ed.childNodes[r.startOffset]).toBe(ed.children[0]);
  });
  it('starts at the top without a caret', () => {
    const ed = editorWith('<p>x</p>');
    const r = insertPoint(ed, null);
    expect(r.startContainer).toBe(ed);
    expect(r.startOffset).toBe(0);
  });
});
