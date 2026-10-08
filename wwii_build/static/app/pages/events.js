// Events journal: the newest rows come from /api/events, new rows arrive live through the events topic (only those that
// match the filters), older rows are paged in with before_id. Filters: search, event type, provider, task id.
import { h, setChildren, syncList } from '../dom.js';
import { eventDetailText, eventMatches, eventsQuery, fmtAgo, fmtTime, taskHash } from '../format.js';
import { count, emptyRow, makeWatcher, setOptions, table } from '../widgets.js';

const PAGE = 100;
const MAX_ROWS = 2000;                 // the page keeps at most this many rows in memory
const FACETS_MIN_MS = 3000;            // live rows refresh the counters at most this often
const FILTERS = ['search', 'event', 'provider', 'task_id'];

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const filters = Object.fromEntries(FILTERS.map((k) => [k, ctx.params[k] || '']));
  const rows = new Map();              // id -> event
  let total = 0;
  let nextBefore = null;               // cursor for the next older page (null: nothing older)
  let topId = 0;                       // live rows are accepted above this id
  let generation = 0;                  // bumped on every reload so a slow answer of an old filter is dropped
  let loading = false;
  let loaded = false;                  // the first page is in: before that live rows would be merged into nothing
  let alive = true;
  let facetsAt = 0;
  let facetsTimer = null;

  // ------------------------------------------------------------------ skeleton
  const counters = h('div', { class: 'counts' });
  const input = (name, label, attrs = {}) => {
    const el = h('input', { type: 'text', name, dir: attrs.dir, placeholder: attrs.placeholder, 'aria-label': label });
    el.value = filters[name];
    return el;
  };
  const search = input('search', 'חיפוש חופשי', { placeholder: 'אירוע, פרטים, משימה או ספק' });
  const task = input('task_id', 'מזהה משימה', { dir: 'ltr' });
  const eventSelect = h('select', { class: 'w', name: 'event', 'aria-label': 'סוג אירוע' });
  const providerSelect = h('select', { class: 'w', name: 'provider', 'aria-label': 'ספק' });
  const submit = h('button', { type: 'submit', class: 'go' }, 'סנן מהמסד');
  const clear = h('button', { type: 'button' }, 'נקה סינון');
  const form = h('form', { class: 'card event-filter' },
    h('label', null, 'חיפוש חופשי', search), h('label', null, 'סוג אירוע', eventSelect), h('label', null, 'ספק', providerSelect),
    h('label', null, 'מזהה משימה', task), h('div', { class: 'ctl-row' }, submit, clear));
  const title = h('h2', null, 'אירועים');
  const tbody = h('tbody');
  const shown = h('span');
  const older = h('button', { type: 'button' }, 'אירועים ישנים יותר ←');
  const live = h('span', { class: 'event-source' }, h('span', { class: 'event-live' }), h('b', null, 'חי: אירועים חדשים מופיעים מיד'));

  setChildren(root,
    h('div', { class: 'deliver-hero' }, h('div', null, h('div', { class: 'hero-kicker' }, 'יומן ביקורת מתמשך'), h('h1', null, 'יומן אירועים'),
      h('p', null, 'כל האירועים בדף נקראים ישירות מטבלת ', h('span', { class: 'mono' }, 'event_log'),
        ' במסד הנתונים. אירוע נכתב למסד לפני שהוא מופיע כאן, והמידע הרגיש מוסתר בזמן הכתיבה.')),
      h('div', { class: 'card' }, live, h('p', { class: 'mono muted' }, '.wwii-build/state.sqlite3 · event_log'),
        h('a', { href: '/api/events' }, 'פתח API של היומן'))),
    counters, h('h2', null, 'סינון היומן'), form,
    h('div', { class: 'bar' }, title, h('small', null, `מוצגות ${PAGE} רשומות בכל טעינה, מהחדשה לישנה`)),
    h('div', { class: 'card' }, table(['ID', 'זמן', 'אירוע', 'משימה', 'ספק', 'ניסיון', 'פרטים'], tbody, 'event-table'),
      h('div', { class: 'pager' }, shown, older)));

  // ------------------------------------------------------------------ rendering
  const active = () => FILTERS.some((k) => filters[k]);

  function renderRows() {
    const list = [...rows.values()].sort((a, b) => b.id - a.id);
    syncList(tbody, list, {
      key: (e) => e.id, sig: (e) => e.id,
      empty: emptyRow(7, 'לא נמצאו אירועים התואמים לסינון.'),
      build: (e) => h('tr', null, h('td', { class: 'event-id' }, `#${e.id}`),
        h('td', null, fmtTime(e.at), h('br'), h('small', null, fmtAgo(e.at))), h('td', { class: 'event-name' }, e.event),
        h('td', null, e.task_id ? h('a', { class: 'mono', href: taskHash(e.task_id) }, e.task_id) : ''), h('td', null, e.provider || ''),
        h('td', { class: 'mono' }, e.attempt_id ?? ''), h('td', { class: 'mono event-detail' }, eventDetailText(e.detail))),
    });
    setChildren(title, `אירועים (${total}${active() ? ' מסוננים' : ''})`);
    setChildren(shown, `${rows.size} רשומות בדף זה`);
    older.hidden = !nextBefore;
    older.disabled = loading;
  }

  function renderFacets(f) {
    setChildren(counters, count('אירועים שמורים', f.total), count('סוגי אירועים', f.type_count), count('משימות ביומן', f.task_count),
      count('רשומה אחרונה', `#${f.latest ? f.latest.id : 0}`, f.latest ? fmtTime(f.latest.at) : '—'));
    setOptions(eventSelect, [['', 'כל סוגי האירועים'], ...f.types.map((t) => [t, t])]);
    setOptions(providerSelect, [['', 'כל הספקים'], ...f.providers.map((p) => [p, p])]);
    eventSelect.value = filters.event;
    providerSelect.value = filters.provider;
  }

  async function loadFacets() {
    facetsAt = Date.now();
    try {
      const f = await ctx.fetchJson('/api/events/facets');
      if (alive) renderFacets(f);
    } catch (e) { /* the counters keep their last values */ }
  }

  function facetsSoon() {
    if (facetsTimer) return;
    facetsTimer = setTimeout(() => { facetsTimer = null; if (alive) loadFacets(); }, Math.max(0, FACETS_MIN_MS - (Date.now() - facetsAt)));
  }

  // ------------------------------------------------------------------ data
  async function load({ more = false } = {}) {
    if (loading) return;
    loading = true;
    const mine = more ? generation : ++generation;
    older.disabled = true;
    try {
      const data = await ctx.fetchJson(`/api/events?${eventsQuery(filters, { before: more ? nextBefore : null, limit: PAGE })}`);
      if (!alive || mine !== generation) return;
      if (!more) rows.clear();
      for (const e of data.events) rows.set(e.id, e);
      total = data.total;
      nextBefore = data.next_before_id;
      if (!more) { topId = Math.max(0, ...rows.keys()); loaded = true; }
      renderRows();
      if (!more) takeLive();                       // rows that arrived while the page was being read
    } catch (e) {
      ctx.toast('טעינת האירועים נכשלה', false);
    } finally {
      loading = false;
      if (alive) older.disabled = false;
    }
  }

  /** Rows that arrived through the socket after the page was loaded and match the filters. */
  function takeLive() {
    if (!loaded) return;
    let added = 0;
    for (const e of store.items('events')) {
      if (e.id <= topId || rows.has(e.id) || !eventMatches(e, filters)) continue;
      rows.set(e.id, e);
      added += 1;
    }
    if (!added) return;
    topId = Math.max(topId, ...rows.keys());
    total += added;
    if (rows.size > MAX_ROWS) {
      for (const id of [...rows.keys()].sort((a, b) => a - b).slice(0, rows.size - MAX_ROWS)) rows.delete(id);
    }
    renderRows();
    facetsSoon();
  }

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    filters.search = search.value.trim();
    filters.task_id = task.value.trim();
    filters.event = eventSelect.value;
    filters.provider = providerSelect.value;
    load();
  });
  clear.addEventListener('click', () => {
    for (const k of FILTERS) filters[k] = '';
    search.value = '';
    task.value = '';
    eventSelect.value = '';
    providerSelect.value = '';
    load();
  });
  older.addEventListener('click', () => load({ more: true }));

  watch('events', takeLive);
  renderRows();
  ctx.setTopics(['events']);
  loadFacets();
  load();
  return () => { alive = false; clearTimeout(facetsTimer); stop(); };
}
