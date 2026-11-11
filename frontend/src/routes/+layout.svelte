<script lang="ts">
	import '../app.css';
	import 'katex/dist/katex.min.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import AppShell from '#lib/components/AppShell.svelte';
	import AuthForm from '#lib/auth/AuthForm.svelte';
	import Setup from '#lib/auth/Setup.svelte';
	import Landing from '#lib/landing/Landing.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import { prefs, resolvedTheme } from '#lib/state/prefs.svelte.ts';
	import { loadSession, session } from '#lib/state/session.svelte.ts';

	let { children } = $props();
	let systemLight = $state(false);

	onMount(() => {
		loadSession();
		const mq = matchMedia('(prefers-color-scheme: light)');
		systemLight = mq.matches;
		const onChange = () => (systemLight = mq.matches);
		mq.addEventListener('change', onChange);
		return () => mq.removeEventListener('change', onChange);
	});

	// People who are not signed in see the system theme unless they picked one on the landing page.
	function publicTheme(): 'dark' | 'light' {
		try {
			const t = JSON.parse(localStorage.getItem('kern:prefs') ?? '{}').theme;
			if (t === 'dark' || t === 'light') return t;
		} catch {
			/* none stored */
		}
		return systemLight ? 'light' : 'dark';
	}

	$effect(() => {
		void systemLight;
		const root = document.documentElement;
		const signedIn = !!session.user;
		root.dataset.theme = signedIn ? resolvedTheme() : publicTheme();
		root.dataset.density = signedIn ? prefs.density : 'comfortable';
		root.dataset.font = signedIn ? prefs.font : 'sans';
		root.dataset.size = signedIn ? prefs.editorSize : 'medium';
		if (signedIn && prefs.accent) root.style.setProperty('--accent', prefs.accent);
		else root.style.removeProperty('--accent');
	});

	let path = $derived(page.url.pathname);
	let site = $derived(session.site);

	// Which screen to show: setup, the app, or one of the public pages.
	let view = $derived.by(() => {
		if (!session.ready) return 'loading';
		if (!site) return 'down';
		if (site.needs_setup) return 'setup';
		if (site.user) return 'app';
		if (path === '/signup') return site.signup_mode === 'closed' ? 'login' : 'signup';
		if (path === '/login') return 'login';
		if (path === '/' && site.landing_enabled) return 'landing';
		return 'login';
	});

	// Signed in on a sign-in page: go home.
	$effect(() => {
		if (view === 'app' && (path === '/login' || path === '/signup')) goto('/', { replaceState: true });
	});
</script>

<svelte:head>
	<title>{site?.site_name ?? 'Kern'}</title>
</svelte:head>

{#if view === 'app'}
	<AppShell {children} />
{:else if view === 'setup'}
	<Setup />
{:else if view === 'landing'}
	<Landing />
{:else if view === 'login' || view === 'signup'}
	<AuthForm mode={view} />
{:else if view === 'down'}
	<div class="splash">
		<Logo size={34} />
		<b>Cannot reach the Kern server</b>
		<span>Check that the backend container is running, then reload.</span>
		<button class="btn" onclick={() => loadSession()}>Retry</button>
	</div>
{:else}
	<div class="splash"><Logo size={34} /></div>
{/if}

<style>
	.splash { height: 100dvh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--text-2); text-align: center; padding: 20px; }
	.splash b { color: var(--text); font-weight: 600; }
</style>
