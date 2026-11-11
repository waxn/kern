import { ui } from '../state/ui.svelte.ts';

/** Fetch a server export and save it with the server-provided file name. */
export async function download(path: string) {
	try {
		const res = await fetch('/api' + path, { headers: { 'X-Kern': '1' } });
		if (!res.ok) {
			let msg = res.statusText;
			try {
				msg = (await res.json()).detail ?? msg;
			} catch {
				/* not json */
			}
			throw new Error(msg);
		}
		const disp = res.headers.get('Content-Disposition') ?? '';
		const m = /filename\*=UTF-8''([^;]+)/.exec(disp) ?? /filename="?([^";]+)"?/.exec(disp);
		const name = m ? decodeURIComponent(m[1]) : 'export';
		const blob = await res.blob();
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = name;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 5000);
	} catch (e) {
		ui.error(e);
	}
}

/** Upload files (with relative paths for folders) to the importer. */
export async function importFiles(files: File[], parent: string | null = null): Promise<Record<string, any> | null> {
	const form = new FormData();
	for (const f of files) {
		form.append('files', f);
		form.append('paths', (f as any).webkitRelativePath || f.name);
	}
	if (parent) form.append('parent', parent);
	ui.toast(`Importing ${files.length} ${files.length === 1 ? 'file' : 'files'}…`);
	try {
		const res = await fetch('/api/import', { method: 'POST', headers: { 'X-Kern': '1' }, body: form });
		const data = await res.json();
		if (!res.ok) throw new Error(data.detail ?? res.statusText);
		const parts = [];
		if (data.pages) parts.push(`${data.pages} ${data.pages === 1 ? 'page' : 'pages'}`);
		if (data.databases) parts.push(`${data.databases} ${data.databases === 1 ? 'database' : 'databases'}`);
		if (data.cards) parts.push(`${data.cards} ${data.cards === 1 ? 'card' : 'cards'}`);
		if (data.files) parts.push(`${data.files} ${data.files === 1 ? 'file' : 'files'}`);
		ui.toast(parts.length ? `Imported ${parts.join(', ')}` : 'Nothing to import in those files', { kind: parts.length ? 'info' : 'error' });
		if (data.skipped?.length) ui.toast(`Skipped: ${data.skipped.slice(0, 3).join('; ')}`, { kind: 'error' });
		return data;
	} catch (e) {
		ui.error(e);
		return null;
	}
}
