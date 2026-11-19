<script lang="ts">
	// Webhooks: Kern POSTs a signed JSON description of an event (a push, …) to a URL you choose.
	import { onMount } from 'svelte';
	import { Check, ChevronRight, CircleAlert, History, Pencil, Plus, Send, Trash2, Webhook } from '@lucide/svelte';
	import { api } from '#lib/api.ts';
	import Toggle from '#lib/auth/Toggle.svelte';
	import { ui } from '#lib/state/ui.svelte.ts';
	import { fullDate, relTime } from '#lib/util.ts';
	import type { GitWebhook, RepoDetail, WebhookDelivery, WebhookDeliveryBrief } from './types.ts';

	let { repo }: { repo: RepoDetail } = $props();

	let hooks = $state<GitWebhook[]>([]);
	let events = $state<{ name: string; label: string }[]>([{ name: 'push', label: 'Push' }]);
	let loaded = $state(false);
	let editing = $state<number | 'new' | null>(null);
	let busy = $state(false);
	let form = $state({ url: '', secret: '', clear_secret: false, events: ['push'] as string[], enabled: true });
	let reveal = $state(false);
	let openLog = $state<number | null>(null);
	let log = $state<WebhookDeliveryBrief[]>([]);
	let detail = $state<Record<number, WebhookDelivery>>({});
	let shown = $state<number | null>(null);

	const base = $derived(`/git/repos/${repo.name}/webhooks`);

	async function load() {
		try {
			const r = await api.get<{ webhooks: GitWebhook[]; events: { name: string; label: string }[] }>(base);
			hooks = r.webhooks;
			events = r.events;
		} catch (e) {
			ui.error(e);
		}
		loaded = true;
	}
	onMount(load);

	function open(h: GitWebhook | null) {
		editing = h ? h.id : 'new';
		reveal = false;
		form = h
			? { url: h.url, secret: '', clear_secret: false, events: [...h.events], enabled: h.enabled }
			: { url: '', secret: '', clear_secret: false, events: ['push'], enabled: true };
	}

	function generate() {
		const b = crypto.getRandomValues(new Uint8Array(24));
		form.secret = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
		reveal = true;
	}

	function flip(name: string, on: boolean) {
		form.events = on ? [...form.events, name] : form.events.filter((e) => e !== name);
	}

	async function save(e: SubmitEvent) {
		e.preventDefault();
		busy = true;
		try {
			const body: Record<string, unknown> = { ...form };
			if (!form.secret) delete body.secret;
			if (editing === 'new') await api.post(base, body);
			else await api.patch(`${base}/${editing}`, body);
			editing = null;
			await load();
		} catch (err) {
			ui.error(err);
		} finally {
			busy = false;
		}
	}

	async function toggle(h: GitWebhook, enabled: boolean) {
		try {
			await api.patch(`${base}/${h.id}`, { enabled });
		} catch (e) {
			ui.error(e);
		}
		await load();
	}

	async function remove(h: GitWebhook) {
		if (!(await ui.confirm({ title: 'Delete this webhook?', message: 'Its delivery log is deleted too.', confirmLabel: 'Delete', danger: true }))) return;
		try {
			await api.del(`${base}/${h.id}`);
			if (openLog === h.id) openLog = null;
		} catch (e) {
			ui.error(e);
		}
		await load();
	}

	async function loadLog(id: number) {
		try {
			log = (await api.get<{ deliveries: WebhookDeliveryBrief[] }>(`${base}/${id}/deliveries`)).deliveries;
		} catch (e) {
			ui.error(e);
		}
	}

	async function toggleLog(h: GitWebhook) {
		if (openLog === h.id) {
			openLog = null;
			return;
		}
		openLog = h.id;
		shown = null;
		log = [];
		await loadLog(h.id);
	}

	async function test(h: GitWebhook) {
		try {
			const d = await api.post<WebhookDelivery>(`${base}/${h.id}/test`);
			ui.toast(d.ok ? `Test delivered (${d.status_code})` : `Test failed: ${d.error || d.status_code}`, { kind: d.ok ? 'info' : 'error' });
		} catch (e) {
			ui.error(e);
		}
		await load();
		if (openLog === h.id) await loadLog(h.id);
	}

	async function show(h: GitWebhook, d: WebhookDeliveryBrief) {
		if (shown === d.id) {
			shown = null;
			return;
		}
		shown = d.id;
		if (!detail[d.id]) {
			try {
				detail[d.id] = await api.get<WebhookDelivery>(`${base}/${h.id}/deliveries/${d.id}`);
			} catch (e) {
				ui.error(e);
			}
		}
	}

	async function redeliver(h: GitWebhook, d: WebhookDeliveryBrief) {
		try {
			const r = await api.post<WebhookDelivery>(`${base}/${h.id}/deliveries/${d.id}/redeliver`);
			ui.toast(r.ok ? `Delivered (${r.status_code})` : `Failed: ${r.error || r.status_code}`, { kind: r.ok ? 'info' : 'error' });
		} catch (e) {
			ui.error(e);
		}
		await load();
		await loadLog(h.id);
	}

	function pretty(s: string | undefined) {
		if (!s) return '';
		try {
			return JSON.stringify(JSON.parse(s), null, 2);
		} catch {
			return s;
		}
	}
	const label = (n: string) => events.find((e) => e.name === n)?.label ?? n;
