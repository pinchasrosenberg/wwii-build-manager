// Task detail: state, attempts, approvals, repair chain, artifacts, dependencies, context access, subtasks and the
// task actions (retry / skip / recheck / change model / expedite). Topic: task:<id> (attempts as items, the rest in
// meta); the diff of the worktree is read from /api/task/diff when the task or its attempts change.
import { h, setChildren, syncList } from '../dom.js';
import { fmtTime, known, fmtTokens, parseDiff, pageHash } from '../format.js';
import { Form, actionButton } from '../forms.js';
import { subtaskForm } from '../subtask_form.js';
import { pill, stateLabel, webBadge } from '../ui.js';
import { artifactView, attemptLogs, backLink, card, details, emptyRow, makeWatcher, modelChoices, muted, note, sig, table, taskLink, deliverLink } from '../widgets.js';

const ACCESS = [['none', 'ללא גישה'], ['limited', 'גישה מוגבלת'], ['full', 'גישה מלאה']];
const CONFIRM_SKIP = 'לבטל את המשימה? המשימות התלויות בה יישארו חסומות.';
const str = (v) => (v === null || v === undefined ? '' : String(v));

/** One attempt as a line: provider, model, status, failure class, tokens and the reported cost. */
export function attemptLine(a) {
  return h('span', null, `${a.provider} `, h('span', { class: 'mono' }, a.model), ' ', pill(a.status), ` ${a.failure_class || ''} · טוקנים נכנסו/מטמון/יצאו ${fmtTokens(a)}`,
    a.reported_cost_usd !== null && a.reported_cost_usd !== undefined ? ` · עלות מדווחת $${Number(a.reported_cost_usd).toFixed(2)}` : null);
}

function checksLine(checks) {
  if (!checks.length) return muted('לא הורצה בדיקת קבלה');
  return checks.map((c) => [c.passed ? `✓ ${c.name}` : h('b', { class: 's-FAILED' }, `✗ ${c.name}`), ' ']);
}

/** The repair chain card(s): a repair task shows its parent, a parent task its executions and repairs in order. */
export function chainView(chain) {
  if (!chain) return null;
  if (chain.role === 'repair') {
    return [h('h2', null, 'תיקון של ', taskLink(chain.parent_task_id), ' ', pill(chain.parent_state)),
      card(`תיקון #${chain.repair_no} · סוג כשל `, h('b', null, chain.failure_class || ''), ` · פרופיל ${chain.model_profile}`, h('br'),
        chain.failure_summary || '',
        chain.violating_paths.length ? h('ul', null, chain.violating_paths.map((p) => h('li', { class: 'mono' }, p))) : null)];
  }
  const steps = chain.steps.map((s) => (s.type === 'execute'
    ? h('div', { class: 'step' }, h('b', null, `ביצוע מקורי #${s.attempt_no}`), ' — ', attemptLine(s.attempt), h('br'), 'קבלה: ', checksLine(s.checks))
    : h('div', { class: 'step' }, '↓', h('br'), h('b', null, taskLink(s.task_id, null), ` (תיקון #${s.repair_no})`), ' ', pill(s.state),
      ` — סיבה: ${s.failure_class || ''}: ${s.failure_summary || ''}`, h('br'),
      s.attempts.length ? s.attempts.map((a) => [attemptLine(a), h('br')]) : [muted('not started'), h('br')],
      'קבלה אחרי התיקון: ', checksLine(s.checks))));
  return [h('h2', null, 'שרשרת תיקונים'),
    card(`תיקונים ${chain.repairs_count} מתוך ${chain.budget} · סוג כשל אחרון `, h('b', null, chain.failure_class || '-'), ' · הורה ', pill(chain.state),
      h('div', { class: 'chain' }, steps))];
}

