import { api } from '#lib/api.ts';
import type { Doc, Tag } from '#lib/types.ts';
import { ui } from './ui.svelte';

class Workspace {
	docs = $state<Record<string, Doc>>({});
	tags = $state<Tag[]>([]);
	loaded = $state(false);
	offline = $state(false);

	/** parent id ('' for root) -> visible children in order. */
	childMap = $derived.by(() => {
		const map: Record<string, Doc[]> = {};
		for (const d of Object.values(this.docs)) {
			if (d.is_archived || d.entry_of) continue;
			(map[d.parent ?? ''] ??= []).push(d);
		}
		for (const list of Object.values(map)) list.sort((a, b) => a.position - b.position);
		return map;
	});

	favorites = $derived(
		Object.values(this.docs)
			.filter((d) => d.is_favorite && !d.is_archived)
			.sort((a, b) => a.title.localeCompare(b.title))
	);

	recents = $derived(
		Object.values(this.docs)
			.filter((d) => d.last_opened_at && !d.is_archived)
			.sort((a, b) => (b.last_opened_at! > a.last_opened_at! ? 1 : -1))
			.slice(0, 12)
	);

	archived = $derived(
		Object.values(this.docs)
			.filter((d) => d.is_archived)
			.sort((a, b) => (b.updated_at > a.updated_at ? 1 : -1))
	);

	/** Database id -> its page document. */
	dbPages = $derived.by(() => {
		const out: Record<string, Doc> = {};
		for (const d of Object.values(this.docs)) if (d.database) out[d.database] = d;
		return out;
	});

	groups = $derived(
		Object.values(this.docs)
			.filter((d) => d.kind === 'group' && !d.parent && !d.is_archived && !d.entry_of)
			.sort((a, b) => a.position - b.position)
	);

	databases = $derived(
		Object.values(this.docs)
			.filter((d) => d.database && !d.is_archived)
			.sort((a, b) => (a.title || 'Untitled').localeCompare(b.title || 'Untitled'))
	);

	tagMap = $derived(Object.fromEntries(this.tags.map((t) => [t.id, t])) as Record<string, Tag>);

	entries(db: string): Doc[] {
		return Object.values(this.docs).filter((d) => d.entry_of === db);
	}

	children(parent: string | null): Doc[] {
		return this.childMap[parent ?? ''] ?? [];
	}

	/** Ancestors from the root down to (excluding) the document. */
	path(id: string): Doc[] {
		const out: Doc[] = [];
		const up = (d: Doc | undefined) =>
			d?.parent ?? (d?.entry_of ? (this.dbPages[d.entry_of]?.id ?? null) : null);
		let cur = up(this.docs[id]);
		let guard = 0;
		while (cur && this.docs[cur] && guard++ < 64) {
			out.unshift(this.docs[cur]);
			cur = up(this.docs[cur]);
		}
		return out;
	}

	isDescendant(id: string, ancestor: string): boolean {
		return id === ancestor || this.path(id).some((d) => d.id === ancestor);
	}

	async load() {
		try {
			const [docs, tags] = await Promise.all([api.get<Doc[]>('/tree'), api.get<Tag[]>('/tags')]);
			this.docs = Object.fromEntries(docs.map((d) => [d.id, d]));
			this.tags = tags;
			this.offline = !navigator.onLine;
		} catch (e) {
			this.offline = true;
			throw e;
		} finally {
			this.loaded = true;
		}
	}

	async createDoc(init: { parent?: string | null; title?: string; icon?: string; kind?: 'page' | 'group' } = {}): Promise<Doc> {
		const doc = await api.post<Doc>('/documents', init);
		this.docs[doc.id] = doc;
		return doc;
	}

	/** Optimistically update a document; rolls back if the server rejects. */
	async updateDoc(id: string, patch: Partial<Doc>) {
		const doc = this.docs[id];
		const before = doc ? { ...doc } : null;
		if (doc) Object.assign(doc, patch);
		try {
			const saved = await api.patch<Doc>(`/documents/${id}`, patch);
			if (this.docs[id]) {
				this.docs[id].updated_at = saved.updated_at;
				this.docs[id].tags = saved.tags;
			}
		} catch (e) {
			if (before && this.docs[id]) Object.assign(this.docs[id], before);
			ui.error(e);
			throw e;
		}
	}

	touchOpened(id: string) {
		if (this.docs[id]) this.docs[id].last_opened_at = new Date().toISOString();
	}

	async moveDoc(id: string, parent: string | null, index?: number) {
		if (parent && this.isDescendant(parent, id)) return;
		try {
			const res = await api.post<{ order: string[] }>(`/documents/${id}/move`, { parent, index });
			if (this.docs[id]) this.docs[id].parent = parent;
			res.order.forEach((did, i) => {
				if (this.docs[did]) this.docs[did].position = i + 1;
			});
		} catch (e) {
			ui.error(e);
		}
	}

	subtree(id: string): string[] {
		const out = [id];
		for (let i = 0; i < out.length; i++)
			for (const d of Object.values(this.docs)) if (d.parent === out[i]) out.push(d.id);
		return out;
	}

	/** Move to trash. Returns the ids that were removed from the tree. */
	async trashDoc(id: string): Promise<string[]> {
		const res = await api.post<{ trashed: string[] }>(`/documents/${id}/trash`);
		for (const did of res.trashed) delete this.docs[did];
		return res.trashed;
	}

	async restoreDoc(id: string) {
		await api.post(`/documents/${id}/restore`);
		await this.load();
	}

	async duplicateDoc(id: string): Promise<Doc> {
		const doc = await api.post<Doc>(`/documents/${id}/duplicate`);
		await this.load();
		return doc;
	}

	async createTag(name: string): Promise<Tag> {
		const tag = await api.post<Tag>('/tags', { name });
		if (!this.tagMap[tag.id]) this.tags = [...this.tags, tag].sort((a, b) => a.name.localeCompare(b.name));
		return tag;
	}

	async updateTag(id: string, patch: Partial<Tag>) {
		const saved = await api.patch<Tag>(`/tags/${id}`, patch);
		this.tags = this.tags
			.map((t) => (t.id === id ? { ...t, ...saved } : t))
			.sort((a, b) => a.name.localeCompare(b.name));
	}

	async deleteTag(id: string) {
		await api.del(`/tags/${id}`);
		this.tags = this.tags.filter((t) => t.id !== id);
		for (const d of Object.values(this.docs)) d.tags = d.tags.filter((t) => t !== id);
	}

	async refreshTags() {
		this.tags = await api.get<Tag[]>('/tags');
	}
}

export const ws = new Workspace();
