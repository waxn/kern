<script lang="ts">
	import { renderMath } from '#lib/editor/dom.ts';
	import type { Block } from '#lib/types.ts';
	import Self from './StaticBlocks.svelte';

	let { blocks, parent = null }: { blocks: Block[]; parent?: string | null } = $props();
	let kids = $derived(blocks.filter((b) => (b.parent ?? null) === parent).sort((a, b) => a.position - b.position));

	function math(node: HTMLElement, _v: string) {
		renderMath(node);
		return { update() { renderMath(node); } };
	}
</script>

{#each kids as b, i (b.id)}
	<div class="sb t-{b.type}">
		<div class="line">
			{#if b.type === 'bullet' || b.type === 'toggle'}<span class="mk">•</span>
			{:else if b.type === 'numbered'}<span class="mk">{kids.slice(0, i + 1).filter((k) => k.type === 'numbered').length}.</span>
			{:else if b.type === 'todo'}<span class="mk">{b.props.checked ? '☑' : '☐'}</span>
			{:else if b.type === 'callout'}<span class="mk">{b.props.icon ?? '💡'}</span>{/if}
			{#if b.type === 'divider'}<hr />
			{:else if b.type === 'code'}<pre>{@html b.html}</pre>
			{:else if b.type === 'equation'}<code class="tex">{b.props.tex}</code>
			{:else if b.type === 'image' && b.props.url}<img src={b.props.url} alt="" />
			{:else if ['video', 'audio', 'file', 'bookmark'].includes(b.type)}<span class="faint">[{b.type}: {b.props.name || b.props.title || b.props.url || 'empty'}]</span>
			{:else if b.type === 'table'}
				<table>{#each b.props.rows ?? [] as r, ri (ri)}<tr>{#each r as c, ci (ci)}<td class="rt">{@html c}</td>{/each}</tr>{/each}</table>
			{:else if b.type === 'embed' || b.type === 'database'}<span class="faint">[{b.type === 'embed' ? 'embedded content' : 'database view'}]</span>
			{:else}<div class="rt txt" use:math={b.html}>{@html b.html || '&nbsp;'}</div>{/if}
		</div>
		<div class="kids"><Self {blocks} parent={b.id} /></div>
	</div>
{/each}

<style>
	.sb { font-family: var(--font-editor); font-size: var(--editor-size); line-height: 1.6; }
	.line { display: flex; gap: 6px; }
	.mk { flex: none; width: 18px; text-align: center; color: var(--text-2); }
	.txt { flex: 1; min-width: 0; white-space: pre-wrap; }
	.kids { margin-left: 24px; }
	.kids:empty { display: none; }
	.t-h1 .txt { font-size: 24px; font-weight: 680; margin-top: 12px; }
	.t-h2 .txt { font-size: 19px; font-weight: 650; margin-top: 10px; }
	.t-h3 .txt { font-size: 16px; font-weight: 640; margin-top: 6px; }
	.t-quote .txt { border-left: 3px solid var(--text-3); padding-left: 10px; color: var(--text-2); }
	.t-callout .line { background: var(--surface-2); padding: 6px 10px; border-radius: var(--radius); }
	hr { flex: 1; border: 0; border-top: 1px solid var(--border-strong); }
	pre { flex: 1; margin: 2px 0; padding: 8px 10px; background: var(--surface); border-radius: var(--radius); font: 13px var(--font-mono); white-space: pre-wrap; }
	img { max-width: 100%; max-height: 260px; border-radius: var(--radius); }
	table { border-collapse: collapse; }
	td { border: 1px solid var(--border-strong); padding: 3px 8px; }
</style>