/** Subtask lineage of a task: the pattern it belongs to and the subtasks it spawned. */
export function lineageView(lineage) {
  if (!lineage.parents.length && !lineage.children.length) return h('p', { class: 'muted' }, 'עדיין אין קשרי פירוק שמורים למשימה הזו.');
  return h('div', { class: 'subtask-tree' },
    lineage.parents.map((p) => h('div', { class: 'subtask-node' }, 'תת־משימה של ', taskLink(p.parent_task_id),
      ` · שימוש ${p.reuse_count}/${p.promotion_threshold} · ${p.promotion_status}`,
      p.promoted_deliver_id ? [' · קוּדם ל־', deliverLink(p.promoted_deliver_id)] : null)),
    lineage.children.map((c) => h('div', { class: 'subtask-node' }, h('b', null, 'תת־משימה'), ' · ', c.task_id ? taskLink(c.task_id) : '—', ' ',
      c.state ? pill(c.state) : null, h('br'),
      h('small', null, `מודל ${c.model_key || 'אוטומטי'} · MCP ${c.mcp.join(', ') || 'ללא'} · כלים ${c.tools.join(', ') || 'ברירת מחדל'} · דפוס ${c.reuse_count}/${c.promotion_threshold}`))));
}

export function mount(ctx) {
  const { store, root } = ctx;
  const id = ctx.params.id || '';
  const topic = `task:${id}`;
  const { watch, stop } = makeWatcher(store);
  const meta = () => store.meta(topic);
  const sigs = {};
  let alive = true;
  let built = false;
  let diffKey = null;
  let ui = {};

  const body = h('div');
  setChildren(root, backLink('#/', '→ חזרה לתור המשימות'), body);

  /** Replace a form's option list only when it changed (an open dropdown must not be rebuilt under the user). */
  function items(form, name, list) {
    const key = sig(list);
    if (sigs[`${form.action}:${name}`] === key) return;
    sigs[`${form.action}:${name}`] = key;
    form.setItems(name, list);
  }

  function layout() {
    for (const key of Object.keys(sigs)) delete sigs[key];       // new forms: their option lists are filled again
    diffKey = null;
    const f = {
      change: new Form(ctx, 'set_provider', { fixed: { task_id: id }, submit: 'שמור מודל למשימה', cls: '', class: 'inline-control' }),
      scoped: new Form(ctx, 'scoped_plan', { fixed: { scope_kind: 'task', scope_id: id, prompt_mode: 'plan_build' }, submit: 'תכנן את השינוי', reset: true }),
      dependency: new Form(ctx, 'add_task_dependency', { fixed: { task_id: id }, submit: 'הוסף תלות לתור', cls: '' }),
      bind: new Form(ctx, 'bind_task_context', { fixed: { task_id: id }, submit: 'הוסף לרשימת המועמדים', cls: '' }),
      context: new Form(ctx, 'add_context', { fixed: { task_id: id }, submit: 'שמור כמועמד ל־Jev', reset: true }),
      graph: new Form(ctx, 'save_deliver_graph_access', { fixed: { deliver_id: id }, submit: 'שמור הרשאת גרף' }),
    };
    const sub = subtaskForm(ctx, { parentId: id });
    ui = { ...f, sub, form: f, hero: h('div'), approvals: h('div'), expedite: h('span'), system: h('div'), contextPlan: h('div'),
      chain: h('div'), deps: h('ul'), bindings: h('div', { class: 'access-list' }), lineage: h('div'), graphSection: h('div'),
      scope: h('div', { class: 'card mono' }), handoff: h('pre'), attempts: h('tbody'), artifacts: h('div'), tests: h('tbody'),
      files: h('div', { class: 'card mono' }), filesTitle: h('h2'), diff: h('div'), pack: h('div'), brief: h('pre') };

    const changeEl = f.change.build(f.change.select('model_key', [], { cls: null }));
    ui.reviewLink = h('a', { class: 'btnlink', href: `/classic/review?id=${encodeURIComponent(id)}` }, 'הצג מה נוצר');
    const actions = h('div', { class: 'form-actions' }, ui.reviewLink, h('a', { class: 'btnlink', href: pageHash('events', { task_id: id }) }, 'אירועי המשימה'), ui.expedite,
      actionButton(ctx, 'נסה שוב', '', 'retry', { task_id: id }),
      actionButton(ctx, 'בטל משימה', '', 'skip', { task_id: id }, CONFIRM_SKIP),
      actionButton(ctx, 'הרץ בדיקות קבלה מחדש', '', 'recheck', { task_id: id }), changeEl);
    ui.heroBox = h('section', { class: 'control-hero' }, ui.hero, ui.approvals, actions);

    const scopedEl = f.scoped.build(
      h('p', { class: 'muted' }, 'מתאים לשינוי מודל, הוספת תלות, שינוי גישה לקונטקסט, הוספת MCP או השלמת עבודה חסרה.'),
      f.scoped.area('prompt', { required: true, rows: 4, placeholder: 'תאר את השינוי הרצוי. המודל ישלים את הצעדים החסרים וישתמש בקונטקסט מינימלי שנבחר דרך Jev.' }),
      f.scoped.select('model_key', [['', 'בחירת מודל אוטומטית']], { cls: null }),
      f.scoped.text('mcp_servers', { placeholder: 'שרתי MCP, אם צריך' }));
    const depEl = f.dependency.build(f.dependency.select('depends_on', [], { label: 'משימה שחייבת להסתיים קודם', required: true }));
    const bindEl = f.bind.build(f.bind.select('source_key', [], { label: 'תן גישה למקור קיים מהגרף', required: true }),
      note('הגישה מוסיפה מועמד בלבד. Jev עדיין חייב לבחור בו לפני שיגיע למודל.'));
    const newCtxEl = f.context.build(f.context.text('source_key', { label: 'מפתח מקור', required: true, dir: 'ltr' }),
      f.context.text('title', { label: 'כותרת', required: true }), f.context.text('origin_ref', { label: 'הפניה לגרף או מקור' }),
      f.context.area('excerpt', { label: 'תוכן מוצע', rows: 6, required: true }));
    const graphEl = f.graph.build(h('div', { class: 'grid2' },
      h('div', null, f.graph.select('access_mode', ACCESS, { label: 'רמת גישה לגרף', value: 'none' }),
        f.graph.text('scope_text', { label: 'תחום מותר בגישה מוגבלת', placeholder: 'לדוגמה: טנקים, בליסטיקה, החזית המזרחית' })),
      h('div', null, f.graph.text('max_chunks', { label: 'מספר מקטעים מרבי', type: 'number', min: 1, max: 50, value: '6' }),
        f.graph.text('max_chars', { label: 'מספר תווים מרבי', type: 'number', min: 500, max: 100000, value: '6000' }))),
      note('ההרשאה קובעת מה ניתן לשלוף. כל מקטע שנשלף נשאר מועמד עד ש־Jev בוחר בו במפורש.'));
    setChildren(ui.graphSection, h('h2', null, 'גישה לגרף ה־RAG של ה־Deliver'), card(graphEl));

    setChildren(body, ui.heroBox, ui.system, ui.contextPlan,
      h('div', { class: 'card command-card' }, h('h2', null, 'בקש מהמודל לשנות את המשימה'), scopedEl), ui.chain,
      h('div', { class: 'control-grid' },
        h('div', null, h('h2', null, 'תלויות המשימה'), card(ui.deps, depEl)),
        h('div', null, h('h2', null, 'גישה לקונטקסט דרך Jev'), card(ui.bindings, bindEl,
          details('צור מקור קונטקסט חדש למשימה', newCtxEl)))),
      h('h2', null, 'פירוק לתת־משימות'),
      card(h('p', { class: 'muted' }, 'כל תת־משימה מקבלת חוזה עצמאי של מודל, קונטקסט וכלים, ונשמרת בלי להפוך ל־Deliver.'), ui.lineage,
        details('הוסף תת־משימה למשימה הזו', sub.el)),
      ui.graphSection,
      h('div', { class: 'grid2' }, h('div', null, h('h2', null, 'תחום כתיבה'), ui.scope),
        h('div', null, h('h2', null, 'העברת עבודה'), card(ui.handoff))),
      h('h2', null, 'ניסיונות ביצוע'),
      card(table(['מזהה', 'סוג', 'ספק', 'מודל', 'מצב', 'כשל', 'זמן', 'טוקנים נכנסו/מטמון/יצאו', 'עלות מדווחת', 'תהליך', 'לוגים'], ui.attempts)),
      h('h2', null, 'תוצרים'), card(ui.artifacts),
      h('h2', null, 'בדיקות'), card(table(['בדיקה', 'סוג', 'תוצאה', 'קוד יציאה', 'משך', 'פלט'], ui.tests)),
      ui.filesTitle, ui.files,
      details('הבדלים בקוד', card(ui.diff)),
      h('h2', null, 'הקונטקסט שנשלח בניסיון האחרון'), card(ui.pack),
      details('תדריך המשימה', card(ui.brief)));
    built = true;
  }

  // ------------------------------------------------------------------ sections
  function renderHero(m) {
    const t = m.task;
    const signature = sig(t.state, t.state_reason, m.description_he, t.packet, t.owner, t.domain, t.mode, t.model_profile, t.wave,
      t.attempts_count, t.failed_attempts, t.branch, !!m.system, !!m.allow_web);
    if (ui.heroSig !== signature) {
      ui.heroSig = signature;
      setChildren(ui.hero, h('div', { class: 'eyebrow' }, m.system ? 'תיקון מערכת ניהול המשימות' : 'ניהול משימה בתור'),
        h('h1', { class: 'mono' }, id), h('p', null, pill(t.state), m.allow_web ? [' ', webBadge()] : null, ` · ${t.state_reason || ''}`),
        h('div', { class: 'card' }, h('h2', null, 'מה המשימה עושה'), h('p', null, m.description_he)),
        h('p', { class: 'muted' }, `חבילה ${t.packet} · אחראי ${t.owner} · תחום ${t.domain || ''} · מצב עבודה ${t.mode} · פרופיל ${t.model_profile} · גל ${known(t.wave)} · ` +
          `ניסיונות ${t.attempts_count} (נכשלו ${t.failed_attempts}) · ענף `, h('span', { class: 'mono' }, t.branch || '-')));
    }
    const readyKey = t.state === 'READY';
    if (ui.readyKey !== readyKey) {
      ui.readyKey = readyKey;
      setChildren(ui.expedite, readyKey ? actionButton(ctx, 'דחוף עכשיו', 'go', 'expedite', { task_id: id }) : null);
    }
  }

  function renderApprovals(m) {
    const signature = sig(m.approvals);
    if (ui.approvalsSig === signature) return;
    ui.approvalsSig = signature;
    setChildren(ui.approvals, m.approvals.map((a) => h('p', null, pill('WAITING_APPROVAL'), ` #${a.id} ${a.kind} ${a.subject || ''}: ${a.reason || ''} `,
      actionButton(ctx, 'Approve', 'go', 'approve', { approval_id: a.id }), ' ',
      actionButton(ctx, 'Reject', '', 'reject', { approval_id: a.id }))));
  }

  function renderSystem(m) {
    const signature = sig(m.system);
    if (ui.systemSig === signature) return;
    ui.systemSig = signature;
    if (!m.system) { setChildren(ui.system); return; }
    setChildren(ui.system, h('div', { class: 'card', style: 'border-color:#ffd85a' }, h('h2', null, 'תיקון מערכת מוגן'),
      h('p', null, h('b', null, 'מצב הפצה:'), ` ${m.system.status || 'טרם הוכן release'} · קבצים בחבילה: ${m.system.changed_count}`),
      h('p', { class: 'muted' }, 'העבודה מתבצעת בצילום מבודד של מנהל המשימות. הפעלה מתרחשת רק אחרי כל בדיקות המערכת, בדיקת drift והתרוקנות העובדים הפעילים. ' +
        'הגרסה הקודמת נשמרת לגיבוי וה־daemon מופעל מחדש בחן.')));
  }

  function renderContextPlan(m) {
    const signature = sig(m.context_request, m.planned_files, m.bindings);
    if (ui.contextPlanSig === signature) return;
    ui.contextPlanSig = signature;
    if (!m.context_request) { setChildren(ui.contextPlan); return; }
    const sources = m.bindings.filter((b) => b.active);
    setChildren(ui.contextPlan, card(h('h2', null, 'בקשת הקונטקסט שתוכננה'), h('p', null, m.context_request),
      h('h3', null, 'קובצי Markdown שנבחרו'),
      h('ul', null, m.planned_files.length ? m.planned_files.map((p) => h('li', { class: 'mono' }, p)) : h('li', { class: 'muted' }, 'לא נבחר קובץ')),
      h('h3', null, 'מקורות גרף שנבחרו דרך Jev'),
      h('ul', null, sources.length ? sources.map((b) => h('li', null, h('b', null, b.title), ' · ', h('span', { class: 'mono' }, b.source_key), ` · ${b.origin_kind} · ${b.origin_ref}`))
        : h('li', { class: 'muted' }, 'לא נבחר מקור גרף')),
      note('המקורות יופיעו גם במניפסט הקונטקסט של כל ניסיון ביצוע.')));
  }

  function renderDeps(m) {
    syncList(ui.deps, m.deps, {
      key: (d) => d.task_id, sig: (d) => sig(d),
      empty: () => h('li', { class: 'muted' }, 'אין (משימת שורש)'),
      build: (d) => h('li', null, taskLink(d.task_id), ' ', d.state ? pill(d.state) : null),
    });
  }

  function renderBindings(m) {
    syncList(ui.bindings, m.bindings, {
      key: (b) => b.source_key, sig: (b) => sig(b),
      empty: () => muted('לא ניתנו הרשאות קונטקסט מפורשות. החיפוש עדיין יכול להציע מקורות גלובליים ל־Jev.'),
      build: (b) => h('div', { class: 'access-row' },
        h('div', null, h('b', null, b.title), h('br'), h('span', { class: 'mono' }, b.source_key), ' ', h('small', null, `${b.origin_kind} · ${b.origin_ref}`)),
        actionButton(ctx, b.active ? 'השבת גישה' : 'הפעל גישה', '', 'toggle_task_context', { task_id: id, source_key: b.source_key, enabled: !b.active })),
    });
  }

  function renderTables(m) {
    const attempts = store.items(topic).sort((a, b) => b.id - a.id);
    syncList(ui.attempts, attempts, {
      key: (a) => a.id, sig: (a) => sig(a), empty: emptyRow(11, 'עדיין לא היו ניסיונות ביצוע.'),
      build: (a) => h('tr', null, h('td', null, a.id), h('td', null, `${a.kind} #${a.attempt_no}`, a.web_enabled ? [' ', webBadge()] : null), h('td', null, a.provider),
        h('td', { class: 'mono' }, `${a.model} (${str(a.effort)})`), h('td', null, pill(a.status)), h('td', null, a.failure_class || ''),
        h('td', null, `${fmtTime(a.started_at)} → ${a.ended_at ? fmtTime(a.ended_at) : '…'}`), h('td', { class: 'mono' }, fmtTokens(a)),
        h('td', null, known(a.reported_cost_usd)), h('td', null, a.pid || '-'), h('td', null, attemptLogs(a.id))),
    });
    syncList(ui.artifacts, m.artifacts, {
      key: (a) => a.id, sig: (a) => sig(a), empty: () => muted('אין עדיין תוצרים'), build: artifactView,
    });
    syncList(ui.tests, m.tests, {
      key: (t) => `${t.name}|${t.kind}|${t.exit_code}|${t.duration_s}|${t.output_tail.length}`, sig: (t) => sig(t), empty: emptyRow(6, 'עדיין לא הורצו בדיקות'),
      build: (t) => h('tr', null, h('td', null, t.name), h('td', null, t.kind), h('td', null, t.passed ? 'pass' : h('b', { class: 's-FAILED' }, 'FAIL')),
        h('td', null, t.exit_code ?? ''), h('td', null, t.duration_s ?? ''), h('td', null, details('output', h('pre', null, t.output_tail)))),
    });
  }

  function renderPack(m) {
    const signature = sig(m.context_pack);
    if (ui.packSig === signature) return;
    ui.packSig = signature;
    const pack = m.context_pack;
    if (!pack) { setChildren(ui.pack, muted('עדיין לא נבנה קונטקסט')); return; }
    setChildren(ui.pack, h('p', { class: 'muted' }, `prompt ${pack.total_bytes} bytes, sha256 ${pack.sha}`),
      table(['מצב', 'שכבה', 'נתיב', 'בתים', 'סיבה'], h('tbody', null, pack.items.map((i) => h('tr', null, h('td', null, i.mode), h('td', null, i.layer),
        h('td', { class: 'mono' }, i.path), h('td', null, i.bytes), h('td', { class: 'muted' }, i.reason))))));
  }

  function renderDiff(data) {
    setChildren(ui.filesTitle, `קבצים שהשתנו (${data.files.length})`);
    setChildren(ui.files, data.files.length ? data.files.map((f, i) => [i ? h('br') : null, f]) : '-');
    setChildren(ui.diff, parseDiff(data.diff).map((b) => h('details', { class: 'hold' },
      h('summary', { class: 'mono' }, `${b.name} `, h('span', { class: 'add' }, `+${b.adds}`), ' ', h('span', { class: 'del' }, `-${b.dels}`)),
      h('pre', { class: 'diff' }, b.lines.map((l, i) => [i ? '\n' : null, l.cls ? h('span', { class: l.cls }, l.text) : l.text])))));
    if (!data.diff) setChildren(ui.diff, muted('אין הבדלים להצגה'));
  }

  async function loadDiff(m) {
    const key = sig(m.task.state, m.task.attempts_count, store.items(topic).length);
    if (key === diffKey) return;
    diffKey = key;
    try {
      const data = await ctx.fetchJson(`/api/task/diff?id=${encodeURIComponent(id)}`);
      if (alive) renderDiff(data);
    } catch (e) {
      if (alive) setChildren(ui.diff, h('p', { class: 'err' }, 'טעינת ההבדלים נכשלה'));
    }
  }

  function renderForms(m) {
    const f = ui.form;
    const models = modelChoices(m.models);
    items(f.change, 'model_key', models);
    f.change.setDefault('model_key', m.task.preferred_model_key || m.task.last_model_key || '');
    items(f.scoped, 'model_key', [['', 'בחירת מודל אוטומטית'], ...models]);
    items(f.dependency, 'depends_on', m.task_options.map((o) => [o.task_id, `${o.task_id} · ${stateLabel(o.state)}`]));
    items(f.bind, 'source_key', m.context_options.map((o) => [o.source_key, `${o.title} · ${o.source_key}`]));
    ui.sub.update({ models: m.models });
    ui.graphSection.hidden = !m.is_deliver;
    const access = m.graph_access || {};
    f.graph.setDefault('access_mode', access.access_mode || 'none');
    f.graph.setDefault('scope_text', str(access.scope_text));
    f.graph.setDefault('max_chunks', str(access.max_chunks ?? 6));
    f.graph.setDefault('max_chars', str(access.max_chars ?? 6000));
  }

  function render() {
    if (!store.has(topic)) { setChildren(body, h('p', { class: 'muted' }, 'טוען…')); built = false; return; }
    const m = meta();
    if (!m.exists) {
      built = false;
      setChildren(body, h('h1', null, 'משימה לא ידועה'), h('p', { class: 'muted mono' }, id));
      return;
    }
    if (!built) layout();
    renderHero(m);
    renderApprovals(m);
    renderSystem(m);
    renderContextPlan(m);
    setChildren(ui.chain, chainView(m.chain));
    renderDeps(m);
    renderBindings(m);
    setChildren(ui.lineage, lineageView(m.lineage));
    setChildren(ui.scope, m.task.write_scope.length ? m.task.write_scope.map((s, i) => [i ? h('br') : null, s]) : '-');
    setChildren(ui.handoff, m.handoff ? JSON.stringify(m.handoff, null, 1) : 'אין');
    setChildren(ui.brief, m.brief);
    renderTables(m);
    renderPack(m);
    renderForms(m);
    loadDiff(m);
  }

  watch(topic, render);
  render();
  ctx.setTopics([topic]);
  return () => { alive = false; stop(); };
}
