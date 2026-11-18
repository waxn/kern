<script>
  // @ts-nocheck: plain JavaScript (ported from Manifest).
  import { onDestroy, onMount } from 'svelte';
  import { addFiles, closeCompose, discardCompose, removeUpload, saveDraft, sendCompose } from '../compose.svelte.js';
  import { bytes } from '../format.js';
  import { account, errorToast, info, toast, ui } from '../state.svelte.js';
  import Icon from './Icon.svelte';
  import RecipientInput from './RecipientInput.svelte';
  import { describeWhen } from '../when.js';
  import { api } from '../api.svelte.js';
  import { insertPoint, isEmptyBody, loadTemplates, templateBody, templates } from '../templates.svelte.js';

  let { c, wide, docked = false } = $props();
  let editor;
  let fileInput;
  let saveTimer;
  let serverTimer;
  let dragging = $state(false);
  let linkOpen = $state(false);
  let linkUrl = $state('');
  let savedRange = null;
  let maximized = $state(false);
  let nudgeMenu = $state(false);
  let savedFlash = $state(false);
  const NUDGES = [['1', 'Tomorrow'], ['3', 'In 3 days'], ['7', 'In a week'], ['14', 'In 2 weeks']];
  function setNudge(days) {
    nudgeMenu = false;
    if (!days) {
      c.followupAt = null;
    } else {
      const d = new Date();
      c.followupAt = new Date(d.getFullYear(), d.getMonth(), d.getDate() + Number(days), 9, 0).toISOString();
    }
    changed();
  }
  const nudgeLabel = $derived(c.followupAt ? describeWhen(new Date(c.followupAt)) : '');

  onMount(() => {
    editor.innerHTML = c.bodyHtml || '<p><br></p>';
    if (docked) requestAnimationFrame(() => editor.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
    if (c.mode === 'reply' || c.mode === 'reply_all') {
      // Put the caret above the quote.
      const r = document.createRange();
      r.setStart(editor, 0);
      r.collapse(true);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      editor.focus();
    }
    serverTimer = setInterval(() => {
      if (c.dirty) saveDraft(c, { toServer: true });
    }, 30000);
  });
  onDestroy(() => {
    clearTimeout(saveTimer);
    clearInterval(serverTimer);
  });

  function changed() {
    c.dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveDraft(c), 1500);
  }
  function onInput() {
    c.bodyHtml = editor.innerHTML;
    changed();
  }
  function cmd(name, arg = null) {
    editor.focus();
    document.execCommand(name, false, arg);
    onInput();
  }
  function openLink() {
    const sel = getSelection();
    savedRange = sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
    linkUrl = 'https://';
    linkOpen = true;
  }
  function applyLink(e) {
    e.preventDefault();
    linkOpen = false;
    const url = linkUrl.trim();
    if (!/^(https?:\/\/|mailto:)/i.test(url)) return;
    editor.focus();
    if (savedRange) {
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(savedRange);
    }
    if (getSelection().isCollapsed) document.execCommand('insertText', false, url);
    else document.execCommand('createLink', false, url);
    onInput();
  }
  function onKey(e) {
    if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 's') {
      e.preventDefault();
      c.bodyHtml = editor.innerHTML;
      c.dirty = true;
      saveDraft(c, { toServer: true }).then(() => {
        if (!c.error) savedFlash = true;
        setTimeout(() => (savedFlash = false), 1500);
      });
      return;
    }
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'c') {
      e.preventDefault();
      c.showCc = true;
      return;
    }
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      send({ archive: e.shiftKey && !!c.threadId });
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeCompose(c);
    }
  }
  function send(opts = {}) {
    c.bodyHtml = editor.innerHTML;
    sendCompose(c, opts).catch(() => {});
  }
  let tplMenu = $state(false);
  let tplRange = null;
  function openTemplates() {
    const sel = getSelection();
    tplRange = sel.rangeCount && editor.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    tplMenu = !tplMenu;
    if (tplMenu) loadTemplates();
  }
  function insertTemplate(t) {
    tplMenu = false;
    editor.focus();
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(insertPoint(editor, tplRange));
    // Server-sanitized HTML (sending.clean_compose_html); sanitized again on send.
    document.execCommand('insertHTML', false, t.bodyHtml);
    if (t.subject && !c.subject.trim()) c.subject = t.subject;
    c.bodyHtml = editor.innerHTML;
    changed();
    api.post(`/templates/${t.id}`).catch(() => {});
  }
  function saveTemplate() {
    tplMenu = false;
    const html = templateBody(editor.innerHTML, account.signature);
    if (isEmptyBody(html)) {
      toast('Write something first, then save it as a template.');
      return;
    }
    ui.dialog = {
      type: 'prompt', title: 'Save as template', label: 'Template name', action: 'Save',
      submit: async (name) => {
        const subject = c.mode === 'new' ? c.subject : '';
        await api.post('/templates', { name, subject, bodyHtml: html });
        await loadTemplates();
        toast(`Saved template “${name}”`);
      },
    };
  }
  function deleteTemplate(t) {
    api.del(`/templates/${t.id}`).then(loadTemplates).then(() => toast(`Deleted “${t.name}”`)).catch(errorToast);
  }
  function sendLater() {
    c.bodyHtml = editor.innerHTML;
    if (!c.to.length && !c.cc.length && !c.bcc.length) {
      c.error = 'Add at least one recipient.';
      return;
    }
    ui.dialog = { type: 'schedule', submit: (at) => sendCompose(c, { at }) };
  }
  function pickFiles(files) {
    const list = [...files];
    if (!list.length) return;
    const total = list.reduce((a, f) => a + f.size, 0) + c.uploads.reduce((a, u) => a + u.size, 0);
    if (info.maxAttachmentBytes && total > info.maxAttachmentBytes) {
      c.error = `Attachments are limited to ${bytes(info.maxAttachmentBytes)} in total.`;
      return;
    }
    addFiles(c, list);
  }
  let dragDepth = 0;
  function hasFiles(e) {
    return [...(e.dataTransfer?.types || [])].includes('Files');
  }
  function onDrop(e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dragging = false;
    pickFiles(e.dataTransfer.files);
  }
  function onPaste(e) {
    // Paste as clean text unless it's simple rich text; never paste remote images.
    const html = e.clipboardData.getData('text/html');
    if (html && /<img|<style|<script|<iframe/i.test(html)) {
      e.preventDefault();
      document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
    }
  }
  function removeForward(a) {
    c.forwardAttachments = c.forwardAttachments.filter((x) => x.id !== a.id);
    changed();
  }
  const title = $derived(c.subject || (c.mode === 'forward' ? 'Forward' : c.mode.startsWith('reply') ? 'Reply' : 'New message'));
