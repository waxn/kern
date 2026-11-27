// Relative URLs: Kern serves this app at /<path>/, so "api/entries" works wherever it lives.
const COLORS = ['#e5aa5c', '#6fa8dc', '#7fbf8f', '#c98fd6', '#e8776e', '#d8c26a', '#5fc4c0', '#b0a08f'];
let entries = [];
const hidden = new Set();
const $ = (s) => document.querySelector(s);
const form = $('#add');
form.day.value = new Date().toISOString().slice(0, 10);

const colorOf = (() => {
	const map = new Map();
	return (s) => map.get(s) ?? (map.set(s, COLORS[map.size % COLORS.length]), map.get(s));
})();

async function load() {
	entries = await (await fetch('api/entries')).json();
	render();
}

function render() {
	const subjects = [...new Set(entries.map((e) => e.subject))];
	subjects.forEach(colorOf);
	$('#subjects').innerHTML = subjects.map((s) => `<option value="${esc(s)}">`).join('');
	$('#legend').innerHTML = subjects.map((s) =>
		`<button type="button" class="${hidden.has(s) ? 'off' : ''}" style="--c:${colorOf(s)}" data-s="${esc(s)}">${esc(s)}</button>`).join('');
	$('#empty').hidden = entries.length > 0;
	drawChart(subjects.filter((s) => !hidden.has(s)));
	$('#table tbody').innerHTML = [...entries].reverse().slice(0, 200).map((e) => `
		<tr><td class="day">${e.day}</td><td><span class="dot" style="--c:${colorOf(e.subject)}"></span>${esc(e.subject)}</td>
		<td class="num">${fmt(e.value)} ${esc(e.unit)}</td><td class="note">${esc(e.note)}</td>
		<td class="num"><button class="x" title="Delete" data-id="${e.id}">✕</button></td></tr>`).join('');
}

function drawChart(subjects) {
	const svg = $('#chart');
	const pts = entries.filter((e) => subjects.includes(e.subject));
	if (!pts.length) { svg.innerHTML = ''; return; }
	const W = 640, H = 240, L = 36, B = 20;
	const days = pts.map((e) => Date.parse(e.day));
	const vals = pts.map((e) => e.value);
	let [x0, x1] = [Math.min(...days), Math.max(...days)];
	let [y0, y1] = [Math.min(...vals), Math.max(...vals)];
	if (x0 === x1) { x0 -= 864e5; x1 += 864e5; }
	const pad = (y1 - y0) * 0.1 || Math.abs(y1) * 0.1 || 1;
	y0 -= pad; y1 += pad;
	const X = (d) => L + ((d - x0) / (x1 - x0)) * (W - L - 8);
	const Y = (v) => 8 + (1 - (v - y0) / (y1 - y0)) * (H - B - 8);
	let out = '';
	for (let i = 0; i <= 4; i++) {
		const v = y0 + ((y1 - y0) * i) / 4, y = Y(v);
		out += `<line class="grid" x1="${L}" x2="${W}" y1="${y}" y2="${y}"/><text x="0" y="${y + 4}">${fmt(v)}</text>`;
	}
	out += `<text x="${L}" y="${H - 4}">${new Date(x0).toLocaleDateString()}</text>`;
	out += `<text x="${W}" y="${H - 4}" text-anchor="end">${new Date(x1).toLocaleDateString()}</text>`;
	for (const s of subjects) {
		const rows = pts.filter((e) => e.subject === s).sort((a, b) => a.day.localeCompare(b.day));
		const d = rows.map((e, i) => `${i ? 'L' : 'M'}${X(Date.parse(e.day)).toFixed(1)},${Y(e.value).toFixed(1)}`).join(' ');
		out += `<path d="${d}" fill="none" stroke="${colorOf(s)}" stroke-width="2.2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
		out += rows.map((e) => `<circle cx="${X(Date.parse(e.day))}" cy="${Y(e.value)}" r="3.2" fill="${colorOf(s)}"><title>${esc(s)} · ${e.day}: ${fmt(e.value)} ${esc(e.unit)}</title></circle>`).join('');
	}
	svg.innerHTML = out;
}

form.addEventListener('submit', async (ev) => {
	ev.preventDefault();
	const data = Object.fromEntries(new FormData(form));
	const res = await fetch('api/entries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
	const body = await res.json();
	$('#error').hidden = res.ok;
	if (!res.ok) { $('#error').textContent = body.error || 'Could not save.'; return; }
	entries.push(body);
	form.value.value = ''; form.note.value = '';
	form.value.focus();
	render();
});

document.addEventListener('click', async (ev) => {
	const del = ev.target.closest('[data-id]');
	if (del) {
		await fetch(`api/entries/${del.dataset.id}`, { method: 'DELETE' });
		entries = entries.filter((e) => String(e.id) !== del.dataset.id);
		render();
	}
	const chip = ev.target.closest('[data-s]');
	if (chip) {
		hidden.has(chip.dataset.s) ? hidden.delete(chip.dataset.s) : hidden.add(chip.dataset.s);
		render();
	}
});

const fmt = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
load();
