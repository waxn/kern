// A tiny guestbook: GET/POST api/messages, stored as JSON in APP_DATA_DIR. No packages needed.
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dataDir = process.env.APP_DATA_DIR || join(here, 'data');
const file = join(dataDir, 'messages.json');
await mkdir(dataDir, { recursive: true });

const load = async () => JSON.parse(await readFile(file, 'utf8').catch(() => '[]'));
const json = (res, status, body) => {
	res.writeHead(status, { 'Content-Type': 'application/json' });
	res.end(JSON.stringify(body));
};

const server = createServer(async (req, res) => {
	const url = new URL(req.url, 'http://x');
	if (url.pathname === '/healthz') return json(res, 200, { ok: true });
	if (url.pathname === '/api/messages' && req.method === 'GET') return json(res, 200, await load());
	if (url.pathname === '/api/messages' && req.method === 'POST') {
		let body = '';
		for await (const chunk of req) body += chunk;
		const { name = '', text = '' } = JSON.parse(body || '{}');
		if (!String(text).trim()) return json(res, 400, { error: 'Write something first.' });
		// Kern tells signed-in visitors' names in X-Kern-User (trust it only with the right secret).
		const kernUser = req.headers['x-kern-app-secret'] === process.env.KERN_APP_SECRET ? req.headers['x-kern-user'] : '';
		const msgs = await load();
		msgs.unshift({ name: String(name || kernUser || 'Someone').slice(0, 60), text: String(text).slice(0, 500), at: new Date().toISOString() });
		await writeFile(file, JSON.stringify(msgs.slice(0, 500)));
		return json(res, 201, msgs[0]);
	}
	if (url.pathname === '/' || url.pathname === '/index.html') {
		res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
		return res.end(await readFile(join(here, 'index.html')));
	}
	json(res, 404, { error: 'Not found' });
});

const port = Number(process.env.PORT || 3000);
server.listen(port, process.env.HOST || '127.0.0.1', () => console.log(`Guestbook listening on port ${port}`));