</script>

<div
  class="composer"
  class:min={c.minimized && !docked}
  class:max={(maximized || !wide) && !docked}
  class:docked
  class:drag={dragging}
  role="dialog"
  aria-label={title}
  tabindex="-1"
  onkeydown={onKey}
  ondragenter={(e) => { if (hasFiles(e)) { dragDepth += 1; dragging = true; } }}
  ondragover={(e) => { if (hasFiles(e)) e.preventDefault(); }}
  ondragleave={(e) => { if (hasFiles(e)) { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dragging = false; } }}
  ondrop={onDrop}
>
  <header>
    <button class="title" onclick={() => (c.minimized = !c.minimized)}>{title}</button>
    <span class="status faint" aria-live="polite">{c.saving ? 'Saving…' : savedFlash ? 'Saved to Drafts' : c.draftId && !c.dirty ? 'Saved' : ''}</span>
    {#if docked}
      <button class="icon-btn small" title="Pop out into a window" aria-label="Pop out" onclick={() => { c.bodyHtml = editor.innerHTML; c.docked = false; c.minimized = false; }}><Icon name="expand" size={15} /></button>
    {:else if wide}
      <button class="icon-btn small" aria-label={c.minimized ? 'Restore' : 'Minimize'} onclick={() => (c.minimized = !c.minimized)}><Icon name="minimize" size={15} /></button>
      <button class="icon-btn small" aria-label={maximized ? 'Exit full screen' : 'Full screen'} onclick={() => { maximized = !maximized; c.minimized = false; }}><Icon name="expand" size={15} /></button>
    {/if}
    <button class="icon-btn small" aria-label="Close (saves draft)" title="Close (saves draft)" onclick={() => closeCompose(c)}><Icon name="close" size={16} /></button>
  </header>

  {#if dragging}
    <div class="drop-overlay" aria-hidden="true"><Icon name="clip" size={22} /> Drop files to attach</div>
  {/if}
  <div class="body" hidden={c.minimized && !docked}>
    <div class="rcpt-row">
      <RecipientInput label="To" bind:value={c.to} onchange={changed} autofocus={c.mode === 'new' || c.mode === 'forward'} />
      {#if !c.showCc}
        <button class="ccbtn" onclick={() => (c.showCc = true)}>Cc Bcc</button>
      {/if}
    </div>
    {#if c.showCc}
      <RecipientInput label="Cc" bind:value={c.cc} onchange={changed} />
      <RecipientInput label="Bcc" bind:value={c.bcc} onchange={changed} />
    {/if}
    <input class="subject" placeholder="Subject" bind:value={c.subject} oninput={changed} aria-label="Subject" />

    <div class="scroll editor-wrap">
      <div
        bind:this={editor}
        class="editor"
        contenteditable="true"
        role="textbox"
        aria-multiline="true"
        aria-label="Message body"
        tabindex="0"
        oninput={onInput}
        onpaste={onPaste}
      ></div>

      {#if c.uploads.length || c.forwardAttachments.length}
        <div class="atts">
          {#each c.forwardAttachments as a (a.id)}
            <span class="att"><Icon name="clip" size={13} /> {a.filename} <span class="faint">{bytes(a.size)}</span>
              <button aria-label={`Remove ${a.filename}`} onclick={() => removeForward(a)}>×</button></span>
          {/each}
          {#each c.uploads as u (u.id)}
            <span class="att"><Icon name="clip" size={13} /> {u.filename} <span class="faint">{bytes(u.size)}</span>
              <button aria-label={`Remove ${u.filename}`} onclick={() => removeUpload(c, u)}>×</button></span>
          {/each}
        </div>
      {/if}
    </div>

    {#if c.error}<div class="error" role="alert">{c.error}</div>{/if}

    {#if linkOpen}
      <form class="linkbar" onsubmit={applyLink}>
        <Icon name="link" size={15} />
        <input bind:value={linkUrl} aria-label="Link URL" />
        <button class="btn small primary">Add link</button>
        <button type="button" class="btn small ghost" onclick={() => (linkOpen = false)}>Cancel</button>
      </form>
    {/if}

    <footer>
      <button class="btn primary send" onclick={() => send()} disabled={c.status !== 'editing'} title="Send (Ctrl+Enter)">
        {c.status === 'sending' ? 'Sending…' : 'Send'} <Icon name="send" size={15} />
      </button>
      <button class="btn small later" onclick={sendLater} disabled={c.status !== 'editing'} title="Send later" aria-label="Send later">
        <Icon name="clock" size={15} />
      </button>
      {#if c.threadId}
        <button class="btn small send-archive" onclick={() => send({ archive: true })} disabled={c.status !== 'editing'}
                title="Send and archive the conversation (Ctrl+Shift+Enter)">
          <Icon name="archive" size={14} />{#if wide}<span>Send &amp; archive</span>{/if}
        </button>
      {/if}
      <div class="tools" role="toolbar" aria-label="Formatting">
        <button class="icon-btn small" title="Bold" aria-label="Bold" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('bold')}><Icon name="bold" size={16} /></button>
        <button class="icon-btn small" title="Italic" aria-label="Italic" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('italic')}><Icon name="italic" size={16} /></button>
        <button class="icon-btn small" title="Underline" aria-label="Underline" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('underline')}><Icon name="underline" size={16} /></button>
        <button class="icon-btn small" title="Link" aria-label="Link" onmousedown={(e) => e.preventDefault()} onclick={openLink}><Icon name="link" size={16} /></button>
        <button class="icon-btn small" title="Bulleted list" aria-label="Bulleted list" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('insertUnorderedList')}><Icon name="list" size={16} /></button>
        <button class="icon-btn small" title="Numbered list" aria-label="Numbered list" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('insertOrderedList')}><Icon name="olist" size={16} /></button>
        <button class="icon-btn small" title="Quote" aria-label="Quote" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('formatBlock', 'blockquote')}><Icon name="quote" size={16} /></button>
        <button class="icon-btn small" title="Clear formatting" aria-label="Clear formatting" onmousedown={(e) => e.preventDefault()} onclick={() => cmd('removeFormat')}><Icon name="clearFormat" size={16} /></button>
        <button class="icon-btn small" title="Attach files" aria-label="Attach files" onclick={() => fileInput.click()}><Icon name="clip" size={16} /></button>
        <input bind:this={fileInput} type="file" multiple hidden onchange={(e) => { pickFiles(e.target.files); e.target.value = ''; }} />
      </div>
      <div class="nudge-wrap">
        <button class="icon-btn small" title="Templates" aria-label="Templates" aria-haspopup="menu" aria-expanded={tplMenu}
                onmousedown={(e) => e.preventDefault()} onclick={openTemplates}>
          <Icon name="note" size={16} />
        </button>
        {#if tplMenu}
          <div class="nudge-menu tpl-menu" role="menu">
            <span class="ledger">Templates</span>
            {#each templates.items as t (t.id)}
              <div class="tpl-row">
                <button role="menuitem" class="tpl" onclick={() => insertTemplate(t)} aria-label={`Insert template ${t.name}`}>{t.name}</button>
                <button class="tpl-del" aria-label={`Delete template ${t.name}`} title="Delete template" onclick={() => deleteTemplate(t)}><Icon name="close" size={12} /></button>
              </div>
            {:else}
              <span class="tpl-none">{templates.loaded ? 'None yet. Write a reply you send often, then save it here.' : 'Loading…'}</span>
            {/each}
            <button role="menuitem" class="off" onclick={saveTemplate}><Icon name="plus" size={13} /> Save this message as a template</button>
          </div>
        {/if}
      </div>
      <div class="nudge-wrap">
        <button class="nudge-btn" class:on={!!c.followupAt} title="Nudge me if nobody replies" aria-haspopup="menu" aria-expanded={nudgeMenu}
                onclick={() => (nudgeMenu = !nudgeMenu)}>
          <Icon name="bell" size={15} />{#if c.followupAt}<span class="num">{nudgeLabel.replace(/ at .*/, '')}</span>{/if}
        </button>
        {#if nudgeMenu}
          <div class="nudge-menu" role="menu">
            <span class="ledger">Nudge me if nobody replies</span>
            {#each NUDGES as [days, label]}
              <button role="menuitem" onclick={() => setNudge(days)}>{label}</button>
            {/each}
            {#if c.followupAt}<button role="menuitem" class="off" onclick={() => setNudge(null)}>Don't nudge me</button>{/if}
          </div>
        {/if}
      </div>
      <button class="icon-btn small danger" title="Discard draft" aria-label="Discard draft"
              onclick={() => (ui.dialog = { type: 'confirm', title: 'Discard this draft?', body: 'The draft will be deleted.', action: 'Discard', danger: true, submit: () => discardCompose(c) })}>
        <Icon name="trash" size={16} />
      </button>
    </footer>
  </div>
</div>

<style>
  .composer {
    pointer-events: auto;
    width: 560px;
    height: min(620px, calc(100vh - 80px));
    display: flex;
    flex-direction: column;
    background: var(--bg-elev);
    border: var(--card-border);
    border-bottom: 0;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    box-shadow: var(--shadow-lg);
    animation: rise .2s var(--ease);
    overflow: hidden;
  }
  .composer.min { height: auto; width: 300px; }
  .composer.docked {
    width: 100%; height: auto; min-height: 300px; border-bottom: var(--card-border);
    border-radius: var(--radius); box-shadow: var(--shadow); animation: rise .18s var(--ease);
  }
  .composer.docked .editor-wrap { min-height: 160px; max-height: 60vh; }
  .composer.max:not(.min) {
    position: fixed;
    inset: 4vh 8vw 0;
    width: auto;
    height: auto;
  }
  .composer { position: relative; }
  .composer.drag { outline: 2px dashed var(--accent); outline-offset: -6px; }
  .drop-overlay {
    position: absolute; inset: 42px 0 0; z-index: 6; display: flex; align-items: center; justify-content: center; gap: 10px;
    background: color-mix(in srgb, var(--bg-elev) 88%, transparent); color: var(--accent-ink); font-weight: 600; font-size: 15px;
    pointer-events: none;
  }
  header {
    display: flex; align-items: center; gap: 2px; height: 42px; padding: 0 6px 0 4px;
    background: var(--bg-sunken); border-bottom: 1px solid var(--line); flex: none;
  }
  .title {
    flex: 1; min-width: 0; text-align: left; border: 0; background: none; cursor: pointer;
    font-family: var(--display); font-style: var(--display-style); font-weight: var(--display-weight); font-size: 16px;
    padding: 0 10px; height: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .status { font: 11px var(--mono); margin-right: 6px; }
  .body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .body[hidden] { display: none; }
  .rcpt-row { position: relative; }
  .ccbtn { position: absolute; right: 10px; top: 9px; border: 0; background: none; color: var(--text-3); cursor: pointer; font-size: 12.5px; }
  .ccbtn:hover { color: var(--text); }
  .subject { border: 0; border-bottom: 1px solid var(--line); background: transparent; outline: none; padding: 10px 14px; font-size: 14px; font-weight: 550; }
  .editor-wrap { flex: 1; min-height: 120px; display: flex; flex-direction: column; }
  .editor {
    flex: 1; padding: 12px 16px; outline: none; font-size: 14.5px; line-height: 1.6; overflow-wrap: anywhere;
  }
  .editor :global(blockquote) { margin: 0 0 0 .8ex; border-left: 2px solid var(--line-strong); padding-left: 1ex; color: var(--text-2); }
  .editor :global(p) { margin: 0 0 .6em; }
  .atts { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 14px; }
  .att {
    display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 4px 0 9px; border-radius: 7px;
    background: var(--bg-sunken); border: 1px solid var(--line); font-size: 12.5px; max-width: 100%;
  }
  .att button { border: 0; background: none; cursor: pointer; color: var(--text-3); font-size: 16px; padding: 0 6px; }
  .error { margin: 0 14px 8px; padding: 7px 10px; border-radius: 8px; background: var(--danger-soft); color: var(--danger); font-size: 13px; }
  .linkbar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-top: 1px solid var(--line); }
  .linkbar input { flex: 1; border: 1px solid var(--line-strong); border-radius: 6px; height: 28px; padding: 0 8px; background: var(--bg); }
  footer { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); flex: none; }
  .send { height: 36px; padding: 0 18px; }
  .send-archive { height: 36px; }
  .later { height: 36px; width: 36px; padding: 0; justify-content: center; }
  .tools { flex: 1; display: flex; align-items: center; gap: 1px; overflow-x: auto; scrollbar-width: none; }
  .danger:hover { color: var(--danger); }
  .nudge-wrap { position: relative; }
  .nudge-btn {
    display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 8px; border-radius: var(--radius-sm);
    border: 1px solid transparent; background: none; color: var(--text-2); cursor: pointer; font-size: 11.5px;
  }
  .nudge-btn:hover { background: var(--bg-hover); }
  .nudge-btn.on { border-color: var(--accent); color: var(--accent-ink); background: var(--accent-soft); }
  .nudge-menu {
    position: absolute; bottom: calc(100% + 6px); right: 0; z-index: 5; min-width: 220px; display: grid; padding: 6px;
    background: var(--bg-elev); border: var(--card-border); border-radius: var(--radius); box-shadow: var(--shadow-lg);
  }
  .nudge-menu .ledger { padding: 6px 8px; font-size: 9.5px; }
  .nudge-menu button { border: 0; background: none; text-align: left; padding: 7px 8px; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; color: var(--text); }
  .nudge-menu button:hover { background: var(--bg-hover); }
  .nudge-menu .off { color: var(--text-3); }
  .tpl-menu { min-width: 250px; max-height: 320px; overflow-y: auto; }
  .tpl-menu .off { display: flex; align-items: center; gap: 6px; border-top: 1px solid var(--line); margin-top: 4px; padding-top: 9px; }
  .tpl-row { display: flex; align-items: center; }
  .tpl-row .tpl { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tpl-del { opacity: 0; display: grid; place-items: center; width: 24px; height: 24px; color: var(--text-3); padding: 0 !important; }
  .tpl-row:hover .tpl-del, .tpl-del:focus-visible { opacity: 1; }
  .tpl-none { padding: 6px 8px 8px; font-size: 12.5px; color: var(--text-3); line-height: 1.45; }
  @media (max-width: 1023px) {
    .composer:not(.min), .composer.max:not(.min) {
      position: fixed; inset: 0; width: auto; height: 100%; border-radius: 0; border: 0;
    }
    .composer.min { width: calc(100vw - 32px); margin: 0 auto; }
  }
</style>
