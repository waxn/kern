<script lang="ts">
	import { History, RotateCcw, Save, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import { htmlToText } from '#lib/editor/dom.ts';
	import type { EditorDoc } from '#lib/editor/doc.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { ws } from '#lib/state/workspace.svelte.ts';
	import type { Block } from '#lib/types.ts';
	import { fullDate, relTime } from '#lib/util.ts';
	import StaticBlocks from './StaticBlocks.svelte';

	interface V { id: string; created_at: string; title: string; icon: string; reason: string; block_count: number; blocks?: Block[] }
	let { doc, onclose }: { doc: EditorDoc; onclose: () => void } = $props();

	let list = $state<V[]>([]);
	let selected = $state<V | null>(null);
	let compare = $state(true);
	let loading = $state(true);

	async function load() {
		await doc.flush();
		try {
			list = await api.get<V[]>(`/documents/${doc.id}/versions`);
			if (list.length) pick(list[0]);
		} catch (e) {
			ui.error(e);
		}
		loading = false;
	}
	onMount(load);

	async function pick(v: V) {
		selected = v;
		if (!v.blocks) {
			const full = await api.get<V>(`/versions/${v.id}`).catch(() => null);
			if (full && selected?.id === v.id) selected = { ...v, blocks: full.blocks };
			const i = list.findIndex((x) => x.id === v.id);
			if (full && i >= 0) list[i].blocks = full.blocks;
		}
	}

	async function saveNow() {
		await doc.flush();
		try {
			const v = await api.post<V>(`/documents/${doc.id}/versions`);
			list = [v, ...list];
			pick(v);
			ui.toast('Version saved');
		} catch (e) {
			ui.error(e);
		}
	}

	async function restore() {
		if (!selected) return;
		const ok = await ui.confirm({
			title: 'Restore this version?',
			message: `The page goes back to how it was ${relTime(selected.created_at)}. The current state is saved as a version first, so you can undo this.`,
			confirmLabel: 'Restore'
		});
		if (!ok) return;
		await doc.flush();
		try {
			await api.post(`/versions/${selected.id}/restore`);
			if (ws.docs[doc.id]) ws.docs[doc.id].title = selected.title;
			doc.status = 'loading';
			await doc.load();
			ui.toast('Version restored');
			onclose();
		} catch (e) {
			ui.error(e);
		}
	}

	// ----- diff (by line of text, in document order)
	function lines(blocks: Block[]): string[] {
		const out: string[] = [];
		const walk = (parent: string | null, depth: number) => {
			for (const b of blocks.filter((x) => (x.parent ?? null) === parent).sort((a, c) => a.position - c.position)) {
				const pre = b.type === 'todo' ? (b.props.checked ? '☑ ' : '☐ ') : b.type.startsWith('h') ? '# ' : b.type === 'bullet' ? '• ' : '';
				const text = b.type === 'table' ? (b.props.rows ?? []).map((r: string[]) => r.map(htmlToText).join(' | ')).join(' / ')
					: b.type === 'equation' ? `$$${b.props.tex ?? ''}$$` : b.props.url && !b.html ? `[${b.type}] ${b.props.name || b.props.url}` : htmlToText(b.html);
				out.push('  '.repeat(depth) + pre + text);
				walk(b.id, depth + 1);
			}
		};
		walk(null, 0);
		return out;
	}

	function diff(a: string[], b: string[]): { t: 'same' | 'add' | 'del'; s: string }[] {
		const n = a.length, m = b.length;
		const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
		for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
		const out: { t: 'same' | 'add' | 'del'; s: string }[] = [];
		let i = 0, j = 0;
		while (i < n && j < m) {
			if (a[i] === b[j]) (out.push({ t: 'same', s: a[i] }), i++, j++);
			else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: 'del', s: a[i++] });
			else out.push({ t: 'add', s: b[j++] });
		}
		while (i < n) out.push({ t: 'del', s: a[i++] });
		while (j < m) out.push({ t: 'add', s: b[j++] });
		return out;
	}

	let current = $derived(Object.values(doc.blocks) as Block[]);
	let changes = $derived(selected?.blocks && compare ? diff(lines(selected.blocks), lines(current)) : []);
	let changed = $derived(changes.filter((c) => c.t !== 'same').length);
	const reasons: Record<string, string> = { auto: 'Autosaved', manual: 'Saved by you', restore: 'Before a restore' };
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && !ui.confirmState && onclose()} />

