// Delivers center: Jev status, runtime strip, live listeners, shelves (system shelves from onboarding, deterministic
// shelf, waves) with a search filter, the listener graph and the catalog forms. Topic: delivers.
import { h, setChildren, svg, syncList } from '../dom.js';
import { fmtAgo, fmtBytes, fmtTime, deliverHash } from '../format.js';
import { Form, actionButton } from '../forms.js';
import { pill } from '../ui.js';
import { by, card, count, deliverLink, details, emptyRow, makeWatcher, metric, sig, table } from '../widgets.js';

const TOPICS = ['delivers'];
const EXECUTION_HE = { worker: 'סוכן ביצוע', deterministic: 'פונקציה דטרמיניסטית', llm_research: 'מחקר מודל',
  context_bundle: 'חבילת קונטקסט', review: 'בקרת איכות' };
const JEV_HE = {
  READY: 'מוכן', MISSING_CREDENTIAL: 'חסר מפתח', AUTH_FAILED: 'האימות נכשל', API_UNREACHABLE: 'השירות אינו נגיש',
  RATE_LIMITED: 'הגעת למגבלת קצב', NO_CREDITS: 'אין יתרה', INVALID_RESPONSE: 'תשובה לא תקינה', reachable: 'נגיש',
  unknown: 'לא ידוע', present: 'קיים', missing: 'חסר', OK: 'תקין', not_checked: 'טרם נבדק', NOT_CHECKED: 'טרם נבדק',
  healthy: 'תקין', tokens: 'טוקנים', LOCAL_ESTIMATE: 'הערכה מקומית', local_estimate: 'הערכה מקומית',
};
const VIEW_KEY = 'wwii-deliver-view';
const jev = (value) => JEV_HE[String(value)] || String(value ?? 'לא ידוע');
const num = (n) => Number(n || 0).toLocaleString('en-US');

/** A stable palette index 0..5 from the Deliver id (the classic page used a sha256 prefix; any stable hash will do). */
export function paletteOf(id) {
  let x = 5381;
  for (const ch of String(id)) x = ((x << 5) + x + ch.charCodeAt(0)) >>> 0;
  return x % 6;
}

const searchText = (d) => ['deliver_id', 'owner', 'domain', 'description', 'execution_kind', 'description_he']
  .map((k) => String(d[k] || '')).join(' ').toLowerCase();
const modelOf = (d) => (d.execution_kind === 'deterministic' ? 'פונקציה מקומית'
  : d.preferred_model_key || d.task_preferred_model_key || d.last_model_key || 'בחירה אוטומטית');
const contextBytes = (d) => fmtBytes((d.context_source_bytes || 0) + (d.global_context_bytes || 0));
const metaItem = (label, value) => h('div', { class: 'meta-item' }, h('span', null, label), h('b', null, value));

/** Shelves for the visible Delivers: system shelves (by onboarding packet), the deterministic shelf, waves. */
export function groupShelves(delivers, meta, query = '') {
  const q = query.trim().toLowerCase();
  const system = new Map();
  const waves = new Map();
  const deterministic = [];
  const push = (map, key, d) => { if (!map.has(key)) map.set(key, []); map.get(key).push(d); };
  const outgoing = new Map();           // listeners proposed by each Deliver (the tile's "מאזינים מוצעים")
  for (const e of (meta && meta.edges) || []) {
    if (e.edge_type === 'listener') outgoing.set(e.source_deliver_id, (outgoing.get(e.source_deliver_id) || 0) + 1);
  }
  let visible = 0;
  for (const row of [...delivers].sort(by((x) => x.wave ?? 999, 'deliver_id'))) {
    if (q && !searchText(row).includes(q)) continue;
    visible += 1;
    const d = { ...row, listener_count: outgoing.get(row.deliver_id) || 0 };
    if (d.source_kind === 'system_manifest') push(system, d.packet || 'system', d);
    else if (d.execution_kind === 'deterministic') deterministic.push(d);
    else push(waves, d.wave ?? 99, d);
  }
  const titles = (meta && meta.shelf_titles) || {};
  const shelves = [];
  for (const [sid, items] of [...system].sort(([a], [b]) => (a < b ? -1 : 1))) {
    shelves.push({ key: `system:${sid}`, kind: 'system', title: titles[sid] || sid, sid, items });
  }
  if (deterministic.length) shelves.push({ key: 'deterministic', kind: 'deterministic', title: 'Delivers דטרמיניסטיים', items: deterministic });
  for (const [wave, items] of [...waves].sort(([a], [b]) => a - b)) {
    shelves.push({ key: `wave:${wave}`, kind: 'wave', title: wave === 99 ? 'Deliverים מהקטלוג' : `גל ${wave}`, items });
  }
  return { shelves, visible };
}

