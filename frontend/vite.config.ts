/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { KERN_ROUTES, KERN_SYSTEM } from './src/lib/kernRoutes';

const backend = process.env.KERN_BACKEND ?? 'http://127.0.0.1:8421';
// Git smart HTTP (clone/push) goes to the backend; /git and /git/<name> stay app pages.
// Apps (/<slug>/…, see docs/apps.md) go to the apps service; Kern's own routes stay app pages.
const gateway = process.env.KERN_APPS_GATEWAY ?? 'http://127.0.0.1:8100';
// (src and node_modules are Vite's own, in dev.)
const notKern = [...KERN_ROUTES, ...KERN_SYSTEM, 'src', 'node_modules'].join('|');
const proxy = {
	'/api': backend, '/media': backend, '^/git/[^/]+\\.git/': backend,
	[`^/(?!(?:${notKern})(?:/|$))[a-z0-9][a-z0-9-]*(?:/|$)`]: { target: gateway, ws: true },
	'^/_apps/': gateway
};

export default defineConfig({
	plugins: [
		sveltekit({
			// Single-page app: every route falls back to index.html.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: { proxy },
	preview: { proxy },
	// Unit tests (npm test): mail's pure helpers, in a browser-like DOM.
	test: { environment: 'jsdom', include: ['src/**/*.test.{js,ts}'] }
});
