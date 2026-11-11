<script lang="ts">
	import { renderMath, readHtml } from '../editor/dom.ts';

	let { value = $bindable(''), placeholder = '', cloze = false, minRows = 2, autofocus = false }: {
		value?: string; placeholder?: string; cloze?: boolean; minRows?: number; autofocus?: boolean;
	} = $props();

	let el = $state<HTMLElement>();

	function content(node: HTMLElement, v: string) {
		node.innerHTML = v;
		renderMath(node);
		if (autofocus) setTimeout(() => node.focus());
		return { update(v: string) { if (readHtml(node) !== v) { node.innerHTML = v; renderMath(node); } } };
	}

	function input() {
		value = readHtml(el!);
	}

	function key(e: KeyboardEvent) {
		const mod = e.ctrlKey || e.metaKey;
		// Let the dialog see Ctrl+Enter (save) and Escape (close); keep everything else local.
		if (!(mod && e.key === 'Enter') && e.key !== 'Escape') e.stopPropagation();
		if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); document.execCommand('bold'); }
		if (mod && e.key.toLowerCase() === 'i') { e.preventDefault(); document.execCommand('italic'); }
		if (mod && e.key.toLowerCase() === 'u') { e.preventDefault(); document.execCommand('underline'); }
		if (cloze && mod && e.shiftKey && e.key.toLowerCase() === 'c') { e.preventDefault(); makeCloze(); }
	}

	export function makeCloze() {
		const sel = getSelection();
		if (!el || !sel || !sel.rangeCount || !el.contains(sel.anchorNode)) {
			el?.focus();
			document.execCommand('insertText', false, '{{}}');
			return;
		}
		const text = sel.toString();
		document.execCommand('insertText', false, `{{${text}}}`);
		input();
	}

	function paste(e: ClipboardEvent) {
		e.preventDefault();
		document.execCommand('insertText', false, e.clipboardData?.getData('text/plain') ?? '');
	}
</script>

<div class="field rt" bind:this={el} contenteditable="true" role="textbox" tabindex="0" aria-multiline="true"
	data-placeholder={placeholder} class:blank={!value} style:min-height="{minRows * 1.55 + 1}em"
	use:content={value} oninput={input} onkeydown={key} onpaste={paste}></div>

<style>
	.field { padding: 8px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--bg); outline: none; line-height: 1.55; white-space: pre-wrap; font-size: 14.5px; }
	.field:focus { border-color: color-mix(in srgb, var(--accent) 65%, var(--border-strong)); }
	.field { position: relative; }
	.field.blank::before { content: attr(data-placeholder); position: absolute; left: 10px; top: 8px; color: var(--text-3); pointer-events: none; }
</style>
