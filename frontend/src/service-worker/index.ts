/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />
import { version } from '$app/env';
import { assets, immutable } from '$app/manifest';

const sw = self as unknown as ServiceWorkerGlobalScope;
const SHELL = `kern-shell-${version}`;
const DATA = 'kern-data-v1';
const MEDIA = 'kern-media-v1';
const ASSETS = [...immutable, ...assets].map((a) => '/' + String(a.path).replace(/^\//, ''));

// API reads that are worth keeping for offline use.
const CACHEABLE = [/^\/api\/tree$/, /^\/api\/tags$/, /^\/api\/settings$/, /^\/api\/documents\/[^/]+$/, /^\/api\/databases(\/[^/]+)?$/, /^\/api\/refs/, /^\/api\/templates$/];

sw.addEventListener('install', (event) => {
	event.waitUntil(caches.open(SHELL).then((c) => c.addAll([...ASSETS, '/'])).then(() => sw.skipWaiting()));
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches.keys()
			.then((keys) => Promise.all(keys.filter((k) => k.startsWith('kern-shell-') && k !== SHELL).map((k) => caches.delete(k))))
			.then(() => sw.clients.claim())
	);
});

sw.addEventListener('fetch', (event) => {
	const req = event.request;
	if (req.method !== 'GET') return;
	const url = new URL(req.url);
	if (url.origin !== location.origin) return;

	if (url.pathname.startsWith('/media/')) {
		// Audio/video stream with HTTP range requests (seeking, big files): straight to the network.
		if (req.headers.has('range') || req.destination === 'audio' || req.destination === 'video' || req.cache === 'no-store') return;
		const kind = req.destination;
		if (kind !== 'image') {
			// Documents can be edited in place under the same URL: network first, cached copy offline.
			event.respondWith(
				fetch(req)
					.then((res) => {
						if (res.ok && res.status === 200 && Number(res.headers.get('content-length') ?? 0) < 25 * 1024 * 1024) {
							const copy = res.clone();
							caches.open(MEDIA).then((c) => c.put(req, copy));
						}
						return res;
					})
					.catch(async () => (await caches.match(req)) ?? Response.error())
			);
			return;
		}
		// Images never change once uploaded: cache first.
		event.respondWith(
			caches.open(MEDIA).then(async (cache) => {
				const hit = await cache.match(req);
				if (hit) return hit;
				const res = await fetch(req);
				if (res.ok && res.status === 200) cache.put(req, res.clone());
				return res;
			})
		);
		return;
	}

	if (url.pathname.startsWith('/api/')) {
		if (!CACHEABLE.some((re) => re.test(url.pathname))) return;
		// Network first, so you always see the latest; fall back to the last copy offline.
		event.respondWith(
			fetch(req)
				.then(async (res) => {
					if (res.ok) {
						const copy = res.clone();
						caches.open(DATA).then((c) => c.put(req, copy));
					} else if (res.status >= 502) {
						// The proxy is up but the app server is not: treat it like being offline.
						throw new Error('server unavailable');
					}
					return res;
				})
				.catch(async () => {
					const hit = await caches.match(req);
					if (hit) {
						const headers = new Headers(hit.headers);
						headers.set('X-Kern-Offline', '1');
						return new Response(hit.body, { status: hit.status, headers });
					}
					return new Response(JSON.stringify({ detail: 'You are offline and this is not saved on this device yet.' }), {
						status: 503, headers: { 'Content-Type': 'application/json' }
					});
				})
		);
		return;
	}

	// Pages: always ask the server first so an update is never masked by an old copy;
	// keep the latest app shell for when the server cannot be reached.
	if (req.mode === 'navigate') {
		event.respondWith(
			fetch(req)
				.then((res) => {
					if (res.status >= 502) throw new Error('server unavailable');
					if (res.ok) {
						const copy = res.clone();
						caches.open(SHELL).then((c) => c.put('/', copy));
					}
					return res;
				})
				.catch(async () => (await caches.match('/')) ?? Response.error())
		);
		return;
	}
	// Built files have content hashes in their names, so a cached copy is always right.
	if (ASSETS.includes(url.pathname)) {
		event.respondWith(caches.match(url.pathname).then((hit) => hit ?? fetch(req)));
	}
});