function tile(d) {
  const palette = `palette-${paletteOf(d.deliver_id)}`;
  const mark = d.deliver_id.split('/').pop().split('.').pop().slice(0, 18);
  const listeners = d.listener_count ?? 0;
  const kind = EXECUTION_HE[d.execution_kind] || d.execution_kind;
  const href = deliverHash(d.deliver_id);
  const cover = (top) => h('div', { class: 'deliver-cover' },
    h('div', { class: 'cover-top' }, top, h('span', { class: 'cover-kind' }, kind)), h('div', { class: 'deliver-mark mono' }, mark));
  if (d.source_kind === 'system_manifest') {
    return h('a', { class: `deliver-tile ${palette}`, href, dataset: { deliverCard: '' } },
      cover(h('span', { class: 'cover-wave' }, d.domain || '')),
      h('div', { class: 'deliver-info' }, h('h3', null, d.deliver_id),
        h('div', null, pill(String(d.availability || 'available').toUpperCase())),
        h('div', { class: 'deliver-description' }, d.description_he),
        h('div', { class: 'deliver-meta' }, metaItem('יכולות', d.capability_groups ?? 0),
          metaItem('תתי־יכולות', d.capability_count ?? 0), metaItem('אחראי', d.owner || 'טרם הוקצה'),
          metaItem('מודל או מנוע', modelOf(d)), metaItem('קונטקסט זמין', contextBytes(d)),
          metaItem('מאזינים מוצעים', listeners))));
  }
  if (d.execution_kind === 'deterministic') {
    return h('a', { class: 'deterministic-tile', href, dataset: { deliverCard: '' } },
      h('div', { class: 'bar' }, h('span', { class: 'cover-kind' }, 'פונקציה מקומית · שמור ב־DB'),
        pill(d.state || (d.enabled ? 'AVAILABLE' : 'PAUSED'))),
      h('h3', null, d.deliver_id), h('div', { class: 'deliver-description' }, d.description_he),
      h('div', { class: 'mini-grid' }, h('div', null, h('span', null, 'קונטקסט זמין'), h('b', null, contextBytes(d))),
        h('div', null, h('span', null, 'הרצות שמורות'), h('b', null, d.deterministic_run_count || 0)),
        h('div', null, h('span', null, 'עלות מודל'), h('b', null, '$0'))));
  }
  const allocated = Number(d.budget_allocated || 0);
  const pct = allocated > 0 ? Math.min(100, Math.round((Number(d.budget_spent || 0) / allocated) * 100)) : 0;
  const wave = d.wave ?? 99;
  return h('a', { class: `deliver-tile ${palette}`, href, dataset: { deliverCard: '' } },
    cover(h('span', { class: 'cover-wave' }, `גל ${wave === 99 ? 'קטלוג' : wave}`)),
    h('div', { class: 'deliver-info' }, h('h3', null, d.deliver_id), h('div', null, pill(d.state || (d.enabled ? 'AVAILABLE' : 'PAUSED'))),
      h('div', { class: 'deliver-description' }, d.description_he),
      h('div', { class: 'deliver-meta' }, metaItem('תחום', d.domain || 'כללי'), metaItem('אחראי', d.owner || 'טרם הוקצה'),
        metaItem('מודל או מנוע', modelOf(d)), metaItem('מאזינים מוצעים', listeners), metaItem('קונטקסט זמין', contextBytes(d)),
        metaItem('פרומפט אחרון', fmtBytes(d.latest_context_bytes)),
        metaItem('מחיר קבוע', d.fixed_price !== null && d.fixed_price !== undefined ? String(d.fixed_price) : 'טרם תומחר'),
        metaItem('ניצול תקציב', String(d.budget_spent || 0))),
      h('div', { class: 'budget-track', title: `ניצול תקציב: ${pct}%` }, h('span', { class: 'budget-fill', style: `width:${pct}%` }))));
}

