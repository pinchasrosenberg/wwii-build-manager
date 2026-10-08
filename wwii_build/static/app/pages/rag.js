// RAG / graph console: Cypher and natural-language queries run as actions (graph_console_query) and their results
// appear inline from the rag topic; service health, per-Deliver graph access and the retrieval history.
// Topic: rag (console queries as items; access rows, history, model profiles and service URLs in meta).
import { h, setChildren, syncList } from '../dom.js';
import { fmtTime } from '../format.js';
import { Form } from '../forms.js';
import { pill } from '../ui.js';
import { card, count, deliverLink, details, emptyRow, makeWatcher, modelChoices, note, sig, table, taskLink } from '../widgets.js';

const ACCESS = [['none', 'ללא גישה'], ['limited', 'גישה מוגבלת'], ['full', 'גישה מלאה']];
const ACCESS_HE = Object.fromEntries(ACCESS);
const num = (n) => (n !== null && n !== undefined ? n : 'לא ידוע');

/** The inline result of one console query (the server already shaped it: table, answer, error or empty). */
export function resultView(result) {
  switch (result.kind) {
    case 'error': return h('div', { class: 'err' }, result.text);
    case 'table':
      if (!result.total) return h('p', { class: 'muted' }, 'השאילתה הושלמה ללא שורות.');
      return h('div', { class: 'result-table' }, h('table', null,
        h('tr', null, result.columns.map((c) => h('th', null, c))),
        result.rows.map((row) => h('tr', null, row.map((cell) => h('td', null, h('pre', null, cell)))))));
    case 'answer':
      return [h('div', { class: 'query-answer' }, result.text),
        result.entities.length ? h('p', { class: 'muted' }, `ישויות שנעשה בהן שימוש: ${result.entities.join(', ')}`) : null,
        result.evidence_ids.length ? h('p', { class: 'muted' }, `מקורות שאושרו ב־Jev: ${result.evidence_ids.join(', ')}`) : null];
    default: return h('p', { class: 'muted' }, 'עדיין אין תוצאה שמורה.');
  }
}

