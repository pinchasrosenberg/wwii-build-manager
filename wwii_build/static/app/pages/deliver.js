// Deliver detail: definition, model control, graph access, capabilities tree (deliver_capabilities grouped by
// group_name), edges, economics, context candidates, history and the listener / dependency / context forms.
// Topic: deliver:<id> (capabilities as items; the Deliver row, edges and `detail` in meta).
import { h, setChildren, syncList } from '../dom.js';
import { fmtBytes, fmtTime, taskHash } from '../format.js';
import { Form, actionButton } from '../forms.js';
import { pill } from '../ui.js';
import { artifactView, attemptLogs, backLink, card, details, emptyRow, makeWatcher, metric, modelChoices, muted, note, sig, table } from '../widgets.js';

const KIND_HE = { files: 'קובץ', py_functions: 'פונקציה', mcp_tools: 'כלי MCP', http_routes: 'נתיב HTTP', argparse: 'פקודה',
  js_functions: 'פונקציה', declared: 'מוצהר' };
const EXECUTION = [['worker', 'סוכן ביצוע'], ['deterministic', 'פונקציה דטרמיניסטית'], ['llm_research', 'מחקר מודל'],
  ['context_bundle', 'חבילת קונטקסט'], ['review', 'בקרת איכות']];
const ACCESS = [['none', 'ללא גישה'], ['limited', 'גישה מוגבלת'], ['full', 'גישה מלאה']];
const EDGE_COLS = ['סוג', 'מזהה', 'נתיב', 'אירוע', 'שער', 'מצב'];

const str = (v) => (v === null || v === undefined ? '' : String(v));
const none = (text) => h('span', { class: 'muted' }, text);

/** Capability rows -> [[group_name, rows]] in first-seen order. */
export function capabilityGroups(rows) {
  const groups = new Map();
  for (const r of rows) {
    if (!groups.has(r.group_name)) groups.set(r.group_name, []);
    groups.get(r.group_name).push(r);
  }
  return [...groups];
}

