// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Drag conversations from the list onto sidebar folders and labels.

export const MIME = 'application/x-kern-mail-threads';

export function startDrag(e, ids) {
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData(MIME, JSON.stringify(ids));
  e.dataTransfer.setData('text/plain', `${ids.length} conversation${ids.length === 1 ? '' : 's'}`);
  const ghost = document.createElement('div');
  ghost.textContent = ids.length === 1 ? '1 conversation' : `${ids.length} conversations`;
  ghost.style.cssText = 'position:fixed;top:-100px;left:-100px;padding:6px 12px;border-radius:6px;'
    + 'background:var(--cta-bg);color:var(--cta-text);font:600 12px var(--ui);box-shadow:var(--shadow)';
  document.body.append(ghost);
  e.dataTransfer.setDragImage(ghost, 10, 10);
  setTimeout(() => ghost.remove(), 0);
}

export function dragIds(e) {
  try {
    return JSON.parse(e.dataTransfer.getData(MIME) || '[]');
  } catch {
    return [];
  }
}

export function isThreadDrag(e) {
  return [...(e.dataTransfer?.types || [])].includes(MIME);
}

// use:dropTarget={{ onDrop(ids) {...} }}
export function dropTarget(node, opts) {
  let o = opts;
  let depth = 0;
  const over = (e) => {
    if (!o || !isThreadDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };
  const enter = (e) => {
    if (!o || !isThreadDrag(e)) return;
    depth += 1;
    node.classList.add('drop-hover');
  };
  const leave = () => {
    depth = Math.max(0, depth - 1);
    if (!depth) node.classList.remove('drop-hover');
  };
  const drop = (e) => {
    depth = 0;
    node.classList.remove('drop-hover');
    if (!o || !isThreadDrag(e)) return;
    e.preventDefault();
    const ids = dragIds(e);
    if (ids.length) o.onDrop(ids);
  };
  node.addEventListener('dragover', over);
  node.addEventListener('dragenter', enter);
  node.addEventListener('dragleave', leave);
  node.addEventListener('drop', drop);
  return {
    update(next) {
      o = next;
    },
    destroy() {
      node.removeEventListener('dragover', over);
      node.removeEventListener('dragenter', enter);
      node.removeEventListener('dragleave', leave);
      node.removeEventListener('drop', drop);
    },
  };
}