<div class="vh">
	<header>
		<History size={16} />
		<b>Version history</b>
		<span class="faint truncate">{ws.docs[doc.id]?.title || doc.meta?.title || 'Untitled'}</span>
		<span class="grow"></span>
		<button class="btn" onclick={saveNow}><Save size={14} />Save version now</button>
		<button class="icon-btn" title="Close (Esc)" onclick={onclose}><X size={16} /></button>
	</header>
	<div class="body">
		<aside>
			<div class="item current"><b>Current version</b><span class="faint">Now</span></div>
			{#each list as v (v.id)}
				<button class="item" class:on={selected?.id === v.id} onclick={() => pick(v)} title={fullDate(v.created_at)}>
					<b>{new Date(v.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</b>
					<span class="faint">{reasons[v.reason] ?? v.reason} · {v.block_count} blocks · {relTime(v.created_at)}</span>
				</button>
			{:else}
				{#if !loading}<p class="faint none">No earlier versions yet. Kern saves one automatically when you return to a page after a pause, and you can save one now.</p>{/if}
			{/each}
		</aside>
		<main>
			{#if selected}
				<div class="banner">
					<span>Viewing the version from <b>{fullDate(selected.created_at)}</b>. This is not the current page.</span>
					<label class="check"><input type="checkbox" bind:checked={compare} />Compare with current</label>
					<button class="btn primary" onclick={restore}><RotateCcw size={14} />Restore this version</button>
				</div>
				<div class="sheet">
					{#if !selected.blocks}<p class="faint">Loading…</p>
					{:else if compare}
						<p class="faint small">{changed ? `${changed} changed ${changed === 1 ? 'line' : 'lines'}: red was in this version, green is new since.` : 'No differences in content.'}{selected.title !== (ws.docs[doc.id]?.title ?? '') ? ` Title then: “${selected.title || 'Untitled'}”.` : ''}</p>
						<div class="diff">
							{#each changes as c, i (i)}<div class="l {c.t}"><span class="sign">{c.t === 'add' ? '+' : c.t === 'del' ? '−' : ''}</span><span class="s">{c.s || ' '}</span></div>{/each}
						</div>
					{:else}
						<h1 class="ttl">{selected.icon} {selected.title || 'Untitled'}</h1>
						<StaticBlocks blocks={selected.blocks} />
					{/if}
				</div>
			{/if}
		</main>
	</div>
</div>

<style>
	.vh { position: fixed; inset: 0; z-index: 640; display: flex; flex-direction: column; background: var(--bg); }
	header { display: flex; align-items: center; gap: 10px; height: 48px; padding: 0 14px; border-bottom: 1px solid var(--border); }
	.grow { flex: 1; }
	.body { flex: 1; min-height: 0; display: flex; }
	aside { width: 290px; flex: none; overflow-y: auto; border-right: 1px solid var(--border); padding: 6px; background: var(--bg-side); }
	.item { display: flex; flex-direction: column; width: 100%; padding: 7px 10px; border-radius: var(--radius); text-align: left; }
	.item span { font-size: 12px; }
	button.item:hover { background: var(--hover); }
	.item.on { background: var(--active); }
	.item.current { border-left: 3px solid var(--accent); border-radius: 0 var(--radius) var(--radius) 0; margin-bottom: 4px; }
	.none { padding: 10px; font-size: 12.5px; }
	main { flex: 1; min-width: 0; overflow-y: auto; }
	.banner { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 20px; background: color-mix(in srgb, var(--c-orange) 16%, var(--bg)); border-bottom: 1px solid var(--border); }
	.banner span { flex: 1; min-width: 200px; }
	.check { display: flex; align-items: center; gap: 5px; color: var(--text-2); }
	.check input { accent-color: var(--accent); }
	.sheet { max-width: 820px; margin: 0 auto; padding: 20px 30px 60px; }
	.ttl { font-size: 30px; margin: 0 0 12px; }
	.small { font-size: 12.5px; }
	.diff { font: 13px/1.55 var(--font-mono); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
	.l { display: flex; white-space: pre-wrap; }
	.l .sign { flex: none; width: 22px; text-align: center; color: var(--text-3); }
	.l .s { flex: 1; padding-right: 8px; }
	.l.add { background: color-mix(in srgb, var(--c-green) 16%, transparent); }
	.l.del { background: color-mix(in srgb, var(--c-red) 16%, transparent); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--c-red) 60%, transparent); }
	.l.same { color: var(--text-2); }
	@media (max-width: 760px) { aside { width: 150px; } .sheet { padding: 14px; } }
</style>
