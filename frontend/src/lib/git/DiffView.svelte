<script lang="ts">
	import { ChevronDown, ChevronRight, FileMinus, FilePen, FilePlus, FileSymlink } from '@lucide/svelte';
	import type { DiffFile } from './types.ts';

	let { files, onopen }: { files: DiffFile[]; onopen?: (path: string) => void } = $props();
	let collapsed = $state<Record<number, boolean>>({});
	const icon = { added: FilePlus, deleted: FileMinus, modified: FilePen, renamed: FileSymlink };
	const bars = (f: DiffFile) => {
		const total = f.additions + f.deletions;
		if (!total) return [0, 0];
		const a = Math.round((f.additions / total) * 5);
		return [a, 5 - a];
	};
</script>

<div class="files">
	{#each files as f, i (i)}
		{@const Icon = icon[f.status]}
		{@const [a, d] = bars(f)}
		<section class="file" id="file-{i}">
			<header>
				<button class="icon-btn" onclick={() => (collapsed[i] = !collapsed[i])} title={collapsed[i] ? 'Expand' : 'Collapse'}>
					{#if collapsed[i]}<ChevronRight size={14} />{:else}<ChevronDown size={14} />{/if}
				</button>
				<span class="st {f.status}"><Icon size={14} /></span>
				<button class="path truncate" onclick={() => f.new_path && onopen?.(f.new_path)} disabled={!f.new_path || !onopen}>
					{#if f.status === 'renamed'}<span class="faint">{f.old_path} →</span> {/if}{f.new_path ?? f.old_path}
				</button>
				<span class="grow"></span>
				<span class="num"><span class="add">+{f.additions}</span> <span class="del">−{f.deletions}</span></span>
				<span class="blocks">{#each { length: 5 } as _, k (k)}<i class={k < a ? 'a' : k < a + d ? 'd' : ''}></i>{/each}</span>
			</header>
			{#if !collapsed[i]}
				{#if f.binary}
					<p class="note">Binary file not shown.</p>
				{:else if !f.hunks.length}
					<p class="note">{f.status === 'renamed' ? 'File renamed without changes.' : f.truncated ? 'Diff too large to show.' : 'No content changes.'}</p>
				{:else}
					<div class="code">
						<table>
							<tbody>
								{#each f.hunks as h, hi (hi)}
									<tr class="hunk"><td class="ln" colspan="2"></td><td>{h.header}</td></tr>
									{#each h.lines as l, li (li)}
										<tr class={l.t === '+' ? 'ins' : l.t === '-' ? 'rem' : ''}>
											<td class="ln">{l.o ?? ''}</td><td class="ln">{l.n ?? ''}</td>
											<td><span class="sign">{l.t === ' ' ? ' ' : l.t === '-' ? '−' : '+'}</span>{l.s}</td>
										</tr>
									{/each}
								{/each}
							</tbody>
						</table>
					</div>
					{#if f.truncated}<p class="note">Diff truncated.</p>{/if}
				{/if}
			{/if}
		</section>
	{/each}
</div>

<style>
	.files { display: flex; flex-direction: column; gap: 12px; }
	.file { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface); }
	header { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 6px; padding: 5px 10px 5px 6px; background: var(--surface-2); border-bottom: 1px solid var(--border); font-size: 13px; }
	.path { font: 12.5px var(--font-mono); color: var(--text); text-align: left; }
	.path:not(:disabled):hover { color: var(--accent); }
	.grow { flex: 1; }
	.st { display: grid; color: var(--text-2); }
	.st.added { color: var(--c-green); } .st.deleted { color: var(--c-red); } .st.renamed { color: var(--c-blue); }
	.num { font: 12px var(--font-mono); white-space: nowrap; }
	.add { color: var(--c-green); } .del { color: var(--c-red); }
	.blocks { display: flex; gap: 1px; }
	.blocks i { width: 7px; height: 7px; border-radius: 1.5px; background: var(--border-strong); }
	.blocks i.a { background: var(--c-green); } .blocks i.d { background: var(--c-red); }
	.note { margin: 0; padding: 10px 14px; color: var(--text-3); font-size: 12.5px; }
	.code { overflow-x: auto; }
	table { border-collapse: collapse; width: 100%; font: 12.5px/1.55 var(--font-mono); tab-size: 4; }
	td { padding: 0 10px 0 0; white-space: pre; vertical-align: top; }
	td.ln { width: 1%; min-width: 38px; padding: 0 8px; text-align: right; color: var(--text-3); user-select: none; }
	.sign { display: inline-block; width: 16px; color: var(--text-3); user-select: none; }
	tr.ins { background: color-mix(in srgb, var(--c-green) 13%, transparent); }
	tr.ins td.ln { background: color-mix(in srgb, var(--c-green) 18%, transparent); }
	tr.ins .sign { color: var(--c-green); }
	tr.rem { background: color-mix(in srgb, var(--c-red) 13%, transparent); }
	tr.rem td.ln { background: color-mix(in srgb, var(--c-red) 18%, transparent); }
	tr.rem .sign { color: var(--c-red); }
	tr.hunk td { padding-top: 3px; padding-bottom: 3px; color: var(--text-3); background: color-mix(in srgb, var(--c-blue) 8%, transparent); }
</style>
