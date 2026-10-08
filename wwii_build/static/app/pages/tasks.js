// Active work, actionable problems, and paged history. Only active/problems
// are live topics; history is an explicit 50-row socket request.
import { h, setChildren } from '../dom.js';
import { fmtTime, pageHash } from '../format.js';
import { pill } from '../ui.js';
import { makeWatcher } from '../widgets.js';
import { dependencyPanel, taskPanelLink } from '../task_views.js';

const ACTIVE_TOPIC = 'tasks.active';
const PROBLEMS_TOPIC = 'tasks.problems';
const PROBLEM_STATES = new Set(['FAILED', 'BLOCKED', 'ESCALATION_REQUIRED', 'ARCHITECTURE_REVIEW_REQUIRED', 'REVIEW_REQUIRED']);

function button(ctx, label, name, args, cls = '', confirmText = '') {
  const el = h('button', { type: 'button', class: cls }, label);
  el.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (confirmText && !window.confirm(confirmText)) return;
    el.disabled = true;
    try { await ctx.act(name, args); } finally { el.disabled = false; }
  });
  return el;
}

function reasonView(reason) {
  if (!reason) return h('p', { class: 'muted' }, 'לא נשמר פירוט.');
  return h('div', { class: 'problem-reason' },
    h('p', null, reason.summary),
    reason.failed_checks?.length ? [h('h4', null, 'בדיקות קבלה שנכשלו'), reason.failed_checks.map((c) => h('details', null,
      h('summary', null, `${c.name}${c.exit_code === null ? '' : ` (exit ${c.exit_code})`}`), h('pre', null, c.output_tail || 'אין פלט שמור')))] : null,
    reason.last_attempt ? [h('h4', null, 'הניסיון האחרון'),
      h('p', null, `${reason.last_attempt.status} · ${reason.last_attempt.failure_class || ''} · exit ${reason.last_attempt.exit_code ?? 'לא ידוע'}`),
      reason.last_attempt.diagnosis ? h('pre', null, reason.last_attempt.diagnosis) : null,
      reason.last_attempt.stderr_tail ? h('pre', null, reason.last_attempt.stderr_tail) : null] : null,
    reason.repairs?.length ? [h('h4', null, 'שרשרת תיקונים'), h('ol', null, reason.repairs.map((r) => h('li', null,
      `תיקון #${r.repair_no} · ${r.model || 'מודל לא ידוע'} · ${r.failure_summary || ''} → ${r.outcome || r.state}`)))] : null,
    reason.approvals?.length ? [h('h4', null, 'אישורים והחלטות'), h('ul', null, reason.approvals.map((a) => h('li', null,
      `${a.kind} · ${a.status} · ${a.note || a.reason || ''}`)))] : null,
    reason.events?.length ? [h('h4', null, 'ניסיונות שחרור / preflight'), h('ul', null, reason.events.map((e) => h('li', null,
      `${e.event}: ${typeof e.detail === 'object' ? JSON.stringify(e.detail) : e.detail || ''}`)))] : null,
    reason.activation_preflight ? [h('h4', null, 'הפעלה / preflight'), h('pre', null, JSON.stringify(reason.activation_preflight, null, 2))] : null);
}

