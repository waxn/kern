<script lang="ts">
	import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation } from 'd3-force';
	import { ExternalLink, Locate, Maximize, Search, X } from '@lucide/svelte';
	import { onMount, untrack } from 'svelte';
	import { api } from '#lib/api.ts';
	import { open } from '#lib/state/tabs.ts';
	import { ui } from '#lib/state/ui.svelte.ts';

	type Kind = 'child' | 'ref' | 'tag' | 'relation';
	interface GNode {
		id: string; kind: 'doc' | 'tag' | 'block'; title: string; icon?: string; color?: string;
		db?: boolean; entry?: boolean; archived?: boolean; doc?: string;
		x?: number; y?: number; vx?: number; vy?: number; fx?: number | null; fy?: number | null; deg?: number;
	}
	interface GEdge { s: string; t: string; kind: Kind }
	interface SimLink { source: GNode; target: GNode; kind: Kind }

	let raw = $state<{ nodes: GNode[]; edges: GEdge[] } | null>(null);
	let canvas = $state<HTMLCanvasElement>();
	let box = $state<HTMLElement>();
	let size = { w: 800, h: 600 };

	const KIND_LABEL: Record<Kind, string> = { child: 'Hierarchy', ref: 'References', tag: 'Tags', relation: 'Relations' };
	let show = $state<Record<Kind, boolean>>({ child: true, ref: true, tag: true, relation: true });
	let showBlocks = $state(true);
	let showEntries = $state(true);
	let hideOrphans = $state(false);
	let focusDepth = $state(0);
	let query = $state('');
	let selected = $state<GNode | null>(null);
	let hovered: GNode | null = null;
	let selectedId = $derived(selected?.id ?? null);

	let nodes: GNode[] = [];
	let links: SimLink[] = [];
	let neighbors = new Map<string, Set<string>>();
	let sim: Simulation<GNode, SimLink> | null = null;
	let view = { x: 0, y: 0, k: 1 };
	let colors: Record<string, string> = {};
	let raf = 0;
	let fitted = false;
	let counts = $state({ nodes: 0, links: 0 });

	onMount(() => {
		api.get<{ nodes: GNode[]; edges: GEdge[] }>('/graph').then((g) => (raw = g)).catch((e) => ui.error(e));
		const ro = new ResizeObserver(() => resize());
		if (box) ro.observe(box);
		const mq = new MutationObserver(() => readColors());
		mq.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'style'] });
		readColors();
		return () => {
			ro.disconnect();
			mq.disconnect();
			sim?.stop();
			cancelAnimationFrame(raf);
		};
	});

	function readColors() {
		const cs = getComputedStyle(document.documentElement);
		for (const k of ['text', 'text-2', 'text-3', 'border-strong', 'accent', 'bg', 'c-green', 'c-blue', 'c-purple', 'c-orange', 'surface'])
			colors[k] = cs.getPropertyValue('--' + k).trim();
		draw();
	}

	function resize() {
		if (!canvas || !box) return;
		const r = box.getBoundingClientRect();
		const dpr = devicePixelRatio || 1;
		size = { w: r.width, h: r.height };
		canvas.width = r.width * dpr;
		canvas.height = r.height * dpr;
		canvas.style.width = r.width + 'px';
		canvas.style.height = r.height + 'px';
		draw();
	}

	// Rebuild the simulation whenever data or filters change.
	$effect(() => {
		if (!raw) return;
		const kinds = { ...show };
		const blocks = showBlocks, entries = showEntries, orphans = hideOrphans, depth = focusDepth;
		const focusId = depth ? selectedId : null;
		const data = raw;
		untrack(() => build(data, kinds, blocks, entries, orphans, focusId ?? null, depth));
	});

	function build(g: { nodes: GNode[]; edges: GEdge[] }, kinds: Record<Kind, boolean>, blocks: boolean, entries: boolean, orphans: boolean, focusId: string | null, depth: number) {
		const prev = new Map(nodes.map((n) => [n.id, n]));
		let ns = g.nodes.filter((n) => (blocks || n.kind !== 'block') && (entries || !n.entry) && (kinds.tag || n.kind !== 'tag'));
		const ids = new Set(ns.map((n) => n.id));
		let es = g.edges.filter((e) => kinds[e.kind] && ids.has(e.s) && ids.has(e.t));
		if (focusId && ids.has(focusId)) {
			const adj = new Map<string, string[]>();
			for (const e of es) {
				(adj.get(e.s) ?? adj.set(e.s, []).get(e.s)!).push(e.t);
				(adj.get(e.t) ?? adj.set(e.t, []).get(e.t)!).push(e.s);
			}
			const keep = new Set([focusId]);
			let frontier = [focusId];
			for (let d = 0; d < depth; d++) {
				const next: string[] = [];
				for (const id of frontier) for (const n of adj.get(id) ?? []) if (!keep.has(n)) (keep.add(n), next.push(n));
				frontier = next;
			}
			ns = ns.filter((n) => keep.has(n.id));
			es = es.filter((e) => keep.has(e.s) && keep.has(e.t));
		}
		const deg = new Map<string, number>();
		for (const e of es) {
			deg.set(e.s, (deg.get(e.s) ?? 0) + 1);
			deg.set(e.t, (deg.get(e.t) ?? 0) + 1);
		}
		if (orphans) ns = ns.filter((n) => deg.get(n.id));
		nodes = ns.map((n) => {
			const old = prev.get(n.id);
			return { ...n, deg: deg.get(n.id) ?? 0, x: old?.x, y: old?.y, vx: old?.vx, vy: old?.vy };
		});
		const byId = new Map(nodes.map((n) => [n.id, n]));
		links = es.filter((e) => byId.has(e.s) && byId.has(e.t)).map((e) => ({ source: byId.get(e.s)!, target: byId.get(e.t)!, kind: e.kind }));
		neighbors = new Map();
		for (const l of links) {
			(neighbors.get(l.source.id) ?? neighbors.set(l.source.id, new Set()).get(l.source.id)!).add(l.target.id);
			(neighbors.get(l.target.id) ?? neighbors.set(l.target.id, new Set()).get(l.target.id)!).add(l.source.id);
		}
		counts = { nodes: nodes.length, links: links.length };
		if (selected && !byId.has(selected.id)) selected = null;
		else if (selected) selected = byId.get(selected.id)!;

		sim?.stop();
		sim = forceSimulation<GNode, SimLink>(nodes)
			.force('link', forceLink<GNode, SimLink>(links).distance((l) => (l.kind === 'child' ? 46 : l.kind === 'tag' ? 70 : 90)).strength((l) => (l.kind === 'child' ? 0.7 : 0.25)))
			.force('charge', forceManyBody<GNode>().strength((n) => -60 - Math.min(240, (n.deg ?? 0) * 18)).distanceMax(600))
			.force('collide', forceCollide<GNode>((n) => radius(n) + 3))
			.force('center', forceCenter(0, 0))
			.force('x', forceX(0).strength(0.03))
			.force('y', forceY(0).strength(0.03))
			.alphaDecay(0.03)
			.on('tick', draw)
			.on('end', () => {
				if (!fitted) {
					fitted = true;
					fit();
				}
			});
		if (prev.size) sim.alpha(0.4);
		else if (!fitted) {
			// Settle the first layout off-screen so the view opens framed, not mid-explosion.
			sim.stop();
			for (let i = 0; i < 160; i++) sim.tick();
			fitted = true;
			fit();
			sim.alpha(0.05).restart();
		}
	}

	function radius(n: GNode) {
		return (n.kind === 'tag' ? 4 : n.kind === 'block' ? 2.5 : 3.5) + Math.sqrt(n.deg ?? 0) * 1.7;
	}

	function nodeColor(n: GNode) {
		if (n.kind === 'tag') return colors['c-green'];
		if (n.kind === 'block') return colors['c-orange'];
		if (n.db) return colors['c-purple'];
		if (n.entry) return colors['c-blue'];
		return colors['text-2'];
	}

	const EDGE: Record<Kind, string> = { child: 'border-strong', ref: 'accent', tag: 'c-green', relation: 'c-blue' };

	function draw() {
		cancelAnimationFrame(raf);
		raf = requestAnimationFrame(paint);
	}

	function paint() {
		const ctx = canvas?.getContext('2d');
		if (!ctx || !canvas) return;
		const dpr = devicePixelRatio || 1;
		ctx.setTransform(1, 0, 0, 1, 0, 0);
		ctx.clearRect(0, 0, canvas.width, canvas.height);
		ctx.setTransform(dpr * view.k, 0, 0, dpr * view.k, dpr * (size.w / 2 + view.x), dpr * (size.h / 2 + view.y));
		const focus = hovered ?? selected;
		const near = focus ? neighbors.get(focus.id) ?? new Set() : null;
		const q = query.trim().toLowerCase();
		const lit = (n: GNode) => !focus || n.id === focus.id || near!.has(n.id);

		for (const l of links) {
			const on = !focus || l.source.id === focus.id || l.target.id === focus.id;
			ctx.globalAlpha = on ? (focus ? 0.9 : 0.45) : 0.06;
			ctx.strokeStyle = colors[EDGE[l.kind]];
			ctx.lineWidth = (l.kind === 'child' ? 1 : 1.2) / Math.sqrt(view.k);
			ctx.setLineDash(l.kind === 'tag' ? [3 / view.k, 3 / view.k] : []);
			ctx.beginPath();
			ctx.moveTo(l.source.x!, l.source.y!);
			ctx.lineTo(l.target.x!, l.target.y!);
			ctx.stroke();
		}
		ctx.setLineDash([]);
		for (const n of nodes) {
			const match = q && n.title.toLowerCase().includes(q);
			ctx.globalAlpha = lit(n) ? (n.archived ? 0.5 : 1) : 0.15;
			if (q && !match) ctx.globalAlpha *= 0.35;
			const r = radius(n);
			ctx.fillStyle = nodeColor(n);
			ctx.beginPath();
			if (n.kind === 'tag') ctx.rect(n.x! - r, n.y! - r, r * 2, r * 2);
			else ctx.arc(n.x!, n.y!, r, 0, Math.PI * 2);
			ctx.fill();
			if (n === selected || match) {
				ctx.strokeStyle = colors.accent;
				ctx.lineWidth = 2 / view.k;
				ctx.stroke();
			}
		}
		// Labels: only when zoomed in, for busy nodes, or around the focus.
		ctx.font = `${12 / view.k}px Inter Variable, system-ui, sans-serif`;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		for (const n of nodes) {
			const important = (n.deg ?? 0) >= 6;
			const show = (focus ? lit(n) : view.k > 1.15 || (important && view.k > 0.55)) || n === selected || (q && n.title.toLowerCase().includes(q));
			if (!show) continue;
			ctx.globalAlpha = lit(n) ? 0.95 : 0.3;
			ctx.fillStyle = colors.text;
			const label = (n.kind === 'tag' ? '#' : '') + (n.icon ? n.icon + ' ' : '') + (n.title || 'Untitled');
			ctx.fillText(label.length > 40 ? label.slice(0, 39) + '…' : label, n.x!, n.y! + radius(n) + 3 / view.k);
		}
		ctx.globalAlpha = 1;
	}

	// ------------------------------------------------------------ interaction

	function toWorld(e: MouseEvent | PointerEvent) {
		const r = canvas!.getBoundingClientRect();
		return { x: (e.clientX - r.left - size.w / 2 - view.x) / view.k, y: (e.clientY - r.top - size.h / 2 - view.y) / view.k };
	}

	function hit(e: MouseEvent): GNode | null {
		const p = toWorld(e);
		let best: GNode | null = null;
		let bestD = Infinity;
		for (const n of nodes) {
			const d = Math.hypot(n.x! - p.x, n.y! - p.y);
			const r = radius(n) + 4 / view.k;
			if (d < r && d < bestD) [best, bestD] = [n, d];
		}
		return best;
	}

	let drag: { node: GNode | null; x: number; y: number; moved: boolean } | null = null;

	function down(e: PointerEvent) {
		canvas!.setPointerCapture(e.pointerId);
		const n = hit(e);
		drag = { node: n, x: e.clientX, y: e.clientY, moved: false };
		if (n) {
			n.fx = n.x;
			n.fy = n.y;
			sim?.alphaTarget(0.25).restart();
		}
	}

	function move(e: PointerEvent) {
		if (!drag) {
			const n = hit(e);
			if (n !== hovered) {
				hovered = n;
				canvas!.style.cursor = n ? 'pointer' : 'grab';
				draw();
			}
			return;
		}
		const dx = e.clientX - drag.x;
		const dy = e.clientY - drag.y;
		if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
		if (drag.node) {
			const p = toWorld(e);
			drag.node.fx = p.x;
			drag.node.fy = p.y;
		} else {
			view.x += dx;
			view.y += dy;
			drag.x = e.clientX;
			drag.y = e.clientY;
			draw();
		}
	}

	function up() {
		if (!drag) return;
		const { node, moved } = drag;
		drag = null;
		if (node) {
			node.fx = node.fy = null;
			sim?.alphaTarget(0);
		}
		if (!moved) {
			selected = node;
			draw();
		}
	}

	function wheel(e: WheelEvent) {
		e.preventDefault();
		const r = canvas!.getBoundingClientRect();
		const mx = e.clientX - r.left - size.w / 2;
		const my = e.clientY - r.top - size.h / 2;
		const k = Math.max(0.15, Math.min(6, view.k * Math.exp(-e.deltaY * 0.0015)));
		view.x = mx - ((mx - view.x) * k) / view.k;
		view.y = my - ((my - view.y) * k) / view.k;
		view.k = k;
		draw();
	}

	function openNode(n: GNode, e?: MouseEvent) {
		if (n.kind === 'tag') open(`/tag/${n.id.slice(4)}`, e);
		else if (n.kind === 'block') open(`/doc/${n.doc}#${n.id.slice(6)}`, e);
		else open(`/doc/${n.id}`, e);
	}

	function center(n: GNode) {
		view.k = Math.max(view.k, 1.4);
		view.x = -n.x! * view.k;
		view.y = -n.y! * view.k;
		draw();
	}

	function fit() {
		if (!nodes.length) return;
		const xs = nodes.map((n) => n.x!), ys = nodes.map((n) => n.y!);
		const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
		const k = Math.min(2, 0.85 * Math.min(size.w / (x1 - x0 + 60), size.h / (y1 - y0 + 60)));
		view = { k, x: (-(x0 + x1) / 2) * k, y: (-(y0 + y1) / 2) * k };
		draw();
	}

	function searchKey(e: KeyboardEvent) {
		if (e.key !== 'Enter') return;
		const q = query.trim().toLowerCase();
		const n = nodes.find((n) => n.title.toLowerCase().includes(q));
		if (n) {
			selected = n;
			center(n);
		}
	}

	$effect(() => {
		void query;
		draw();
	});

	let connections = $derived.by(() => {
		if (!selected || !raw) return [];
		const ids = neighbors.get(selected.id) ?? new Set();
		return nodes.filter((n) => ids.has(n.id)).sort((a, b) => a.title.localeCompare(b.title));
	});
