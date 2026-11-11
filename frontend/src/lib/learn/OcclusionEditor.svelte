<script lang="ts">
	import { Trash2, Upload } from '@lucide/svelte';
	import { api } from '../api.ts';
	import { ui } from '../state/ui.svelte.ts';
	import type { Region } from '../types.ts';
	import { uid } from '../util.ts';

	let { image = $bindable(''), regions = $bindable([]) }: { image?: string; regions?: Region[] } = $props();

	let box = $state<HTMLElement>();
	let draft = $state<{ x0: number; y0: number; x: number; y: number } | null>(null);
	let picker = $state<HTMLInputElement>();
	let busy = $state(false);

	async function upload(file?: File) {
		if (!file) return;
		busy = true;
		try {
			image = (await api.upload(file)).url;
		} catch (e) {
			ui.error(e);
		} finally {
			busy = false;
		}
	}

	function point(e: PointerEvent) {
		const r = box!.getBoundingClientRect();
		return { x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) };
	}

	function down(e: PointerEvent) {
		if ((e.target as HTMLElement).closest('.region')) return;
		e.preventDefault();
		box!.setPointerCapture(e.pointerId);
		const p = point(e);
		draft = { x0: p.x, y0: p.y, x: p.x, y: p.y };
	}

	function move(e: PointerEvent) {
		if (!draft) return;
		const p = point(e);
		draft.x = p.x;
		draft.y = p.y;
	}

	function up() {
		if (!draft) return;
		const d = draft;
		draft = null;
		const x = Math.min(d.x0, d.x), y = Math.min(d.y0, d.y);
		const w = Math.abs(d.x - d.x0), h = Math.abs(d.y - d.y0);
		if (w < 0.01 || h < 0.01) return;
		const n = regions.length ? Math.max(...regions.map((r) => r.n)) + 1 : 0;
		regions = [...regions, { id: uid(), n, x, y, w, h, label: '' }];
	}
</script>

{#if !image}
	<div class="drop">
		<input type="file" accept="image/*" hidden bind:this={picker} onchange={(e) => upload(e.currentTarget.files?.[0])} />
		<button class="btn" disabled={busy} onclick={() => picker?.click()}><Upload size={14} />{busy ? 'Uploading…' : 'Upload an image'}</button>
		<span class="faint">Then drag boxes over the parts to hide. Each box becomes a card.</span>
	</div>
{:else}
	<p class="hint faint">Drag on the image to hide a region. Each region becomes its own card.</p>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="stage" bind:this={box} onpointerdown={down} onpointermove={move} onpointerup={up}>
		<img src={image} alt="" draggable="false" />
		{#each regions as r, i (r.id)}
			<div class="region" style:left="{r.x * 100}%" style:top="{r.y * 100}%" style:width="{r.w * 100}%" style:height="{r.h * 100}%">{i + 1}</div>
		{/each}
		{#if draft}
			<div class="region draft" style:left="{Math.min(draft.x0, draft.x) * 100}%" style:top="{Math.min(draft.y0, draft.y) * 100}%"
				style:width="{Math.abs(draft.x - draft.x0) * 100}%" style:height="{Math.abs(draft.y - draft.y0) * 100}%"></div>
		{/if}
	</div>
	<div class="list">
		{#each regions as r, i (r.id)}
			<div class="row">
				<span class="n">{i + 1}</span>
				<input class="input" bind:value={r.label} placeholder="Answer (shown when revealed)" onkeydown={(e) => e.stopPropagation()} />
				<button class="icon-btn" title="Remove region" onclick={() => (regions = regions.filter((x) => x.id !== r.id))}><Trash2 size={13} /></button>
			</div>
		{/each}
		<button class="btn ghost" onclick={() => { image = ''; regions = []; }}>Change image</button>
	</div>
{/if}

<style>
	.drop { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 28px; border: 1px dashed var(--border-strong); border-radius: var(--radius); }
	.hint { margin: 0 0 6px; font-size: 12.5px; }
	.stage { position: relative; display: inline-block; max-width: 100%; cursor: crosshair; user-select: none; touch-action: none; }
	.stage img { display: block; max-width: 100%; max-height: 46vh; border-radius: var(--radius); }
	.region { position: absolute; display: grid; place-items: center; background: color-mix(in srgb, var(--accent) 70%, transparent); color: #17130c; font-weight: 700; border-radius: 3px; font-size: 12px; }
	.draft { background: color-mix(in srgb, var(--accent) 35%, transparent); border: 1.5px dashed var(--accent); }
	.list { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
	.row { display: flex; align-items: center; gap: 6px; }
	.row .input { flex: 1; }
	.n { width: 20px; text-align: center; color: var(--text-3); font-weight: 600; }
</style>
