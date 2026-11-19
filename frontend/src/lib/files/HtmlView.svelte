<script lang="ts">
	/* An HTML file rendered as a page. It is treated as untrusted: DOMPurify cleans it, and it is
	   shown in an <iframe srcdoc> with no allow-scripts and a CSP that allows no network access
	   except images embedded as data: URLs. Links open in a new tab. */
	import type { FileRef } from './kind.ts';

	let { file, version = 0 }: { file: FileRef; version?: number } = $props();
	let srcdoc = $state('');
	let error = $state('');

	const CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; script-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'";

	async function load() {
		error = '';
		try {
			const [{ default: DOMPurify }, res] = await Promise.all([import('dompurify'), fetch(file.url, { cache: 'no-store' })]);
			if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
			const clean = DOMPurify.sanitize(await res.text(), { WHOLE_DOCUMENT: true, FORBID_TAGS: ['form', 'meta', 'base', 'link'] });
			const doc = new DOMParser().parseFromString(clean, 'text/html');
			srcdoc =
				`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CSP}">` +
				'<meta name="referrer" content="no-referrer"><base target="_blank">' +
				'<style>html{background:#fff;color:#222}body{font:15px/1.5 system-ui,sans-serif;margin:16px 20px}img{max-width:100%}</style>' +
				doc.head.innerHTML + '</head><body>' + doc.body.innerHTML + '</body></html>';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
	// Reload after the source is saved (version bumps) or another file is shown.
	$effect(() => {
		void version;
		void file.url;
		load();
	});
</script>

{#if error}<div class="msg">{error}</div>
{:else if srcdoc}<iframe title={file.name} sandbox="allow-popups allow-popups-to-escape-sandbox" {srcdoc} referrerpolicy="no-referrer"></iframe>
{:else}<div class="msg faint">Loading…</div>{/if}

<style>
	iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: #fff; }
	.msg { padding: 40px; text-align: center; }
</style>
