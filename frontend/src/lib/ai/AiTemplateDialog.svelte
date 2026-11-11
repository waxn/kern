<script lang="ts">
	import { goto } from '$app/navigation';
	import { ai } from './ai.svelte.ts';
	import Sparkle from './Sparkle.svelte';

	let { onclose }: { onclose: () => void } = $props();
	let prompt = $state('');
	let busy = $state(false);
	const ideas = ['Weekly review', 'Meeting notes with decisions and action items', 'Book notes', 'Project brief', 'Daily journal'];

	async function generate() {
		if (!prompt.trim()) return;
		busy = true;
		const t = await ai.run<{ id: string }>('/ai/template', { prompt });
		busy = false;
		if (t) {
			onclose();
			goto(`/doc/${t.id}`);
		}
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="overlay" onmousedown={(e) => e.target === e.currentTarget && !busy && onclose()} onkeydown={(e) => e.key === 'Escape' && !busy && onclose()}>
	<div class="dialog popover" role="dialog" aria-label="Generate a template">
		<h2><Sparkle size={18} />Generate a template</h2>
		<!-- svelte-ignore a11y_autofocus -->
		<textarea class="input" rows="3" autofocus bind:value={prompt} placeholder="Describe the template: what it's for and what sections it needs…"
			onkeydown={(e) => { e.stopPropagation(); if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate(); }}></textarea>
		<div class="ideas">{#each ideas as i (i)}<button class="chip" onclick={() => (prompt = i)}>{i}</button>{/each}</div>
		<p class="faint small">You can edit the template after it's created.</p>
		<div class="foot">
			<button class="btn ghost" onclick={onclose}>Cancel</button>
			<button class="btn primary" disabled={busy || !prompt.trim()} onclick={generate}>{busy ? 'Thinking…' : 'Create template'}</button>
		</div>
	</div>
</div>

<style>
	.overlay { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 16px; background: rgba(0, 0, 0, 0.5); animation: fade 0.12s; }
	.dialog { width: min(520px, 100%); padding: 18px; display: flex; flex-direction: column; gap: 10px; }
	h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 16px; }
	textarea { width: 100%; resize: vertical; font: inherit; }
	.ideas { display: flex; flex-wrap: wrap; gap: 6px; }
	.ideas .chip { cursor: pointer; }
	.ideas .chip:hover { color: var(--text); }
	.small { margin: 0; font-size: 12.5px; }
	.foot { display: flex; justify-content: flex-end; gap: 8px; }
</style>
