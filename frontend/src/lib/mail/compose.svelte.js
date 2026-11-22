// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Compose windows: open/close, autosave, send with undo.

import { api } from './api.svelte.js';
import { route } from './router.svelte.js';
import { account, errorToast, info, loadFolders, loadScheduled, loadThread, threadAction, toast, ui, updateToast, dismissToast } from './state.svelte.js';
import { describeWhen } from './when.js';

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Plain-text signature as compose HTML ("-- " separator, as per convention).
export function signatureHtml() {
  const sig = (account.signature || '').trim();
  if (!sig) return '';
  return '<div><br></div><div>-- <br>' + escapeHtml(sig).replace(/\n/g, '<br>') + '</div>';
}

let seq = 0;

export function openCompose(init = {}) {
  if (ui.composers.length >= 3) ui.composers.shift();
  if (!init.docked) ui.composers.forEach((c) => { if (!c.docked) c.minimized = true; });
  ui.composers.push({
    docked: !!init.docked,
    key: ++seq,
    draftId: init.draftId || null,
    mode: init.mode || 'new',
    inReplyTo: init.inReplyTo || null,
    threadId: init.threadId || null,
    from: init.from || '',
    to: init.to || [],
    cc: init.cc || [],
    bcc: init.bcc || [],
    showCc: !!(init.cc && init.cc.length) || !!(init.bcc && init.bcc.length),
    subject: init.subject || '',
    bodyHtml: init.bodyHtml ?? '<p><br></p>' + signatureHtml(),
    uploads: init.uploads || [],
    forwardAttachments: init.forwardAttachments || [],
    followupAt: init.followupAt || null,
    minimized: false,
    status: 'editing',
    saving: false,
    dirty: false,
    error: '',
  });
}

// Replies opened while reading a conversation dock inline under it.
export async function openReply(message, mode, { docked } = {}) {
  const inline = docked ?? (route.page === 'mail' && route.threadId === message.threadId && innerWidth >= 1024);
  if (inline) {
    const open = ui.composers.find((c) => c.docked && c.threadId === message.threadId);
    if (open) {
      document.querySelector('.composer.docked [contenteditable]')?.focus();
      return;
    }
  }
  try {
    const pre = await api.get('/compose/prefill', { message: message.id, mode });
    openCompose({
      docked: inline,
      threadId: message.threadId,
      mode: pre.mode, inReplyTo: pre.in_reply_to, to: pre.to, cc: pre.cc, subject: pre.subject, from: pre.from || '',
      bodyHtml: account.signature_on_replies && account.signature.trim()
        ? '<p><br></p>' + signatureHtml() + pre.body_html
        : pre.body_html,
      forwardAttachments: pre.forward_attachments,
    });
  } catch (e) {
    errorToast(e);
  }
}

export async function openDraft(draftIdOrMessage) {
  try {
    const d = typeof draftIdOrMessage === 'number'
      ? await api.get(`/drafts/${draftIdOrMessage}`)
      : await api.get(`/messages/${draftIdOrMessage.id}/draft`);
    const existing = ui.composers.find((c) => c.draftId === d.id);
    if (existing) {
      existing.minimized = false;
      return;
    }
    openCompose({
      draftId: d.id, mode: d.mode, inReplyTo: d.inReplyTo, to: d.to, cc: d.cc, bcc: d.bcc,
      subject: d.subject, bodyHtml: d.bodyHtml, uploads: d.uploads, forwardAttachments: d.forwardAttachments,
      followupAt: d.followupAt, from: d.from || '',
    });
  } catch (e) {
    errorToast(e);
  }
}

function payload(c) {
  return {
    from: c.from || '',
    to: c.to, cc: c.cc, bcc: c.bcc, subject: c.subject, bodyHtml: c.bodyHtml,
    forwardAttachments: c.forwardAttachments.map((a) => a.id),
    followupAt: c.followupAt || '',
  };
}

export async function ensureDraft(c) {
  if (c.draftId) return c.draftId;
  const d = await api.post('/drafts', { mode: c.mode, inReplyTo: c.inReplyTo, ...payload(c) });
  c.draftId = d.id;
  c.forwardAttachments = d.forwardAttachments.length ? d.forwardAttachments : c.forwardAttachments;
  return d.id;
}