function shelfNode(shelf) {
  const caps = shelf.kind === 'system' ? shelf.items.reduce((n, d) => n + (d.capability_count || 0), 0) : 0;
  const sub = shelf.kind === 'system'
    ? [`${shelf.items.length} רכיבים · ${caps} תתי־יכולות · הוכנסו ב־`, h('span', { class: 'mono' }, `wwii-build onboard ${shelf.sid}`)]
    : shelf.kind === 'deterministic'
      ? 'חוזה קל: פונקציה, קונטקסט, listeners והיסטוריית הרצות · ללא מודל או תמחור LLM'
      : `${shelf.items.length} רכיבים`;
  return h('section', { class: 'deliver-shelf' },
    h('div', { class: 'shelf-title' }, h('h2', null, shelf.title), h('small', null, sub)),
    h('div', { class: shelf.kind === 'deterministic' ? 'deterministic-rail' : 'deliver-rail' }, shelf.items.map(tile)));
}

/** The listener graph as SVG: waves are columns, listeners dashed, active listeners highlighted. */
export function graphSvg(delivers, edges, activeListeners, running) {
  if (!delivers.length) return h('p', { class: 'muted' }, 'עדיין לא יובאו Delivers. הריצו import-plan.');
  const byWave = new Map();
  for (const n of delivers) {
    const wave = n.wave ?? 99;
    if (!byWave.has(wave)) byWave.set(wave, []);
    byWave.get(wave).push(n);
  }
  const pos = new Map();
  [...byWave.keys()].sort((a, b) => a - b).forEach((wave, col) => {
    byWave.get(wave).forEach((n, row) => pos.set(n.deliver_id, [90 + col * 190, 45 + row * 72]));
  });
  const width = Math.max(...[...pos.values()].map(([x]) => x)) + 110;
  const height = Math.max(...[...pos.values()].map(([, y]) => y)) + 55;
  const active = new Set(activeListeners || []);
  const runningSet = new Set(running || []);
  const paths = [];
  for (const e of edges || []) {
    if (!pos.has(e.source_deliver_id) || !pos.has(e.target_deliver_id)) continue;
    const [x1, y1] = pos.get(e.source_deliver_id);
    const [x2, y2] = pos.get(e.target_deliver_id);
    const cls = active.has(e.listener_id) ? 'edge listener active'
      : e.edge_type === 'listener' && !e.enabled ? 'edge listener pending' : e.edge_type === 'listener' ? 'edge listener' : 'edge';
    const sx = x1 + 62;
    const ex = x2 - 62;
    const bend = Math.max(45, Math.abs(ex - sx) * 0.42);
    const c1 = ex >= sx ? sx + bend : sx - bend;
    const c2 = ex >= sx ? ex - bend : ex + bend;
    paths.push(svg('path', { class: cls, fill: 'none', 'marker-end': 'url(#arrow)', d: `M ${sx} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${ex} ${y2}` },
      svg('title', null, `${e.edge_type}: ${e.source_deliver_id} → ${e.target_deliver_id}`)));
  }
  const boxes = delivers.map((n) => {
    const [x, y] = pos.get(n.deliver_id);
    const state = n.state || 'CATALOG';
    const cls = runningSet.has(n.deliver_id) ? 'node running' : state === 'PASSED' ? 'node passed' : 'node';
    const label = n.deliver_id.length <= 22 ? n.deliver_id : `${n.deliver_id.slice(0, 20)}…`;
    return svg('a', { href: deliverHash(n.deliver_id) },
      svg('rect', { class: cls, x: x - 64, y: y - 22, width: 128, height: 44, rx: 7 },
        svg('title', null, `${n.deliver_id} · ${n.execution_kind} · ${state} · לחץ לפרטים`)),
      svg('text', { class: 'nlabel', x, y: y - 2, 'text-anchor': 'middle' }, label),
      svg('text', { class: 'nlabel', x, y: y + 13, 'text-anchor': 'middle' }, `${n.execution_kind} · ${state}`));
  });
  const defs = svg('defs', null, svg('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse' },
    svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#88a8c9' })));
  return svg('svg', { class: 'graph', viewBox: `0 0 ${width} ${height}`, role: 'img' }, defs, ...paths, ...boxes);
}

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const meta = () => store.meta('delivers');
  const items = () => store.items('delivers');
  let view = 'catalog';
  try { view = (typeof localStorage !== 'undefined' && localStorage.getItem(VIEW_KEY)) || 'catalog'; } catch (e) { /* private mode */ }

  // ------------------------------------------------------------------ skeleton
  const catalogBtn = h('button', { type: 'button' }, 'כרטיסים בלבד');
  const arcsBtn = h('button', { type: 'button' }, 'הצג קשרים וקשתות');
  const hero = h('section', { class: 'deliver-hero' },
    h('div', null, h('div', { class: 'hero-kicker' }, 'מערכת בנייה ותזמור'), h('h1', null, 'מרכז השליטה של ה־Delivers'),
      h('p', null, 'כל יכולת מוצגת כרכיב עצמאי עם בעלות, מודל, תקציב, מאזינים והיסטוריית ביצוע. ' +
        'Jev מקבל רק מועמדים שנמצאו בגרף ובוחר את הקונטקסט והנתיב המדויקים לכל פעולה.')),
    h('div', { class: 'mode-switch', role: 'group', 'aria-label': 'מצב תצוגה' }, catalogBtn, arcsBtn));
  const jevStrip = h('div', { class: 'counts' });
  const runtimeStrip = h('div', { class: 'runtime-strip' });
  const listenersGrid = h('div', { class: 'listener-live-grid' });
  const search = h('input', { id: 'deliverSearch', type: 'text', placeholder: 'חיפוש לפי מזהה, תחום, אחראי או תיאור', 'aria-label': 'חיפוש Delivers' });
  const visibleCount = h('b', null, '0');
  const totalCount = h('span', null, '0');
  const shelvesEl = h('div');
  const emptyFilter = h('div', { class: 'empty-filter', hidden: true }, 'לא נמצאו רכיבים שמתאימים לחיפוש.');
  const graphStage = h('div', { class: 'card graph-stage' });
  const graphShell = h('section', { class: 'graph-shell' },
    h('div', { class: 'shelf-title' }, h('h2', null, 'מפת הקשרים'), h('small', null, 'קו מלא: תלות קשיחה · קו מקווקו: מאזין שעובר דרך Jev')), graphStage);
  const opsBody = h('div');
  const workspace = h('div', { id: 'deliverWorkspace' });

  const keyForm = new Form(ctx, 'save_typesafe_key', { submit: 'שמור מפתח והרץ בדיקה חיה', reset: true });
  const deliverForm = new Form(ctx, 'save_deliver', { submit: 'שמור Deliver', reset: true });
  const contextForm = new Form(ctx, 'add_context', { submit: 'שמור מועמד קונטקסט', reset: true });

  const keyCard = card(h('div', { class: 'grid2' },
    keyForm.build(keyForm.text('typesafe_key', { label: 'מפתח API של TypeSafe', type: 'password', required: true,
      placeholder: 'נשמר ב־Keychain: typesafe-delivers', attrs: { autocomplete: 'new-password' } })),
    h('div', null, h('p', null, 'המפתח מועבר בזיכרון בלבד ל־SDK הרשמי של TypeSafe. הוא אינו נשמר במסד הנתונים, בקובצי הגדרות, בלוגים, בכתובות או בריפו.'),
      actionButton(ctx, 'הרץ בדיקת תקינות חיה', '', 'jev_health', {}))));
  const deliverCardForm = card(deliverForm.build(h('div', { class: 'grid2' },
    h('div', null, deliverForm.text('deliver_id', { label: 'מזהה Deliver', required: true, placeholder: 'weather.snow_research', dir: 'ltr' }),
      deliverForm.text('owner', { label: 'אחראי' }), deliverForm.text('domain', { label: 'תחום' })),
    h('div', null, deliverForm.select('execution_kind', Object.entries(EXECUTION_HE), { label: 'סוג ביצוע', value: 'worker' }),
      deliverForm.area('description', { label: 'מה ה־Deliver עושה — בעברית', rows: 5, required: true })))));
  const onboardForm = new Form(ctx, 'system_onboard', { submit: 'הטמע מערכת' });
  const onboardCard = card(onboardForm.build(
    h('p', { class: 'muted' }, 'כמו ', h('span', { class: 'mono' }, 'wwii-build onboard'),
      ': קובצי הקשר, Delivers ויכולות, ואז שליחה לגרף. ההתקדמות מוצגת חיה, ורק הטמעה אחת רצה בכל רגע.'),
    onboardForm.text('manifest', { label: 'מניפסט (שם מתוך systems/ או נתיב לקובץ toml בריפו)', required: true,
      placeholder: 'ww2_atlas', dir: 'ltr' }),
    onboardForm.select('graph', [['', 'לפי המניפסט'], ['1', 'כן'], ['0', 'לא']], { label: 'שליחה לגרף ה־RAG', value: '' })));
  if (ctx.bindBusy) ctx.bindBusy(onboardForm.button, 'system_onboard');
  const contextCard = card(contextForm.build(
    contextForm.text('source_key', { label: 'מפתח מקור', required: true, dir: 'ltr' }),
    contextForm.text('title', { label: 'כותרת', required: true }),
    contextForm.text('origin_ref', { label: 'מקור, כתובת או הפניה לגרף' }),
    contextForm.area('excerpt', { label: 'קונטקסט', rows: 8, required: true }),
    h('p', { class: 'muted' }, 'נשמר כמועמד בלבד. הוא יגיע למודל רק אם Jev יבחר בו עבור המשימה.')));

  const opsDetails = details('נתוני תפעול, מקור והיסטוריה', opsBody);
  setChildren(workspace, hero, jevStrip,
    h('h2', null, 'מצב הריצה וזיכרון מצטבר'), runtimeStrip,
    h('section', null, h('div', { class: 'shelf-title' }, h('h2', null, 'Listeners שנבחרו או רצים בפועל'),
      h('small', null, 'SELECTED ממתין להפעלה · RUNNING מבצע עבודה עכשיו')), listenersGrid),
    h('div', { class: 'catalog-tools' }, search, h('span', { class: 'result-count' }, visibleCount, ' מתוך ', totalCount, ' רכיבים')),
    shelvesEl, emptyFilter, graphShell,
    h('h2', null, 'חיבור Jev וניהול הקטלוג'), keyCard,
    details('הוספה או עדכון של Deliver', deliverCardForm),
    details('הוספת מועמד קונטקסט גלובלי', contextCard),
    details('הטמעת מערכת מקובץ מניפסט', onboardCard),
    opsDetails,
    h('p', { class: 'muted' }, 'רכיב נשאר ללא מחיר עד שיש מקור מתועד ומדיניות שמירת תקציב. הערכת שימוש מקומית אינה מוצגת כיתרה רשמית של TypeSafe.'));
  setChildren(root, workspace);

  // ------------------------------------------------------------------ sections
  function setView(mode) {
    view = mode;
    graphShell.hidden = mode === 'catalog';
    catalogBtn.classList.toggle('active', mode === 'catalog');
    arcsBtn.classList.toggle('active', mode === 'arcs');
    catalogBtn.setAttribute('aria-pressed', String(mode === 'catalog'));
    arcsBtn.setAttribute('aria-pressed', String(mode === 'arcs'));
    try { if (typeof localStorage !== 'undefined') localStorage.setItem(VIEW_KEY, mode); } catch (e) { /* ignore */ }
    if (mode === 'arcs') renderGraph();
  }
  catalogBtn.addEventListener('click', () => setView('catalog'));
  arcsBtn.addEventListener('click', () => setView('arcs'));

  function renderJev() {
    const j = meta().jev;
    if (!j) { setChildren(jevStrip); return; }
    const usage = j.usage || {};
    setChildren(jevStrip,
      count('מצב ניתוב Jev', jev(j.routing)),
      count('מפתח גישה', j.credential_present ? `שמור ב־${j.credential_source}` : 'חסר', 'הערך לעולם אינו מוצג'),
      count('API ואימות', jev(j.api), jev(j.authentication)),
      count('מודל Jev', j.model || 'לא ידוע'),
      count('מצב שימוש', jev(usage.state)),
      count('יתרה משוערת', usage.remaining !== null && usage.remaining !== undefined ? String(usage.remaining) : 'לא ידוע',
        `${usage.unit ?? ''} · ${usage.basis ?? ''}`),
      count('API רשמי ליתרה', usage.official_balance_available ? 'זמין' : 'לא קיים בתיעוד הרשמי'));
  }

  function renderRuntime() {
    const r = meta().runtime;
    if (!r) { setChildren(runtimeStrip); return; }
    const c = r.context; const m = r.cost_memory; const l = r.listeners; const d = r.deterministic;
    const jevMemory = m.jev_unit === 'tokens' ? `${num(m.jev_input_tokens + m.jev_output_tokens)} טוקנים`
      : `${Number(m.jev_estimated_cost).toFixed(4)} ${m.jev_unit}`;
    setChildren(runtimeStrip,
      metric('שכבת קונטקסט רשומה', fmtBytes(c.source_bytes), `${c.source_count} מקורות פעילים · ${c.global_source_count} גלובליים`),
      metric('Context Packs שנבנו', fmtBytes(c.pack_bytes), `${c.pack_count} חבילות שמורות במסד`),
      metric('קונטקסט בריצה עכשיו', fmtBytes(c.active_worker_bytes), `${c.active_worker_count} workers פעילים`, c.active_worker_count > 0),
      metric('עלות מדווחת שמורה', `$${Number(m.reported_cost_usd).toFixed(4)}`, `${m.attempt_count} ניסיונות · ${m.unknown_cost_attempts} ללא מחיר מדווח`),
      metric('זיכרון טוקנים של workers', num(m.input_tokens + m.cached_input_tokens + m.output_tokens),
        `${num(m.input_tokens)} קלט · ${num(m.cached_input_tokens)} מטמון · ${num(m.output_tokens)} פלט`),
      metric('שימוש Jev שמור', jevMemory, `${m.jev_requests} בקשות · ${m.jev_uncertain_requests} עם שימוש לא ודאי`),
      metric('Listeners פעילים', String(l.active_count), `${l.running_count} רצים · ${l.selected_count} נבחרו וממתינים`, l.active_count > 0),
      metric('Delivers דטרמיניסטיים', String(d.deliver_count), `${d.run_count} הרצות שמורות · עלות מודל $0`));
  }

  function renderListeners() {
    const rows = meta().active_activations || [];
    syncList(listenersGrid, rows, {
      key: (a) => a.listener_id + a.event_id,
      sig: (a) => sig(a),
      empty: () => h('div', { class: 'listener-empty' }, 'אין כרגע listener שנבחר או רץ. ההיסטוריה נשמרת במסד.'),
      build: (a) => h('div', { class: `listener-live ${String(a.status).toLowerCase()}` },
        h('div', { class: 'bar' }, h('b', { class: 'mono' }, a.listener_id), pill(a.status)),
        h('span', { class: 'route mono' }, `${a.source_deliver_id} → ${a.target_deliver_id}`),
        h('small', null, `${a.event_type || ''} · אירוע ${a.event_id} · גרסת מצב ${a.selected_state_version} · ${fmtAgo(a.created_at)}`)),
    });
  }

  function renderShelves() {
    const all = items();
    const { shelves, visible } = groupShelves(all, meta(), search.value);
    visibleCount.textContent = String(visible);
    totalCount.textContent = String(all.length);
    emptyFilter.hidden = visible > 0 || !all.length;
    syncList(shelvesEl, shelves, {
      key: (s) => s.key,
      sig: (s) => sig(s.kind, s.title, s.items),
      build: shelfNode,
    });
  }

  function renderGraph() {
    if (view !== 'arcs') return;
    const m = meta();
    setChildren(graphStage, graphSvg(items().sort(by((x) => x.wave ?? 999, 'deliver_id')), m.edges, m.active_listeners, m.running));
  }

  // operational history (large; loaded on demand from /api/delivers)
  async function loadOps() {
    setChildren(opsBody, h('p', { class: 'muted' }, 'טוען…'));
    let data;
    try { data = await ctx.fetchJson('/api/delivers'); } catch (e) { setChildren(opsBody, h('p', { class: 'err' }, 'הטעינה נכשלה')); return; }
    const when = (t) => fmtTime(t);
    const none = (cols) => emptyRow(cols, 'אין נתונים');
    const tbody = (rows, cols, build) => { const body = h('tbody'); syncList(body, rows, { key: (r) => JSON.stringify(r), sig: () => '', build, empty: none(cols) }); return body; };
    setChildren(opsBody,
      h('h2', null, 'מצב בניית האפיזודה'),
      card(table(['אפיזודה', 'גרסה', 'שלב', 'מטרה', 'Deliver אחרון', 'מצב'], tbody(data.episode_states || [], 6, (s) => h('tr', null,
        h('td', null, s.episode_id), h('td', null, s.version), h('td', null, s.phase), h('td', null, s.objective),
        h('td', { class: 'mono' }, s.updated_by_deliver_id || ''),
        h('td', null, h('pre', null, `${s.episode_state_json}\n${s.build_state_json}\n${s.context_refs_json}`)))))),
      h('h2', null, 'הפעלת מאזינים שנבחרו בידי Jev'),
      card(table(['זמן', 'אירוע', 'מאזין', 'נתיב', 'מצב', 'גרסת מצב'], tbody(data.activations || [], 6, (a) => h('tr', null,
        h('td', null, when(a.created_at)), h('td', { class: 'mono' }, a.event_id), h('td', { class: 'mono' }, a.listener_id),
        h('td', { class: 'mono' }, `${a.source_deliver_id} → ${a.target_deliver_id}`), h('td', null, pill(a.status)),
        h('td', null, a.selected_state_version))))),
      h('h2', null, 'אירועי מצב של Delivers'),
      card(table(['זמן', 'אפיזודה', 'Deliver מקור', 'אירוע', 'גרסה', 'ניתוב'], tbody(data.deliver_events || [], 6, (e) => h('tr', null,
        h('td', null, when(e.created_at)), h('td', null, e.episode_id), h('td', { class: 'mono' }, e.source_deliver_id),
        h('td', null, e.event_type), h('td', null, e.state_version), h('td', null, pill(e.status)))))),
      h('h2', null, 'מקורות הקונטקסט'),
      card(table(['מקור', 'סוג', 'הפניה', 'ישות בגרף', 'חתימה', 'כותרת'], tbody(data.context_sources || [], 6, (c) => h('tr', null,
        h('td', { class: 'mono' }, c.source_key), h('td', null, c.origin_kind), h('td', { class: 'mono' }, c.origin_ref),
        h('td', null, c.graph_entity_id || ''), h('td', { class: 'mono' }, String(c.content_sha256 || '').slice(0, 12)), h('td', null, c.title))))),
      h('h2', null, 'מה נשלח ל־Jev'),
      card(table(['זמן', 'סוג', 'בחירה', 'מצב', 'מודל', 'טוקנים נכנסו/יצאו', 'זמן תגובה', 'בקשה'], tbody(data.decisions || [], 8, (r) => h('tr', null,
        h('td', null, when(r.created_at)), h('td', null, r.route_kind), h('td', { class: 'mono' }, r.selected_id || r.fallback_id || ''),
        h('td', null, jev(r.status)), h('td', null, r.model || '—'),
        h('td', null, `${r.input_tokens ?? 'לא ידוע'} / ${r.output_tokens ?? 'לא ידוע'}`), h('td', null, `${r.latency_ms} מילישניות`),
        h('td', null, details('בקשה והסתברויות', h('pre', null, `${r.request_preview_json || '{}'}\n\n${r.probabilities_json || 'לא ידוע'}`))))))));
  }
  opsDetails.addEventListener('toggle', () => { if (opsDetails.open) loadOps(); });

  search.addEventListener('input', renderShelves);

  function renderAll() {
    renderJev(); renderRuntime(); renderListeners(); renderShelves(); renderGraph();
  }
  watch('delivers', renderAll);
  setView(view);
  renderAll();
  ctx.setTopics(TOPICS);
  return stop;
}
