<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { api } from '../api.svelte.js';

  let { label, value = $bindable([]), autofocus = false, onchange } = $props();
  let text = $state('');
  let suggestions = $state([]);
  let active = $state(0);
  let input;
  let timer;

  const EMAIL = /^[^@\s<>()[\],;:"]+@[^@\s<>()[\],;:"]+\.[^@\s<>()[\],;:"]+$/;

  function parse(raw) {
    const m = raw.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) return { name: m[1].trim(), addr: m[2].trim() };
    return { name: '', addr: raw.trim() };
  }
  function commit(raw = text) {
    const parts = raw.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const added = [];
    for (const p of parts) {
      const r = parse(p);
      if (!value.some((v) => v.addr.toLowerCase() === r.addr.toLowerCase())) added.push(r);
    }
    value = [...value, ...added];
    text = '';
    suggestions = [];
    onchange?.();
  }
  function remove(i) {
    value = value.filter((_, j) => j !== i);
    onchange?.();
  }
  function pick(s) {
    if (!value.some((v) => v.addr === s.addr)) value = [...value, { name: s.name, addr: s.addr }];
    text = '';
    suggestions = [];
    onchange?.();
    input.focus();
  }
  function onInput() {
    clearTimeout(timer);
    const q = text.trim();
    if (q.length < 2) {
      suggestions = [];
      return;
    }
    timer = setTimeout(async () => {
      try {
        const res = await api.get('/contacts', { q });
        suggestions = res.filter((s) => !value.some((v) => v.addr === s.addr));
        active = 0;
      } catch {
        suggestions = [];
      }
    }, 150);
  }
  function onKey(e) {
    if (suggestions.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length;
    } else if ((e.key === 'Enter' || e.key === 'Tab') && suggestions.length && text.trim()) {
      e.preventDefault();
      pick(suggestions[active]);
    } else if (e.key === 'Enter' || e.key === ',' || e.key === ';') {
      if (text.trim()) {
        e.preventDefault();
        commit();
      }
    } else if (e.key === 'Backspace' && !text && value.length) {
      remove(value.length - 1);
    } else if (e.key === 'Escape' && suggestions.length) {
      e.stopPropagation();
      suggestions = [];
    }
  }
</script>

<div class="field">
  <span class="label">{label}</span>
  <div class="chips">
    {#each value as v, i (v.addr)}
      <span class="rcpt" class:bad={!EMAIL.test(v.addr)} title={v.addr}>
        {v.name || v.addr}
        <button type="button" aria-label={`Remove ${v.addr}`} onclick={() => remove(i)}>×</button>
      </span>
    {/each}
    <input
      bind:this={input}
      bind:value={text}
      oninput={onInput}
      onkeydown={onKey}
      onblur={() => setTimeout(() => { if (text.trim()) commit(); suggestions = []; }, 120)}
      onpaste={(e) => { const t = e.clipboardData.getData('text'); if (/[,;\n]/.test(t)) { e.preventDefault(); commit(t); } }}
      aria-label={label}
      autocomplete="off"
      spellcheck="false"
      {autofocus}
    />
  </div>
  {#if suggestions.length}
    <ul class="sugg" role="listbox">
      {#each suggestions as s, i}
        <li role="option" aria-selected={i === active}>
          <button type="button" class:active={i === active} onmousedown={(e) => { e.preventDefault(); pick(s); }}>
            <span class="n">{s.name || s.addr}</span>
            {#if s.name}<span class="a">{s.addr}</span>{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .field { position: relative; display: flex; align-items: flex-start; gap: 8px; padding: 5px 14px; border-bottom: 1px solid var(--line); min-height: 38px; }
  .label { color: var(--text-3); font-size: 13px; padding-top: 5px; min-width: 22px; }
  .chips { flex: 1; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; min-width: 0; }
  input { flex: 1; min-width: 120px; border: 0; background: transparent; outline: none; height: 26px; font-size: 13.5px; }
  .rcpt {
    display: inline-flex; align-items: center; gap: 2px; height: 24px; padding: 0 3px 0 9px; border-radius: 999px;
    background: var(--bg-sunken); border: 1px solid var(--line); font-size: 12.5px; max-width: 260px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .rcpt.bad { background: var(--danger-soft); color: var(--danger); border-color: transparent; }
  .rcpt button { border: 0; background: none; cursor: pointer; color: var(--text-3); font-size: 15px; line-height: 1; padding: 0 5px; border-radius: 50%; }
  .rcpt button:hover { color: var(--text); }
  .sugg {
    position: absolute; left: 40px; right: 14px; top: 100%; z-index: 10; list-style: none; margin: 2px 0 0; padding: 4px;
    background: var(--bg-elev); border: 1px solid var(--line); border-radius: 9px; box-shadow: var(--shadow-lg);
  }
  .sugg button { display: flex; gap: 8px; align-items: baseline; width: 100%; border: 0; background: none; padding: 6px 9px; border-radius: 6px; cursor: pointer; text-align: left; }
  .sugg button.active, .sugg button:hover { background: var(--bg-hover); }
  .n { font-weight: 600; font-size: 13px; }
  .a { color: var(--text-3); font-size: 12px; }
</style>
