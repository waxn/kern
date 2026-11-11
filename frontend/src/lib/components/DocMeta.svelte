<script lang="ts">
	import { Plus, X } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import type { EditorDoc } from '#lib/editor/doc.svelte.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { PropDef, PropType } from '#lib/types.ts';
	import { peekDb } from '#lib/db/state.svelte.ts';
	import { DB_PROP_TYPES, PROP_ICONS, PROP_TYPES } from '#lib/propTypes.ts';
	import PropertyField from './PropertyField.svelte';

	let { doc }: { doc: EditorDoc } = $props();
	let meta = $derived(ws.docs[doc.id] ?? doc.meta ?? undefined);
	let tags = $derived((meta?.tags ?? []).map((id) => ws.tagMap[id]).filter(Boolean));

	let tagOpen = $state(false);
	let tagFilter = $state('');
	let adding = $state(false);
	let newName = $state('');
	let newType = $state<PropType>('text');

	let tagChoices = $derived(
		ws.tags.filter((t) => !meta?.tags.includes(t.id) && t.name.toLowerCase().includes(tagFilter.trim().toLowerCase())).slice(0, 8)
	);

	async function setTags(ids: string[]) {
		await doc.flush();
		if (ws.docs[doc.id]) await ws.updateDoc(doc.id, { tags: ids }).catch(() => {});
		else {
			await api.patch(`/documents/${doc.id}`, { tags: ids }).catch((e) => ui.error(e));
			if (doc.meta) doc.meta.tags = ids;
		}
		await doc.load(); // tag-defined properties and tag templates may have changed the page
		ws.refreshTags().catch(() => {});
	}

	async function addTag(id?: string) {
		try {
			const tagId = id ?? (await ws.createTag(tagFilter.trim())).id;
			if (!meta.tags.includes(tagId)) await setTags([...meta.tags, tagId]);
			tagFilter = '';
			tagOpen = false;
		} catch (e) {
			ui.error(e);
		}
	}

	async function setValue(def: PropDef, value: any) {
		doc.properties.values[def.id] = value;
		try {
			doc.properties = await api.put(`/documents/${doc.id}/properties/${def.id}`, { value });
		} catch (e) {
			ui.error(e);
		}
		if (meta?.entry_of) peekDb(meta.entry_of)?.refresh();
		if (def.type === 'relation' && def.config?.target) peekDb(def.config.target)?.refresh();
	}

	async function addProperty() {
		const name = newName.trim();
		if (!name) return;
		try {
			const def = await api.post<PropDef>('/properties', { name, type: newType, database: meta?.entry_of ?? undefined });
			doc.properties = await api.put(`/documents/${doc.id}/properties/${def.id}`, { value: null });
			newName = '';
			adding = false;
		} catch (e) {
			ui.error(e);
		}
	}

	function propMenu(e: MouseEvent, def: PropDef) {
		ui.openMenu(e, [
			{
				label: 'Rename',
				onSelect: async () => {
					const name = prompt('Property name', def.name)?.trim();
					if (!name) return;
					const saved = await api.patch<PropDef>(`/properties/${def.id}`, { name }).catch((err) => ui.error(err));
					if (saved) updateDef(saved);
				}
			},
			def.tag || def.database
				? { label: 'Clear value', onSelect: () => setValue(def, null) }
				: {
						label: 'Delete property', danger: true,
						onSelect: async () => {
							if (!(await ui.confirm({ title: `Delete property “${def.name}”?`, message: 'Its value on this page will be removed.', confirmLabel: 'Delete', danger: true }))) return;
							await api.del(`/properties/${def.id}`).catch((err) => ui.error(err));
							doc.load();
						}
					}
		]);
	}

	function updateDef(saved: PropDef) {
		doc.properties.defs = doc.properties.defs.map((d) => (d.id === saved.id ? saved : d));
	}
</script>

