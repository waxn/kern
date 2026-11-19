<script lang="ts">
	// Settings → "CI secrets": values only ever go to the server; the list shows names.
	import { KeyRound, Plus, Trash2 } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { relTime } from '#lib/util.ts';
	import type { CiSecret } from './ci.ts';

	let { repo }: { repo: string } = $props();
	const base = $derived(`/git/repos/${encodeURIComponent(repo)}/ci/secrets`);

	let secrets = $state<CiSecret[]>([]);
	let name = $state('');
	let value = $state('');
	let busy = $state(false);

	$effect(() => {
		const b = base;
		let stale = false;
		api.get<{ secrets: CiSecret[] }>(b).then((d) => !stale && (secrets = d.secrets)).catch((e) => ui.error(e));
		return () => (stale = true);
	});

	const valid = $derived(/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(name.trim()) && !name.trim().startsWith('KERN_') && value.length > 0);

	async function save(e: SubmitEvent) {
		e.preventDefault();
		if (!valid || busy) return;
		busy = true;
		try {
			const n = name.trim();
			secrets = (await api.put<{ secrets: CiSecret[] }>(`${base}/${encodeURIComponent(n)}`, { value })).secrets;
			ui.toast(`Saved ${n}`);
			name = '';
			value = '';
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function remove(s: CiSecret) {
		const ok = await ui.confirm({
			title: `Delete ${s.name}?`,
			message: 'Pipelines that list this secret will fail until it is set again.',
			confirmLabel: 'Delete secret', danger: true
		});
		if (!ok) return;
		try {
			await api.del(`${base}/${encodeURIComponent(s.name)}`);
			secrets = secrets.filter((x) => x.name !== s.name);
		} catch (err) {
			ui.error(err);
		}
	}
</script>

<section class="set">
	<h3><KeyRound size={15} />CI secrets</h3>
	<p class="muted">
		Available to the jobs of this repository's pipelines that list them under <code>secrets:</code>, as environment variables.
		They are stored encrypted, masked in logs and never shown again. Saving a name that exists replaces its value.
	</p>
	{#if secrets.length}
		<div class="box">
			{#each secrets as s (s.name)}
				<div class="row">
					<code class="pat">{s.name}</code>
					<span class="grow"></span>
					<span class="faint">updated {relTime(s.updated)}</span>
					<button class="icon-btn" title="Delete {s.name}" onclick={() => remove(s)}><Trash2 size={14} /></button>
				</div>
			{/each}
		</div>
	{/if}
	<form class="add" onsubmit={save}>
		<input class="input nm" placeholder="NAME" bind:value={name} autocomplete="off" spellcheck="false" aria-label="Secret name" />
		<input class="input" type="password" placeholder="Value" bind:value autocomplete="new-password" aria-label="Secret value" />
		<button class="btn" disabled={!valid || busy}><Plus size={13} />Save</button>
	</form>
</section>

<style>
	.set { margin-bottom: 28px; }
	.set :global(h3) { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.set :global(.muted) { margin: 0 0 10px; font-size: 13px; }
	.box { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; }
	.row { display: flex; align-items: center; gap: 12px; padding: 7px 10px; flex-wrap: wrap; }
	.row + .row { border-top: 1px solid var(--border); }
	.pat { font-size: 13px; }
	.grow { flex: 1; }
	.faint { font-size: 12px; }
	.add { display: flex; gap: 8px; max-width: 560px; flex-wrap: wrap; }
	.add .input { flex: 1; min-width: 140px; }
	.add .nm { flex: 0 1 180px; font-family: var(--font-mono); }
</style>
