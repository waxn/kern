<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Mail inside Kern: checks that mail can be used here (two-factor sign-in, a
  // connected account), then shows the mail shell. Lives at /mail/... .
  import './mail.css';
  import { onDestroy, onMount } from 'svelte';
  import { KeyRound, LogOut, Mail, Settings } from '@lucide/svelte';
  import { goto } from '$app/navigation';
  import { logout } from '#lib/state/session.svelte.ts';
  import { gate } from './api.svelte.js';
  import { sync } from './router.svelte.js';
  import { mailStatus, loadMailStatus } from './status.svelte.js';
  import { unreadInbox } from './state.svelte.js';
  import Shell from './components/Shell.svelte';

  let { url } = $props();

  $effect(() => sync(url));
  onMount(() => loadMailStatus());
  // Kern's other pages don't set a title; don't leave "(3) Mail" behind.
  onDestroy(() => { if (typeof document !== 'undefined') document.title = 'Kern'; });

  // What stands between the user and their mail, if anything.
  const blocker = $derived.by(() => {
    const s = mailStatus.data;
    if (gate.code === 'needs_2fa' || (s && !s.two_factor.enabled)) return 'needs_2fa';
    if (gate.code === 'needs_2fa_session' || (s && !s.two_factor.session_verified)) return 'needs_session';
    if (s && !s.allowed && !s.connected) return 'off';
    if (s && !s.connected && !s.account?.address) return 'connect';
    return '';
  });
  const unread = $derived(blocker || !mailStatus.data ? 0 : unreadInbox());
</script>

<svelte:head><title>{unread ? `(${unread}) Mail` : 'Mail'} · Kern</title></svelte:head>

<div class="mail-app">
  {#if !mailStatus.data && !mailStatus.error}
    <div class="center"><span class="spinner"></span></div>
  {:else if blocker}
    <div class="center">
      <div class="gate">
        {#if blocker === 'needs_2fa'}
          <KeyRound size={28} strokeWidth={1.5} />
          <h1>Mail needs two-factor sign-in</h1>
          <p>Your whole mailbox would be reachable with just your password, so Kern asks for an authenticator
            app first. It takes a minute: Settings → Account → Two-factor sign-in.</p>
          <button class="btn primary" onclick={() => goto('/settings?s=account')}><Settings size={14} /> Set it up</button>
        {:else if blocker === 'needs_session'}
          <KeyRound size={28} strokeWidth={1.5} />
          <h1>Sign in again with your code</h1>
          <p>This browser signed in with your password only. To open mail, sign out and back in with the code from
            your authenticator app.</p>
          <button class="btn primary" onclick={() => logout()}><LogOut size={14} /> Sign out</button>
        {:else if blocker === 'off'}
          <Mail size={28} strokeWidth={1.5} />
          <h1>Mail is turned off</h1>
          <p>An administrator has turned mail off on this server.</p>
        {:else}
          <Mail size={28} strokeWidth={1.5} />
          <h1>Connect your mailbox</h1>
          <p>Kern reads and sends your mail over IMAP and SMTP, keeps a local copy for fast search, and changes on
            either side show up on the other. Works with Purelymail, Fastmail, Gmail, iCloud, Outlook and most
            providers.</p>
          <button class="btn primary" onclick={() => goto('/settings?s=mail')}><Settings size={14} /> Connect an account</button>
        {/if}
      </div>
    </div>
  {:else}
    <Shell />
  {/if}
</div>

<style>
  .center { height: 100%; display: grid; place-items: center; padding: 24px; }
  .gate { max-width: 440px; text-align: center; color: var(--text-2); display: grid; justify-items: center; gap: 8px; }
  .gate :global(svg:first-child) { color: var(--text-3); }
  h1 { font-size: 17px; font-weight: 650; color: var(--text); margin: 6px 0 0; }
  p { margin: 0 0 8px; line-height: 1.55; }
</style>
