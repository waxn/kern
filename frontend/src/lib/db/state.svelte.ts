import { api } from '../api.ts';
import { ui } from '../state/ui.svelte.ts';
import { ws } from '../state/workspace.svelte.ts';
import type { DbPayload, DbRow, DbView, Doc, PropDef, ViewConfig } from '../types.ts';
import { debounce } from '../util.ts';
import { compareRows, matchGroup, TITLE, titleOf, type Col } from './query.ts';

export class DbState {
	readonly id: string;
	data = $state<DbPayload | null>(null);
	status = $state<'loading' | 'ready' | 'missing' | 'error'>('loading');
	private loadSeq = 0;
	private viewSaves = new Map<string, ReturnType<typeof debounce>>();

	constructor(id: string) {
		this.id = id;
	}

	cols = $derived.by((): Col[] => {
		if (!this.data) return [];
		return [
			{ id: TITLE, name: 'Name', type: 'title' as const },
			...this.data.properties.map((d) => ({ id: d.id, name: d.name, type: d.type, def: d }))
		];
	});

	colMap = $derived(Object.fromEntries(this.cols.map((c) => [c.id, c])) as Record<string, Col>);

	async load() {
		const seq = ++this.loadSeq;
		try {
			const data = await api.get<DbPayload>(`/databases/${this.id}`);
			if (seq !== this.loadSeq) return;
			this.data = data;
			this.status = 'ready';
			// Keep the workspace index in step so titles and links resolve.
			if (data.rows.some((r) => !ws.docs[r.id])) ws.load().catch(() => {});
		} catch (e: any) {
			if (seq !== this.loadSeq) return;
			if (this.status !== 'ready') this.status = e?.status === 404 ? 'missing' : 'error';
		}
	}

	/** Re-fetch soon; computed columns (rollups, formulas) come from the server. */
	refresh = debounce(() => this.load(), 250);

	row(id: string): DbRow | undefined {
		return this.data?.rows.find((r) => r.id === id);
	}

	/** Rows of a view after its filter and sorts. */
	rowsFor(view: DbView): DbRow[] {
		if (!this.data) return [];
		const cfg = view.config;
		let rows = this.data.rows.filter((r) => ws.docs[r.id] ? !ws.docs[r.id].trashed_at : true);
		if (cfg.filter?.rules.length) rows = rows.filter((r) => matchGroup(r, cfg.filter!, this.colMap));
		const sorts = (cfg.sorts ?? []).filter((s) => this.colMap[s.prop]);
		if (sorts.length)
			rows = [...rows].sort((a, b) => {
				for (const s of sorts) {
					const c = compareRows(a, b, this.colMap[s.prop]);
					if (c) return s.dir === 'desc' ? -c : c;
				}
				return a.position - b.position;
			});
		return rows;
	}

	/** Columns a view shows, in property order. Title is always first. */
	visibleCols(view: DbView): Col[] {
		const hidden = new Set(view.config.hidden ?? []);
		return this.cols.filter((c) => c.id === TITLE || !hidden.has(c.id));
	}

	// ------------------------------------------------------------ rows

	async setValue(rowId: string, prop: string, value: any) {
		const row = this.row(rowId);
		if (prop === TITLE) return this.setTitle(rowId, String(value ?? ''));
		if (row) row.values[prop] = value;
		try {
			await api.put(`/documents/${rowId}/properties/${prop}`, { value });
		} catch (e) {
			ui.error(e);
		}
		this.refreshRelated(prop);
		this.refresh();
	}

	/** A relation change also changes the other database. */
	private refreshRelated(prop: string) {
		const def = this.data?.properties.find((p) => p.id === prop);
		const target = def?.type === 'relation' ? def.config.target : null;
		if (target && target !== this.id) peekDb(target)?.refresh();
	}

	async setTitle(rowId: string, title: string) {
		const row = this.row(rowId);
		if (row) row.title = title;
		if (ws.docs[rowId]) ws.docs[rowId].title = title;
		try {
			await api.patch(`/documents/${rowId}`, { title });
		} catch (e) {
			ui.error(e);
		}
		this.refresh();
	}

	async addRow(values: Record<string, any> = {}, opts: { title?: string; template?: string } = {}): Promise<Doc | null> {
		try {
			const doc = await api.post<Doc>(`/databases/${this.id}/entries`, { values, ...opts });
			ws.docs[doc.id] = doc;
			await this.load();
			return doc;
		} catch (e) {
			ui.error(e);
			return null;
		}
	}