/** One console query as a card (the same facts as the classic result card). */
export function queryCard(q) {
  const ready = q.status === 'READY' || q.status === 'PASSED';
  const model = q.model_key === 'local' ? 'Graph RAG מקומי' : q.model_key || 'Neo4j';
  const [i, c, o] = q.tokens;
  return h('article', { class: `card graph-result ${ready ? 'ready' : q.status === 'FAILED' ? 'failed' : ''}` },
    h('div', { class: 'result-meta' }, h('b', null, `#${q.id}`), pill(q.status), h('span', null, q.mode === 'cypher' ? 'Cypher ישיר' : 'שפה חופשית'),
      h('span', { class: 'mono' }, model), h('span', null, `${q.elapsed_ms} מ״ש`), h('span', null, `טוקנים ${i}/${c}/${o}`),
      q.task_id ? [' · ', taskLink(q.task_id)] : null),
    h('div', { class: 'query-preview' }, q.query_text),
    q.generated_cypher ? details('Cypher שנוצר או בוצע', h('pre', null, q.generated_cypher)) : null,
    resultView(q.result));
}

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const meta = () => store.meta('rag');
  const sigs = {};
  let alive = true;

  const cypher = new Form(ctx, 'graph_console_query', { fixed: { query_mode: 'cypher' }, submit: 'הרץ Cypher לקריאה', cls: 'big go' });
  const natural = new Form(ctx, 'graph_console_query', { fixed: { query_mode: 'natural' }, submit: 'שאל עכשיו', cls: 'big go' });
  const healthButton = h('button', { type: 'button' }, 'הרץ בדיקת תקינות');
  healthButton.addEventListener('click', async () => {
    healthButton.disabled = true;
    try { await ctx.act('graph_rag_health', {}); await loadHealth(); } finally { healthButton.disabled = false; }
  });
  const config = new Form(ctx, 'save_graph_rag_config', { submit: 'שמור ובדוק חיבור', extraButtons: [healthButton], onResult: () => loadHealth() });
  const healthCounts = h('div', { class: 'counts' });
  const results = h('div');
  const accessBody = h('tbody');
  const historyBody = h('tbody');

  const cypherEl = cypher.build(
    cypher.area('query', { required: true, rows: 6, dir: 'ltr', cls: 'query ltr', placeholder: 'MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC LIMIT 25' }),
    cypher.area('parameters', { label: 'פרמטרים כאובייקט JSON (לא חובה)', rows: 2, dir: 'ltr', cls: 'params ltr', placeholder: '{"name": "Stalingrad"}' }),
    cypher.text('max_rows', { label: 'מספר שורות מרבי', type: 'number', min: 1, max: 200, value: '100' }));
  const naturalEl = natural.build(
    natural.area('query', { required: true, rows: 6, cls: 'query', placeholder: 'לדוגמה: אילו יחידות משוריינות מתועדות באזור סטלינגרד בינואר 1943, ומה רמת הביטחון של כל מקור?' }),
    natural.select('model_key', [['local', 'מקומי ומיידי']], { label: 'המודל שיענה', value: 'local' }));
  const configEl = config.build(
    config.text('graph_rag_url', { label: 'כתובת שירות Graph RAG', dir: 'ltr', cls: 'ltr' }),
    h('p', { class: 'muted' }, 'כתובת ה־API הציבורי של הגרף (HTTPS בלבד; כתובות מקומיות נחסמות).'),
    config.text('graph_cypher_url', { label: 'כתובת גשר Cypher לקריאה בלבד', dir: 'ltr', cls: 'ltr' }),
    h('p', { class: 'muted' }, 'קונסולת Cypher לקריאה בלבד; דורשת WW2_GRAPH_CONSOLE_KEY בסביבה. ה־API מאמת את השאילתה ומגביל זמן ושורות.'));

  setChildren(root,
    h('section', { class: 'control-hero' }, h('div', { class: 'eyebrow' }, 'ידע ושליפה'), h('h1', null, 'מרכז השליטה של גרף ה־RAG'),
      h('p', null, 'מתכנן המשימות מקבל גישה מלאה לגרף. לכל Deliver ניתן להגדיר ללא גישה, גישה מוגבלת או גישה מלאה. ' +
        'התוצאה אינה נכנסת ישירות לפרומפט: היא מפוצלת למועמדים ורק Jev רשאי לבחור מהם.')),
    healthCounts,
    h('section', null, h('h2', null, 'קונסולת שאילתות לגרף'),
      h('p', { class: 'muted' }, 'Cypher, המודל המקומי ו־Codex/Claude מתבצעים מיד ואינם נכנסים לתור המשימות.'),
      h('div', { class: 'graph-query-grid' },
        h('article', { class: 'graph-query-card cypher' }, h('h3', null, 'שאילתת Neo4j בשפת Cypher'),
          h('p', { class: 'muted' }, 'מבוצעת ישירות בגשר הקריאה בלבד. פעולות כתיבה, מחיקה, CALL וניהול חסומות לפני הביצוע.'), cypherEl),
        h('article', { class: 'graph-query-card' }, h('h3', null, 'שאלה חופשית דרך LLM'),
          h('p', { class: 'muted' }, 'כל מודל שנבחר רץ מיד. Codex או Claude מקבל רק מקורות ש־Jev בחר ומחזיר תשובה מנומקת באותה בקשה.'), naturalEl))),
    h('h2', null, 'תוצאות אחרונות'), results,
    h('div', { class: 'grid2' },
      h('div', null, h('h2', null, 'חיבור לשירות המקומי'), card(configEl)),
      h('div', null, h('h2', null, 'מה פירוש גישה מלאה למתכנן?'), card(h('b', null, 'חופש חיפוש, לא חופש ביצוע.'),
        ' המתכנן רשאי לחפש בכל הגרף בחיפוש וקטורי ובשאילתת Cypher כדי למצוא מועמדי קונטקסט. ' +
        'Jev עדיין בוחר אילו מקטעים נכנסים לפרומפט, ומגבלות המקטעים והתווים נשארות פעילות. ' +
        'ההרשאה אינה נותנת למתכנן גישה לסודות, ל־shell, לכתיבה בריפו או לעקיפת אישור משימות.'))),
    h('h2', null, 'הרשאות לפי Deliver'),
    card(table(['Deliver', 'תחום', 'אחראי', 'סוג', 'גישה', 'תחום מוגבל', 'מקטעים / תווים', 'ניהול'], accessBody)),
    h('h2', null, 'היסטוריית שאילתות'),
    card(table(['זמן', 'יעד', 'גישה', 'מועמדים / נבחרו', 'מצב', 'זמן'], historyBody)));

  // ------------------------------------------------------------------ sections
  function renderHealth(health) {
    setChildren(healthCounts, count('מצב השירות', health.status), count('צמתים', num(health.nodes)), count('קשרים', num(health.relationships)),
      count('מודל שליפה', health.model || 'לא זמין'));
  }

  async function loadHealth() {
    try {
      const health = await ctx.fetchJson('/api/rag/health');
      if (alive) renderHealth(health);
    } catch (e) { if (alive) renderHealth({ status: 'לא ידוע' }); }
  }

  function accessRow(r) {
    const form = new Form(ctx, 'save_deliver_graph_access', { fixed: { deliver_id: r.deliver_id }, submit: 'שמור הרשאת גרף' });
    const el = form.build(form.select('access_mode', ACCESS, { label: 'רמת גישה לגרף', value: r.access_mode }),
      form.text('scope_text', { label: 'תחום מותר בגישה מוגבלת', value: r.scope_text, placeholder: 'לדוגמה: טנקים, בליסטיקה, החזית המזרחית' }),
      form.text('max_chunks', { label: 'מספר מקטעים מרבי', type: 'number', min: 1, max: 50, value: String(r.max_chunks) }),
      form.text('max_chars', { label: 'מספר תווים מרבי', type: 'number', min: 500, max: 100000, value: String(r.max_chars) }),
      note('ההרשאה קובעת מה ניתן לשלוף. כל מקטע שנשלף נשאר מועמד עד ש־Jev בוחר בו במפורש.'));
    return h('tr', null, h('td', null, deliverLink(r.deliver_id)), h('td', null, r.domain || '—'), h('td', null, r.owner || '—'),
      h('td', null, r.execution_kind), h('td', null, ACCESS_HE[r.access_mode] || r.access_mode), h('td', null, r.scope_text || '—'),
      h('td', null, `${r.max_chunks} / ${r.max_chars}`), h('td', null, details('עריכת הרשאה', el)));
  }

  function render() {
    const m = meta();
    const queries = store.items('rag').sort((a, b) => b.id - a.id);
    syncList(results, queries, {
      key: (q) => q.id, sig: (q) => sig(q), build: queryCard,
      empty: () => h('div', { class: 'card muted' }, 'עדיין לא הורצו שאילתות מהקונסולה.'),
    });
    const key = sig(m.models);
    if (sigs.models !== key) {
      sigs.models = key;
      natural.setItems('model_key', [['local', 'מקומי ומיידי'], ...modelChoices(m.models)]);
    }
    config.setDefault('graph_rag_url', m.graph_rag_url || '');
    config.setDefault('graph_cypher_url', m.graph_cypher_url || '');
    syncList(accessBody, m.access || [], {
      key: (r) => r.deliver_id, sig: (r) => sig(r), build: accessRow, empty: emptyRow(8, 'אין Delivers פעילים'),
    });
    syncList(historyBody, m.history || [], {
      key: (r) => r.id, sig: (r) => r.id, empty: emptyRow(6, 'אין עדיין שאילתות'),
      build: (r) => h('tr', null, h('td', null, fmtTime(r.created_at)), h('td', { class: 'mono' }, r.scope_id), h('td', null, r.access_mode),
        h('td', null, `${r.candidate_count} / ${r.selected_count}`), h('td', null, r.status), h('td', null, `${r.latency_ms || 0} מ״ש`)),
    });
  }

  watch('rag', render);
  render();
  ctx.setTopics(['rag']);
  loadHealth();
  return () => { alive = false; stop(); };
}
