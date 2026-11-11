<script lang="ts">
	/* The app-wide audio/video player. Mounted once in the root layout so playback survives
	   navigation; "full" is the big viewer, "mini" a small dock in the corner. */
	import {
		Download, Gauge, Maximize, Minimize, Minimize2, Maximize2, Music, Pause, PictureInPicture2, Play,
		RotateCcw, RotateCw, Volume1, Volume2, VolumeX, X
	} from '@lucide/svelte';
	import { fileSize } from '#lib/util.ts';
	import { coverColors, fileKind, fmtTime } from './kind.ts';
	import { player } from './player.svelte.ts';

	const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
	const WAVE_MAX_BYTES = 40 * 1024 * 1024;

	let el = $state<HTMLMediaElement>();
	let stage = $state<HTMLDivElement>();
	let paused = $state(true);
	let current = $state(0);
	let duration = $state(0);
	let buffered = $state<{ start: number; end: number }[]>([]);
	let volume = $state(load('kern.player.volume', 1));
	let muted = $state(false);
	let rate = $state(load('kern.player.rate', 1));
	let waiting = $state(false);
	let error = $state('');
	let fs = $state(false);
	let pip = $state(false);
	let idle = $state(false);
	let speedOpen = $state(false);
	let scrub = $state<number | null>(null); // fraction while dragging the seek bar
	let hover = $state<number | null>(null);
	let peaks = $state<number[] | null>(null);
	let canvas = $state<HTMLCanvasElement>();

	let f = $derived(player.file);
	let full = $derived(player.mode === 'full');
	let video = $derived(!!f && fileKind(f) === 'video');
	let shown = $derived(scrub !== null ? scrub * duration : current);
	let pct = $derived(duration ? (shown / duration) * 100 : 0);
	let colors = $derived(f ? coverColors(f.name) : ['#555', '#222']);
	const pipOk = typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && document.pictureInPictureEnabled;

	function load(key: string, fallback: number): number {
		try {
			const v = parseFloat(localStorage.getItem(key) ?? '');
			return isFinite(v) ? v : fallback;
		} catch {
			return fallback;
		}
	}
	function save(key: string, v: number) {
		try {
			localStorage.setItem(key, String(v));
		} catch {
			/* private mode */
		}
	}
	$effect(() => save('kern.player.volume', volume));
	$effect(() => save('kern.player.rate', rate));

	// A new file: reset state and (re)load the waveform for audio.
	$effect(() => {
		const file = f;
		void player.seq;
		error = '';
		peaks = null;
		scrub = null;
		if (!file || fileKind(file) !== 'audio' || (file.size ?? 0) > WAVE_MAX_BYTES) return;
		const ctl = new AbortController();
		waveform(file.url, ctl.signal).then((p) => !ctl.signal.aborted && (peaks = p), () => {});
		return () => ctl.abort();
	});

	$effect(() => {
		if (!f || !('mediaSession' in navigator)) return;
		try {
			navigator.mediaSession.metadata = new MediaMetadata({ title: f.name, artist: 'Kern' });
			navigator.mediaSession.setActionHandler('seekbackward', () => skip(-10));
			navigator.mediaSession.setActionHandler('seekforward', () => skip(10));
		} catch {
			/* not supported */
		}
	});

	async function waveform(url: string, signal: AbortSignal): Promise<number[]> {
		const buf = await (await fetch(url, { signal })).arrayBuffer();
		const ctx = new OfflineAudioContext(1, 1, 44100);
		const audio = await ctx.decodeAudioData(buf);
		const n = 480;
		const chans = Array.from({ length: Math.min(2, audio.numberOfChannels) }, (_, i) => audio.getChannelData(i));
		const step = Math.max(1, Math.floor(audio.length / n));
		const out: number[] = [];
		for (let i = 0; i < n; i++) {
			let peak = 0;
			const from = i * step;
			// Sample within the bucket: plenty for a picture and fast on long files.
			for (let j = 0; j < step; j += Math.max(1, Math.floor(step / 400)))
				for (const ch of chans) peak = Math.max(peak, Math.abs(ch[from + j] ?? 0));
			out.push(peak);
		}
		const max = Math.max(0.01, ...out);
		return out.map((v) => Math.sqrt(v / max)); // sqrt lifts quiet passages so they stay visible
	}

	// Draw the waveform; redraws as playback moves.
	$effect(() => {
		if (!canvas || !peaks) return;
		const c = canvas;
		const p = peaks;
		void pct;
		void hover;
		const draw = () => {
			const dpr = devicePixelRatio || 1;
			const w = c.clientWidth;
			const h = c.clientHeight;
			c.width = w * dpr;
			c.height = h * dpr;
			const g = c.getContext('2d')!;
			g.scale(dpr, dpr);
			const css = getComputedStyle(c);
			const on = css.getPropertyValue('--accent').trim() || '#e2a85a';
			const off = css.getPropertyValue('--wave-off').trim() || '#666';
			const bars = Math.max(20, Math.floor(w / 3));
			const played = (pct / 100) * bars;
			const hovered = hover !== null ? hover * bars : -1;
			for (let i = 0; i < bars; i++) {
				const v = p[Math.floor((i / bars) * p.length)];
				const bh = Math.max(2, v * h * 0.92);
				g.fillStyle = i < played ? on : off;
				g.globalAlpha = i >= played && i < hovered ? 0.85 : i < played ? 1 : 0.45;
				g.fillRect(i * 3, (h - bh) / 2, 2, bh);
			}
		};
		draw();
		const ro = new ResizeObserver(draw);
		ro.observe(c);
		return () => ro.disconnect();
	});

	$effect(() => {
		const v = el;
		if (!(v instanceof HTMLVideoElement)) return;
		const on = () => (pip = true);
		const off = () => (pip = false);
		v.addEventListener('enterpictureinpicture', on);
		v.addEventListener('leavepictureinpicture', off);
		return () => {
			v.removeEventListener('enterpictureinpicture', on);
			v.removeEventListener('leavepictureinpicture', off);
		};
	});

	function toggle() {
		if (!el) return;
		if (el.paused) el.play().catch(() => {});
		else el.pause();
	}
	function skip(s: number) {
		if (el) el.currentTime = Math.max(0, Math.min(duration || 0, el.currentTime + s));
	}
	function setVolume(v: number) {
		volume = Math.max(0, Math.min(1, v));
		if (volume > 0) muted = false;
	}
	async function fullscreen() {
		if (!stage) return;
		if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
		else await stage.requestFullscreen().catch(() => {});
	}
	async function togglePip() {
		if (!(el instanceof HTMLVideoElement)) return;
		try {
			if (document.pictureInPictureElement) await document.exitPictureInPicture();
			else await el.requestPictureInPicture();
		} catch {
			/* blocked */
		}
	}
	function close() {
		if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
		if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
		el?.pause();
		player.close();
	}
	/** Leaving the big view keeps it playing in the dock; a paused file just closes. */
	function dismiss() {
		if (paused) close();
		else player.minimize();
	}

	function frac(e: PointerEvent, target: HTMLElement) {
		const r = target.getBoundingClientRect();
		return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
	}
	function seekDown(e: PointerEvent) {
		if (!duration) return;
		const t = e.currentTarget as HTMLElement;
		t.setPointerCapture(e.pointerId);
		scrub = frac(e, t);
	}
	function seekMove(e: PointerEvent) {
		const t = e.currentTarget as HTMLElement;
		hover = frac(e, t);
		if (scrub !== null) scrub = hover;
	}
	function seekUp() {
		if (scrub !== null && el) el.currentTime = scrub * duration;
		scrub = null;
	}

	let idleTimer: ReturnType<typeof setTimeout> | undefined;
	function poke() {
		idle = false;
		clearTimeout(idleTimer);
		idleTimer = setTimeout(() => (idle = !paused && video && full && !speedOpen), 2500);
	}
	$effect(() => {
		if (paused) idle = false;
		else poke();
	});

	function onError() {
		const code = el?.error?.code;
		error = code === 4 ? 'Your browser cannot play this format.' : code === 2 ? 'The file could not be loaded.' : 'Playback failed.';
	}

	function keydown(e: KeyboardEvent) {
		if (!f || !full || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
		const t = e.target as HTMLElement;
		if (t?.closest?.('input, textarea, select, [contenteditable]')) return;
		const k = e.key;
		const act = (fn: () => void) => {
			e.preventDefault();
			fn();
			poke();
		};
		if (k === ' ' || k === 'k' || k === 'K') return act(toggle);
		if (k === 'ArrowLeft' || k === 'j') return act(() => skip(k === 'j' || e.shiftKey ? -10 : -5));
		if (k === 'ArrowRight' || k === 'l') return act(() => skip(k === 'l' || e.shiftKey ? 10 : 5));
		if (k === 'ArrowUp') return act(() => setVolume(volume + 0.05));
		if (k === 'ArrowDown') return act(() => setVolume(volume - 0.05));
		if (k === 'm' || k === 'M') return act(() => (muted = !muted));
		if ((k === 'f' || k === 'F') && video) return act(fullscreen);
		if ((k === 'p' || k === 'P') && video && pipOk) return act(togglePip);
		if (k === '>' || k === '<')
			return act(() => (rate = SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, SPEEDS.indexOf(rate) + (k === '>' ? 1 : -1)))] ?? 1));
		if (/^[0-9]$/.test(k) && duration) return act(() => el && (el.currentTime = (Number(k) / 10) * duration));
		if (k === 'Escape' && !document.fullscreenElement) return act(dismiss);
	}