export function mount(ctx) {
  const { store, root } = ctx;
  const watcher = makeWatcher(store);
  const panel = dependencyPanel(ctx);
  const mode = ['active', 'problems', 'history'].includes(ctx.params.view) ? ctx.params.view : 'active';
  const body = h('div');
  const badge = store.items(PROBLEMS_TOPIC).length;
  const tabs = h('nav', { class: 'task-tabs' },
    h('a', { href: pageHash('tasks', { view: 'active' }), class: mode === 'active' ? 'active' : '' }, 'פעילות וממתינות'),
    h('a', { href: pageHash('tasks', { view: 'problems' }), class: `${mode === 'problems' ? 'active ' : ''}problem-tab` },
      'נכשלו / נחסמו ', h('span', { class: 'red-badge' }, badge)),
    h('a', { href: pageHash('tasks', { view: 'history' }), class: mode === 'history' ? 'active' : '' }, 'היסטוריה'));
  setChildren(root, h('h1', null, 'משימות'), tabs, body, panel.el);

  function refreshBadge() {
    const el = tabs.querySelector('.red-badge');
    if (el) el.textContent = String(store.items(PROBLEMS_TOPIC).length);
  }

  function activeView() {
    const requestedStates = new Set(String(ctx.params.state || '').split(',').filter(Boolean));
    const tasks = store.items(ACTIVE_TOPIC).filter((t) => !requestedStates.size || requestedStates.has(t.state));
    setChildren(body,
      h('p', { class: 'muted' }, 'מוצגות רק משימות שעדיין דורשות עבודה. לחיצה מציגה את עץ התלויות.'),
      h('div', { class: 'card task-list' }, tasks.length ? tasks.map((t) => h('article', { class: 'task-row' },
        h('div', null, taskPanelLink(panel, t.task_id), t.title ? ` — ${t.title}` : '', h('br'), h('small', null, t.description_he || '')),
        h('div', null, pill(t.state)), h('div', { class: 'mono' }, t.model || ''),
        h('div', null, t.wait_summary || ''),
        t.repairs?.length ? h('div', { class: 'nested-repairs' }, t.repairs.map((r) => h('div', null,
          `↳ תיקון #${r.repair_no} · ${r.model || 'מודל לא ידוע'} `, pill(r.state)))) : null))
        : h('p', { class: 'muted' }, 'אין כרגע פעילות או משימות ממתינות.')));
  }

  let allProblems = null;
  function renderProblems(items = allProblems || store.items(PROBLEMS_TOPIC)) {
    const requestedStates = new Set(String(ctx.params.state || '').split(',').filter(Boolean));
    items = items.filter((t) => !requestedStates.size || requestedStates.has(t.state));
    setChildren(body,
      h('label', { class: 'show-all' }, h('input', { type: 'checkbox', checked: allProblems !== null,
        onchange: async (event) => {
          if (!event.target.checked) { allProblems = null; renderProblems(); return; }
          const result = await ctx.request('search', { topic: 'tasks.problems', include_all: true });
          allProblems = result.ok ? result.items : [];
          renderProblems();
        } }), ' הצג הכול, כולל כשלים ישנים ותיקונים שההורה שלהם עבר'),
      h('p', { class: 'muted' }, 'ברירת המחדל מציגה רק בעיות משבעת הימים האחרונים שעדיין משפיעות על העבודה.'),
      h('div', { class: 'card problem-list' }, items.length ? items.map((t) => h('details', { class: 'problem-row' },
        h('summary', null, taskPanelLink(panel, t.task_id), ' ', pill(t.state), ` · ${t.reason?.summary || t.state_reason || ''}`),
        reasonView(t.reason), h('div', { class: 'ctl-row' },
          button(ctx, 'נסה שוב', 'retry', { task_id: t.task_id }),
          button(ctx, 'דלג', 'skip', { task_id: t.task_id }, '', `לבטל את ${t.task_id}? משימות שתלויות בה יישארו חסומות.`),
          h('a', { class: 'btnlink', href: `#/task?id=${encodeURIComponent(t.task_id)}` }, 'פתח משימה'),
          button(ctx, 'המשך', 'unstick', {}, 'go')))) : h('p', { class: 'muted' }, 'אין כשלים או חסימות שעדיין דורשים טיפול.')));
  }

  let historyPage = Number(ctx.params.page || 1) || 1;
  const controls = {};
  function historyView() {
    controls.query = h('input', { type: 'text', placeholder: 'חיפוש לפי מזהה, כותרת, הערה או סיבה', value: ctx.params.query || '' });
    controls.state = h('select', null, h('option', { value: '' }, 'כל המצבים'),
      [...PROBLEM_STATES, 'RUNNING', 'READY', 'PENDING', 'PASSED', 'CANCELLED', 'SKIPPED'].map((s) => h('option', { value: s }, s)));
    controls.state.value = ctx.params.state || '';
    controls.from = h('input', { type: 'date', value: ctx.params.date_from || '' });
    controls.to = h('input', { type: 'date', value: ctx.params.date_to || '' });
    controls.model = h('input', { type: 'text', placeholder: 'מודל', value: ctx.params.model || '' });
    controls.provider = h('input', { type: 'text', placeholder: 'ספק', value: ctx.params.provider || '' });
    controls.owner = h('input', { type: 'text', placeholder: 'owner', value: ctx.params.owner || '' });
    controls.failed = h('input', { type: 'checkbox', checked: ctx.params.has_failed === '1' });
    controls.results = h('div', { class: 'card' }, h('p', { class: 'muted' }, 'הקלידו חיפוש או הפעילו מסנן.'));
    const submit = h('button', { type: 'submit', class: 'go' }, 'חיפוש');
    const form = h('form', { class: 'history-filter', onsubmit: (event) => { event.preventDefault(); historyPage = 1; searchHistory(); } },
      controls.query, controls.state, controls.from, controls.to, controls.model, controls.provider, controls.owner,
      h('label', null, controls.failed, ' כולל כשל'), submit);
    setChildren(body, form, controls.results);
    searchHistory();
  }

  async function searchHistory() {
    setChildren(controls.results, h('p', { class: 'muted' }, 'מחפש…'));
    const filters = { state: controls.state.value, date_from: controls.from.value, date_to: controls.to.value,
      model: controls.model.value, provider: controls.provider.value, owner: controls.owner.value, has_failed: controls.failed.checked };
    const result = await ctx.request('search', { topic: 'tasks.history', query: controls.query.value, filters, page: historyPage });
    if (!result.ok) return setChildren(controls.results, h('p', { class: 'err' }, 'החיפוש נכשל.'));
    setChildren(controls.results,
      h('p', { class: 'muted' }, `${result.total} תוצאות · עמוד ${result.page} מתוך ${result.pages}`),
      result.items.length ? h('table', null,
        h('thead', null, h('tr', null, ['משימה', 'מצב', 'אחראי', 'מודל', 'עודכן'].map((x) => h('th', null, x)))),
        h('tbody', null, result.items.map((t) => h('tr', null, h('td', null, taskPanelLink(panel, t.task_id)),
          h('td', null, pill(t.state)), h('td', null, t.owner), h('td', { class: 'mono' }, t.model || ''), h('td', null, fmtTime(t.updated_at))))))
        : h('p', { class: 'muted' }, 'לא נמצאו משימות.'),
      h('div', { class: 'pager' },
        h('button', { type: 'button', disabled: result.page <= 1, onclick: () => { historyPage -= 1; searchHistory(); } }, 'הקודם'),
        h('button', { type: 'button', disabled: result.page >= result.pages, onclick: () => { historyPage += 1; searchHistory(); } }, 'הבא')));
  }

  if (mode === 'active') activeView();
  else if (mode === 'problems') renderProblems();
  else historyView();
  watcher.watch(ACTIVE_TOPIC, () => { if (mode === 'active') activeView(); });
  watcher.watch(PROBLEMS_TOPIC, () => { refreshBadge(); if (mode === 'problems' && allProblems === null) renderProblems(); });
  ctx.setTopics([ACTIVE_TOPIC, PROBLEMS_TOPIC]);
  return () => watcher.stop();
}
