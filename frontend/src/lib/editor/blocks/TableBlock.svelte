<script lang="ts">
	import { Plus } from '@lucide/svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import type { Block } from '#lib/types.ts';
	import { readHtml } from '../dom';
	import { getEditor } from '../context';

	let { block }: { block: Block } = $props();
	const ed = getEditor();
	let rows = $derived((block.props.rows as string[][] | undefined) ?? [['', ''], ['', '']]);
	let timer: ReturnType<typeof setTimeout>;
	let table = $state<HTMLTableElement>();

	function cell(node: HTMLElement, value: string) {
		node.innerHTML = value;
		return { update(v: string) { if (readHtml(node) !== v) node.innerHTML = v; } };
	}

	function grid(): string[][] {
		return rows.map((r) => [...r]);
	}

	function commit(next: string[][], extra: Record<string, any> = {}) {
		clearTimeout(timer);
		ed.doc.setProps(block.id, { rows: next, ...extra });
	}

	function readDom(): string[][] {
		return [...table!.rows].map((tr) => [...tr.cells].map((td) => readHtml(td.firstElementChild as HTMLElement)));
	}

	function oninput() {
		clearTimeout(timer);
		timer = setTimeout(() => commit(readDom()), 500);
	}

	function flush() {
		const now = readDom();
		if (JSON.stringify(now) !== JSON.stringify(rows)) commit(now);
	}

	function focusCell(r: number, c: number) {
		const el = table?.rows[r]?.cells[c]?.firstElementChild as HTMLElement | undefined;
		if (!el) return false;
		el.focus();
		const range = document.createRange();
		range.selectNodeContents(el);
		range.collapse(false);
		getSelection()?.removeAllRanges();
		getSelection()?.addRange(range);
		return true;
	}

	function keydown(e: KeyboardEvent, r: number, c: number) {
		e.stopPropagation();
		if (e.key === 'Tab') {
			e.preventDefault();
			const n = r * rows[0].length + c + (e.shiftKey ? -1 : 1);
			if (n >= rows.length * rows[0].length) {
				addRow(rows.length);
				setTimeout(() => focusCell(rows.length - 1, 0));
			} else if (n >= 0) focusCell(Math.floor(n / rows[0].length), n % rows[0].length);
		} else if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			if (!focusCell(r + 1, c)) {
				addRow(rows.length);
				setTimeout(() => focusCell(r + 1, c));
			}
		}
	}

	function addRow(at: number) {
		flush();
		const g = grid();
		g.splice(at, 0, Array(g[0].length).fill(''));
		commit(g);
	}
	function addCol(at: number) {
		flush();
		commit(grid().map((r) => (r.splice(at, 0, ''), r)));
	}
	function delRow(at: number) {
		flush();
		if (rows.length > 1) commit(grid().filter((_, i) => i !== at));
	}
	function delCol(at: number) {
		flush();
		if (rows[0].length > 1) commit(grid().map((r) => r.filter((_, i) => i !== at)));
	}

	function menu(e: MouseEvent, r: number, c: number) {
		ui.openMenu(e, [
			{ label: 'Insert row above', onSelect: () => addRow(r) },
			{ label: 'Insert row below', onSelect: () => addRow(r + 1) },
			{ label: 'Insert column left', onSelect: () => addCol(c) },
			{ label: 'Insert column right', onSelect: () => addCol(c + 1) },
			{ separator: true },
			{ label: 'Header row', checked: !!block.props.header, onSelect: () => ed.doc.setProps(block.id, { header: !block.props.header }) },
			{ separator: true },
			{ label: 'Delete row', danger: true, onSelect: () => delRow(r) },
			{ label: 'Delete column', danger: true, onSelect: () => delCol(c) }
		]);
	}
</script>

<div class="wrap">
	<div class="scroll">
		<table bind:this={table} class:header={block.props.header}>
			<tbody>
				{#each rows as row, r (r)}
					<tr>
						{#each row as html, c (c)}
							<td oncontextmenu={(e) => menu(e, r, c)}>
								<div class="rt" contenteditable="true" use:cell={html} {oninput} onblur={flush} onkeydown={(e) => keydown(e, r, c)} role="textbox" tabindex="0"></div>
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		<button class="add col" title="Add column" onclick={() => addCol(rows[0].length)}><Plus size={13} /></button>
	</div>
	<button class="add row" title="Add row" onclick={() => addRow(rows.length)}><Plus size={13} /></button>
</div>

<style>
	.wrap { flex: 1; min-width: 0; margin: 4px 0; }
	.scroll { display: flex; overflow-x: auto; }
	table { border-collapse: collapse; }
	td { border: 1px solid var(--border-strong); min-width: 110px; max-width: 340px; padding: 0; vertical-align: top; }
	td > div { padding: 5px 9px; min-height: 30px; outline: none; }
	td:focus-within { box-shadow: inset 0 0 0 1.5px var(--accent); }
	table.header tr:first-child td { background: var(--surface-2); font-weight: 600; }
	.add { display: grid; place-items: center; color: var(--text-3); border-radius: var(--radius-sm); opacity: 0; transition: opacity 0.12s; }
	.wrap:hover .add { opacity: 1; }
	.add:hover { background: var(--hover); color: var(--text); }
	.add.col { flex: none; width: 20px; margin-left: 4px; }
	.add.row { width: 100%; height: 20px; margin-top: 4px; }
</style>
