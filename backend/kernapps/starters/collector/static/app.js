let data = { days: [], sources: [], token: '' };
let metric = '';
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const fmt = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });

async function load() {
	data = await (await fetch('api/summary')).json();
	const metrics = [...new Set(data.days.map((d) => d.metric))];
	if (!metrics.includes(metric)) metric = metrics[0] || '';
	$('#metrics').innerHTML = metrics.map((m) => `<button class="${m === metric ? 'on' : ''}" data-m="${esc(m)}">${esc(m)}</button>`).join('');
	const days = [];
	for (let i = 29; i >= 0; i--) days.push(new Date(Date.now() - i * 864e5).toISOString().slice(0, 10));
	const totals = Object.fromEntries(data.days.filter((d) => d.metric === metric).map((d) => [d.day, d.total]));
	const max = Math.max(1, ...Object.values(totals));
	$('#bars').innerHTML = days.map((d) => `<div style="height:${((totals[d] || 0) / max) * 100}%" title="${d}: ${fmt(totals[d] || 0)}"></div>`).join('');
	$('#empty').hidden = data.days.length > 0;
	$('#sources tbody').innerHTML = data.sources.map((s) => `<tr><td>${esc(s.source)}</td><td class="note">${esc(s.metric)}</td>
		<td class="num">${fmt(s.total)}</td><td class="num note">${s.n}×</td><td class="day">${new Date(s.last).toLocaleString()}</td></tr>`).join('');
	const url = new URL('api/ingest', location.href).href;
	$('#snippet').textContent = `curl -X POST ${url} \\\n  -H "Authorization: Bearer ${data.token}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"source": "laptop", "metric": "tokens", "value": 1234}'`;
}

document.addEventListener('click', (e) => {
	const b = e.target.closest('[data-m]');
	if (b) { metric = b.dataset.m; load(); }
});
load();
setInterval(load, 30000);
