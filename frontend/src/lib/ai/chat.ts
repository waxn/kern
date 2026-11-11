import { api } from '../api.ts';
import { refreshDoc, releaseDoc } from '../editor/doc.svelte.ts';
import { ws } from '../state/workspace.svelte.ts';

export interface ChatAction { verb: string; detail: string; page?: { id: string; title: string; icon: string } }
export interface ChatSource { url: string; title: string }
export interface ChatMessage { role: 'user' | 'assistant'; text: string; actions?: ChatAction[]; sources?: ChatSource[]; at?: string }
export interface ChatSummary { id: string; title: string; updated_at: string }
export interface Chat extends ChatSummary { messages: ChatMessage[] }

/** Send one message (creating the chat first if needed); refreshes whatever the assistant changed. */
export async function sendChat(chat: Chat | null, text: string, page?: string | null, onCreated?: (c: Chat) => void): Promise<Chat> {
	// Save the open page first, so the assistant reads (and snapshots) what is on screen.
	if (page) await releaseDoc(page, true);
	let target = chat;
	if (!target) {
		target = await api.post<Chat>('/chats', {});
		onCreated?.(target);
	}
	const updated = await api.post<Chat>(`/chats/${target.id}/message`, { text, page: page ?? null });
	const last = updated.messages[updated.messages.length - 1];
	if (last?.actions?.length) {
		// Pages it changed reload in place wherever they are open.
		for (const a of last.actions) if (a.page) refreshDoc(a.page.id);
		ws.load().catch(() => {});
	}
	return updated;
}
