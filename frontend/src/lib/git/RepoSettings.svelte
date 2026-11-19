<script lang="ts">
	// The repository's Settings tab. Each feature (protected branches, access tokens, CI, mirrors…)
	// is its own <section class="set"> here, usually its own component.
	import { Plus, ShieldCheck, Trash2 } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import RepoAccess from './RepoAccess.svelte';
	import type { ProtectedRule, RepoDetail } from './types.ts';

	let { repo, onchange }: { repo: RepoDetail; onchange: (r: RepoDetail) => void } = $props();

	let rules = $state<ProtectedRule[]>([]);
	let pattern = $state('');
	$effect(() => {
		rules = (repo.protected ?? []).map((r) => ({ ...r }));
	});

	async function saveRules(next: ProtectedRule[]) {
		try {
			onchange(await api.patch<RepoDetail>(`/git/repos/${repo.name}`, { protected: next }));
		} catch (e) {
			ui.error(e);
			rules = (repo.protected ?? []).map((r) => ({ ...r }));
		}
	}

	function addRule(e: SubmitEvent) {
		e.preventDefault();
		const p = pattern.trim();
		if (!p) return;
		pattern = '';
		saveRules([...rules, { pattern: p, allow_force: false, allow_delete: false }]);
	}
</script>

<section class="set">
	<h3><ShieldCheck size={15} />Protected branches</h3>
	<p class="muted">Pushes that would rewrite or delete these branches are refused, from every client. Patterns may use <code>*</code>, e.g. <code>release/*</code>.</p>
	{#if rules.length}
		<div class="box">
			{#each rules as r, i (r.pattern)}
				<div class="row">
					<code class="pat">{r.pattern}</code>
					<span class="grow"></span>
					<label class="chk"><input type="checkbox" bind:checked={r.allow_force} onchange={() => saveRules(rules)} />Allow force-push</label>
					<label class="chk"><input type="checkbox" bind:checked={r.allow_delete} onchange={() => saveRules(rules)} />Allow delete</label>
					<button class="icon-btn" title="Stop protecting {r.pattern}" onclick={() => saveRules(rules.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
				</div>
			{/each}
		</div>
	{/if}
	<form class="add" onsubmit={addRule}>
		<input class="input" placeholder={rules.length ? 'Another branch or pattern' : repo.default_branch || 'main'} bind:value={pattern} aria-label="Branch or pattern to protect" />
		<button class="btn" disabled={!pattern.trim()}><Plus size={13} />Protect</button>
	</form>
</section>

<RepoAccess {repo} {onchange} />

<style>
	.set { margin-bottom: 28px; }
	.set :global(h3) { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.set :global(.muted) { margin: 0 0 10px; font-size: 13px; }
	.box { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; }
	.row { display: flex; align-items: center; gap: 12px; padding: 7px 10px; flex-wrap: wrap; }
	.row + .row { border-top: 1px solid var(--border); }
	.pat { font-size: 13px; }
	.grow { flex: 1; }
	.chk { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--text-2); }
	.add { display: flex; gap: 8px; max-width: 420px; }
	.add .input { flex: 1; min-width: 0; }
</style>
