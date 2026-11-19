<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  // Plain-text attachments (.txt, .csv, .json, …) shown as text, never as markup.
  // CSV and TSV files get a table.
  let { url, name } = $props();
  let text = $state(null);
  let error = $state('');

  const ext = $derived((name.split('.').pop() || '').toLowerCase());
  const sep = $derived(ext === 'csv' ? ',' : ext === 'tsv' ? '\t' : null);

  $effect(() => {
    const u = url;
    text = null;
    error = '';
    fetch(u, { credentials: 'same-origin', cache: 'no-store' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`Could not load the file (${r.status}).`))))
      .then((t) => u === url && (text = t))
      .catch((e) => u === url && (error = e.message));
  });

  function parse(src, d) {
    const rows = [];
    let row = [], cell = '', q = false;
    for (let i = 0; i < src.length; i++) {
      const c = src[i];
      if (q) {
        if (c === '"' && src[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') q = false;
        else cell += c;
      } else if (c === '"' && cell === '') q = true;
      else if (c === d) { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && src[i + 1] === '\n') i++;
        row.push(cell); rows.push(row); row = []; cell = '';
      } else cell += c;
      if (rows.length > 5000) break;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }
  const table = $derived(text != null && sep ? parse(text, sep) : null);
</script>

<div class="text scroll">
  {#if error}<p class="msg">{error}</p>
  {:else if text == null}<p class="msg faint">Loading…</p>
  {:else if table && table.length}
    <table>
      <thead><tr>{#each table[0] as h}<th>{h}</th>{/each}</tr></thead>
      <tbody>{#each table.slice(1) as r}<tr>{#each r as c}<td>{c}</td>{/each}</tr>{/each}</tbody>
    </table>
  {:else}<pre>{text}</pre>{/if}
</div>

<style>
  .text { height: 100%; overflow: auto; padding: 18px 22px; }
  pre { margin: 0; font: 13px/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text); }
  table { border-collapse: collapse; font-size: 13px; }
  th, td { border: 1px solid var(--line); padding: 5px 9px; text-align: left; white-space: nowrap; }
  th { background: var(--bg-sunken); font-weight: 600; position: sticky; top: -18px; }
  .msg { text-align: center; margin-top: 40px; }
</style>
