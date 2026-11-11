<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '#lib/api.ts';
	import Toggle from '#lib/auth/Toggle.svelte';
	import { session } from '#lib/state/session.svelte.ts';
	import { ui } from '#lib/state/ui.svelte.ts';

	interface Cfg { site_name: string; landing_enabled: boolean; signup_mode: 'closed' | 'approval' | 'open'; allow_git: boolean }
	let cfg = $state<Cfg | null>(null);
	let name = $state('');

	onMount(async () => {
		try {
			cfg = await api.get<Cfg>('/admin/site');
			name = cfg.site_name;
		} catch (e) {
			ui.error(e);
		}
	});

	async function save(patch: Partial<Cfg>) {
		try {
			cfg = await api.patch<Cfg>('/admin/site', patch);
			if (session.site) session.site = { ...session.site, ...cfg };
		} catch (e) {
			ui.error(e);
		}
	}
</script>

{#if cfg}
	<p class="lede">These apply to the whole server. Only administrators can see this page.</p>
	<div class="group">
		<div class="item">
			<div><b>Server name</b><span>Shown on the sign-in and landing pages.</span></div>
			<div class="row"><input class="input wide" bind:value={name} maxlength="60" /><button class="btn" disabled={name.trim() === cfg.site_name || !name.trim()} onclick={() => save({ site_name: name })}>Save</button></div>
		</div>
		<div class="item">
			<div><b>Public landing page</b><span>When on, people who are not signed in see the landing page at <code>/</code>. When off they go straight to sign in.</span></div>
			<Toggle checked={cfg.landing_enabled} label="Public landing page" onchange={(v) => save({ landing_enabled: v })} />
		</div>
		<div class="item">
			<div><b>Sign-ups</b><span>Who may create an account on their own. Administrators can always add people under Users.</span></div>
			<div class="seg">
				{#each [['closed', 'Invite only'], ['approval', 'Needs approval'], ['open', 'Open']] as [v, label] (v)}
					<button class:on={cfg.signup_mode === v} onclick={() => save({ signup_mode: v as Cfg['signup_mode'] })}>{label}</button>
				{/each}
			</div>
		</div>
		<div class="item">
			<div><b>Git hosting</b><span>Let people host repositories and push to them over HTTP. Turning it off also blocks git clients.</span></div>
			<Toggle checked={cfg.allow_git} label="Git hosting" onchange={(v) => save({ allow_git: v })} />
		</div>
	</div>
{:else}
	<p class="lede">Loading…</p>
{/if}

<style>
	.group { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; }
	.item { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
	.item:first-child { border-top: 0; }
	.item > div:first-child { flex: 1; min-width: 220px; }
	.item b { display: block; font-weight: 550; }
	.item span { color: var(--text-3); font-size: 12.5px; }
	.row { display: flex; gap: 6px; }
	.wide { width: min(260px, 100%); }
	.seg { display: flex; padding: 2px; border-radius: var(--radius); background: var(--surface-2); }
	.seg button { padding: 3px 11px; border-radius: 4px; color: var(--text-2); }
	.seg button.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	code { font-family: var(--font-mono); font-size: 0.9em; background: var(--code-bg); padding: 0 4px; border-radius: 3px; }
</style>
