<script lang="ts">
	import { Camera, Eye, GitCompareArrows, History, Trash2 } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fileSize, fullDate, relTime } from '#lib/util.ts';
	import { TRIGGER_LABEL, changeText, priceDirection, type Diff, type Version } from './types.ts';

	let {
		id, count, viewing, canSave, onview, onsaved
	}: {
		id: string; count: number; viewing: Version | null; canSave: boolean;
		onview: (v: Version | null) => void; onsaved: () => void;
	} = $props();

	let versions = $state<Version[]>([]);
	let saving = $state(false);
	let diffFor = $state<number | null>(null);
	let diff = $state<Diff | null>(null);
	let showAll = $state(false);
	const PAGE = 8;

	async function load() {
		try {
			versions = await api.get<Version[]>(`/web/${id}/versions`);
		} catch (e) {
			ui.error(e);
		}
	}
	// Reloads when the bookmark changes or gains a version (a check, a re-fetch).
	$effect(() => {
		void id; void count;
		load();
	});

	async function saveNow() {
		saving = true;
		try {
			await api.post<Version>(`/web/${id}/versions`);
			ui.toast('Snapshot saved to history');
			onsaved();
			await load();
		} catch (e) {
			ui.error(e);
		}
		saving = false;
	}

	async function compare(v: Version) {
		if (diffFor === v.id) {
			diffFor = null;
			return;
		}
		diffFor = v.id;
		diff = null;
		try {
			diff = await api.get<Diff>(`/web/${id}/versions/${v.id}/diff`);
		} catch (e) {
			ui.error(e);
			diffFor = null;
		}
	}

	async function remove(v: Version) {
		const ok = await ui.confirm({
			title: 'Delete this version?',
			message: `The snapshot from ${fullDate(v.created_at)} is removed from the history. This cannot be undone.`,
			confirmLabel: 'Delete', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`/web/${id}/versions/${v.id}`);
			if (viewing?.id === v.id) onview(null);
			if (diffFor === v.id) diffFor = null;
			await load();
		} catch (e) {
			ui.error(e);
		}
	}

	let shown = $derived(showAll ? versions : versions.slice(0, PAGE));
</script>

