<script lang="ts">
	/* PDF viewer on pdf.js: thumbnails, zoom, page navigation, search and text selection, plus
	   highlights and notes. Annotations are stored on the server, never written into the file,
	   unless you choose "Save a copy with annotations". */
	import {
		ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Copy, FilePlus2, Highlighter, LayoutGrid, MessageSquarePlus,
		Minus, PanelLeft, Plus, Search, StickyNote, Trash2, X
	} from '@lucide/svelte';
	import { onDestroy, onMount, tick } from 'svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { mod } from '#lib/util.ts';
	import type { FileRef } from './kind.ts';

	let { file, onsaved }: { file: FileRef; onsaved?: () => void } = $props();

	interface Annot { id: string; page: number; kind: 'highlight' | 'note'; color: string; rects: number[][]; text: string; note: string; created_at: string }
	type Part = { page: number; rects: number[][]; text: string };

	const COLORS: Record<string, [number, number, number]> = {
		yellow: [1, 0.85, 0.1], green: [0.45, 0.85, 0.4], blue: [0.45, 0.72, 1], pink: [1, 0.5, 0.75], orange: [1, 0.62, 0.2], purple: [0.7, 0.55, 1]
	};
	const ZOOMS: [string, string][] = [['auto', 'Automatic'], ['page-width', 'Page width'], ['page-fit', 'Whole page'], ['0.5', '50%'], ['0.75', '75%'], ['1', '100%'], ['1.25', '125%'], ['1.5', '150%'], ['2', '200%'], ['3', '300%']];

	let container = $state<HTMLDivElement>();
	let viewerEl = $state<HTMLDivElement>();
	let searchInput = $state<HTMLInputElement>();
	let thumbsEl = $state<HTMLDivElement>();
	let loading = $state(true);
	let error = $state('');
	let pages = $state(0);
	let page = $state(1);
	let pageInput = $state('1');
	let scale = $state(1);
	let scaleValue = $state('page-width');
	let side = $state<'pages' | 'notes' | null>(typeof innerWidth !== 'undefined' && innerWidth < 800 ? null : 'pages');
	let query = $state('');
	let matches = $state({ current: 0, total: 0 });
	let notFound = $state(false);
	let annots = $state<Annot[]>([]);
	let lastColor = $state('yellow');
	let noteMode = $state(false);
	let sel = $state<{ x: number; y: number; parts: Part[]; text: string } | null>(null);
	let editing = $state<{ id: string; x: number; y: number } | null>(null);
	let selected = $state<string | null>(null);
	let savingCopy = $state(false);
	let thumbRatio = $state(1.3);

	// pdf.js objects (not reactive)
	let lib: typeof import('pdfjs-dist');
	let pdfDoc: import('pdfjs-dist').PDFDocumentProxy | null = null;
	let task: import('pdfjs-dist').PDFDocumentLoadingTask | null = null;
	let viewer: import('pdfjs-dist/web/pdf_viewer.mjs').PDFViewer | null = null;
	let eventBus: import('pdfjs-dist/web/pdf_viewer.mjs').EventBus | null = null;
	const rendered = new Set<number>();
	let destroyed = false;

	onMount(async () => {
		try {
			lib = await import('pdfjs-dist');
			const worker = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
			lib.GlobalWorkerOptions.workerSrc = worker;
			// The viewer components read the core library from this global.
			(globalThis as any).pdfjsLib = lib;
			const v = await import('pdfjs-dist/web/pdf_viewer.mjs');
			await import('pdfjs-dist/web/pdf_viewer.css');
			if (destroyed || !container || !viewerEl) return;

			eventBus = new v.EventBus();
			const linkService = new v.PDFLinkService({ eventBus, externalLinkTarget: v.LinkTarget.BLANK });
			const findController = new v.PDFFindController({ eventBus, linkService });
			viewer = new v.PDFViewer({
				container, viewer: viewerEl, eventBus, linkService, findController,
				imageResourcesPath: '/pdfjs/', // sticky-note icons (copied from pdfjs-dist/web/images)
				annotationEditorMode: lib.AnnotationEditorType.DISABLE
			});
			linkService.setViewer(viewer);
			eventBus.on('pagesinit', () => viewer && (viewer.currentScaleValue = innerWidth < 800 ? 'page-width' : 'auto'));
			eventBus.on('pagechanging', (e: { pageNumber: number }) => {
				page = e.pageNumber;
				pageInput = String(e.pageNumber);
				scrollThumb();
			});
			eventBus.on('scalechanging', (e: { scale: number; presetValue?: string }) => {
				scale = e.scale;
				scaleValue = e.presetValue ?? String(e.scale);
				sel = null;
			});
			eventBus.on('pagerendered', (e: { pageNumber: number }) => {
				rendered.add(e.pageNumber);
				drawPage(e.pageNumber);
			});
			const onCount = (e: { matchesCount: { current: number; total: number }; state?: number }) => {
				matches = e.matchesCount;
				if (e.state !== undefined) notFound = e.state === 1;
			};
			eventBus.on('updatefindmatchescount', onCount);
			eventBus.on('updatefindcontrolstate', onCount);

			task = lib.getDocument({ url: file.url, disableAutoFetch: (file.size ?? 0) > 30 * 1024 * 1024 });
			task.onPassword = (cb: (p: string) => void, reason: number) => {
				const p = prompt(reason === 2 ? 'Wrong password. Try again:' : 'This PDF is protected. Enter its password:');
				if (p === null) task?.destroy();
				else cb(p);
			};
			pdfDoc = await task.promise;
			if (destroyed) return;
			viewer.setDocument(pdfDoc);
			linkService.setDocument(pdfDoc);
			pages = pdfDoc.numPages;
			const first = await pdfDoc.getPage(1);
			const vp = first.getViewport({ scale: 1 });
			thumbRatio = vp.height / vp.width;
			if (file.id) annots = await api.get<Annot[]>(`/library/${file.id}/annotations`).catch(() => []);
		} catch (e) {
			if (!destroyed) error = e instanceof Error ? e.message : String(e);
		}
		loading = false;
	});

	onDestroy(() => {
		destroyed = true;
		thumbObserver?.disconnect();
		task?.destroy();
		pdfDoc = null;
		viewer = null;
	});

	/* ---------------- navigation, zoom, search */

	function goPage(n: number) {
		if (!viewer || !pages) return;
		viewer.currentPageNumber = Math.max(1, Math.min(pages, Math.round(n) || 1));
	}
	function zoom(dir: number) {
		if (!viewer) return;
		viewer.currentScale = Math.max(0.25, Math.min(5, Math.round(scale * (dir > 0 ? 1.15 : 1 / 1.15) * 100) / 100));
	}
	function setZoom(v: string) {
		if (viewer) viewer.currentScaleValue = v;
	}
	function wheel(e: WheelEvent) {
		if (!(e.ctrlKey || e.metaKey)) return;
		e.preventDefault();
		zoom(-e.deltaY);
	}
	$effect(() => {
		const c = container;
		if (!c) return;
		c.addEventListener('wheel', wheel, { passive: false });
		return () => c.removeEventListener('wheel', wheel);
	});

	function find(again = false, previous = false) {
		eventBus?.dispatch('find', { source: null, type: again ? 'again' : '', query, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: previous, matchDiacritics: false });
	}
	let findTimer: ReturnType<typeof setTimeout> | undefined;
	function onQuery() {
		clearTimeout(findTimer);
		findTimer = setTimeout(() => find(), 180);
	}
	function searchKey(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			find(true, e.shiftKey);
		} else if (e.key === 'Escape' && query) {
			e.stopPropagation();
			e.preventDefault();
			query = '';
			eventBus?.dispatch('findbarclose', { source: null });
			matches = { current: 0, total: 0 };
		}
	}

	function keydown(e: KeyboardEvent) {
		if (mod(e) && e.key.toLowerCase() === 'f') {
			e.preventDefault();
			searchInput?.focus();
			searchInput?.select();
			return;
		}
		if (mod(e) && (e.key === '=' || e.key === '+' || e.key === '-' || e.key === '0')) {
			e.preventDefault();
			if (e.key === '0') setZoom('auto');
			else zoom(e.key === '-' ? -1 : 1);
			return;
		}
		if (e.key === 'Escape' && (editing || sel || noteMode)) {
			e.stopPropagation();
			e.preventDefault();
			editing = null;
			sel = null;
			noteMode = false;
			return;
		}
		const t = e.target as HTMLElement;
		if (t?.closest?.('input, textarea, select, [contenteditable]')) return;
		if (e.key === 'ArrowRight' && !e.shiftKey && container && container.scrollWidth <= container.clientWidth) return (e.preventDefault(), goPage(page + 1));
		if (e.key === 'ArrowLeft' && !e.shiftKey && container && container.scrollWidth <= container.clientWidth) return (e.preventDefault(), goPage(page - 1));
	}

	/* ---------------- thumbnails */

	let thumbObserver: IntersectionObserver | undefined;
	const thumbDone = new Set<number>();
	function thumb(node: HTMLCanvasElement, n: number) {
		if (!thumbObserver)
			thumbObserver = new IntersectionObserver(
				(entries) => {
					for (const en of entries) if (en.isIntersecting) renderThumb(en.target as HTMLCanvasElement);
				},
				{ root: thumbsEl, rootMargin: '300px 0px' }
			);
		node.dataset.page = String(n);
		thumbObserver.observe(node);
		return { destroy: () => thumbObserver?.unobserve(node) };
	}
	async function renderThumb(c: HTMLCanvasElement) {
		const n = Number(c.dataset.page);
		if (!pdfDoc || thumbDone.has(n)) return;
		thumbDone.add(n);
		thumbObserver?.unobserve(c);
		try {
			const p = await pdfDoc.getPage(n);
			const base = p.getViewport({ scale: 1 });
			const dpr = Math.min(2, devicePixelRatio || 1);
			const vp = p.getViewport({ scale: (120 / base.width) * dpr });
			c.width = vp.width;
			c.height = vp.height;
			await p.render({ canvas: c, viewport: vp }).promise;
		} catch {
			thumbDone.delete(n);
		}
	}
	function scrollThumb() {
		if (side !== 'pages' || !thumbsEl) return;
		thumbsEl.querySelector(`[data-thumb="${page}"]`)?.scrollIntoView({ block: 'nearest' });
	}

	/* ---------------- annotations: drawing */

	function pageDiv(n: number): HTMLElement | null {
		return (viewer?.getPageView(n - 1) as any)?.div ?? null;
	}

	function drawPage(n: number, list: Annot[] = annots) {
		const div = pageDiv(n);
		if (!div) return;
		let layer = div.querySelector<HTMLDivElement>(':scope > .kern-annots');
		if (!layer) {
			layer = document.createElement('div');
			layer.className = 'kern-annots';
			div.append(layer);
		}
		const els: HTMLElement[] = [];
		for (const a of list) {
			if (a.page !== n) continue;
			if (a.kind === 'highlight')
				for (const [x, y, w, h] of a.rects) {
					const d = document.createElement('div');
					d.className = 'kh' + (a.id === selected ? ' sel' : '');
					d.dataset.c = a.color;
					d.style.cssText = `left:${x * 100}%;top:${y * 100}%;width:${w * 100}%;height:${h * 100}%`;
					els.push(d);
				}
			if (a.kind === 'note' || a.note) {
				const [x, y, w] = a.rects[0];
				const m = document.createElement('button');
				m.className = 'kn' + (a.kind === 'highlight' ? ' small' : '') + (a.id === selected ? ' sel' : '');
				m.dataset.c = a.color;
				m.dataset.id = a.id;
				m.title = a.note || 'Note';
				m.style.cssText = a.kind === 'note' ? `left:${x * 100}%;top:${y * 100}%` : `left:${(x + w) * 100}%;top:${y * 100}%`;
				m.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
				els.push(m);
			}
		}
		layer.replaceChildren(...els);
	}

	$effect(() => {
		const list = $state.snapshot(annots) as Annot[];
		void selected;
		for (const n of rendered) drawPage(n, list);
	});

	/* ---------------- annotations: creating and editing */

	function pageOf(el: Node | null): { div: HTMLElement; n: number } | null {
		const div = (el instanceof Element ? el : el?.parentElement)?.closest<HTMLElement>('.page[data-page-number]');
		return div ? { div, n: Number(div.dataset.pageNumber) } : null;
	}

	function mergeRects(rs: number[][]): number[][] {
		rs.sort((a, b) => a[1] - b[1] || a[0] - b[0]);
		const out: number[][] = [];
		for (const r of rs) {
			const last = out[out.length - 1];
			if (last && Math.abs(last[1] - r[1]) < Math.min(last[3], r[3]) * 0.5 && r[0] <= last[0] + last[2] + 0.012) {
				const right = Math.max(last[0] + last[2], r[0] + r[2]);
				const top = Math.min(last[1], r[1]);
				const bottom = Math.max(last[1] + last[3], r[1] + r[3]);
				last[0] = Math.min(last[0], r[0]);
				last[2] = right - last[0];
				last[1] = top;
				last[3] = bottom - top;
			} else out.push([...r]);
		}
		return out.map((r) => r.map((v) => Math.round(v * 1e5) / 1e5));
	}

	function readSelection() {
		const s = getSelection();
		if (!s || s.isCollapsed || !s.rangeCount || !viewerEl) return (sel = null);
		const range = s.getRangeAt(0);
		if (!viewerEl.contains(range.commonAncestorContainer)) return (sel = null);
		const start = pageOf(range.startContainer)?.n ?? page;
		const end = pageOf(range.endContainer)?.n ?? start;
		const boxes = new Map<number, DOMRect>();
		for (let n = start; n <= end; n++) {
			const d = pageDiv(n);
			if (d) boxes.set(n, d.getBoundingClientRect());
		}
		const byPage = new Map<number, number[][]>();
		let last: DOMRect | null = null;
		for (const r of range.getClientRects()) {
			if (r.width < 1 || r.height < 1) continue;
			const cx = r.left + r.width / 2;
			const cy = r.top + r.height / 2;
			for (const [n, b] of boxes) {
				if (cx < b.left || cx > b.right || cy < b.top || cy > b.bottom) continue;
				const nr = [(r.left - b.left) / b.width, (r.top - b.top) / b.height, r.width / b.width, r.height / b.height];
				if (nr[3] > 0.15) break; // pdf.js's end-of-content filler, not text
				byPage.set(n, [...(byPage.get(n) ?? []), nr]);
				last = r;
				break;
			}
		}
		const text = s.toString().replace(/\s+/g, ' ').trim();
		const parts = [...byPage].map(([n, rs]) => ({ page: n, rects: mergeRects(rs), text }));
		if (!parts.length || !last || !text) return (sel = null);
		sel = { x: Math.min(innerWidth - 150, Math.max(150, last.right)), y: Math.min(innerHeight - 60, last.bottom + 8), parts, text };
	}

	function pointerUp(e: PointerEvent) {
		if (e.button !== 0) return;
		setTimeout(readSelection, 0);
	}

	function clickPage(e: MouseEvent) {
		const target = e.target as HTMLElement;
		const marker = target.closest<HTMLElement>('.kn');
		if (marker?.dataset.id) return openEditor(marker.dataset.id, e.clientX, e.clientY);
		const s = getSelection();
		if (s && !s.isCollapsed) return;
		const p = pageOf(target);
		if (!p) return;
		const b = p.div.getBoundingClientRect();
		const x = (e.clientX - b.left) / b.width;
		const y = (e.clientY - b.top) / b.height;
		if (noteMode) {
			noteMode = false;
			return create({ page: p.n, rects: [[x, y, 0, 0]], text: '' }, 'note', true, e.clientX, e.clientY);
		}
		const hit = annots.find((a) => a.page === p.n && a.kind === 'highlight' && a.rects.some(([rx, ry, rw, rh]) => x >= rx && x <= rx + rw && y >= ry && y <= ry + rh));
		if (hit) openEditor(hit.id, e.clientX, e.clientY);
		else {
			editing = null;
			selected = null;
		}
	}

	function openEditor(id: string, x: number, y: number) {
		selected = id;
		editing = { id, x: Math.min(innerWidth - 300, Math.max(10, x - 20)), y: Math.min(innerHeight - 260, y + 12) };
	}

	async function create(part: Part, kind: 'highlight' | 'note', edit: boolean, x: number, y: number) {
		if (!file.id) return ui.toast('Only files in your library can be annotated.');
		try {
			const a = await api.post<Annot>(`/library/${file.id}/annotations`, { ...part, kind, color: lastColor });
			annots = [...annots, a].sort((p, q) => p.page - q.page || p.rects[0][1] - q.rects[0][1]);
			if (edit) {
				openEditor(a.id, x, y);
				await tick();
				document.querySelector<HTMLTextAreaElement>('.annot-pop textarea')?.focus();
			}
			return a;
		} catch (e) {
			ui.error(e);
		}
	}

	async function highlightSelection(color: string, withNote = false) {
		if (!sel) return;
		lastColor = color;
		const { parts, x, y } = sel;
		sel = null;
		getSelection()?.removeAllRanges();
		for (const [i, part] of parts.entries()) await create(part, 'highlight', withNote && i === 0, x, y);
	}

	const saveTimers = new Map<string, ReturnType<typeof setTimeout>>();
	function patch(a: Annot, data: Partial<Annot>, delay = 0) {
		Object.assign(a, data);
		clearTimeout(saveTimers.get(a.id));
		saveTimers.set(a.id, setTimeout(() => {
			api.patch(`/library/${file.id}/annotations/${a.id}`, data).catch((e) => ui.error(e));
		}, delay));
	}
	async function remove(a: Annot) {
		annots = annots.filter((x) => x.id !== a.id);
		editing = null;
		try {
			await api.del(`/library/${file.id}/annotations/${a.id}`);
		} catch (e) {
			ui.error(e);
		}
	}

	function goTo(a: Annot) {
		selected = a.id;
		const div = pageDiv(a.page);
		if (!div || !container) return goPage(a.page);
		container.scrollTo({ top: div.offsetTop + a.rects[0][1] * div.clientHeight - 90, behavior: 'smooth' });
	}

	/* ---------------- save a copy with the annotations burned in */

	async function saveCopy() {
		if (!annots.length) return ui.toast('Add a highlight or note first.');
		savingCopy = true;
		try {
			const { PDFDocument, PDFHexString, rgb, BlendMode } = await import('pdf-lib');
			const bytes = await (await fetch(file.url)).arrayBuffer();
			const out = await PDFDocument.load(bytes, { ignoreEncryption: true });
			for (const a of annots) {
				const p = out.getPages()[a.page - 1];
				if (!p) continue;
				const box = p.getCropBox();
				const rot = (((p.getRotation().angle % 360) + 360) % 360) as 0 | 90 | 180 | 270;
				// Fractions of the page as displayed -> PDF user space (origin bottom-left, unrotated).
				const map = (nx: number, ny: number): [number, number] =>
					rot === 90 ? [box.x + ny * box.width, box.y + nx * box.height]
					: rot === 180 ? [box.x + (1 - nx) * box.width, box.y + ny * box.height]
					: rot === 270 ? [box.x + (1 - ny) * box.width, box.y + (1 - nx) * box.height]
					: [box.x + nx * box.width, box.y + (1 - ny) * box.height];
				const c = COLORS[a.color] ?? COLORS.yellow;
				if (a.kind === 'highlight')
					for (const [x, y, w, h] of a.rects) {
						const [x1, y1] = map(x, y);
						const [x2, y2] = map(x + w, y + h);
						p.drawRectangle({ x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1), color: rgb(...c), opacity: 0.4, blendMode: BlendMode.Multiply });
					}
				if (a.note || a.kind === 'note') {
					const [x, y, w] = a.rects[0];
					const [px, py] = map(a.kind === 'note' ? x : x + w, y);
					const dict = out.context.obj({
						Type: 'Annot', Subtype: 'Text', Name: 'Comment', F: 4, Open: false,
						Rect: [px, py - 20, px + 20, py], C: c,
						Contents: PDFHexString.fromText(a.note || a.text || ''), T: PDFHexString.fromText('Kern')
					});
					p.node.addAnnot(out.context.register(dict));
				}
			}
			const data = await out.save();
			const name = file.name.replace(/\.pdf$/i, '') + ' (annotated).pdf';
			await api.upload(new File([data as BlobPart], name, { type: 'application/pdf' }));
			ui.toast(`Saved a copy as “${name}”. The original is unchanged.`);
			onsaved?.();
		} catch (e) {
			ui.error(e);
		}
		savingCopy = false;
	}

	let editingAnnot = $derived(editing ? annots.find((a) => a.id === editing!.id) : undefined);
	let notesCount = $derived(annots.length);
