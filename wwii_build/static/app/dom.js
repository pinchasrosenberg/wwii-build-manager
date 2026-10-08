// Tiny DOM helpers. Text always goes in through text nodes, never through markup strings.

function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

/** h('div', {class: 'card', onclick: fn, dataset: {x: 1}}, child, 'text', [more]) */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  append(el, kids);
  return el;
}

/** Same as h() for SVG elements: svg('rect', {x: 1, class: 'node'}, svg('title', null, 'text')). */
export function svg(tag, attrs, ...kids) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    el.setAttribute(k, String(v));
  }
  append(el, kids);
  return el;
}

export function setChildren(el, ...kids) {
  el.replaceChildren();
  append(el, kids);
}

/**
 * Keep `parent`'s children in step with `items` without rebuilding rows that did not change:
 * a row is rebuilt only when sig(item) differs, so inputs inside untouched rows keep what the user typed.
 */
export function syncList(parent, items, { key, sig, build, empty }) {
  const old = new Map();
  for (const el of parent.children) if (el._key !== undefined) old.set(el._key, el);
  const want = [];
  for (const item of items) {
    const k = key(item);
    const s = sig(item);
    let el = old.get(k);
    if (!el || el._sig !== s) {
      el = build(item);
      el._key = k;
      el._sig = s;
    }
    want.push(el);
  }
  if (!want.length && empty) {
    const el = old.get('\0empty') || empty();
    el._key = '\0empty';
    el._sig = '';
    want.push(el);
  }
  const keep = new Set(want);
  for (const el of [...parent.children]) if (!keep.has(el)) el.remove();
  let cursor = parent.firstChild;
  for (const el of want) {
    if (el === cursor) cursor = cursor.nextSibling;
    else parent.insertBefore(el, cursor);
  }
}

/** Run `fn` at most once per animation frame however often it is requested. */
export function frameBatch(fn) {
  let queued = false;
  return () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; fn(); });
  };
}