export async function saveDraft(c, { toServer = false } = {}) {
  if (c.status !== 'editing') return;
  c.saving = true;
  try {
    const id = await ensureDraft(c);
    await api.patch(`/drafts/${id}`, { ...payload(c), saveToServer: toServer });
    c.dirty = false;
    c.error = '';
  } catch (e) {
    c.error = e.message;
  } finally {
    c.saving = false;
  }
}

export async function addFiles(c, files) {
  try {
    const id = await ensureDraft(c);
    const res = await api.upload(`/drafts/${id}/uploads`, files);
    c.uploads.push(...res.uploads);
  } catch (e) {
    errorToast(e);
  }
}

export async function removeUpload(c, upload) {
  c.uploads = c.uploads.filter((u) => u.id !== upload.id);
  if (c.draftId) api.del(`/drafts/${c.draftId}/uploads/${upload.id}`).catch(errorToast);
}

export function closeCompose(c, { save = true } = {}) {
  ui.composers = ui.composers.filter((x) => x.key !== c.key);
  if (save && c.dirty && c.status === 'editing') saveDraft(c, { toServer: true }).then(() => toast('Draft saved'));
  else if (save && c.draftId && c.status === 'editing') api.patch(`/drafts/${c.draftId}`, { saveToServer: true }).catch(() => {});
}

export async function discardCompose(c) {
  ui.composers = ui.composers.filter((x) => x.key !== c.key);
  if (c.draftId) {
    try {
      await api.del(`/drafts/${c.draftId}`);
    } catch (e) {
      errorToast(e);
    }
  }
  toast('Draft discarded');
}

export async function sendCompose(c, { archive = false, at = null } = {}) {
  if (!c.to.length && !c.cc.length && !c.bcc.length) {
    c.error = 'Add at least one recipient.';
    throw new Error(c.error);
  }
  c.status = 'sending';
  try {
    const id = await ensureDraft(c);
    const d = await api.post(`/drafts/${id}/send`, { ...payload(c), ...(at ? { sendAt: at.toISOString() } : {}) });
    ui.composers = ui.composers.filter((x) => x.key !== c.key);
    if (d.status === 'scheduled') {
      toast(`Scheduled for ${describeWhen(new Date(d.sendAt))}`, {
        timeout: 8000,
        action: { label: 'Cancel', run: () => unscheduleDraft(d).catch(errorToast) },
      });
      loadScheduled();
      if (c.threadId) loadThread(c.threadId, { quiet: true });
      return;
    }
    const secs = info.undoSeconds || 0;
    const tid = toast(secs ? 'Sending…' : 'Message sent', {
      timeout: secs ? (secs + 1) * 1000 : 4000,
      action: secs ? { label: 'Undo', run: () => undoSend(c, d.id, tid) } : null,
    });
    if (secs) setTimeout(() => updateToast(tid, { message: 'Message sent', action: null, timeout: 3000 }), secs * 1000);
    setTimeout(loadFolders, (secs + 2) * 1000);
    if (archive && c.threadId) {
      // The reply is on its way; file the conversation away.
      threadAction([c.threadId], 'archive', { silent: true }).catch(() => {});
    }
  } catch (e) {
    c.status = 'editing';
    c.error = e.message;
    throw e;
  }
}

function reopen(d, threadId = null) {
  openCompose({
    draftId: d.id, mode: d.mode, inReplyTo: d.inReplyTo, to: d.to, cc: d.cc, bcc: d.bcc, threadId,
    subject: d.subject, bodyHtml: d.bodyHtml, uploads: d.uploads, forwardAttachments: d.forwardAttachments,
    followupAt: d.followupAt, from: d.from || '',
  });
}

// Cancel a scheduled send and put it back in a compose window.
export async function unscheduleDraft(d, { open = true } = {}) {
  const back = await api.post(`/drafts/${d.id}/unschedule`);
  loadScheduled();
  if (d.threadId) loadThread(d.threadId, { quiet: true });
  if (open) reopen(back, d.threadId || null);
  toast(open ? 'Schedule cancelled. Edit and send when ready.' : 'Schedule cancelled');
  return back;
}

export async function sendScheduledNow(d) {
  await api.post(`/drafts/${d.id}/unschedule`);
  await api.post(`/drafts/${d.id}/send`);
  loadScheduled();
  toast('Sending now');
}

async function undoSend(c, draftId, toastId) {
  dismissToast(toastId);
  try {
    const d = await api.post(`/drafts/${draftId}/undo`);
    reopen(d);
    toast('Sending undone');
  } catch (e) {
    errorToast(e);
  }
}