</script>

<svelte:window onkeydown={keydown} />
<svelte:document onselectionchange={() => sel && getSelection()?.isCollapsed && (sel = null)} />

<div class="pdf">
	<div class="tools">
		<button class="icon-btn" class:on={side === 'pages'} title="Pages" onclick={() => (side = side === 'pages' ? null : 'pages')}><PanelLeft size={15} /></button>
		<button class="icon-btn notes-btn" class:on={side === 'notes'} title="Highlights and notes" onclick={() => (side = side === 'notes' ? null : 'notes')}><StickyNote size={15} />{#if notesCount}<span class="count">{notesCount}</span>{/if}</button>
		<span class="sep"></span>
		<button class="icon-btn" title="Previous page" disabled={page <= 1} onclick={() => goPage(page - 1)}><ChevronLeft size={16} /></button>
		<input class="pg" bind:value={pageInput} aria-label="Page" onchange={() => goPage(Number(pageInput))} onfocus={(e) => e.currentTarget.select()} />
		<span class="faint of">/ {pages || '–'}</span>
		<button class="icon-btn" title="Next page" disabled={page >= pages} onclick={() => goPage(page + 1)}><ChevronRight size={16} /></button>
		<span class="sep"></span>
		<button class="icon-btn" title="Zoom out" onclick={() => zoom(-1)}><Minus size={15} /></button>
		<select class="zoom" value={ZOOMS.some(([v]) => v === scaleValue) ? scaleValue : 'custom'} onchange={(e) => setZoom(e.currentTarget.value)} aria-label="Zoom">
			{#each ZOOMS as [v, label] (v)}<option value={v}>{label}</option>{/each}
			{#if !ZOOMS.some(([v]) => v === scaleValue)}<option value="custom" disabled>{Math.round(scale * 100)}%</option>{/if}
		</select>
		<button class="icon-btn" title="Zoom in" onclick={() => zoom(1)}><Plus size={15} /></button>
		<span class="grow"></span>
		{#if file.id}
			<button class="icon-btn" class:on={noteMode} title="Add a note: click anywhere on a page" onclick={() => (noteMode = !noteMode)}><MessageSquarePlus size={15} /></button>
			<button class="btn ghost" title="Save a new PDF with your highlights and notes written into it; the original stays as it is" disabled={savingCopy} onclick={saveCopy}><FilePlus2 size={14} /><span class="hide-narrow">{savingCopy ? 'Saving…' : 'Save a copy'}</span></button>
		{/if}
		<div class="search" class:miss={notFound && query}>
			<Search size={13} class="faint" />
			<input bind:this={searchInput} bind:value={query} placeholder="Find in document" oninput={onQuery} onkeydown={searchKey} />
			{#if query}
				<span class="faint hits">{matches.total ? `${matches.current}/${matches.total}` : notFound ? '0' : ''}</span>
				<button class="icon-btn sm" title="Previous match (Shift+Enter)" onclick={() => find(true, true)}><ChevronUp size={14} /></button>
				<button class="icon-btn sm" title="Next match (Enter)" onclick={() => find(true)}><ChevronDown size={14} /></button>
			{/if}
		</div>
	</div>

	<div class="main">
		{#if side}
			<aside class="side">
				{#if side === 'pages'}
					<div class="thumbs" bind:this={thumbsEl}>
						{#each { length: pages } as _, i (i)}
							<button class="th" class:on={page === i + 1} data-thumb={i + 1} onclick={() => goPage(i + 1)}>
								<canvas use:thumb={i + 1} style="aspect-ratio: 1 / {thumbRatio}"></canvas>
								<span>{i + 1}</span>
							</button>
						{/each}
					</div>
				{:else}
					<div class="notes">
						{#each annots as a (a.id)}
							<button class="nitem" class:on={selected === a.id} onclick={() => goTo(a)}>
								<span class="bar" data-c={a.color}></span>
								<span class="nbody">
									<span class="faint pnum">Page {a.page}{a.kind === 'note' ? ' · note' : ''}</span>
									{#if a.text}<span class="quote">{a.text}</span>{/if}
									{#if a.note}<span class="ntext">{a.note}</span>{/if}
								</span>
							</button>
						{:else}
							<div class="hint faint">
								<LayoutGrid size={18} />
								<p>Select text to highlight it, or use <MessageSquarePlus size={12} /> to pin a note on a page.</p>
								<p>Highlights are saved in Kern; the PDF itself is not changed.</p>
							</div>
						{/each}
					</div>
				{/if}
			</aside>
		{/if}
		<div class="stagewrap">
			<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
			<div class="container" class:notemode={noteMode} bind:this={container} onpointerup={pointerUp} onclick={clickPage} onscroll={() => (sel = null)}>
				<div class="pdfViewer" bind:this={viewerEl}></div>
			</div>
			{#if loading}<div class="state faint">Loading PDF…</div>{/if}
			{#if error}<div class="state"><div class="empty"><b>Could not open this PDF</b>{error}</div></div>{/if}
		</div>
	</div>
</div>

{#if sel}
	<div class="popover selbar" style="left:{sel.x}px;top:{sel.y}px">
		<Highlighter size={14} class="faint" />
		{#each Object.keys(COLORS) as c (c)}<button class="sw" data-c={c} class:last={c === lastColor} title="Highlight {c}" aria-label="Highlight {c}" onclick={() => highlightSelection(c)}></button>{/each}
		<span class="sep"></span>
		{#if file.id}<button class="icon-btn" title="Highlight and add a note" onclick={() => highlightSelection(lastColor, true)}><MessageSquarePlus size={14} /></button>{/if}
		<button class="icon-btn" title="Copy text" onclick={() => sel && navigator.clipboard?.writeText(sel.text).then(() => ui.toast('Copied'))}><Copy size={14} /></button>
	</div>
{/if}

{#if editing && editingAnnot}
	{@const a = editingAnnot}
	<div class="popover annot-pop" style="left:{editing.x}px;top:{editing.y}px">
		<div class="ahead">
			{#each Object.keys(COLORS) as c (c)}<button class="sw" data-c={c} class:last={c === a.color} aria-label="Colour {c}" onclick={() => patch(a, { color: c })}></button>{/each}
			<span class="grow"></span>
			<button class="icon-btn" title="Delete" onclick={() => remove(a)}><Trash2 size={14} /></button>
			<button class="icon-btn" title="Close" onclick={() => (editing = null)}><X size={14} /></button>
		</div>
		{#if a.text}<blockquote>{a.text}</blockquote>{/if}
		<textarea class="input" rows="4" placeholder="Add a note…" value={a.note} oninput={(e) => patch(a, { note: e.currentTarget.value }, 500)}></textarea>
		<div class="faint small">Page {a.page} · saved automatically</div>
	</div>
{/if}

<style>
	.pdf { height: 100%; display: flex; flex-direction: column; min-height: 0; }
	.tools { display: flex; align-items: center; gap: 3px; padding: 6px 10px; border-bottom: 1px solid var(--border); flex: none; flex-wrap: wrap; }
	.sep { width: 1px; height: 18px; background: var(--border); margin: 0 5px; }
	.grow { flex: 1; }
	.icon-btn:disabled { opacity: 0.4; }
	.icon-btn.sm { width: 22px; height: 22px; }
	.notes-btn { position: relative; width: auto; padding: 0 5px; gap: 3px; display: inline-flex; align-items: center; }
	.count { font-size: 11px; font-variant-numeric: tabular-nums; }
	.pg { width: 42px; height: 26px; text-align: center; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg); font-variant-numeric: tabular-nums; }
	.of { font-size: 12.5px; margin: 0 4px 0 2px; white-space: nowrap; }
	.zoom { height: 26px; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--bg); padding: 0 4px; font-size: 12.5px; }
	.search { display: flex; align-items: center; gap: 4px; height: 28px; padding: 0 4px 0 8px; margin-left: 6px; width: 250px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--bg); }
	.search.miss { border-color: color-mix(in srgb, var(--danger) 60%, var(--border-strong)); }
	.search input { flex: 1; min-width: 0; border: 0; outline: 0; background: none; }
	.hits { font-size: 11.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }

	.main { flex: 1; min-height: 0; display: flex; }
	.side { width: 190px; flex: none; border-right: 1px solid var(--border); background: var(--bg-side); display: flex; flex-direction: column; min-height: 0; }
	.thumbs { flex: 1; overflow: auto; padding: 12px 0; display: flex; flex-direction: column; align-items: center; gap: 12px; }
	.th { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 5px; border-radius: 6px; color: var(--text-3); font-size: 11.5px; }
	.th canvas { width: 120px; background: #fff; border-radius: 2px; box-shadow: 0 0 0 1px var(--border-strong); }
	.th:hover { background: var(--hover); }
	.th.on canvas { box-shadow: 0 0 0 2px var(--accent); }
	.th.on span { color: var(--accent); font-weight: 600; }
	.notes { flex: 1; overflow: auto; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
	.nitem { display: flex; gap: 8px; text-align: left; padding: 6px; border-radius: 6px; }
	.nitem:hover, .nitem.on { background: var(--hover); }
	.nitem .bar { width: 3px; flex: none; border-radius: 2px; background: var(--hl); }
	.nbody { min-width: 0; display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; }
	.pnum { font-size: 11px; }
	.quote { color: var(--text-2); font-style: italic; display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
	.ntext { color: var(--text); white-space: pre-wrap; display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
	.hint { padding: 14px 8px; font-size: 12.5px; text-align: center; }
	.hint p { margin: 8px 0 0; }

	.stagewrap { position: relative; flex: 1; min-width: 0; background: var(--surface-2); }
	.container { position: absolute; inset: 0; overflow: auto; }
	.container.notemode, .container.notemode :global(.textLayer) { cursor: crosshair; }
	.container :global(.pdfViewer) { padding: 8px 0 40px; }
	.container :global(.pdfViewer .page) { box-shadow: 0 1px 6px rgba(0, 0, 0, 0.2); border: 0; margin: 12px auto; }
	.state { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; }
	.state .empty { pointer-events: auto; background: var(--bg); max-width: 420px; }

	/* annotation layer, created by drawPage() inside pdf.js's page elements */
	.container :global(.kern-annots) { position: absolute; inset: 0; pointer-events: none; z-index: 3; mix-blend-mode: multiply; }
	.container :global(.kh) { position: absolute; background: var(--hl); opacity: 0.42; border-radius: 2px; }
	.container :global(.kh.sel) { opacity: 0.62; outline: 2px solid var(--hl); outline-offset: 1px; }
	.container :global(.kn) { position: absolute; pointer-events: auto; width: 24px; height: 24px; margin: -12px 0 0 -4px; display: grid; place-items: center; border-radius: 6px 6px 6px 2px; color: #2b2410; background: var(--hl); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3); mix-blend-mode: normal; cursor: pointer; }
	.container :global(.kn.small) { width: 18px; height: 18px; margin: -14px 0 0 0; }
	.container :global(.kn.small svg) { width: 11px; height: 11px; }
	.container :global(.kn.sel) { outline: 2px solid var(--accent); }
	.container :global(.kern-annots:has(.kn)) { mix-blend-mode: normal; }
	.container :global(.kern-annots:has(.kn) .kh) { mix-blend-mode: multiply; }

	:global([data-c='yellow']) { --hl: rgb(255 212 0); }
	:global([data-c='green']) { --hl: rgb(120 220 110); }
	:global([data-c='blue']) { --hl: rgb(110 180 255); }
	:global([data-c='pink']) { --hl: rgb(255 130 190); }
	:global([data-c='orange']) { --hl: rgb(255 160 60); }
	:global([data-c='purple']) { --hl: rgb(180 140 255); }

	.selbar { position: fixed; z-index: 960; transform: translateX(-50%); display: flex; align-items: center; gap: 4px; padding: 4px 6px; }
	.sw { width: 18px; height: 18px; border-radius: 50%; background: var(--hl); box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.15); }
	.sw:hover { transform: scale(1.12); }
	.sw.last { box-shadow: 0 0 0 2px var(--surface), 0 0 0 3.5px var(--text-2); }
	.annot-pop { position: fixed; z-index: 960; width: 290px; padding: 8px; display: flex; flex-direction: column; gap: 8px; }
	.ahead { display: flex; align-items: center; gap: 5px; }
	blockquote { margin: 0; padding: 2px 0 2px 9px; border-left: 3px solid var(--border-strong); color: var(--text-2); font-size: 12.5px; font-style: italic; max-height: 90px; overflow: auto; }
	.annot-pop textarea { resize: vertical; font-size: 13px; }
	.small { font-size: 11.5px; }

	@media (max-width: 800px) {
		.side { position: absolute; z-index: 5; top: 0; bottom: 0; box-shadow: var(--shadow); }
		.main { position: relative; }
		.search { width: 100%; margin: 4px 0 0; order: 10; }
		.hide-narrow { display: none; }
	}
</style>
