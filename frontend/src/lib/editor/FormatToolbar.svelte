<script lang="ts">
	import { Baseline, Bold, Braces, Code, Highlighter, Italic, Link, Sigma, Strikethrough, Underline, StickyNote } from '@lucide/svelte';
	import { tick } from 'svelte';
	import { COLORS, HIGHLIGHTS } from './blockTypes';
	import { applyWrap, mathHtml, notifyInput, renderMath, toggleWrap } from './dom';

	let { root }: { root: HTMLElement } = $props();

	let el = $state<HTMLElement | null>(null);
	let rect = $state<DOMRect | null>(null);
	let mode = $state<'main' | 'link' | 'color' | 'bg' | 'note'>('main');
	let noteText = $state('');
	let noteInput = $state<HTMLTextAreaElement>();
	let url = $state('');
	let saved: Range | null = null;
	let bar = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });
	let linkInput = $state<HTMLInputElement>();
	let mouseDown = false;

	function update() {
		if (mode === 'link' && document.activeElement === linkInput) return;
		if (mode === 'note' && document.activeElement === noteInput) return;
		const sel = getSelection();
		const node = sel?.anchorNode;
		const host = (node instanceof Element ? node : node?.parentElement)?.closest<HTMLElement>('[data-editable]:not([data-plain])');
		if (!sel || sel.isCollapsed || !host || !root.contains(host) || !host.contains(sel.focusNode) || mouseDown) {
			el = null;
			return;
		}
		const r = sel.getRangeAt(0).getBoundingClientRect();
		if (!r.width && !r.height) {
			el = null;
			return;
		}
		if (el !== host) mode = 'main';
		el = host;
		rect = r;
	}

	$effect(() => {
		const down = () => { mouseDown = true; };
		const up = () => { mouseDown = false; setTimeout(update); };
		document.addEventListener('selectionchange', update);
		root.addEventListener('mousedown', down);
		document.addEventListener('mouseup', up);
		return () => {
			document.removeEventListener('selectionchange', update);
			root.removeEventListener('mousedown', down);
			document.removeEventListener('mouseup', up);
		};
	});

	$effect(() => {
		void mode;
		if (!bar || !rect) return;
		const b = bar.getBoundingClientRect();
		const above = rect.top - b.height - 8;
		pos = {
			x: Math.max(8, Math.min(rect.left + rect.width / 2 - b.width / 2, innerWidth - b.width - 8)),
			y: above < 44 ? rect.bottom + 8 : above
		};
	});

	function cmd(name: string, value?: string) {
		document.execCommand(name, false, value);
	}

	function restore() {
		if (!saved || !el) return;
		el.focus();
		const sel = getSelection()!;
		sel.removeAllRanges();
		sel.addRange(saved);
	}

	async function openNote() {
		const sel = getSelection()!;
		saved = sel.getRangeAt(0).cloneRange();
		const existing = (sel.anchorNode?.parentElement)?.closest<HTMLElement>('mark[data-note]');
		noteText = existing?.dataset.note ?? '';
		mode = 'note';
		await tick();
		noteInput?.focus();
	}

	function applyNote() {
		restore();
		const text = noteText.trim();
		if (el) applyWrap(el, 'mark', 'data-note', text);
		mode = 'main';
		getSelection()?.collapseToEnd();
	}

	async function openLink() {
		const sel = getSelection()!;
		saved = sel.getRangeAt(0).cloneRange();
		const a = (sel.anchorNode?.parentElement)?.closest('a:not([data-ref])');
		url = a?.getAttribute('href') ?? '';
		mode = 'link';
		await tick();
		linkInput?.focus();
	}

	function applyLink() {
		restore();
		let u = url.trim();
		if (!u) cmd('unlink');
		else {
			if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = 'https://' + u;
			cmd('createLink', u);
		}
		mode = 'main';
	}

	function toMath() {
		if (!el) return;
		const sel = getSelection()!;
		const tex = sel.toString();
		cmd('insertHTML', mathHtml(tex));
		renderMath(el);
		notifyInput(el);
	}

	/** Exposed so the editor can trigger the link prompt from Ctrl+K. */
	export function link() {
		update();
		if (el) openLink();
	}
</script>