	async trashRows(ids: string[]) {
		if (!ids.length) return;
		try {
			const res = await api.post<{ trashed: string[] }>(`/databases/${this.id}/entries/trash`, { ids });
			for (const id of res.trashed) delete ws.docs[id];
			await this.load();
			ui.toast(ids.length === 1 ? 'Moved entry to trash' : `Moved ${ids.length} entries to trash`, {
				action: {
					label: 'Undo',
					run: async () => {
						for (const id of ids) await ws.restoreDoc(id).catch(() => {});
						this.load();
					}
				}
			});
		} catch (e) {
			ui.error(e);
		}
	}

	// ------------------------------------------------------- properties

	async addProperty(init: Partial<PropDef> & { name: string; type: string }): Promise<PropDef | null> {
		try {
			const def = await api.post<PropDef>('/properties', { database: this.id, ...init });
			await this.load();
			if (def.type === 'relation' && def.config.target && def.config.target !== this.id) peekDb(def.config.target)?.load();
			return def;
		} catch (e) {
			ui.error(e);
			return null;
		}
	}

	async updateProperty(id: string, patch: Partial<PropDef>) {
		const def = this.data?.properties.find((p) => p.id === id);
		if (def) Object.assign(def, patch.config ? { ...patch, config: { ...def.config, ...patch.config } } : patch);
		try {
			await api.patch(`/properties/${id}`, patch);
		} catch (e) {
			ui.error(e);
		}
		await this.load();
	}

	async deleteProperty(id: string) {
		const def = this.data?.properties.find((p) => p.id === id);
		const ok = await ui.confirm({
			title: `Delete property “${def?.name}”?`,
			message: 'Its values will be removed from every entry. This cannot be undone.',
			confirmLabel: 'Delete property', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/properties/${id}`);
		} catch (e) {
			ui.error(e);
		}
		await this.load();
	}

	async moveProperty(id: string, dir: -1 | 1) {
		if (!this.data) return;
		const list = this.data.properties.map((p) => p.id);
		const i = list.indexOf(id);
		const j = i + dir;
		if (i < 0 || j < 0 || j >= list.length) return;
		[list[i], list[j]] = [list[j], list[i]];
		this.data.properties.sort((a, b) => list.indexOf(a.id) - list.indexOf(b.id));
		await api.post(`/databases/${this.id}/property-order`, { order: list }).catch((e) => ui.error(e));
	}

	// ------------------------------------------------------------ views

	updateView(view: DbView, patch: Partial<ViewConfig>) {
		view.config = { ...view.config, ...patch };
		let save = this.viewSaves.get(view.id);
		if (!save) {
			save = debounce(() => {
				api.patch(`/views/${view.id}`, { config: $state.snapshot(view.config) }).catch((e) => ui.error(e));
			}, 400);
			this.viewSaves.set(view.id, save);
		}
		save();
	}

	async renameView(view: DbView, name: string) {
		view.name = name;
		await api.patch(`/views/${view.id}`, { name }).catch((e) => ui.error(e));
	}

	async addView(type: DbView['type'], config: ViewConfig = {}): Promise<DbView | null> {
		try {
			const v = await api.post<DbView>(`/databases/${this.id}/views`, { type, config });
			this.data?.views.push(v);
			return v;
		} catch (e) {
			ui.error(e);
			return null;
		}
	}

	async duplicateView(view: DbView): Promise<DbView | null> {
		const v = await this.addView(view.type, $state.snapshot(view.config));
		if (v) await this.renameView(v, view.name + ' (copy)');
		return v;
	}

	async deleteView(view: DbView): Promise<boolean> {
		if (!this.data || this.data.views.length <= 1) {
			ui.toast('A database needs at least one view.');
			return false;
		}
		if (!(await ui.confirm({ title: `Delete view “${view.name}”?`, message: 'The entries are not affected.', confirmLabel: 'Delete view', danger: true }))) return false;
		try {
			await api.del(`/views/${view.id}`);
			this.data.views = this.data.views.filter((v) => v.id !== view.id);
			return true;
		} catch (e) {
			ui.error(e);
			return false;
		}
	}
}

const cache = new Map<string, DbState>();

export function getDb(id: string): DbState {
	let db = cache.get(id);
	if (!db) {
		db = new DbState(id);
		cache.set(id, db);
	}
	db.load();
	return db;
}

/** The loaded state for a database, if any view of it is open. */
export function peekDb(id: string): DbState | undefined {
	return cache.get(id);
}

export { titleOf };
