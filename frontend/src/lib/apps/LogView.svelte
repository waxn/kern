<script lang="ts">
	// A live log: asks the server for what came after the last offset, keeps the view at the bottom
	// while you are there. App logs have "<time> <mark> <text>" lines (mark: " " out, "!" err, "#" Kern).
	import { ArrowDown, Search, WrapText } from '@lucide/svelte';
	import { onDestroy, tick } from 'svelte';
	import { api } from '#lib/api.ts';

	let { url, live = true, kind = 'app', height = '100%', ondone, empty = 'Nothing here yet.' }: {
		url: string; live?: boolean; kind?: 'app' | 'build'; height?: string; ondone?: () => void; empty?: string;
	} = $props();

	interface Line { t: string; m: string; s: string }
	let lines = $state<Line[]>([]);
	let offset: number | null = null;
	let box = $state<HTMLDivElement>();
	let atBottom = $state(true);
	let wrap = $state(true);
	let filter = $state('');
	let timer: ReturnType<typeof setTimeout> | null = null;
	let stopped = false;
	let loadedUrl = '';
	const MAX = 5000;
	// eslint-disable-next-line no-control-regex
	const ANSI = /\u001b\[[0-9;?]*[A-Za-z]/g;

	function parse(text: string): Line[] {
		return text.split('\n').filter((l, i, all) => l !== '' || i < all.length - 1).map((raw) => {
			const l = raw.replace(ANSI, '');
			if (kind === 'app') {
				const m = /^(\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d)Z) ([ !#]) ?(.*)$/.exec(l);
				if (m) return { t: m[1], m: m[3], s: m[4] };
			}
			return { t: '', m: l.startsWith('▸') ? '>' : l.startsWith('✗') ? '!' : l.startsWith('✓') ? '+' : l.startsWith('$ ') ? '$' : ' ', s: l };
		});
	}

	async function poll() {
		timer = null;
		if (stopped) return;
		const myUrl = url;
		try {
			const sep = myUrl.includes('?') ? '&' : '?';
			const r = await api.get<{ text: string; offset: number; size: number; done?: boolean }>(myUrl + (offset === null ? '' : `${sep}offset=${offset}`));
			if (myUrl !== url) return;
			if (offset !== null && r.offset < offset) lines = [];
			if (r.text) {
				const add = parse(r.text);
				lines = lines.length + add.length > MAX ? [...lines, ...add].slice(-MAX) : [...lines, ...add];
				if (atBottom) tick().then(() => box && (box.scrollTop = box.scrollHeight));
			}
			offset = r.offset;
			if (r.done) {
				ondone?.();
				if (r.offset >= r.size) return;
			}
			if (r.offset < r.size) return poll();
		} catch {
			/* try again */
		}
		if (live && !stopped) timer = setTimeout(poll, document.visibilityState === 'visible' ? 1500 : 6000);
	}

	$effect(() => {
		if (url !== loadedUrl) {
			loadedUrl = url;
			lines = [];
			offset = null;
			if (timer) clearTimeout(timer);
			atBottom = true;
			poll();
		}
	});

	onDestroy(() => {
		stopped = true;
		if (timer) clearTimeout(timer);
	});

	function onScroll() {
		if (!box) return;
		atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
	}

	export function clear() {
		lines = [];
	}

	let shown = $derived(filter ? lines.filter((l) => l.s.toLowerCase().includes(filter.toLowerCase())) : lines);
	const local = (t: string) => (t ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '');
</script>

<div class="log" style:height>
	<div class="bar">
		<div class="find"><Search size={12} /><input bind:value={filter} placeholder="Filter" /></div>
		<span class="grow"></span>
		<button class="icon-btn" class:on={wrap} title="Wrap long lines" onclick={() => (wrap = !wrap)}><WrapText size={14} /></button>
	</div>
	<div class="out" class:wrap bind:this={box} onscroll={onScroll}>
		{#each shown as l, i (i)}
			<div class="ln m{l.m === ' ' ? 'o' : l.m === '!' ? 'e' : l.m === '#' ? 'k' : l.m === '>' ? 's' : l.m === '+' ? 'ok' : l.m === '$' ? 'c' : 'o'}">
				{#if l.t}<time title={new Date(l.t).toLocaleString()}>{local(l.t)}</time>{/if}<span>{l.s || ' '}</span>
			</div>
		{:else}
			<p class="none">{filter ? 'No lines match.' : empty}</p>
		{/each}
	</div>
	{#if !atBottom}
		<button class="jump" onclick={() => { if (box) box.scrollTop = box.scrollHeight; atBottom = true; }}><ArrowDown size={13} />Latest</button>
	{/if}
</div>

<style>
	.log { position: relative; display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); overflow: hidden; }
	.bar { display: flex; align-items: center; gap: 6px; padding: 4px 6px 4px 8px; border-bottom: 1px solid var(--border); background: var(--surface); }
	.find { display: flex; align-items: center; gap: 5px; color: var(--text-3); }
	.find input { width: 160px; border: 0; outline: 0; background: none; font-size: 12.5px; color: var(--text); }
	.grow { flex: 1; }
	.out { flex: 1; overflow: auto; padding: 8px 0; font: 12px/1.55 var(--font-mono); }
	.ln { display: flex; gap: 10px; padding: 0 12px; white-space: pre; }
	.out.wrap .ln { white-space: pre-wrap; overflow-wrap: anywhere; }
	.ln:hover { background: var(--hover); }
	.ln time { flex: none; color: var(--text-3); user-select: none; }
	.ln span { min-width: 0; }
	.me span { color: var(--c-red); }
	.mk span { color: var(--text-3); font-style: italic; }
	.ms span { color: var(--text); font-weight: 650; padding-top: 4px; }
	.mok span { color: var(--c-green); font-weight: 600; }
	.mc span { color: var(--c-blue); }
	.none { margin: 0; padding: 16px; color: var(--text-3); font-family: var(--font-sans); font-size: 13px; }
	.jump { position: absolute; right: 14px; bottom: 12px; display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 10px; border-radius: 13px; background: var(--surface-2); border: 1px solid var(--border-strong); font-size: 12px; box-shadow: var(--shadow); }
</style>
