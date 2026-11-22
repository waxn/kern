<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onMount } from 'svelte';
  import { api } from '../api.svelte.js';
  import { errorToast, toast } from '../state.svelte.js';
  import { shortDate } from '../format.js';
  import Icon from '../components/Icon.svelte';

  let rules = $state([]);
  let kind = $state('address');
  let value = $state('');
  let error = $state('');
  let loading = $state(true);

  async function load() {
    try {
      rules = await api.get('/blocklist');
    } catch (e) {
      errorToast(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  async function add(e) {
    e.preventDefault();
    error = '';
    try {
      await api.post('/blocklist', { kind, value });
      value = '';
      await load();
      toast('Blocked');
    } catch (err) {
      error = err.message;
    }
  }
  async function remove(r) {
    try {
      await api.del(`/blocklist/${r.id}`);
      rules = rules.filter((x) => x.id !== r.id);
      toast(`Unblocked ${r.value}`);
    } catch (e) {
      errorToast(e);
    }
  }
</script>

<div class="mail-page scroll">
  <div class="inner">
    <h1>Blocked senders</h1>
    <p class="muted">New mail from these addresses and domains goes straight to Junk, on your mail server too. “Not spam” on a
      message removes its block automatically.</p>

    <form class="add" onsubmit={add}>
      <select bind:value={kind} aria-label="Block type" class="input">
        <option value="address">Address</option>
        <option value="domain">Domain</option>
      </select>
      <input class="input" bind:value placeholder={kind === 'address' ? 'name@example.com' : 'example.com'} aria-label="Address or domain" required />
      <button class="btn primary">Block</button>
    </form>
    {#if error}<p class="error" role="alert">{error}</p>{/if}

    {#if !loading && !rules.length}
      <div class="empty faint">Nobody is blocked. Use “Report spam” on a message to block its sender.</div>
    {:else}
      <ul>
        {#each rules as r (r.id)}
          <li>
            <span class="chip">{r.kind}</span>
            <span class="v">{r.value}</span>
            <span class="faint meta">{r.hits ? `${r.hits} blocked · ` : ''}{shortDate(r.created)}</span>
            {#if r.note}<span class="faint note">{r.note}</span>{/if}
            <button class="btn small" onclick={() => remove(r)}><Icon name="close" size={13} /> Unblock</button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>

<style>
  .mail-page { flex: 1; min-height: 0; width: 100%; }
  .inner { max-width: 860px; margin: 0 auto; padding: 36px 40px 80px; }
  @media (max-width: 760px) { .inner { padding: 48px 16px 80px; } }
  h1 { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; margin: 0 0 4px; }
  .add { display: flex; gap: 8px; margin: 18px 0 10px; }
  .add select { width: 120px; flex: none; }
  .error { color: var(--danger); background: var(--danger-soft); padding: 8px 10px; border-radius: 8px; font-size: 13px; }
  ul { list-style: none; margin: 14px 0 0; padding: 0; background: var(--bg-elev); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  li { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; padding: 10px 12px; border-bottom: 1px solid var(--line); }
  li:last-child { border-bottom: 0; }
  .v { font-weight: 600; flex: 1; min-width: 160px; overflow-wrap: anywhere; }
  .meta { font-size: 12px; }
  .note { flex-basis: 100%; font-size: 12px; order: 5; }
  .empty { padding: 40px 0; text-align: center; }
  @media (max-width: 560px) { .add { flex-wrap: wrap; } .add select { width: 100%; } }
</style>
