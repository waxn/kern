import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.KERN_BACKEND ?? 'http://127.0.0.1:8421';

export default defineConfig({
	plugins: [
		sveltekit({
			// Single-page app: every route falls back to index.html.
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: { '/api': backend, '/media': backend }
	},
	preview: {
		proxy: { '/api': backend, '/media': backend }
	}
});
