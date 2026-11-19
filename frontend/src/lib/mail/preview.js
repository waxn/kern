// @ts-nocheck: plain JavaScript (ported from Manifest).
// Opening an attachment: audio and video go to Kern's app-wide player (it keeps
// playing while you read on); images, PDFs, HTML, text and Word files open in
// the attachment viewer, with ← → between them. `preview` comes from the
// server (mail/api/views.py _preview), which also decides what is served inline.
import { player } from '#lib/files/player.svelte.ts';
import { ui } from './state.svelte.js';

export const attUrl = (messageId, id, inline = false) =>
  `/api/mail/messages/${messageId}/attachments/${id}${inline ? '?inline=1' : ''}`;

export const isMedia = (a) => a.preview === 'audio' || a.preview === 'video';

/** `list`: the attachments to page through, each {id, messageId, filename, size, contentType, preview, risk?}. */
export function openAttachment(list, a) {
  if (isMedia(a)) {
    const ct = (a.contentType || '').toLowerCase();
    player.open({
      url: attUrl(a.messageId, a.id, true),
      name: a.filename,
      // The player only needs the kind; the server sends the real type.
      mime: ct.startsWith(a.preview + '/') ? ct : `${a.preview}/x-unknown`,
      size: a.size,
    });
    return;
  }
  const items = list.filter((x) => x.preview && !isMedia(x));
  ui.viewer = {
    index: Math.max(0, items.findIndex((x) => x.id === a.id && x.messageId === a.messageId)),
    items: items.map((x) => ({
      key: `${x.messageId}:${x.id}`,
      messageId: x.messageId,
      id: x.id,
      name: x.filename,
      size: x.size,
      mime: x.contentType,
      preview: x.preview,
      risk: x.risk,
      src: attUrl(x.messageId, x.id, true),
      href: attUrl(x.messageId, x.id),
    })),
  };
}
