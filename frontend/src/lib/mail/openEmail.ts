// A task's link back to the email it came from (mail/taskbridge.py): the
// server finds the conversation by Message-ID, which survives resyncs.
import { api } from '#lib/api.ts';
import { open } from '#lib/state/tabs.ts';
import { ui } from '#lib/state/ui.svelte.ts';

export async function openEmail(key: string, e?: MouseEvent) {
	try {
		const r = await api.get<{ threadId: number }>(`/mail/open?key=${encodeURIComponent(key)}`);
		open(`/mail/all/t/${r.threadId}`, e);
	} catch (err) {
		ui.error(err);
	}
}
