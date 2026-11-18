// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// What puts a conversation action back the way it was.
// roles: { inbox, archive, trash, junk } folder ids. context: the folder the
// action was taken in (null for virtual views like Starred or search).

export function inverseOf(ids, action, context, payload, roles) {
  const back = context ?? roles.inbox;
  switch (action) {
    case 'archive': return { ids, action: 'move', context: roles.archive, dest: back };
    case 'trash': return { ids, action: 'move', context: roles.trash, dest: back };
    case 'move': return back ? { ids, action: 'move', context: payload.dest, dest: back } : null;
    case 'spam': return { ids, action: 'not_spam', context: roles.junk };
    case 'not_spam': return { ids, action: 'move', context: roles.inbox, dest: roles.junk };
    case 'inbox': return context ? { ids, action: 'move', context: roles.inbox, dest: context } : null;
    case 'snooze': return { ids, action: 'unsnooze' };
    case 'mute': return { ids, action: 'unmute', dest: back };
    case 'unmute': return { ids, action: 'mute' };
    case 'label_add': return { ids, action: 'label_remove', label: payload.label };
    case 'label_remove': return { ids, action: 'label_add', label: payload.label };
    case 'unread': return { ids, action: 'read' };
    default: return null;
  }
}
