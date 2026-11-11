import { goto } from '$app/navigation';
import {
	Archive, ArchiveRestore, Copy, ExternalLink, FilePlus, LayoutDashboard, LayoutTemplate, Pencil, Star, StarOff, Trash2
} from '@lucide/svelte';
import { api } from '#lib/api.ts';
import { releaseDoc } from '#lib/editor/doc.svelte.ts';
import { prefs } from '#lib/state/prefs.svelte.ts';
import { closeTabsFor, openTab } from '#lib/state/tabs.ts';
import { ui, type MenuItem } from '#lib/state/ui.svelte.ts';
import { ws } from '#lib/state/workspace.svelte.ts';
import type { Doc } from '#lib/types.ts';

export async function newPage(parent: string | null = null, newTab = false) {
	try {
		const doc = await ws.createDoc({ parent });
		if (parent) prefs.expanded[parent] = true;
		if (newTab) openTab(`/doc/${doc.id}`);
		else await goto(`/doc/${doc.id}`);
		return doc;
	} catch (e) {
		ui.error(e);
	}
}

export async function newGroup() {
	try {
		const doc = await ws.createDoc({ kind: 'group', icon: '📚' });
		await goto(`/doc/${doc.id}`);
		return doc;
	} catch (e) {
		ui.error(e);
	}
}

export async function trashPage(id: string) {
	const title = ws.docs[id]?.title || 'Untitled';
	try {
		await releaseDoc(id);
		const removed = await ws.trashDoc(id);
		for (const r of removed) if (r !== id) await releaseDoc(r);
		closeTabsFor(removed);
		ui.toast(`Moved “${title}” to trash`, {
			action: { label: 'Undo', run: () => ws.restoreDoc(id).catch((e) => ui.error(e)) }
		});
	} catch (e) {
		ui.error(e);
	}
}

export async function duplicatePage(id: string) {
	try {
		await releaseDoc(id, true);
		const doc = await ws.duplicateDoc(id);
		await goto(`/doc/${doc.id}`);
	} catch (e) {
		ui.error(e);
	}
}

export function setArchived(id: string, archived: boolean) {
	const title = ws.docs[id]?.title || 'Untitled';
	ws.updateDoc(id, { is_archived: archived }).then(() => {
		if (archived)
			ui.toast(`Archived “${title}”`, {
				action: { label: 'Undo', run: () => ws.updateDoc(id, { is_archived: false }) }
			});
	}).catch(() => {});
}

export function docMenu(doc: Doc, opts: { rename?: () => void } = {}): MenuItem[] {
	const items: MenuItem[] = [
		{ label: 'Open in new tab', icon: ExternalLink, onSelect: () => openTab(`/doc/${doc.id}`) },
		{ label: 'Add sub-page', icon: FilePlus, onSelect: () => newPage(doc.id) }
	];
	if (opts.rename) items.push({ label: 'Rename', icon: Pencil, onSelect: opts.rename });
	items.push(
		{
			label: doc.is_favorite ? 'Remove from favorites' : 'Add to favorites',
			icon: doc.is_favorite ? StarOff : Star,
			onSelect: () => ws.updateDoc(doc.id, { is_favorite: !doc.is_favorite }).catch(() => {})
		},
		{ label: 'Duplicate', icon: Copy, onSelect: () => duplicatePage(doc.id) },
		...(doc.database || doc.entry_of ? [] : [{
			label: doc.kind === 'group' ? 'Turn into page' : 'Turn into group', icon: LayoutDashboard,
			onSelect: () => ws.updateDoc(doc.id, { kind: doc.kind === 'group' ? 'page' : 'group' }).catch(() => {})
		}]),
		...(doc.database ? [] : [{ label: 'Save as template', icon: LayoutTemplate, onSelect: () => saveAsTemplate(doc.id) }]),
		{ separator: true },
		doc.is_archived
			? { label: 'Unarchive', icon: ArchiveRestore, onSelect: () => setArchived(doc.id, false) }
			: { label: 'Archive', icon: Archive, onSelect: () => setArchived(doc.id, true) },
		{ label: 'Move to trash', icon: Trash2, danger: true, onSelect: () => trashPage(doc.id) }
	);
	return items;
}

export async function saveAsTemplate(id: string) {
	try {
		await releaseDoc(id, true);
		const t = await api.post<Doc>('/templates', { from: id });
		ui.toast('Saved as a template', { action: { label: 'Edit', run: () => goto(`/doc/${t.id}`) } });
	} catch (e) {
		ui.error(e);
	}
}
