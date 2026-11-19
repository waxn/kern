<script lang="ts">
	// A small 3D knowledge graph that slowly turns, with one node that has drifted off and cannot
	// find a link. Drawn on a canvas with hand-rolled perspective so it adds no dependency.
	import { onMount } from 'svelte';

	let canvas: HTMLCanvasElement;
	let wrap: HTMLDivElement;

	type V = { x: number; y: number; z: number };
	type Node = V & { r: number; phase: number };

	onMount(() => {
		const ctx = canvas.getContext('2d')!;
		const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
		let w = 0, h = 0, dpr = 1, raf = 0;
		let colors = { accent: '#e2a85a', text: '#e7e5e0', dim: '#706e69', glow: '#ffd89a', light: false };

		function readColors() {
			const cs = getComputedStyle(document.documentElement);
			const pick = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
			const light = document.documentElement.dataset.theme === 'light';
			const accent = pick('--accent', '#e2a85a');
			colors = {
				accent,
				text: pick('--text', '#e7e5e0'),
				dim: pick('--text-3', '#706e69'),
				glow: light ? accent : `color-mix(in srgb, ${accent} 55%, white)`,
				light
			};
		}

		// Deterministic scatter so the shape is stable between visits.
		let seed = 7;
		const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
		const nodes: Node[] = [{ x: 0, y: 0, z: 0, r: 5.5, phase: 0 }];
		for (let i = 0; i < 64; i++) {
			const u = rnd() * 2 - 1, t = rnd() * Math.PI * 2;
			const rad = 0.35 + Math.pow(rnd(), 0.6) * 0.65;
			const s = Math.sqrt(1 - u * u);
			nodes.push({ x: s * Math.cos(t) * rad, y: u * rad * 0.8, z: s * Math.sin(t) * rad, r: 1.6 + rnd() * 2, phase: rnd() * 6.28 });
		}
		const edges: [number, number][] = [];
		for (let i = 0; i < nodes.length; i++) {
			const near = nodes
				.map((n, j) => ({ j, d: (n.x - nodes[i].x) ** 2 + (n.y - nodes[i].y) ** 2 + (n.z - nodes[i].z) ** 2 }))
				.filter((o) => o.j !== i)
				.sort((a, b) => a.d - b.d)
				.slice(0, i === 0 ? 7 : 2);
			for (const o of near) if (!edges.some(([a, b]) => (a === i && b === o.j) || (a === o.j && b === i))) edges.push([i, o.j]);
		}
		const packets = Array.from({ length: 14 }, () => ({ e: Math.floor(rnd() * edges.length), t: rnd(), v: 0.15 + rnd() * 0.25 }));

		let mx = 0, my = 0, smx = 0, smy = 0, t0 = performance.now();

		function resize() {
			const r = wrap.getBoundingClientRect();
			dpr = Math.min(devicePixelRatio || 1, 2);
			w = r.width; h = r.height;
			canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			readColors();
			if (reduce) draw(0);
		}

		function project(p: V, ry: number, rx: number, scale: number) {
			const cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
			let x = p.x * cy - p.z * sy, z = p.x * sy + p.z * cy;
			const y = p.y * cx - z * sx; z = p.y * sx + z * cx;
			const f = 2.6 / (2.6 + z);
			return { x: w / 2 + x * scale * f, y: h / 2 + y * scale * f, z, f };
		}

		function draw(now: number) {
			const t = (now - t0) / 1000;
			smx += (mx - smx) * 0.05; smy += (my - smy) * 0.05;
			const ry = t * 0.16 + smx * 0.7, rx = -0.28 + smy * 0.4;
			const scale = Math.min(w, h * 1.25) * 0.4;
			ctx.clearRect(0, 0, w, h);
			if (colors.light) ctx.globalCompositeOperation = 'source-over';

			const P = nodes.map((n) => project(n, ry, rx, scale));
			const fade = (z: number) => Math.max(0.08, Math.min(1, 0.62 - z * 0.5));

			// Soft kernel glow behind everything.
			const k = P[0], gr = scale * 0.7;
			const g = ctx.createRadialGradient(k.x, k.y, 0, k.x, k.y, gr);
			g.addColorStop(0, colors.accent + (colors.light ? '40' : '55'));
			g.addColorStop(1, colors.accent + '00');
			ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

			// Edges.
			ctx.lineWidth = 1;
			for (const [a, b] of edges) {
				const pa = P[a], pb = P[b];
				ctx.globalAlpha = fade((pa.z + pb.z) / 2) * 0.55;
				ctx.strokeStyle = a === 0 || b === 0 ? colors.accent : colors.dim;
				ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
			}

			// Light packets running along edges.
			ctx.fillStyle = colors.glow;
			for (const p of packets) {
				p.t += p.v * 0.016 * (reduce ? 0 : 1);
				if (p.t > 1) { p.t = 0; p.e = Math.floor(rnd() * edges.length); }
				const [a, b] = edges[p.e];
				const x = P[a].x + (P[b].x - P[a].x) * p.t, y = P[a].y + (P[b].y - P[a].y) * p.t;
				ctx.globalAlpha = fade((P[a].z + P[b].z) / 2) * 1.3;
				ctx.beginPath(); ctx.arc(x, y, 2, 0, 7); ctx.fill();
			}

			// Nodes, far to near.
			const order = P.map((p, i) => i).sort((i, j) => P[j].z - P[i].z);
			for (const i of order) {
				const p = P[i], n = nodes[i];
				const pulse = 1 + Math.sin(t * 1.6 + n.phase) * 0.12;
				const r = n.r * p.f * pulse * (i === 0 ? 1.5 : 1.25);
				ctx.globalAlpha = i === 0 ? 1 : fade(p.z);
				ctx.fillStyle = i === 0 ? colors.accent : colors.text;
				ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.fill();
				if (i === 0) {
					ctx.globalAlpha = 0.35 + Math.sin(t * 1.4) * 0.12;
					ctx.strokeStyle = colors.accent; ctx.lineWidth = 1.5;
					ctx.beginPath(); ctx.arc(p.x, p.y, r * 2.4, 0, 7); ctx.stroke();
				}
			}

			// The lost node: wanders a wide tilted orbit, reaches toward the graph, and never connects.
			const a = t * 0.5;
			const lost: V = { x: Math.cos(a) * 1.55, y: Math.sin(a * 1.3) * 0.5 - 0.15, z: Math.sin(a) * 1.55 };
			const L = project(lost, ry, rx, scale);
			let best = 1, bd = 1e9;
			for (let i = 1; i < nodes.length; i++) {
				const d = (nodes[i].x - lost.x) ** 2 + (nodes[i].y - lost.y) ** 2 + (nodes[i].z - lost.z) ** 2;
				if (d < bd) { bd = d; best = i; }
			}
			const tgt = P[best];
			const reach = 0.55 + Math.sin(t * 2.1) * 0.12; // stops short every time
			ctx.globalAlpha = 0.85; ctx.strokeStyle = colors.accent; ctx.lineWidth = 1.2;
			ctx.setLineDash([3, 5]); ctx.lineDashOffset = -t * 14;
			ctx.beginPath(); ctx.moveTo(L.x, L.y); ctx.lineTo(L.x + (tgt.x - L.x) * reach, L.y + (tgt.y - L.y) * reach); ctx.stroke();
			ctx.setLineDash([]);
			// Hollow ring with a flickering "?".
			const lr = 9 * L.f + 4;
			ctx.globalAlpha = 1; ctx.lineWidth = 2; ctx.strokeStyle = colors.accent;
			ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#0f0f11';
			ctx.beginPath(); ctx.arc(L.x, L.y, lr, 0, 7); ctx.fill(); ctx.stroke();
			ctx.globalAlpha = Math.sin(t * 9) > 0.92 ? 0.25 : 1;
			ctx.fillStyle = colors.accent;
			ctx.font = `600 ${Math.round(lr * 1.2)}px ui-monospace, monospace`;
			ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
			ctx.fillText('?', L.x, L.y + 1);
			ctx.globalAlpha = 1;
		}

		function frame(now: number) {
			draw(now);
			raf = requestAnimationFrame(frame);
		}
		function move(e: PointerEvent) {
			mx = (e.clientX / innerWidth - 0.5) * 2;
			my = (e.clientY / innerHeight - 0.5) * 2;
			wrap.parentElement?.style.setProperty('--mx', String(mx));
			wrap.parentElement?.style.setProperty('--my', String(my));
		}

		const ro = new ResizeObserver(resize);
		ro.observe(wrap);
		const mo = new MutationObserver(readColors);
		mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'style'] });
		resize();
		if (!reduce) {
			addEventListener('pointermove', move);
			raf = requestAnimationFrame(frame);
		}
		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect(); mo.disconnect();
			removeEventListener('pointermove', move);
		};
	});
</script>

<div class="scene" bind:this={wrap} aria-hidden="true"><canvas bind:this={canvas}></canvas></div>

<style>
	.scene { position: absolute; inset: 0; pointer-events: none; }
	canvas { width: 100%; height: 100%; display: block; }
</style>