</script>

<svelte:window onkeydown={keydown} />
<svelte:document onfullscreenchange={() => (fs = !!document.fullscreenElement)} />

{#snippet seekbar(thin: boolean)}
	<div class="seek" class:thin role="slider" tabindex="-1" aria-label="Seek" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(shown)}
		onpointerdown={seekDown} onpointermove={seekMove} onpointerup={seekUp} onpointercancel={seekUp} onpointerleave={() => (hover = null)}>
		<div class="rail">
			{#each buffered as b, i (i)}<div class="buf" style="left:{(b.start / (duration || 1)) * 100}%;width:{((b.end - b.start) / (duration || 1)) * 100}%"></div>{/each}
			<div class="played" style="width:{pct}%"></div>
			<div class="knob" style="left:{pct}%"></div>
		</div>
		{#if hover !== null && duration && !thin}<div class="tip" style="left:{hover * 100}%">{fmtTime(hover * duration)}</div>{/if}
	</div>
{/snippet}

{#snippet volumeCtl()}
	{@const VolIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2}
	<div class="vol">
		<button class="cbtn" title={muted ? 'Unmute (M)' : 'Mute (M)'} onclick={() => (muted = !muted)}><VolIcon size={18} /></button>
		<input type="range" min="0" max="1" step="0.01" value={muted ? 0 : volume} aria-label="Volume" style="--v:{(muted ? 0 : volume) * 100}%"
			oninput={(e) => setVolume(parseFloat(e.currentTarget.value))} />
	</div>
{/snippet}

{#snippet controls()}
	<div class="row">
		<button class="cbtn play" title={paused ? 'Play (Space)' : 'Pause (Space)'} onclick={toggle}>
			{#if paused}<Play size={20} fill="currentColor" />{:else}<Pause size={20} fill="currentColor" />{/if}
		</button>
		<button class="cbtn" title="Back 10 s (J)" onclick={() => skip(-10)}><RotateCcw size={17} /></button>
		<button class="cbtn" title="Forward 10 s (L)" onclick={() => skip(10)}><RotateCw size={17} /></button>
		{@render volumeCtl()}
		<span class="time"><b>{fmtTime(shown)}</b> / {fmtTime(duration)}</span>
		<span class="grow"></span>
		<div class="speed">
			<button class="cbtn wide" class:on={rate !== 1} title="Playback speed (&lt; &gt;)" onclick={() => (speedOpen = !speedOpen)}><Gauge size={16} />{rate}×</button>
			{#if speedOpen}
				<div class="popover menu">
					{#each SPEEDS as s (s)}<button class="menu-item" class:active={s === rate} onclick={() => { rate = s; speedOpen = false; }}>{s === 1 ? 'Normal' : s + '×'}</button>{/each}
				</div>
			{/if}
		</div>
		{#if video && pipOk}<button class="cbtn" class:on={pip} title="Picture in picture (P)" onclick={togglePip}><PictureInPicture2 size={17} /></button>{/if}
		{#if video}<button class="cbtn" title={fs ? 'Exit full screen (F)' : 'Full screen (F)'} onclick={fullscreen}>{#if fs}<Minimize size={17} />{:else}<Maximize size={17} />{/if}</button>{/if}
	</div>
{/snippet}

{#if f}
	<div class="dock" class:full class:mini={!full} class:video class:audio={!video}>
		{#if full}
			<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
			<div class="backdrop" onclick={dismiss}></div>
		{/if}
		<div class="frame" role="region" aria-label="Media player">
			{#if full}
				<div class="bar">
					<span class="truncate">{f.name}</span>
					<button class="icon-btn" title="Keep playing in the corner (Esc)" onclick={() => player.minimize()}><Minimize2 size={15} /></button>
					<a class="icon-btn" href={f.url} download={f.name} title="Download"><Download size={15} /></a>
					<button class="icon-btn" title="Close" onclick={close}><X size={16} /></button>
				</div>
			{/if}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="stage" class:idle bind:this={stage} onpointermove={poke}>
				{#if video}
					<!-- svelte-ignore a11y_media_has_caption, a11y_click_events_have_key_events -->
					<video bind:this={el} src={f.url} autoplay playsinline preload="metadata"
						bind:paused bind:currentTime={current} bind:duration bind:buffered bind:volume bind:muted bind:playbackRate={rate}
						onwaiting={() => (waiting = true)} onplaying={() => (waiting = false)} oncanplay={() => (waiting = false)} onerror={onError}
						onclick={() => (full ? toggle() : player.expand())} ondblclick={() => full && fullscreen()}></video>
				{:else}
					<audio bind:this={el} src={f.url} autoplay preload="metadata"
						bind:paused bind:currentTime={current} bind:duration bind:buffered bind:volume bind:muted bind:playbackRate={rate}
						onwaiting={() => (waiting = true)} onplaying={() => (waiting = false)} oncanplay={() => (waiting = false)} onerror={onError}></audio>
				{/if}

				{#if full && !video}
					<div class="cover" style="--c1:{colors[0]};--c2:{colors[1]}">
						<div class="art" class:spin={!paused}><Music size={44} strokeWidth={1.4} /></div>
						<div class="title">
							<b class="truncate">{f.name.replace(/\.[^.]+$/, '')}</b>
							<span>Audio{f.size ? ' · ' + fileSize(f.size) : ''}{duration ? ' · ' + fmtTime(duration) : ''}</span>
						</div>
					</div>
					{#if peaks}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div class="wave" onpointerdown={seekDown} onpointermove={seekMove} onpointerup={seekUp} onpointercancel={seekUp} onpointerleave={() => (hover = null)}>
							<canvas bind:this={canvas}></canvas>
							{#if hover !== null && duration}<div class="tip" style="left:{hover * 100}%">{fmtTime(hover * duration)}</div>{/if}
						</div>
					{:else}
						<div class="wave">{@render seekbar(false)}</div>
					{/if}
				{/if}

				{#if error}
					<div class="msg"><p>{error}</p><a class="btn" href={f.url} download={f.name}><Download size={14} />Download instead</a></div>
				{:else if waiting && video}
					<div class="spinner"></div>
				{/if}

				{#if full}
					<div class="controls">
						{#if video}{@render seekbar(false)}{/if}
						{@render controls()}
					</div>
				{:else}
					<div class="minictl">
						{#if !video}<div class="mini-art" style="--c1:{colors[0]};--c2:{colors[1]}"><Music size={16} /></div>{/if}
						{#if !video}<button class="mini-name truncate" title="Open player" onclick={() => player.expand()}>{f.name}<span>{fmtTime(shown)} / {fmtTime(duration)}</span></button>{/if}
						<button class="cbtn" title={paused ? 'Play' : 'Pause'} onclick={toggle}>{#if paused}<Play size={16} fill="currentColor" />{:else}<Pause size={16} fill="currentColor" />{/if}</button>
						<button class="cbtn" title="Open player" onclick={() => player.expand()}><Maximize2 size={15} /></button>
						<button class="cbtn" title="Stop and close" onclick={close}><X size={16} /></button>
						<div class="mini-seek">{@render seekbar(true)}</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.dock { --wave-off: var(--text-3); }
	.dock.full { position: fixed; inset: 0; z-index: 940; display: flex; flex-direction: column; animation: fade 0.12s; }
	.backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.86); }
	.full .frame { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; pointer-events: none; }
	.full .frame > * { pointer-events: auto; }
	.bar { display: flex; align-items: center; gap: 6px; height: 44px; padding: 0 12px; color: #eee; flex: none; }
	.bar span { flex: 1; }
	.bar :global(.icon-btn) { color: #ddd; }
	.bar :global(.icon-btn:hover) { background: rgba(255, 255, 255, 0.1); color: #fff; }

	.stage { position: relative; }
	.full .stage { flex: 1; min-height: 0; margin: 0 auto 20px; width: min(1200px, calc(100% - 40px)); display: flex; flex-direction: column; justify-content: center; }
	.full.video .stage { background: #000; border-radius: 8px; overflow: hidden; }
	.full.video .stage:fullscreen { width: 100%; margin: 0; border-radius: 0; }
	video { display: block; width: 100%; height: 100%; object-fit: contain; background: #000; }
	.full video { position: absolute; inset: 0; }
	.stage.idle, .stage.idle video { cursor: none; }

	/* controls */
	.controls { position: relative; z-index: 2; padding: 6px 12px 8px; color: #f1f1f1; }
	.full.video .controls { position: absolute; left: 0; right: 0; bottom: 0; padding-top: 34px; background: linear-gradient(transparent, rgba(0, 0, 0, 0.72)); transition: opacity 0.2s var(--ease); }
	.stage.idle .controls { opacity: 0; pointer-events: none; }
	.row { display: flex; align-items: center; gap: 2px; }
	.grow { flex: 1; }
	.cbtn { display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 34px; min-width: 34px; padding: 0 6px; border-radius: 6px; color: inherit; opacity: 0.9; font-size: 12.5px; font-variant-numeric: tabular-nums; }
	.cbtn:hover { opacity: 1; background: rgba(255, 255, 255, 0.12); }
	.cbtn.on { color: var(--accent); }
	.cbtn.play { width: 40px; }
	.time { margin-left: 8px; font-size: 12.5px; opacity: 0.85; font-variant-numeric: tabular-nums; white-space: nowrap; }
	.time b { font-weight: 550; }
	.vol { display: flex; align-items: center; }
	.vol input { width: 0; opacity: 0; transition: width 0.15s var(--ease), opacity 0.15s; }
	.vol:hover input, .vol:focus-within input { width: 78px; opacity: 1; margin: 0 6px 0 2px; }
	input[type='range'] { appearance: none; height: 4px; border-radius: 2px; background: linear-gradient(to right, currentColor var(--v), rgba(255, 255, 255, 0.25) var(--v)); cursor: pointer; }
	input[type='range']::-webkit-slider-thumb { appearance: none; width: 12px; height: 12px; border-radius: 50%; background: #fff; }
	input[type='range']::-moz-range-thumb { width: 12px; height: 12px; border: 0; border-radius: 50%; background: #fff; }
	.speed { position: relative; }
	.speed .menu { position: absolute; bottom: 40px; right: 0; padding: 4px; min-width: 110px; color: var(--text); z-index: 5; }

	.seek { position: relative; height: 16px; display: flex; align-items: center; cursor: pointer; touch-action: none; }
	.seek.thin { height: 10px; }
	.rail { position: relative; width: 100%; height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 0.22); transition: height 0.1s; }
	.seek:hover .rail { height: 6px; }
	.thin .rail, .seek.thin:hover .rail { height: 3px; }
	.buf { position: absolute; top: 0; bottom: 0; background: rgba(255, 255, 255, 0.35); border-radius: 2px; }
	.played { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); border-radius: 2px; }
	.knob { position: absolute; top: 50%; width: 13px; height: 13px; margin: -6.5px 0 0 -6.5px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.25); transform: scale(0); transition: transform 0.1s; }
	.seek:hover .knob { transform: scale(1); }
	.thin .knob { display: none; }
	.tip { position: absolute; bottom: 100%; transform: translateX(-50%); margin-bottom: 6px; padding: 2px 6px; border-radius: 4px; background: rgba(0, 0, 0, 0.8); color: #fff; font-size: 11.5px; font-variant-numeric: tabular-nums; pointer-events: none; white-space: nowrap; }

	/* audio, full view */
	.full.audio .stage { width: min(620px, calc(100% - 40px)); flex: none; margin: auto; padding: 22px 22px 10px; border-radius: 14px; background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
	.full.audio .controls { color: var(--text); padding: 4px 0 0; }
	.full.audio .cbtn:hover { background: var(--hover); }
	.full.audio .rail { background: color-mix(in srgb, var(--text) 16%, transparent); }
	.full.audio .buf { background: color-mix(in srgb, var(--text) 22%, transparent); }
	.full.audio input[type='range'] { background: linear-gradient(to right, var(--accent) var(--v), color-mix(in srgb, var(--text) 18%, transparent) var(--v)); }
	.full.audio input[type='range']::-webkit-slider-thumb { background: var(--text); }
	.cover { display: flex; align-items: center; gap: 18px; }
	.art { width: 104px; height: 104px; flex: none; display: grid; place-items: center; border-radius: 12px; color: rgba(255, 255, 255, 0.9); background: radial-gradient(circle at 30% 25%, var(--c1), var(--c2)); box-shadow: 0 10px 30px color-mix(in srgb, var(--c2) 50%, transparent); }
	.art.spin :global(svg) { animation: bob 1.6s ease-in-out infinite; }
	@keyframes bob { 50% { transform: translateY(-3px) rotate(-4deg); } }
	.title { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
	.title b { font-size: 18px; font-weight: 620; }
	.title span { color: var(--text-2); font-size: 13px; }
	.wave { position: relative; height: 72px; margin: 18px 0 4px; display: flex; align-items: center; cursor: pointer; touch-action: none; }
	.wave canvas { width: 100%; height: 100%; display: block; }

	.msg { position: absolute; inset: 0; z-index: 3; display: grid; place-content: center; justify-items: center; gap: 10px; text-align: center; color: #eee; background: rgba(0, 0, 0, 0.55); }
	.full.audio .msg { position: static; color: var(--text-2); background: none; padding: 14px 0 0; }
	.mini .msg { font-size: 12px; }
	.spinner { position: absolute; left: 50%; top: 50%; width: 36px; height: 36px; margin: -18px; border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.25); border-top-color: #fff; animation: spin 0.8s linear infinite; pointer-events: none; }
	@keyframes spin { to { transform: rotate(360deg); } }

	/* mini dock */
	.dock.mini { position: fixed; right: 16px; bottom: 16px; z-index: 945; width: 340px; max-width: calc(100vw - 32px); border-radius: 10px; overflow: hidden; background: var(--surface); box-shadow: var(--shadow); animation: pop 0.14s var(--ease); }
	.mini.video video { aspect-ratio: 16 / 9; height: auto; cursor: pointer; }
	.minictl { display: flex; align-items: center; gap: 2px; padding: 6px 6px 10px 8px; color: var(--text); position: relative; }
	.mini.video .minictl { position: absolute; left: 0; right: 0; bottom: 0; justify-content: flex-end; color: #fff; padding-top: 26px; background: linear-gradient(transparent, rgba(0, 0, 0, 0.7)); opacity: 0; transition: opacity 0.15s; }
	.mini.video:hover .minictl, .mini.video:focus-within .minictl { opacity: 1; }
	.mini .cbtn { height: 30px; min-width: 30px; }
	.mini.audio .cbtn:hover { background: var(--hover); }
	.mini-art { width: 34px; height: 34px; flex: none; display: grid; place-items: center; border-radius: 6px; color: #fff; background: radial-gradient(circle at 30% 25%, var(--c1), var(--c2)); }
	.mini-name { flex: 1; display: flex; flex-direction: column; align-items: flex-start; padding: 0 6px; font-weight: 550; font-size: 13px; text-align: left; }
	.mini-name span { font-weight: 400; font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
	.mini-seek { position: absolute; left: 0; right: 0; bottom: 0; padding: 0 0; }
	.mini.audio .rail { background: color-mix(in srgb, var(--text) 14%, transparent); border-radius: 0; }
	.mini.audio .buf { background: color-mix(in srgb, var(--text) 20%, transparent); }

	@media (max-width: 600px) {
		.vol input { display: none; }
		.time { margin-left: 2px; font-size: 11.5px; }
		.full .stage { width: calc(100% - 16px); }
		.art { width: 72px; height: 72px; }
	}
</style>