export function mount(ctx) {
  const { store, root } = ctx;
  const id = ctx.params.id || '';
  const topic = `deliver:${id}`;
  const { watch, stop } = makeWatcher(store);
  const meta = () => store.meta(topic);
  const detail = () => meta().detail || {};
  const openGroups = new Map();
  let built = null;                       // 'full' | 'light' once the layout exists
  let ui = {};

  const body = h('div');
  setChildren(root, backLink('#/delivers', '→ חזרה למפת ה־Delivers'), body);

  // ------------------------------------------------------------------ layout (built once per variant)
  function edgesTable() {
    ui.edges = h('tbody');
    return table(EDGE_COLS, ui.edges);
  }

  function layoutLight() {
    const edit = new Form(ctx, 'save_deliver', { fixed: { deliver_id: id, execution_kind: 'deterministic' }, submit: 'שמור חוזה קל' });
    const contextForm = new Form(ctx, 'add_context', { fixed: { deliver_id: id }, submit: 'שמור קונטקסט', reset: true });
    ui = { edit, contextForm, hero: h('section', { class: 'control-hero light-contract' }), metrics: h('div', { class: 'runtime-strip' }),
      runs: h('tbody'), contexts: h('div'), events: h('tbody') };
    const editEl = edit.build(h('div', { class: 'grid2' },
      h('div', null, edit.text('owner', { label: 'אחראי' }), edit.text('domain', { label: 'תחום' })),
      h('div', null, edit.area('description', { label: 'מה הפונקציה עושה — בעברית', rows: 5, required: true }))));
    const ctxEl = contextForm.build(contextForm.text('source_key', { label: 'מפתח מקור', required: true, dir: 'ltr' }),
      contextForm.text('title', { label: 'כותרת', required: true }), contextForm.text('origin_ref', { label: 'מקור או הפניה' }),
      contextForm.area('excerpt', { label: 'תוכן', rows: 5, required: true }));
    setChildren(body, ui.explain = h('section', { class: 'card' }), ui.caps = h('div'), ui.hero, ui.metrics,
      h('div', { class: 'grid2' }, h('div', null, h('h2', null, 'חוזה קל'), card(editEl)),
        h('div', null, h('h2', null, 'קונטקסט'), card(details('הוסף מועמד קונטקסט לפונקציה', ctxEl)))),
      h('h2', null, 'קשרים ו־Listeners'), card(edgesTable()),
      h('h2', null, 'הרצות שמורות'),
      card(table(['מזהה', 'מצב', 'אפיזודה', 'התחלה', 'סיום', 'קלט / פלט', 'עלות', 'פרטים'], ui.runs)),
      h('h2', null, 'מועמדי קונטקסט ומקורם'), card(ui.contexts),
      h('h2', null, 'היסטוריית ה־Deliver'), card(table(['זמן', 'אירוע', 'פרטים'], ui.events)));
  }

  function layoutFull() {
    const f = {
      model: new Form(ctx, 'set_deliver_model', { fixed: { deliver_id: id }, submit: 'שמור מודל', cls: '', class: 'inline-control' }),
      scoped: new Form(ctx, 'scoped_plan', { fixed: { scope_kind: 'deliver', scope_id: id, prompt_mode: 'plan_build' }, submit: 'תכנן את השינוי', reset: true }),
      edit: new Form(ctx, 'save_deliver', { fixed: { deliver_id: id }, submit: 'שמור Deliver' }),
      graph: new Form(ctx, 'save_deliver_graph_access', { fixed: { deliver_id: id }, submit: 'שמור הרשאת גרף' }),
      listener: new Form(ctx, 'add_listener', { fixed: { source_deliver_id: id }, submit: 'שמור מאזין', reset: true }),
      dependency: new Form(ctx, 'add_dependency', { fixed: { target_deliver_id: id }, submit: 'הוסף תלות קשיחה', cls: '' }),
      context: new Form(ctx, 'add_context', { fixed: { deliver_id: id }, submit: 'שמור מועמד קונטקסט', reset: true }),
      economics: new Form(ctx, 'save_economics', { fixed: { deliver_id: id }, submit: 'שמור נתונים כלכליים' }),
    };
    ui = { ...f, form: f, hero: h('section', { class: 'control-hero' }), metrics: h('div', { class: 'runtime-strip' }),
      toggleSlot: h('span'), attempts: h('tbody'), artifacts: h('div'), contexts: h('div'), events: h('tbody') };

    const modelEl = f.model.build(h('label', null, 'מודל קבוע ל־Deliver '), f.model.select('model_key', [['', 'בחירה אוטומטית']], { cls: null }));
    ui.modelSlot = h('div', null, modelEl, ui.taskLinks = h('span'));
    const scopedEl = f.scoped.build(h('p', { class: 'muted' }, 'המודל יקבל את הגדרת הרכיב, הקשרים הישירים ורשימת מועמדים קצרה מהגרף. Jev יחליט איזה קונטקסט ייכנס בפועל.'),
      f.scoped.area('prompt', { label: 'מה לשנות?', required: true, placeholder: 'לדוגמה: הוסף מאזין שמפעיל בדיקת מזג אוויר כאשר מיקום ותאריך האפיזודה ידועים' }),
      f.scoped.select('model_key', [['', 'בחירת מודל אוטומטית']], { cls: null }),
      f.scoped.text('mcp_servers', { placeholder: 'שרתי MCP, אם צריך' }));
    const editEl = f.edit.build(h('div', { class: 'grid2' },
      h('div', null, f.edit.text('owner', { label: 'אחראי' }), f.edit.text('domain', { label: 'תחום' }),
        f.edit.select('execution_kind', EXECUTION, { label: 'סוג ביצוע', value: 'worker' })),
      h('div', null, f.edit.area('description', { label: 'מה ה־Deliver עושה — בעברית', rows: 8, required: true }), ui.toggleSlot)));
    const graphEl = f.graph.build(h('div', { class: 'grid2' },
      h('div', null, f.graph.select('access_mode', ACCESS, { label: 'רמת גישה לגרף', value: 'none' }),
        f.graph.text('scope_text', { label: 'תחום מותר בגישה מוגבלת', placeholder: 'לדוגמה: טנקים, בליסטיקה, החזית המזרחית' })),
      h('div', null, f.graph.text('max_chunks', { label: 'מספר מקטעים מרבי', type: 'number', min: 1, max: 50, value: '6' }),
        f.graph.text('max_chars', { label: 'מספר תווים מרבי', type: 'number', min: 500, max: 100000, value: '6000' }))),
      note('ההרשאה קובעת מה ניתן לשלוף. כל מקטע שנשלף נשאר מועמד עד ש־Jev בוחר בו במפורש.'));
    const listenerEl = f.listener.build(h('div', { class: 'grid2' },
      h('div', null, f.listener.text('listener_id', { label: 'מזהה מאזין', required: true, placeholder: `${id}::signal`, dir: 'ltr' }),
        f.listener.text('source_lego_id', { label: 'מזהה רכיב הלגו המקורי', dir: 'ltr' }),
        f.listener.text('event_type', { label: 'סוג אירוע', required: true, value: 'DELIVER_PASSED', dir: 'ltr' }),
        f.listener.select('target_deliver_id', [], { label: 'Deliver יעד' })),
      h('div', null, f.listener.area('proposal_reason', { label: 'למה להציע את ההפעלה', rows: 3, required: true }),
        f.listener.area('context_selector', { label: 'בורר דטרמיניסטי, JSON', rows: 6, value: '{}', dir: 'ltr' }),
        h('p', { class: 'muted' }, 'המאזין נשמר כמועמד. Jev עדיין מחליט בכל אירוע אם להפעיל אותו.'))));
    const dependencyEl = f.dependency.build(f.dependency.select('depends_on', [], { label: 'Deliver נדרש' }));
    const contextEl = f.context.build(f.context.text('source_key', { label: 'מפתח מקור קונטקסט', required: true, dir: 'ltr' }),
      f.context.text('title', { label: 'כותרת', required: true }), f.context.text('origin_ref', { label: 'מקור, כתובת או הפניה לגרף' }),
      f.context.text('graph_entity_id', { label: 'מזהה ישות בגרף' }),
      f.context.area('excerpt', { label: 'מועמד הקונטקסט', rows: 8, required: true }),
      h('p', { class: 'muted' }, 'המתזמן חושף אותו כמועמד בלבד; Jev חייב לבחור בו לפני שייכנס לפרומפט של מודל.'));
    const econEl = f.economics.build(h('div', { class: 'grid2' },
      h('div', null, f.economics.text('currency', { label: 'מטבע', value: 'USD' }), f.economics.text('fixed_price', { label: 'מחיר קבוע' }),
        f.economics.text('budget_allocated', { label: 'תקציב מוקצה' })),
      h('div', null, f.economics.text('valuation_amount', { label: 'שווי נוכחי' }), f.economics.text('valuation_as_of', { label: 'תאריך הערכת שווי' }),
        f.economics.text('valuation_source_url', { label: 'כתובת מקור להערכת שווי' }),
        f.economics.area('valuation_basis', { label: 'בסיס להערכת השווי', rows: 3 }))));
    setChildren(body, ui.explain = h('section', { class: 'card' }), ui.caps = h('div'), ui.hero, ui.metrics,
      h('div', { class: 'control-grid' }, h('div', { class: 'card command-card' }, h('h2', null, 'בקש שינוי ב־Deliver הזה'), scopedEl),
        h('div', null, h('h2', null, 'הגדרת ה־Deliver'), card(editEl))),
      h('h2', null, 'גישה לגרף ה־RAG'), card(graphEl),
      h('div', { class: 'grid2' }, h('div', null, h('h2', null, 'קשרים, תלויות ומאזינים'), card(edgesTable())),
        h('div', null, h('h2', null, 'נתונים כלכליים ותקציב'), card(econEl))),
      h('div', { class: 'grid2' }, h('div', null, h('h2', null, 'הוספת מאזין שעובר דרך Jev'), card(listenerEl)),
        h('div', null, h('h2', null, 'הוספת תלות קשיחה'), card(dependencyEl), h('h2', null, 'הוספת מועמד קונטקסט'), card(contextEl))),
      h('h2', null, 'מה ה־Deliver בנה'), card(ui.artifacts),
      h('h2', null, 'היסטוריית בנייה'),
      card(table(['ניסיון', 'סוג', 'ספק', 'מודל', 'מצב', 'התחלה', 'בדיקה'], ui.attempts)),
      h('h2', null, 'מועמדי קונטקסט ומקורם'), card(ui.contexts),
      h('h2', null, 'היסטוריית ה־Deliver'), card(table(['זמן', 'אירוע', 'פרטים'], ui.events)));
  }

  // ------------------------------------------------------------------ data sections
  function renderExplain(d) {
    setChildren(ui.explain, h('h2', null, 'מה הרכיב עושה'), h('p', null, d.description_he),
      h('h2', null, 'איך הוא מיושם כעת'), h('p', null, d.implementation_he),
      h('p', { class: 'muted' }, 'הסבר המימוש מחושב ממצב המשימה, נתיבי התוצרים, סוג ההרצה והמאזינים העדכניים.'));
  }

  function renderCaps() {
    const rows = store.items(topic);
    const groups = capabilityGroups(rows);
    if (!groups.length) { setChildren(ui.caps); return; }
    const host = h('div', { class: 'card capabilities' });
    syncList(host, groups, {
      key: ([g]) => g,
      sig: ([g, items]) => sig(g, items),
      build: ([g, items]) => {
        const el = h('details', { class: 'cap-group hold', open: openGroups.has(g) ? openGroups.get(g) : groups.length <= 3 },
          h('summary', null, h('b', null, g), ' ', h('span', { class: 'muted' }, `(${items.length})`)),
          h('table', { class: 'cap-table' }, h('tbody', null, items.map((r) => h('tr', null,
            h('td', { class: 'mono' }, r.name), h('td', null, KIND_HE[r.kind] || r.kind), h('td', null, r.description || ''),
            h('td', { class: 'mono muted' }, r.source_ref || ''))))));
        el.addEventListener('toggle', () => openGroups.set(g, !!el.open));
        return el;
      },
    });
    host.append(h('p', { class: 'muted' }, 'התגלו אוטומטית מהקוד של הרכיב בהכנסת המערכת (', h('span', { class: 'mono' }, 'wwii-build onboard'),
      '). כל תת־יכולת רשומה גם בגרף ה־RAG.'));
    setChildren(ui.caps, h('h2', null, 'יכולות ותתי־יכולות ', h('span', { class: 'muted' }, `(${groups.length} יכולות · ${rows.length} תתי־יכולות)`)), host);
  }

  function renderEdges(d) {
    const edges = meta().edges || [];
    syncList(ui.edges, [...edges.filter((e) => e.target_deliver_id === id), ...edges.filter((e) => e.target_deliver_id !== id)], {
      key: (e) => `${e.listener_id}|${e.source_deliver_id}|${e.target_deliver_id}`,
      sig: (e) => sig(e),
      empty: emptyRow(6, 'אין עדיין קשרים'),
      build: (e) => h('tr', null, h('td', null, e.edge_type === 'listener' ? 'מאזין' : 'תלות קשיחה'), h('td', { class: 'mono' }, e.listener_id),
        h('td', { class: 'mono' }, e.target_deliver_id === id ? `${e.source_deliver_id} ← ה־Deliver הזה` : `ה־Deliver הזה ← ${e.target_deliver_id}`),
        h('td', null, e.event_type), h('td', null, e.jev_gate ? 'בחירת Jev' : 'חובה מוקדמת'),
        h('td', null, pill(e.enabled ? 'AVAILABLE' : 'PAUSED'), ' ',
          e.edge_type === 'listener'
            ? actionButton(ctx, e.enabled ? 'השבת' : 'הפעל', '', 'toggle_listener', { listener_id: e.listener_id, enabled: !e.enabled }) : null)),
    });
  }

  function renderContexts(det) {
    syncList(ui.contexts, det.contexts || [], {
      key: (c) => c.source_key, sig: (c) => sig(c),
      empty: () => none('אין מועמדי קונטקסט'),
      build: (c) => h('details', null, h('summary', null, `${c.title} · `, h('span', { class: 'mono' }, c.source_key)),
        h('p', { class: 'muted' }, `${c.origin_kind}: ${c.origin_ref} · graph ${c.graph_entity_id || '—'} · sha ${c.sha}`),
        h('pre', null, c.excerpt)),
    });
  }

  function renderEvents(det) {
    syncList(ui.events, det.events || [], {
      key: (e) => e.id, sig: (e) => sig(e), empty: emptyRow(3, 'אין עדיין אירועים.'),
      build: (e) => h('tr', null, h('td', null, fmtTime(e.at)), h('td', null, e.event), h('td', null, h('pre', null, e.detail || ''))),
    });
  }

  function renderHero(d, det) {
    // rebuilt only when it changed: the model select inside must not be replaced while it is being used
    const signature = sig(built, d.state, d.enabled, d.execution_kind, d.source_ref, d.source_kind, d.implementation_ref, det.has_task);
    if (ui.heroSig === signature) return;
    ui.heroSig = signature;
    const state = d.state || (d.enabled ? 'AVAILABLE' : 'PAUSED');
    if (built === 'light') {
      setChildren(ui.hero, h('div', { class: 'eyebrow' }, 'Deliver דטרמיניסטי · חוזה קל ושמור'), h('h1', { class: 'mono' }, id),
        h('p', null, pill(state), ' · פונקציה מקומית · עלות מודל $0 · ',
          h('span', { class: 'mono' }, d.implementation_ref || d.source_ref || 'ללא מימוש רשום')));
      return;
    }
    setChildren(ui.hero, h('div', { class: 'eyebrow' }, 'ניהול רכיב'), h('h1', { class: 'mono' }, id),
      h('p', null, pill(state), ` · ${d.execution_kind} · מקור `, h('span', { class: 'mono' }, d.source_ref || d.source_kind || '')), ui.modelSlot);
    setChildren(ui.taskLinks, det.has_task ? [' ', h('a', { class: 'btnlink', href: taskHash(id) }, 'ניהול המשימה'), ' ',
      h('a', { class: 'btnlink', href: `/classic/review?id=${encodeURIComponent(id)}` }, 'הצג מה נבנה')] : null);
  }

  function renderMetrics(d, det) {
    const m = det.metrics || {};
    const edges = meta().edges || [];
    if (built === 'light') {
      const running = (det.runs || []).filter((r) => r.status === 'RUNNING').length;
      setChildren(ui.metrics,
        metric('קונטקסט זמין', fmtBytes(m.context_bytes), `${m.context_sources || 0} מקורות · ${m.own_context_sources || 0} ייחודיים ל־Deliver`),
        metric('הרצות דטרמיניסטיות', String((det.runs || []).length), `${running} רצות עכשיו · נשמרות ב־SQLite`, running > 0),
        metric('עלות LLM', '$0', 'אין בחירת מודל ואין טוקנים'),
        metric('Listeners מחוברים', String(edges.length), `${edges.filter((e) => e.source_deliver_id === id).length} יוצאים · ${edges.filter((e) => e.target_deliver_id === id).length} נכנסים`));
      return;
    }
    setChildren(ui.metrics,
      metric('קונטקסט זמין ל־Deliver', fmtBytes(m.context_bytes), `${m.context_sources || 0} מקורות פעילים, כולל גלובליים`),
      metric('Context Packs בפועל', fmtBytes(m.pack_bytes), `${m.pack_count || 0} חבילות · אחרונה ${fmtBytes(m.latest_pack_bytes)}`),
      metric('עלות מדווחת שמורה', `$${Number(m.reported_cost_usd || 0).toFixed(4)}`, `${m.attempt_count || 0} ניסיונות · ${m.unknown_cost_attempts || 0} ללא מחיר`),
      metric('Listeners פעילים סביב הרכיב', String(m.active_listeners || 0), 'נבחרו או רצים כעת', (m.active_listeners || 0) > 0));
  }

  function renderRuns(det) {
    syncList(ui.runs, det.runs || [], {
      key: (r) => r.run_id, sig: (r) => sig(r), empty: emptyRow(8, 'עדיין לא נרשמה הרצה דטרמיניסטית.'),
      build: (r) => h('tr', null, h('td', { class: 'mono' }, r.run_id), h('td', null, pill(r.status)), h('td', null, r.episode_id || '—'),
        h('td', null, fmtTime(r.started_at)), h('td', null, r.completed_at ? fmtTime(r.completed_at) : '…'),
        h('td', null, `${fmtBytes(r.input_bytes)} / ${fmtBytes(r.output_bytes)}`), h('td', null, '$0'),
        h('td', null, details('פרטים', h('pre', null, r.detail_json || '')))),
    });
  }

  function renderFull(d, det) {
    const f = ui.form;
    const models = modelChoices(det.models);
    f.model.setItems('model_key', [['', 'בחירה אוטומטית'], ...models]);
    f.model.setDefault('model_key', d.preferred_model_key || d.task_preferred_model_key || '');
    f.scoped.setItems('model_key', [['', 'בחירת מודל אוטומטית'], ...models]);
    f.edit.setDefault('owner', str(d.owner));
    f.edit.setDefault('domain', str(d.domain));
    f.edit.setDefault('execution_kind', d.execution_kind);
    f.edit.setDefault('description', str(d.description_he));
    if (ui.toggleSig !== d.enabled) {
      ui.toggleSig = d.enabled;
      setChildren(ui.toggleSlot, ' ', actionButton(ctx, d.enabled ? 'השבת' : 'הפעל', '', 'toggle_deliver', { deliver_id: id, enabled: !d.enabled }));
    }
    const access = det.graph_access || {};
    f.graph.setDefault('access_mode', access.access_mode || 'none');
    f.graph.setDefault('scope_text', str(access.scope_text));
    f.graph.setDefault('max_chunks', str(access.max_chunks ?? 6));
    f.graph.setDefault('max_chars', str(access.max_chars ?? 6000));
    const others = (det.other_delivers || []).map((x) => [x, x]);
    f.listener.setItems('target_deliver_id', others);
    f.dependency.setItems('depends_on', others);
    const econ = det.economics || {};
    f.economics.setDefault('currency', econ.currency || 'USD');
    for (const k of ['fixed_price', 'budget_allocated', 'valuation_amount', 'valuation_as_of', 'valuation_source_url', 'valuation_basis']) {
      f.economics.setDefault(k, str(econ[k]));
    }
    renderEdges(d);
    syncList(ui.attempts, det.attempts || [], {
      key: (a) => a.id, sig: (a) => sig(a), empty: emptyRow(7, 'עדיין לא היו ניסיונות בנייה.'),
      build: (a) => h('tr', null, h('td', null, a.id), h('td', null, `${a.kind} #${a.attempt_no}`), h('td', null, a.provider),
        h('td', { class: 'mono' }, a.model), h('td', null, pill(a.status)), h('td', null, fmtTime(a.started_at)), h('td', null, attemptLogs(a.id))),
    });
    syncList(ui.artifacts, det.artifacts || [], {
      key: (a) => a.id, sig: (a) => sig(a), empty: () => none('עדיין לא נשמרו תוצרים.'), build: artifactView,
    });
  }

  function render() {
    const m = meta();
    if (!store.has(topic)) { setChildren(body, h('p', { class: 'muted' }, 'טוען…')); built = null; return; }
    if (!m.exists) {
      built = null;
      setChildren(body, h('h1', null, 'Unknown Deliver'), h('p', { class: 'muted mono' }, id));
      return;
    }
    const d = m.deliver;
    const det = detail();
    const kind = d.execution_kind === 'deterministic' ? 'light' : 'full';
    if (built !== kind) { built = kind; (kind === 'light' ? layoutLight : layoutFull)(); }
    renderExplain(d);
    renderCaps();
    renderHero(d, det);
    renderMetrics(d, det);
    if (kind === 'light') {
      ui.edit.setDefault('owner', str(d.owner));
      ui.edit.setDefault('domain', str(d.domain));
      ui.edit.setDefault('description', str(d.description_he));
      renderEdges(d); renderRuns(det);
    } else {
      renderFull(d, det);
    }
    renderContexts(det);
    renderEvents(det);
  }

  watch(topic, render);
  render();
  ctx.setTopics([topic]);
  return stop;
}
