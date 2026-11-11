import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.KERN_BACKEND ?? 'http://127.0.0.1:8421';
// Git smart HTTP (clone/push) goes to the backend; /git and /git/<name> stay app pages.
const proxy = { '/api': backend, '/media': backend, '^/git/[^/]+\\.git/': backend };

export default defineConfig({
	plugins: [
		sveltekit({
			// Single-page app: every route falls back to index.html.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: { proxy },
	preview: { proxy }
});