{#if el && rect}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="bar popover" bind:this={bar} style:left="{pos.x}px" style:top="{pos.y}px"
		onmousedown={(e) => { if (!(e.target instanceof HTMLInputElement)) e.preventDefault(); }}>
		{#if mode === 'main'}
			<button title="Bold (Ctrl+B)" onclick={() => cmd('bold')}><Bold size={15} /></button>
			<button title="Italic (Ctrl+I)" onclick={() => cmd('italic')}><Italic size={15} /></button>
			<button title="Underline (Ctrl+U)" onclick={() => cmd('underline')}><Underline size={15} /></button>
			<button title="Strikethrough (Ctrl+Shift+S)" onclick={() => cmd('strikeThrough')}><Strikethrough size={15} /></button>
			<button title="Inline code (Ctrl+E)" onclick={() => toggleWrap(el!, 'code')}><Code size={15} /></button>
			<button title="Inline equation" onclick={toMath}><Sigma size={15} /></button>
			<button title="Make a cloze flashcard gap (Ctrl+Shift+C)" onclick={() => cmd('insertText', `{{${getSelection()?.toString() ?? ''}}}`)}><Braces size={15} /></button>
			<span class="sep"></span>
			<button title="Link (Ctrl+K)" onclick={openLink}><Link size={15} /></button>
			<button title="Text color" onclick={() => (mode = 'color')}><Baseline size={15} /></button>
			<button title="Highlight" onclick={() => (mode = 'bg')}><Highlighter size={15} /></button>
			<span class="sep"></span>
			<button class="txt note" title="Attach a note to this text" onclick={openNote}><StickyNote size={14} />Note</button>
		{:else if mode === 'note'}
			<form class="noteform" onsubmit={(e) => { e.preventDefault(); applyNote(); }}>
				<textarea bind:this={noteInput} bind:value={noteText} rows="3" placeholder="Write a note about this text…"
					onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') { restore(); mode = 'main'; } if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); applyNote(); } }}></textarea>
				<div class="noteacts"><span class="faint">Enter to save · Shift+Enter for a new line</span><button type="submit" class="txt">Save</button></div>
			</form>
		{:else if mode === 'link'}
			<form onsubmit={(e) => { e.preventDefault(); applyLink(); }}>
				<input bind:this={linkInput} bind:value={url} placeholder="Paste or type a link…"
					onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Escape') { restore(); mode = 'main'; } }} />
				<button type="submit" class="txt">{url.trim() ? 'Apply' : 'Remove'}</button>
			</form>
		{:else}
			{@const list = mode === 'color' ? COLORS : HIGHLIGHTS}
			<button class="txt" onclick={() => { mode === 'color' ? applyWrap(el!, 'span', 'data-color', '') : applyWrap(el!, 'mark', 'data-bg', ''); mode = 'main'; }}>Default</button>
			{#each list as c (c)}
				<button title={c} onclick={() => { mode === 'color' ? applyWrap(el!, 'span', 'data-color', c) : applyWrap(el!, 'mark', 'data-bg', c); mode = 'main'; }}>
					<span class="swatch" class:bg={mode === 'bg'} style:--sw="var(--c-{c})">{mode === 'color' ? 'A' : ''}</span>
				</button>
			{/each}
		{/if}
	</div>
{/if}

<style>
	.bar { position: fixed; z-index: 590; display: flex; align-items: center; gap: 1px; padding: 3px; animation: none; }
	button { min-width: 28px; height: 28px; display: grid; place-items: center; border-radius: 4px; color: var(--text-2); }
	button:hover { background: var(--hover); color: var(--text); }
	.txt { padding: 0 8px; font-size: 12.5px; }
	.note { display: flex; align-items: center; gap: 5px; }
	.noteform { display: flex; flex-direction: column; gap: 4px; width: 300px; padding: 2px; }
	.noteform textarea { width: 100%; resize: vertical; border: 0; outline: 0; background: var(--bg); border-radius: 4px; padding: 6px 8px; font: inherit; font-size: 13px; }
	.noteacts { display: flex; align-items: center; justify-content: space-between; font-size: 11px; }
	.sep { width: 1px; height: 18px; margin: 0 3px; background: var(--border); }
	form { display: flex; align-items: center; }
	input { width: 240px; height: 28px; padding: 0 8px; border: 0; outline: 0; background: none; }
	.swatch { width: 18px; height: 18px; display: grid; place-items: center; border-radius: 4px; font-weight: 700; font-size: 13px; color: var(--sw); }
	.swatch.bg { background: color-mix(in srgb, var(--sw) 45%, transparent); }
</style>