<section class="history">
	<div class="head">
		<History size={15} /><b>History</b><span class="faint">{versions.length} {versions.length === 1 ? 'version' : 'versions'}</span>
		<span class="grow"></span>
		{#if canSave}
			<button class="btn" disabled={saving} onclick={saveNow}><Camera size={13} />{saving ? 'Saving…' : 'Save snapshot now'}</button>
		{/if}
	</div>

	{#if versions.length}
		<ol class="timeline">
			{#each shown as v (v.id)}
				{@const dir = priceDirection(v.change)}
				<li class:current={viewing?.id === v.id}>
					<span class="dot" class:change={v.trigger === 'change'}></span>
					<div class="row">
						<button class="when" disabled={!v.has_page} title={v.has_page ? 'View this version' : 'No saved page'} onclick={() => onview(viewing?.id === v.id ? null : v)}>
							<b>{fullDate(v.created_at)}</b>
							<span class="faint">{relTime(v.created_at)}</span>
						</button>
						<span class="tag" class:change={v.trigger === 'change'}>{TRIGGER_LABEL[v.trigger] ?? v.trigger}</span>
						<span class="grow"></span>
						{#if v.has_page}
							<button class="icon-btn" class:on={viewing?.id === v.id} title="View this version" onclick={() => onview(viewing?.id === v.id ? null : v)}><Eye size={14} /></button>
						{/if}
						{#if v.prev}
							<button class="icon-btn" class:on={diffFor === v.id} title="Compare with the version before" onclick={() => compare(v)}><GitCompareArrows size={14} /></button>
						{/if}
						<button class="icon-btn" title="Delete version" onclick={() => remove(v)}><Trash2 size={13} /></button>
					</div>
					{#if changeText(v.change) || v.price}
						<div class="sub small" class:down={dir === 'down'} class:up={dir === 'up'}>
							{changeText(v.change) || `Price ${v.price}`}
							{#if v.change && 'type' in v.change && v.change.type === 'posts'}
								<span class="faint">— {v.change.added.slice(0, 3).map((p) => p.title).filter(Boolean).join(' · ')}</span>
							{/if}
						</div>
					{/if}
					{#if v.size}<div class="faint tiny">{v.title ? v.title + ' · ' : ''}{fileSize(v.size)}</div>{/if}

					{#if diffFor === v.id}
						<div class="diff">
							{#if !diff}
								<div class="faint small">Comparing…</div>
							{:else if !diff.ops.length}
								<div class="faint small">The text is the same as the version before{diff.from_at ? ` (${fullDate(diff.from_at)})` : ''}. Only the layout or images may differ.</div>
							{:else}
								<div class="small dhead">
									Since {fullDate(diff.from_at)}: <span class="add">+{diff.added}</span> <span class="del">−{diff.removed}</span> lines
								</div>
								<div class="lines">
									{#each diff.ops as op, i (i)}
										{#if op.op === 'skip'}
											<div class="skip">⋯ {op.count} unchanged {op.count === 1 ? 'line' : 'lines'}</div>
										{:else}
											{#each op.lines ?? [] as line, j (j)}
												<div class="ln {op.op}"><span class="mark">{op.op === 'add' ? '+' : op.op === 'del' ? '−' : ' '}</span>{line}</div>
											{/each}
										{/if}
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ol>
		{#if versions.length > PAGE}
			<button class="btn ghost more" onclick={() => (showAll = !showAll)}>{showAll ? 'Show fewer' : `Show all ${versions.length}`}</button>
		{/if}
	{:else}
		<p class="faint small">No saved versions yet. {canSave ? 'Save a snapshot, or watch the page to keep one each time it changes.' : ''}</p>
	{/if}
</section>

<style>
	.history { margin-top: 18px; }
	.head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; font-size: 14px; flex-wrap: wrap; }
	.grow { flex: 1; }
	.small { font-size: 12.5px; }
	.tiny { font-size: 11.5px; }
	p { margin: 4px 0; }
	.timeline { list-style: none; margin: 0; padding: 0 0 0 14px; border-left: 2px solid var(--border); display: flex; flex-direction: column; gap: 2px; }
	li { position: relative; padding: 6px 8px; border-radius: 8px; }
	li.current { background: color-mix(in srgb, var(--accent) 10%, transparent); }
	.dot { position: absolute; left: -21px; top: 13px; width: 10px; height: 10px; border-radius: 50%; background: var(--bg); border: 2px solid var(--text-3); }
	.dot.change { border-color: var(--accent); background: var(--accent); }
	.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.when { display: flex; align-items: baseline; gap: 8px; color: inherit; font: inherit; font-size: 13.5px; text-align: left; padding: 0; }
	.when:not(:disabled):hover b { text-decoration: underline; }
	.tag { font-size: 11px; padding: 1px 6px; border-radius: 8px; background: var(--surface-2); color: var(--text-2); }
	.tag.change { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
	.sub { margin-top: 2px; color: var(--text-2); }
	.sub.down { color: var(--c-green, #2e8b57); }
	.sub.up { color: var(--c-red, #c0392b); }
	.icon-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; height: 26px; border-radius: 6px; color: var(--text-2); }
	.icon-btn:hover, .icon-btn.on { color: var(--text); background: var(--hover); }
	.more { margin: 6px 0 0 14px; }
	.diff { margin-top: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); overflow: hidden; }
	.diff > .small { padding: 8px 10px; }
	.dhead { padding: 6px 10px; border-bottom: 1px solid var(--border); }
	.dhead .add { color: var(--c-green, #2e8b57); font-weight: 600; }
	.dhead .del { color: var(--c-red, #c0392b); font-weight: 600; }
	.lines { max-height: 420px; overflow: auto; font-family: var(--mono, ui-monospace, monospace); font-size: 12px; line-height: 1.55; }
	.ln { padding: 0 10px 0 4px; white-space: pre-wrap; overflow-wrap: anywhere; }
	.ln .mark { display: inline-block; width: 16px; color: var(--text-3); user-select: none; }
	.ln.eq { color: var(--text-2); }
	.ln.add { background: color-mix(in srgb, var(--c-green, #2e8b57) 14%, transparent); }
	.ln.del { background: color-mix(in srgb, var(--c-red, #c0392b) 14%, transparent); text-decoration: line-through; text-decoration-color: color-mix(in srgb, currentColor 40%, transparent); }
	.skip { padding: 2px 10px; color: var(--text-3); background: var(--surface-2); font-size: 11.5px; }
</style>
