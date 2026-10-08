// Small building blocks shared by the pages (cards, tables, metric tiles, links, topic watching).
import { frameBatch, h } from './dom.js';
import { deliverHash, taskHash } from './format.js';

export const sig = (...parts) => JSON.stringify(parts);
export const card = (...kids) => h('div', { class: 'card' }, ...kids);
export const section = (title, ...kids) => [h('h2', null, title), ...kids];
export const details = (summary, ...kids) => h('details', { class: 'hold' }, h('summary', null, summary), ...kids);
export const muted = (text) => h('span', { class: 'muted' }, text);
export const note = (text) => h('p', { class: 'section-note' }, text);

export const table = (cols, body, cls) => h('table', cls ? { class: cls } : null,
  h('thead', null, h('tr', null, cols.map((c) => h('th', null, c)))), body);
export const emptyRow = (cols, text) => () => h('tr', { class: 'app-empty' }, h('td', { colspan: cols }, text));

export const taskLink = (id, cls = 'mono') => h('a', { href: taskHash(id), class: cls }, id);
export const deliverLink = (id, cls = 'mono') => h('a', { href: deliverHash(id), class: cls }, id);
export const backLink = (href, text) => h('p', null, h('a', { href }, text));

export const count = (label, value, small) => h('div', { class: 'count' },
  h('span', { class: 'muted' }, label), h('b', null, value), small ? h('small', null, small) : null);
export const metric = (label, value, small, live) => h('div', { class: `runtime-metric${live ? ' live' : ''}` },
  h('span', null, label), h('strong', null, value), small ? h('small', null, small) : null);

/** Hide/show without touching the node (keeps what the user typed inside). */
export const show = (el, visible) => { el.hidden = !visible; };

/** Sort helper: by a list of keys, numbers numerically, null last. */
export const by = (...keys) => (a, b) => {
  for (const key of keys) {
    const x = typeof key === 'function' ? key(a) : a[key];
    const y = typeof key === 'function' ? key(b) : b[key];
    if (x === y) continue;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return x < y ? -1 : 1;
  }
  return 0;
};

/** Topic subscriptions of a page: every callback runs at most once per animation frame; stop() detaches them all. */
export function makeWatcher(store) {
  const offs = [];
  return {
    watch(topic, fn) { offs.push(store.on(topic, frameBatch(fn))); },
    stop() { offs.forEach((off) => off()); offs.length = 0; },
  };
}

/** Replace an element's <option>s keeping the selected value when it is still offered. */
export function setOptions(select, options, keep = true) {
  const chosen = select.value;
  select.replaceChildren();
  for (const [value, label] of options) select.append(h('option', { value }, label));
  if (keep && options.some(([value]) => value === chosen)) select.value = chosen;
}

/** [[key, "key — provider · model"]] of the model profiles in a topic's `models` meta. */
export const modelChoices = (models) => Object.entries(models || {}).map(([key, m]) => [key, `${key} — ${m.provider}/${m.model}`]);

/** Log links of one attempt (served by the server as plain text). */
export const attemptLogs = (id) => ['prompt', 'stdout', 'stderr', 'message', 'diff'].flatMap((which) =>
  [h('a', { href: `/log/${id}/${which}`, target: '_blank', rel: 'noopener' }, which), ' ']);

export function artifactView(a) {
  const label = `${a.task_id} · ${a.kind} · ${a.source_path || ''}`;
  const url = `/artifact/${a.id}`;
  if (a.media === 'image') {
    return h('div', null, h('a', { href: url, target: '_blank', rel: 'noopener' }, h('img', { class: 'thumb', src: url, alt: '' })),
      h('div', { class: 'muted' }, label));
  }
  if (a.media === 'video') return h('div', null, h('video', { class: 'thumb', controls: true, src: url }), h('div', { class: 'muted' }, label));
  return h('div', null, h('a', { href: url, target: '_blank', rel: 'noopener' }, label), ' ', muted(a.description || ''));
}
