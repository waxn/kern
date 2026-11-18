<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Plus, Trash2 } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import BacklinkList from '#lib/components/BacklinkList.svelte';
	import DocList from '#lib/components/DocList.svelte';
	import { PROP_TYPES } from '#lib/propTypes.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { BacklinkGroup, Doc, PropDef, PropType, Tag } from '#lib/types.ts';
	import { relTime, TAG_COLORS } from '#lib/util.ts';

	interface BookmarkRef { id: string; url: string; title: string; thumbnail: string; created_at: string; monitor: { unseen: number; enabled: boolean } | null }
	interface Detail { tag: Tag; properties: PropDef[]; documents: Doc[]; bookmarks?: BookmarkRef[]; blocks: BacklinkGroup[] }
	const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };

	let id = $derived(page.params.id!);
	let detail = $state<Detail | null>(null);
	let missing = $state(false);
	let newName = $state('');
	let newType = $state<PropType>('text');

	async function load(tagId: string) {
		try {
			detail = await api.get<Detail>(`/tags/${tagId}`);
			missing = false;
		} catch {
			detail = null;
			missing = true;
		}
	}
	$effect(() => {
		load(id);
	});

	async function rename(name: string) {
		if (!detail || !name.trim() || name.trim() === detail.tag.name) return;
		try {
			await ws.updateTag(id, { name: name.trim() });
			detail.tag.name = name.trim();
		} catch (e) {
			ui.error(e);
			load(id);
		}
	}

	async function recolor(color: string) {
		if (!detail) return;
		detail.tag.color = color;
		await ws.updateTag(id, { color }).catch((e) => ui.error(e));
	}

	async function remove() {
		if (!detail) return;
		const ok = await ui.confirm({
			title: `Delete tag #${detail.tag.name}?`,
			message: 'The tag and its properties are removed from every page. Inline mentions will show as broken. Pages themselves are not deleted.',
			confirmLabel: 'Delete tag', danger: true
		});
		if (!ok) return;
		await ws.deleteTag(id).catch((e) => ui.error(e));
		goto('/tags');
	}

	async function addProp() {
		if (!newName.trim() || !detail) return;
		try {
			const def = await api.post<PropDef>('/properties', { name: newName.trim(), type: newType, tag: id });
			detail.properties.push(def);
			newName = '';
		} catch (e) {
			ui.error(e);
		}
	}

	async function patchProp(def: PropDef, patch: Partial<PropDef>) {
		if (patch.type && patch.type !== def.type) {
			const ok = await ui.confirm({
				title: `Change “${def.name}” to a different type?`,
				message: 'Existing values of this property will be cleared on every page.',
				confirmLabel: 'Change type', danger: true
			});
			if (!ok) return load(id);
		}
		try {
			const saved = await api.patch<PropDef>(`/properties/${def.id}`, patch);
			if (detail) detail.properties = detail.properties.map((d) => (d.id === saved.id ? saved : d));
		} catch (e) {
			ui.error(e);
		}
	}

	async function delProp(def: PropDef) {
		const ok = await ui.confirm({
			title: `Delete property “${def.name}”?`,
			message: 'Its values will be removed from every page with this tag.',
			confirmLabel: 'Delete', danger: true
		});
		if (!ok || !detail) return;
		await api.del(`/properties/${def.id}`).catch((e) => ui.error(e));
		detail.properties = detail.properties.filter((d) => d.id !== def.id);
	}
</script>

