<script lang="ts">
	// A live log: asks the server for what came after the last offset and keeps going until the
	// server says it is done. "Follow" keeps the view at the bottom; scrolling up lets go of it.
	// App logs have "<time> <mark> <text>" lines (mark: " " out, "!" err, "#" Kern); build logs have
	// "[HH:MM:SS] text" lines with "▸" phase headers and "✗" errors.
	import { ArrowDown, Check, Copy, ListEnd, Search, WrapText } from '@lucide/svelte';
	import { onDestroy, tick } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { DeployLog, Phase } from './types.ts';

	let { url, live = true, kind = 'app', height = '100%', ondone, onphases, empty = 'Nothing here yet.' }: {
		url: string; live?: boolean; kind?: 'app' | 'build'; height?: string; ondone?: () => void; onphases?: (p: Phase[]) => void; empty?: string;
	} = $props();

	// t: full timestamp when the line has one; c: the clock shown in front of it.
	interface Line { t: string; c: string; m: string; s: string }
	let lines = $state<Line[]>([]);
	let offset: number | null = null;
	let box = $state<HTMLDivElement>();
	let follow = $state(true);
	let wrap = $state(true);
	let filter = $state('');
	let copied = $state(false);
	let timer: ReturnType<typeof setTimeout> | null = null;
	let stopped = false;
	let loadedUrl = '';
	let gen = 0;
	let busy = false;
	let finished = false;
	const MAX = 5000;
	// eslint-disable-next-line no-control-regex
	const ANSI = /\u001b\[[0-9;?]*[A-Za-z]/g;
	const local = (t: string) => (t ? new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '');

	function parse(text: string): Line[] {
		return text.split('\n').filter((l, i, all) => l !== '' || i < all.length - 1).map((raw) => {
			let l = raw.replace(ANSI, '');
			if (kind === 'app') {
				const m = /^(\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d)Z) ([ !#]) ?(.*)$/.exec(l);
				if (m) return { t: m[1], c: local(m[1]), m: m[3], s: m[4] };
			}
			let c = '';
			const b = /^\[(\d\d:\d\d:\d\d)\] ?/.exec(l);
			if (b) {
				c = b[1];
				l = l.slice(b[0].length);
			}
			const head = l.trimStart();
			return { t: '', c, m: head.startsWith('▸') ? '>' : head.startsWith('✗') ? '!' : head.startsWith('✓') ? '+' : l.startsWith('$ ') ? '$' : ' ', s: l };
		});
	}

	async function poll() {
		timer = null;
		if (stopped || busy) return;
		const myGen = gen;
		busy = true;
		try {
			for (;;) {
				const sep = url.includes('?') ? '&' : '?';
				const r = await api.get<DeployLog>(url + (offset === null ? '' : `${sep}offset=${offset}`));
				if (myGen !== gen) return;
				if (offset !== null && r.offset < offset) lines = [];
				if (r.text) {
					const add = parse(r.text);
					lines = lines.length + add.length > MAX ? [...lines, ...add].slice(-MAX) : [...lines, ...add];
					if (follow) tick().then(() => box && (box.scrollTop = box.scrollHeight));
				}
				offset = r.offset;
				if (r.phases) onphases?.(r.phases);
				if (r.done && r.offset >= r.size) {
					finished = true;
					ondone?.();
				}
				if (r.offset < r.size) continue;
				break;
			}
		} catch {
			/* try again */
		} finally {
			if (myGen === gen) busy = false;
		}
		if (myGen === gen && live && !finished && !stopped) timer = setTimeout(poll, document.visibilityState === 'visible' ? 1500 : 6000);
	}

	$effect(() => {
		if (url !== loadedUrl) {
			loadedUrl = url;
			lines = [];
			offset = null;
			finished = false;
			busy = false;
			gen++;
			if (timer) clearTimeout(timer);
			follow = true;
			poll();
		}
	});

	// The deployment just ended: read what was written after the last poll.
	let wasLive = true;
	$effect(() => {
		const now = live;
		if (wasLive && !now && !finished && loadedUrl) {
			if (timer) clearTimeout(timer);
			poll();
		}
		wasLive = now;
	});

	onDestroy(() => {
		stopped = true;
		if (timer) clearTimeout(timer);
	});

	function onScroll() {
		if (!box) return;
		follow = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
	}

	function toBottom() {
		follow = true;
		tick().then(() => box && (box.scrollTop = box.scrollHeight));
	}

	async function copy() {
		const text = lines.map((l) => (l.c ? `${l.c} ${l.s}` : l.s)).join('\n');
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {
			ui.toast('Could not copy the log', { kind: 'error' });
		}
	}

	export function clear() {
		lines = [];
	}

	let shown = $derived(filter ? lines.filter((l) => l.s.toLowerCase().includes(filter.toLowerCase())) : lines);
</script>

<div class="log" style:height>
	<div class="bar">
		<div class="find"><Search size={12} /><input bind:value={filter} placeholder="Filter" /></div>
		<span class="grow"></span>
		<button class="icon-btn" title="Copy the log" disabled={!lines.length} onclick={copy}>{#if copied}<Check size={14} />{:else}<Copy size={14} />{/if}</button>
		<button class="icon-btn" class:on={follow} title={follow ? 'Following the newest line' : 'Follow the newest line'} aria-pressed={follow} onclick={() => (follow ? (follow = false) : toBottom())}><ListEnd size={14} /></button>
		<button class="icon-btn" class:on={wrap} title="Wrap long lines" aria-pressed={wrap} onclick={() => (wrap = !wrap)}><WrapText size={14} /></button>
	</div>
	<div class="out" class:wrap bind:this={box} onscroll={onScroll}>
		{#each shown as l, i (i)}
			<div class="ln m{l.m === ' ' ? 'o' : l.m === '!' ? 'e' : l.m === '#' ? 'k' : l.m === '>' ? 's' : l.m === '+' ? 'ok' : l.m === '$' ? 'c' : 'o'}">
				{#if l.c}<time title={l.t ? new Date(l.t).toLocaleString() : ''}>{l.c}</time>{/if}<span>{l.s || ' '}</span>
			</div>
		{:else}
			<p class="none">{filter ? 'No lines match.' : empty}</p>
		{/each}
	</div>
	{#if !follow}
		<button class="jump" onclick={toBottom}><ArrowDown size={13} />Latest</button>
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
	.me { background: color-mix(in srgb, var(--danger) 9%, transparent); box-shadow: inset 2px 0 0 var(--danger); }
	.me span { color: var(--c-red); font-weight: 550; }
	.mk span { color: var(--text-3); font-style: italic; }
	.ms span { color: var(--text); font-weight: 650; padding-top: 4px; }
	.mok span { color: var(--c-green); font-weight: 600; }
	.mc span { color: var(--c-blue); }
	.none { margin: 0; padding: 16px; color: var(--text-3); font-family: var(--font-sans); font-size: 13px; }
	.jump { position: absolute; right: 14px; bottom: 12px; display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 10px; border-radius: 13px; background: var(--surface-2); border: 1px solid var(--border-strong); font-size: 12px; box-shadow: var(--shadow); }
</style>