{#if meta}
	<div class="meta">
		<div class="row">
			<span class="name">Tags</span>
			<div class="tags">
				{#each tags as t (t.id)}
					<span class="chip" data-c={t.color || undefined}>
						<a href="/tag/{t.id}" onclick={(e) => { e.preventDefault(); open(`/tag/${t.id}`, e); }}>#{t.name}</a>
						<button title="Remove tag" onclick={() => setTags(meta.tags.filter((x) => x !== t.id))}><X size={11} /></button>
					</span>
				{/each}
				<span class="tagadd">
					<button class="addbtn" onclick={() => (tagOpen = !tagOpen)}><Plus size={12} />Add tag</button>
					{#if tagOpen}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div class="backdrop" onmousedown={() => (tagOpen = false)}></div>
						<div class="pop popover">
							<!-- svelte-ignore a11y_autofocus -->
							<input class="input" autofocus bind:value={tagFilter} placeholder="Find or create a tag…"
								onkeydown={(e) => {
									if (e.key === 'Escape') tagOpen = false;
									if (e.key === 'Enter' && tagFilter.trim()) {
										const exact = ws.tags.find((t) => t.name.toLowerCase() === tagFilter.trim().toLowerCase());
										addTag(exact?.id ?? tagChoices[0]?.id);
									}
								}} />
							{#each tagChoices as t (t.id)}
								<button class="menu-item" onclick={() => addTag(t.id)}><span class="chip" data-c={t.color || undefined}>#{t.name}</span></button>
							{/each}
							{#if tagFilter.trim() && !ws.tags.some((t) => t.name.toLowerCase() === tagFilter.trim().toLowerCase())}
								<button class="menu-item" onclick={() => addTag()}>Create tag “{tagFilter.trim()}”</button>
							{:else if !tagChoices.length}
								<div class="faint pad">{ws.tags.length ? 'No more tags.' : 'Type a name to create your first tag.'}</div>
							{/if}
						</div>
					{/if}
				</span>
			</div>
		</div>

		{#each doc.properties.defs as def (def.id)}
			{@const Icon = PROP_ICONS[def.type] ?? PROP_ICONS.text}
			<div class="row">
				<button class="name truncate" title="{def.name}{def.tag ? ` · from #${ws.tagMap[def.tag]?.name ?? 'tag'}` : ''}" onclick={(e) => propMenu(e, def)}>
					<Icon size={12} />{def.name}
				</button>
				<div class="value"><PropertyField {def} value={doc.properties.values[def.id]} onchange={(v) => setValue(def, v)} ondef={updateDef} /></div>
			</div>
		{/each}

		{#if adding}
			<form class="row new" onsubmit={(e) => { e.preventDefault(); addProperty(); }}>
				<!-- svelte-ignore a11y_autofocus -->
				<input class="input" autofocus bind:value={newName} placeholder="Property name" onkeydown={(e) => e.key === 'Escape' && (adding = false)} />
				<select class="input" bind:value={newType}>
					{#each meta?.entry_of ? DB_PROP_TYPES.filter((t) => t[0] !== 'relation' && t[0] !== 'rollup') : PROP_TYPES as [v, label] (v)}<option value={v}>{label}</option>{/each}
				</select>
				<button class="btn primary" type="submit">Add</button>
				<button class="btn ghost" type="button" onclick={() => (adding = false)}>Cancel</button>
			</form>
		{:else}
			<button class="addbtn prop" onclick={() => (adding = true)}><Plus size={12} />Add property</button>
		{/if}
	</div>
{/if}

<style>
	.meta { margin: 6px 0 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); font-family: var(--font-sans); font-size: 13.5px; }
	.row { display: flex; align-items: flex-start; gap: 8px; min-height: 28px; }
	.name { flex: none; width: 140px; height: 26px; display: flex; align-items: center; gap: 6px; padding: 0 6px; border-radius: var(--radius-sm); color: var(--text-3); text-align: left; }
	button.name:hover { background: var(--hover); color: var(--text-2); }
	.value { flex: 1; min-width: 0; }
	.tags { flex: 1; display: flex; flex-wrap: wrap; align-items: center; gap: 5px; min-height: 26px; padding: 0 6px; }
	.chip a { text-decoration: none; }
	.chip a:hover { text-decoration: underline; }
	.chip button { display: grid; color: inherit; opacity: 0.6; }
	.chip button:hover { opacity: 1; }
	.tagadd { position: relative; }
	.addbtn { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 6px; border-radius: var(--radius-sm); color: var(--text-3); font-size: 12.5px; }
	.addbtn:hover { background: var(--hover); color: var(--text-2); }
	.addbtn.prop { margin: 2px 0 0 0; }
	.backdrop { position: fixed; inset: 0; z-index: 400; }
	.pop { position: absolute; z-index: 401; top: calc(100% + 4px); left: 0; width: 240px; padding: 6px; }
	.pop .input { width: 100%; margin-bottom: 4px; }
	.pad { padding: 6px 8px; }
	.new { align-items: center; margin-top: 4px; flex-wrap: wrap; }
	.new .input:first-child { flex: 1; min-width: 120px; }
	@media (max-width: 760px) { .name { width: 96px; } }
</style>
