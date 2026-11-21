import { api } from '../api.ts';
import { refreshDoc, releaseDoc } from '../editor/doc.svelte.ts';
import { ws } from '../state/workspace.svelte.ts';

export interface ChatAction { verb: string; detail: string; page?: { id: string; title: string; icon: string } }
export interface ChatSource { url: string; title: string }
export interface ChatMessage { role: 'user' | 'assistant'; text: string; actions?: ChatAction[]; sources?: ChatSource[]; at?: string }
export interface ChatSummary { id: string; title: string; updated_at: string }
/** Permission scopes the server knows (backend notes/agent_access.py). */
export type ChatScope = 'mail.read' | 'bookmarks.write';
/** A turn paused until the user allows or refuses what the assistant wants to do. */
export interface ChatPending { id: string; asks: { scope: ChatScope; title: string; detail: string }[]; scopes: ChatScope[] }
export interface Chat extends ChatSummary { messages: ChatMessage[]; pending?: ChatPending | null; granted?: ChatScope[] }
export type PermissionAnswer = 'once' | 'chat' | 'deny';

export const SCOPE_LABELS: Record<ChatScope, string> = {
	'mail.read': 'Read your email',
	'bookmarks.write': 'Change your bookmarks'
};

/** Pages the last reply changed reload in place wherever they are open. */
function afterTurn(updated: Chat): Chat {
	const last = updated.messages[updated.messages.length - 1];
	if (!updated.pending && last?.role === 'assistant' && last.actions?.length) {
		for (const a of last.actions) if (a.page) refreshDoc(a.page.id);
		ws.load().catch(() => {});
	}
	return updated;
}

/** Send one message (creating the chat first if needed); refreshes whatever the assistant changed. */
export async function sendChat(chat: Chat | null, text: string, page?: string | null, onCreated?: (c: Chat) => void): Promise<Chat> {
	// Save the open page first, so the assistant reads (and snapshots) what is on screen.
	if (page) await releaseDoc(page, true);
	let target = chat;
	if (!target) {
		target = await api.post<Chat>('/chats', {});
		onCreated?.(target);
	}
	return afterTurn(await api.post<Chat>(`/chats/${target.id}/message`, { text, page: page ?? null }));
}

/** Answer the waiting permission request; the turn then carries on on the server. */
export async function answerPermission(chat: Chat, answer: PermissionAnswer): Promise<Chat> {
	if (!chat.pending) return chat;
	return afterTurn(await api.post<Chat>(`/chats/${chat.id}/permission`, { id: chat.pending.id, decision: answer }));
}

/** Take back an "allow in this chat" permission. */
export async function revokeGrant(chat: Chat, scope: ChatScope): Promise<Chat> {
	return api.del<Chat>(`/chats/${chat.id}/grants/${encodeURIComponent(scope)}`);
}