</script>

<section class="set">
	<h3><Webhook size={15} />Webhooks</h3>
	<p class="muted">Kern sends a JSON <code>POST</code> to a URL when something happens here. If you set a secret, each request carries an <code>X-Kern-Signature-256</code> header (HMAC-SHA256 of the body) so the receiver can verify it came from Kern.</p>

	{#if loaded && hooks.length}
		<div class="box">
			{#each hooks as h (h.id)}
				<div class="item">
					<div class="top">
						<code class="url" title={h.url}>{h.url}</code>
						<span class="grow"></span>
						<button class="btn" onclick={() => test(h)}><Send size={13} />Send test</button>
						<button class="btn" class:on={openLog === h.id} onclick={() => toggleLog(h)}><History size={13} />Deliveries</button>
						<Toggle checked={h.enabled} label="Webhook enabled" onchange={(v) => toggle(h, v)} />
						<button class="icon-btn" title="Edit" onclick={() => open(h)}><Pencil size={14} /></button>
						<button class="icon-btn" title="Delete" onclick={() => remove(h)}><Trash2 size={14} /></button>
					</div>
					<div class="status">
						<span class="muted">{h.events.map(label).join(', ')}</span>
						{#if h.last_delivery}
							{#if h.last_delivery.ok}
								<span class="good" title={fullDate(h.last_delivery.at)}><Check size={13} />{h.last_delivery.status_code} · {relTime(h.last_delivery.at)}</span>
							{:else}
								<span class="bad" title={h.last_delivery.error}><CircleAlert size={13} />{h.last_delivery.status_code ?? 'Failed'} · {relTime(h.last_delivery.at)}</span>
							{/if}
						{:else}
							<span class="muted">No deliveries yet</span>
						{/if}
					</div>
					{#if openLog === h.id}
						<div class="log">
							{#each log as d (d.id)}
								<div class="drow">
									<button class="dhead" onclick={() => show(h, d)} aria-expanded={shown === d.id}>
										<ChevronRight size={13} class={shown === d.id ? 'open' : ''} />
										<span class="pill" class:ok={d.ok} class:fail={!d.ok}>{d.status_code ?? 'error'}</span>
										<b>{d.event}</b>
										<span class="muted">{relTime(d.at)} · {d.duration_ms} ms{d.attempts > 1 ? ` · ${d.attempts} attempts` : ''}</span>
									</button>
									<button class="btn ghost" onclick={() => redeliver(h, d)}>Redeliver</button>
								</div>
								{#if shown === d.id}
									<div class="detail">
										{#if d.error}<p class="bad">{d.error}</p>{/if}
										{#if detail[d.id]}
											<h4>Request <span class="muted">{d.guid}</span></h4>
											<pre>{Object.entries(detail[d.id].request_headers ?? {}).map(([k, v]) => `${k}: ${v}`).join('\n')}

{pretty(detail[d.id].request_body)}</pre>
											<h4>Response</h4>
											<pre>{detail[d.id].response_body || '(empty)'}</pre>
										{:else}
											<p class="muted">Loading…</p>
										{/if}
									</div>
								{/if}
							{:else}
								<p class="muted pad">No deliveries yet. The last 30 are kept.</p>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if editing !== null}
		<form class="form" onsubmit={save}>
			<label>Payload URL<input class="input" type="url" placeholder="https://example.com/kern-hook" bind:value={form.url} required autocomplete="off" /></label>
			<label>Secret <span class="muted">(optional; used to sign requests)</span>
				<span class="inline">
					{#if reveal}
						<input class="input grow" bind:value={form.secret} autocomplete="off" />
					{:else}
						<input class="input grow" type="password" bind:value={form.secret} autocomplete="new-password"
							placeholder={editing !== 'new' && hooks.find((h) => h.id === editing)?.has_secret ? 'unchanged' : ''} />
					{/if}
					<button type="button" class="btn" onclick={generate}>Generate</button>
				</span>
			</label>
			{#if reveal}<p class="muted">Copy the secret now; it is not shown again after saving.</p>{/if}
			{#if editing !== 'new' && hooks.find((h) => h.id === editing)?.has_secret}
				<label class="chk"><input type="checkbox" bind:checked={form.clear_secret} />Remove the stored secret</label>
			{/if}
			<fieldset>
				<legend>Events</legend>
				{#each events as ev (ev.name)}
					<label class="chk"><input type="checkbox" checked={form.events.includes(ev.name)} onchange={(e) => flip(ev.name, e.currentTarget.checked)} />{ev.label}</label>
				{/each}
			</fieldset>
			<div class="actions">
				<button class="btn primary" disabled={busy || !form.url.trim() || !form.events.length}>{editing === 'new' ? 'Add webhook' : 'Save'}</button>
				<button type="button" class="btn ghost" onclick={() => (editing = null)}>Cancel</button>
			</div>
		</form>
	{:else}
		<button class="btn" onclick={() => open(null)}><Plus size={13} />Add webhook</button>
	{/if}
</section>

<style>
	.set { margin-bottom: 28px; }
	.set :global(h3) { display: flex; align-items: center; gap: 7px; font-size: 14.5px; margin: 0 0 4px; }
	.set :global(.muted) { margin: 0; font-size: 13px; color: var(--text-3); }
	p.muted { margin-bottom: 10px; }
	.box { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; }
	.item { padding: 8px 10px; }
	.item + .item { border-top: 1px solid var(--border); }
	.top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.url { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; min-width: 0; }
	.grow { flex: 1; }
	.btn.on { background: var(--surface-2); }
	.status { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12.5px; margin-top: 4px; }
	.status > span { display: inline-flex; align-items: center; gap: 4px; }
	.good { color: var(--text-2); }
	.bad { color: var(--danger); }
	.log { margin-top: 8px; border-top: 1px solid var(--border); }
	.pad { padding: 8px 0; }
	.drow { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
	.dhead { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; text-align: left; padding: 3px 0; font-size: 13px; }
	.dhead :global(.open) { transform: rotate(90deg); }
	.pill { font-size: 11.5px; padding: 0 6px; border-radius: 9px; border: 1px solid var(--border-strong); }
	.pill.ok { color: var(--text-2); }
	.pill.fail { color: var(--danger); border-color: var(--danger); }
	.detail { padding: 0 0 8px 20px; }
	.detail h4 { margin: 8px 0 3px; font-size: 12.5px; }
	.detail p { margin: 4px 0; font-size: 12.5px; }
	pre { margin: 0; padding: 6px 8px; border-radius: var(--radius); background: var(--code-bg); font-size: 12px; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; }
	.form { display: flex; flex-direction: column; gap: 10px; max-width: 520px; }
	.form label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--text-2); }
	.form label.chk { flex-direction: row; align-items: center; gap: 6px; }
	.inline { display: flex; gap: 8px; }
	fieldset { border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; margin: 0; display: flex; flex-direction: column; gap: 4px; }
	legend { font-size: 12.5px; color: var(--text-2); padding: 0 4px; }
	.actions { display: flex; gap: 8px; }
</style>