</script>

<div class="graph">
	<div class="controls">
		<div class="search">
			<Search size={14} class="faint" />
			<input bind:value={query} placeholder="Find a node…" onkeydown={searchKey} />
		</div>
		<div class="group">
			{#each Object.keys(KIND_LABEL) as k (k)}
				<label class="tog" data-k={k}><input type="checkbox" bind:checked={show[k as Kind]} /><i></i>{KIND_LABEL[k as Kind]}</label>
			{/each}
		</div>
		<div class="group">
			<label class="tog"><input type="checkbox" bind:checked={showBlocks} />Referenced blocks</label>
			<label class="tog"><input type="checkbox" bind:checked={showEntries} />Database entries</label>
			<label class="tog"><input type="checkbox" bind:checked={hideOrphans} />Hide unconnected</label>
		</div>
		<div class="group">
			<label class="tog">Focus
				<select class="input sm" bind:value={focusDepth} disabled={!selected} title={selected ? '' : 'Select a node first'}>
					<option value={0}>Off</option><option value={1}>1 step</option><option value={2}>2 steps</option><option value={3}>3 steps</option>
				</select>
			</label>
			<button class="icon-btn" title="Fit to screen" onclick={fit}><Maximize size={14} /></button>
		</div>
		<span class="faint stat">{counts.nodes} nodes · {counts.links} links</span>
	</div>

	<div class="stage" bind:this={box}>
		<canvas bind:this={canvas} onpointerdown={down} onpointermove={move} onpointerup={up} onpointerleave={() => { hovered = null; draw(); }}
			onwheel={wheel} ondblclick={(e) => { const n = hit(e); if (n) openNode(n, e); }}></canvas>
		{#if raw && !raw.nodes.length}
			<div class="empty overlay"><b>Nothing to draw yet</b>Pages, links and tags you create appear here.</div>
		{/if}
		<div class="legend">
			<span><i class="dot"></i>Page</span><span><i class="dot db"></i>Database</span><span><i class="dot entry"></i>Entry</span>
			<span><i class="sq"></i>Tag</span><span><i class="dot block"></i>Block</span>
		</div>
		{#if selected}
			<aside class="info popover">
				<div class="ih">
					<b class="truncate">{selected.kind === 'tag' ? '#' : ''}{selected.icon ?? ''} {selected.title || 'Untitled'}</b>
					<button class="icon-btn" title="Close" onclick={() => { selected = null; focusDepth = 0; draw(); }}><X size={14} /></button>
				</div>
				<div class="kind faint">{selected.kind === 'tag' ? 'Tag' : selected.kind === 'block' ? 'Block' : selected.db ? 'Database' : selected.entry ? 'Database entry' : 'Page'} · {connections.length} connections</div>
				<div class="acts">
					<button class="btn" onclick={(e) => openNode(selected!, e)}><ExternalLink size={13} />Open</button>
					<button class="btn" onclick={() => center(selected!)}><Locate size={13} />Center</button>
					<button class="btn" onclick={() => (focusDepth = focusDepth ? 0 : 1)}>{focusDepth ? 'Show all' : 'Focus'}</button>
				</div>
				<div class="conns">
					{#each connections as n (n.id)}
						<button class="menu-item" onclick={() => { selected = n; center(n); }}>
							<span class="truncate">{n.kind === 'tag' ? '#' : ''}{n.icon ?? ''} {n.title || 'Untitled'}</span>
						</button>
					{/each}
				</div>
			</aside>
		{/if}
	</div>
</div>

<style>
	.graph { display: flex; flex-direction: column; height: 100%; }
	.controls { flex: none; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 8px 14px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
	.search { display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); }
	.search input { border: 0; outline: 0; background: none; width: 150px; }
	.group { display: flex; align-items: center; gap: 10px; }
	.tog { display: flex; align-items: center; gap: 5px; color: var(--text-2); cursor: pointer; }
	.tog input { accent-color: var(--accent); }
	.tog i { width: 14px; height: 2px; border-radius: 1px; background: var(--border-strong); }
	.tog[data-k='ref'] i { background: var(--accent); }
	.tog[data-k='tag'] i { background: var(--c-green); }
	.tog[data-k='relation'] i { background: var(--c-blue); }
	.sm { height: 24px; padding: 0 4px; }
	.stat { margin-left: auto; }
	.stage { position: relative; flex: 1; min-height: 0; overflow: hidden; }
	canvas { display: block; cursor: grab; touch-action: none; }
	.overlay { position: absolute; top: 30%; left: 50%; transform: translateX(-50%); }
	.legend { position: absolute; left: 12px; bottom: 10px; display: flex; gap: 12px; font-size: 11.5px; color: var(--text-3); pointer-events: none; }
	.legend span { display: flex; align-items: center; gap: 5px; }
	.dot, .sq { width: 8px; height: 8px; border-radius: 50%; background: var(--text-2); }
	.dot.db { background: var(--c-purple); } .dot.entry { background: var(--c-blue); } .dot.block { background: var(--c-orange); }
	.sq { border-radius: 1px; background: var(--c-green); }
	.info { position: absolute; top: 12px; right: 12px; width: 270px; max-height: calc(100% - 24px); display: flex; flex-direction: column; padding: 10px; animation: none; }
	.ih { display: flex; align-items: center; gap: 6px; }
	.ih b { flex: 1; }
	.kind { font-size: 12px; margin: 2px 0 8px; }
	.acts { display: flex; gap: 6px; margin-bottom: 8px; }
	.conns { overflow-y: auto; border-top: 1px solid var(--border); padding-top: 4px; }
	@media (max-width: 760px) { .controls { gap: 8px; } .stat { display: none; } .info { left: 12px; width: auto; top: auto; bottom: 12px; max-height: 45%; } }
</style>
