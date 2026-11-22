<script lang="ts">
	// Notes | Mail, at the top of the sidebar (like Claude's Chat | Code switch).
	import { Mail, NotebookPen } from '@lucide/svelte';
	import { mailToday } from '#lib/mail/badge.svelte.js';
	import { session } from '#lib/state/session.svelte.ts';
	import { switchMode, type Mode } from '#lib/state/mode.ts';

	let { mode }: { mode: Mode } = $props();
	const unread = $derived((mailToday as { data?: { unread?: number } }).data?.unread ?? 0);
</script>

{#if session.site?.allow_mail !== false}
	<div class="switch" role="radiogroup" aria-label="Notes or Mail">
		<button role="radio" aria-checked={mode === 'notes'} class:on={mode === 'notes'} title="Notes"
			onclick={() => mode !== 'notes' && switchMode('notes')}><NotebookPen size={15} strokeWidth={1.75} /></button>
		<button role="radio" aria-checked={mode === 'mail'} class:on={mode === 'mail'} title="Mail{unread ? ` · ${unread} unread` : ''} (Alt+M)"
			onclick={() => mode !== 'mail' && switchMode('mail')}>
			<Mail size={15} strokeWidth={1.75} />
			{#if unread && mode !== 'mail'}<span class="dot" aria-label="{unread} unread"></span>{/if}
		</button>
		<span class="pill" class:right={mode === 'mail'} aria-hidden="true"></span>
	</div>
{/if}

<style>
	.switch { position: relative; display: inline-flex; align-items: center; gap: 0; padding: 2px; border-radius: 9px; background: var(--surface-2, var(--hover)); border: 1px solid var(--border); flex: none; }
	button { position: relative; z-index: 1; width: 30px; height: 24px; display: grid; place-items: center; border-radius: 7px; color: var(--text-3); transition: color 0.15s var(--ease); }
	button:hover { color: var(--text); }
	button.on { color: var(--text); }
	.pill { position: absolute; z-index: 0; top: 2px; left: 2px; width: 30px; height: 24px; border-radius: 7px; background: var(--bg); box-shadow: 0 1px 2px rgb(0 0 0 / 0.25), inset 0 0 0 1px var(--border); transition: transform 0.2s var(--ease); }
	.pill.right { transform: translateX(30px); }
	.dot { position: absolute; top: 3px; right: 5px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 2px var(--surface-2, var(--bg-side)); }
	@media (prefers-reduced-motion: reduce) { .pill { transition: none; } }
</style>