<div class="page-scroll">
	<div class="page">
		{#if detail}
			{@const tag = detail.tag}
			<div class="head">
				<span class="hash" data-c={tag.color || undefined}>#</span>
				<input class="name" value={tag.name} aria-label="Tag name" onchange={(e) => rename(e.currentTarget.value)}
					onkeydown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
				<button class="btn ghost" onclick={remove}><Trash2 size={14} />Delete tag</button>
			</div>
			<div class="colors">
				<button class="sw none" class:on={!tag.color} title="No color" onclick={() => recolor('')}></button>
				{#each TAG_COLORS as c (c)}
					<button class="sw" class:on={tag.color === c} data-c={c} title={c} onclick={() => recolor(c)}></button>
				{/each}
			</div>

			<div class="section-title">Properties</div>
			<p class="muted small">Every page tagged #{tag.name} gets these fields.</p>
			{#if detail.properties.length}
				<div class="props">
					{#each detail.properties as def (def.id)}
						<div class="prop">
							<input class="input grow" value={def.name} onchange={(e) => patchProp(def, { name: e.currentTarget.value })} />
							<select class="input" value={def.type} onchange={(e) => patchProp(def, { type: e.currentTarget.value as PropType })}>
								{#each PROP_TYPES as [v, label] (v)}<option value={v}>{label}</option>{/each}
							</select>
							<button class="icon-btn" title="Delete property" onclick={() => delProp(def)}><Trash2 size={14} /></button>
						</div>
					{/each}
				</div>
			{/if}
			<form class="prop" onsubmit={(e) => { e.preventDefault(); addProp(); }}>
				<input class="input grow" bind:value={newName} placeholder="New property, e.g. Email" />
				<select class="input" bind:value={newType}>
					{#each PROP_TYPES as [v, label] (v)}<option value={v}>{label}</option>{/each}
				</select>
				<button class="btn" type="submit"><Plus size={14} />Add</button>
			</form>

			<div class="section-title">Pages · {detail.documents.length}</div>
			{#if detail.documents.length}
				<DocList docs={detail.documents} sub={(d) => 'Edited ' + relTime(d.updated_at)} />
			{:else}
				<div class="empty">No pages have this tag. Add it from a page's “Add tag” button.</div>
			{/if}

			{#if detail.bookmarks?.length}
				<div class="section-title">Bookmarks · {detail.bookmarks.length} <a class="all" href="/web?tag={tag.id}">Open in Bookmarks</a></div>
				<div class="bms">
					{#each detail.bookmarks as b (b.id)}
						<a class="bm" href="/web?open={b.id}">
							<span class="th">{#if b.thumbnail}<img src={b.thumbnail} alt="" loading="lazy" referrerpolicy="no-referrer" />{/if}</span>
							<span class="bt truncate">{b.title || host(b.url)}</span>
							<span class="faint truncate">{host(b.url)}</span>
							{#if b.monitor?.unseen}<em class="new">{b.monitor.unseen} new</em>{/if}
						</a>
					{/each}
				</div>
			{/if}

			<div class="section-title">Mentions in blocks · {detail.blocks.reduce((n, g) => n + g.items.length, 0)}</div>
			<BacklinkList groups={detail.blocks} empty="No blocks mention this tag. Type #{tag.name} while writing." />
		{:else if missing}
			<div class="empty"><b>Tag not found</b>It may have been deleted.</div>
		{/if}
	</div>
</div>

<style>
	.head { display: flex; align-items: center; gap: 4px; }
	.hash { font-size: 24px; font-weight: 650; color: var(--chip, var(--text-3)); }
	.name { flex: 1; min-width: 0; font-size: 24px; font-weight: 650; letter-spacing: -0.01em; border: 0; outline: 0; background: none; padding: 2px 4px; border-radius: var(--radius-sm); }
	.name:hover, .name:focus { background: var(--hover); }
	.colors { display: flex; gap: 6px; margin: 10px 0 4px; }
	.sw { width: 18px; height: 18px; border-radius: 50%; background: var(--chip, var(--text-3)); opacity: 0.75; }
	.sw.none { background: none; border: 1.5px dashed var(--text-3); }
	.sw.on { opacity: 1; box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--chip, var(--text-2)); }
	.small { margin: 0 0 8px; font-size: 12.5px; }
	.props { display: flex; flex-direction: column; gap: 6px; margin-bottom: 6px; }
	.prop { display: flex; align-items: center; gap: 6px; }
	.grow { flex: 1; }
	.all { float: right; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--text-2); }
	.bms { display: flex; flex-direction: column; gap: 2px; }
	.bm { display: flex; align-items: center; gap: 10px; padding: 5px 6px; border-radius: var(--radius-sm); color: inherit; text-decoration: none; font-size: 14px; }
	.bm:hover { background: var(--hover); }
	.th { flex: none; width: 40px; height: 24px; border-radius: 4px; overflow: hidden; background: var(--surface-2); }
	.th img { width: 100%; height: 100%; object-fit: cover; }
	.bt { flex: 0 1 auto; }
	.bm .faint { flex: 1; font-size: 12.5px; }
	.new { font-style: normal; font-size: 11px; font-weight: 600; padding: 0 6px; border-radius: 8px; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); }
</style>
