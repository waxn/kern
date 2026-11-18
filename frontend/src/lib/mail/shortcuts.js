// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Global keyboard shortcuts (Gmail-style). Ignored while typing.

export const SHORTCUTS = [
  ['Navigation', [
    ['j / k', 'Next / previous conversation'],
    ['o or Enter', 'Open conversation'],
    ['u', 'Back to list'],
    ['n / p', 'Next / previous message in a conversation'],
    ['Enter', 'Expand or collapse the focused message'],
    ['g then i', 'Go to Inbox'],
    ['g then s', 'Go to Starred'],
    ['g then a', 'Go to All mail'],
    ['g then d', 'Go to Drafts'],
    ['g then z', 'Go to Snoozed'],
    ['g then p', 'Go to Packages'],
    ['t', 'Make a Kern task from the conversation'],
    ['g then f', 'Go to Files (all attachments)'],
    ['/', 'Search'],
  ]],
  ['Actions', [
    ['c', 'Compose'],
    ['r', 'Reply'],
    ['a', 'Reply all'],
    ['f', 'Forward'],
    ['e', 'Archive'],
    ['#', 'Move to Trash'],
    ['!', 'Report spam'],
    ['s', 'Star / unstar'],
    ['b', 'Snooze…'],
    ['m', 'Mute / unmute conversation'],
    ['x', 'Select conversation'],
    ['Shift + i', 'Mark as read'],
    ['Shift + u', 'Mark as unread'],
    ['v', 'Move to…'],
    ['l', 'Label…'],
    ['?', 'Show shortcuts'],
    ['Esc', 'Close dialog / composer'],
  ]],
  ['Composer', [
    ['Ctrl + Enter', 'Send'],
    ['Ctrl + Shift + Enter', 'Send and archive the conversation'],
    ['Ctrl + s', 'Save draft'],
    ['Ctrl + Shift + c', 'Show Cc and Bcc'],
    ['Ctrl + b / i / u', 'Bold / italic / underline'],
  ]],
];

export function isTyping(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

export function installShortcuts(handle) {
  let prefix = null;
  let prefixTimer = null;

  function onKey(e) {
    if (e.defaultPrevented) return;
    if (e.key === 'Escape') {
      handle('escape', e);
      return;
    }
    if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
    let key = e.key;
    if (e.shiftKey && key.length === 1 && /[a-z]/i.test(key)) key = 'shift+' + key.toLowerCase();
    if (prefix === 'g') {
      prefix = null;
      clearTimeout(prefixTimer);
      if (handle('g ' + key, e) !== false) e.preventDefault();
      return;
    }
    if (key === 'g') {
      prefix = 'g';
      prefixTimer = setTimeout(() => (prefix = null), 1200);
      return;
    }
    if (handle(key, e) !== false) e.preventDefault();
  }

  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}
