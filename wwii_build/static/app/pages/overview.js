// Overview page: status/counts, controls, "why is the run stuck", auto-approval, state chat, workers, approvals,
// quotas and tasks. The skeleton is built once; every topic update only touches its own section, and rows are
// reused when unchanged, so text typed into the chat box / a reject note is never lost.
import { frameBatch, h, setChildren, syncList } from '../dom.js';
import { COUNT_GROUPS, countTiles, fmtAgo, fmtRuntime, fmtTime, pageHash, quotaWindow, taskHash, weeklyUsed } from '../format.js';
import { pill, webBadge } from '../ui.js';
import { dependencyPanel, taskPanelLink } from '../task_views.js';

const BASE_TOPICS = ['overview', 'tasks.active', 'tasks.problems', 'workers', 'quota', 'approvals', 'unstick'];
const STATUS = {
  'EMERGENCY STOP': ['BLOCKED', 'עצירת חירום'],
  PAUSED: ['PAUSED', 'מושהה'],
  RUNNING: ['RUNNING', 'רץ'],
  'DAEMON NOT RUNNING': ['FAILED', 'הדמון לא רץ'],
};
const MODEL_CHOICE_KINDS = ['escalation', 'astra_recommended', 'repair_limit', 'architecture_review'];
const AUTOMATIC = 'אוטומטי: המודל המתאים ביותר';
const CONFIRM_STOP = 'עצירה: לא יתחילו משימות חדשות; עובדים רצים ייקטעו בעדינות והעבודה שלהם תישמר. להמשיך?';
const CONFIRM_INTERRUPT = 'להפסיק עכשיו את העובדים הרצים? העבודה נשארת ב־worktrees שלהם.';
const CONFIRM_KILL = 'לשלוח SIGKILL לכל העובדים מיד ולכבות את המתזמן?';

const sig = (...parts) => JSON.stringify(parts);
const emptyRow = (cols, text) => () => h('tr', { class: 'app-empty' }, h('td', { colspan: cols }, text));

export function mount(ctx) {
  const { store, root } = ctx;
  let models = {};
  let modelsSig = '';
  let chatTopic = null;
  let sending = false;
  const taskPanel = dependencyPanel(ctx);

  /** A button that confirms (when asked), runs one action over the socket and shows the result toast. */
  function actionButton(label, cls, name, args, confirmText, title) {
    const button = h('button', { type: 'button', class: cls, title }, label);
    button.addEventListener('click', async () => {
      if (confirmText && !window.confirm(confirmText)) return;
      button.disabled = true;
      try { await ctx.act(name, typeof args === 'function' ? args() : args); } finally { button.disabled = false; }
    });
    return button;
  }

  // ------------------------------------------------------------------ skeleton
  const head = h('div', { class: 'bar' });
  const counts = h('div', { class: 'counts' });
  const unstickBody = h('div');
  const unstickButton = actionButton('⟳ בדוק למה הריצה תקועה והמשך', 'big go', 'unstick', {});
  if (ctx.bindBusy) ctx.bindBusy(unstickButton, 'unstick');      // disabled while any unstick runs (also from the nav)
  const unstickCard = h('div', { class: 'card unstick' },
    h('div', { class: 'bar' }, h('h2', { style: 'margin:0' }, 'למה הריצה תקועה?'), unstickButton),
    unstickBody);
  const autoCard = h('div', { class: 'card' });

  const chatMessages = h('div');
  const chatInput = h('textarea', {
    class: 'state-chat-input w', rows: 3, name: 'message', 'aria-label': 'הודעה על המצב',
    placeholder: 'למשל: למה שום משימה לא רצה עכשיו?',
  });
  const chatModel = h('select', { name: 'model_key', 'aria-label': 'מודל לשיחה' });
  const chatSend = h('button', { type: 'button' }, 'שלח');
  const chatNew = h('div');
  const chatBox = h('div', { class: 'state-chat' }, chatMessages,
    chatInput, h('div', { class: 'planner-controls' }, chatModel, chatSend), chatNew);

  const workersBody = h('tbody');
  const approvalsBody = h('tbody');
  const quotaBody = h('tbody');
  const tasksBody = h('tbody');
  const problemsBody = h('div');
  const table = (cols, body) => h('table', null,
    h('thead', null, h('tr', null, cols.map((c) => h('th', null, c)))), body);

  setChildren(root,
    head,
    h('h2', null, 'סקירה'), counts, unstickCard, autoCard,
    h('h2', null, 'שיחה על המצב'), h('div', { class: 'card' }, chatBox),
    h('h2', null, 'עובדים פעילים'),
    h('div', { class: 'card' }, table(['משימה', 'ספק', 'מודל', 'זמן ריצה', 'PID', 'קונטקסט', 'worktree'], workersBody)),
    h('h2', null, 'מחכה לך'),
    h('div', { class: 'card' }, table(['#', 'משימה', 'סוג', 'נושא', 'סיבה', ''], approvalsBody)),
    h('h2', null, 'מכסות'),
    h('div', { class: 'card' }, table(['ספק', 'מצב', '5 שעות: שימוש', '5 שעות: איפוס', 'שבועי: שימוש', 'שבועי: איפוס',
      'חסום עד', 'עודכן', 'מקור', ''], quotaBody)),
    h('h2', null, 'פעילות וממתינות'),
    h('div', { class: 'card' }, table(['גל', 'משימה', 'אחראי', 'מצב', 'מודל', 'סיבה', 'שליטה'], tasksBody)),
    h('p', null, h('a', { class: 'btnlink', href: pageHash('tasks', { view: 'active' }) }, 'כל הפעילות והממתינות')),
    h('h2', null, 'נכשלו / נחסמו'), problemsBody,
    taskPanel.el,
    h('p', null, h('a', { href: '#/events' }, 'יומן אירועים'), ' · ', h('a', { href: '/api/state' }, 'api/state'),
      ' · ', h('a', { href: '/classic/' }, 'הסקירה הקלאסית (תוצרים, פערי יכולת ובדיקת מודלים)')));

  // ------------------------------------------------------------------ sections
  const overview = () => store.meta('overview');

  function renderHead() {
    const m = overview();
    const loaded = store.has('overview');
    const [cls, label] = STATUS[m.status] || ['UNKNOWN', loaded ? m.status : 'טוען…'];
    const signature = sig(loaded, m.paused, m.emergency_stop);
    const controls = head._controls || (head._controls = h('div'));
    if (controls._sig !== signature) {
      controls._sig = signature;
      const paused = m.paused && !m.emergency_stop;
      setChildren(controls,
        paused ? actionButton('המשך', 'big go', 'resume', {}) : actionButton('השהה', 'big pause', 'pause', {}), ' ',
        actionButton('עצור', 'big stop', 'stop', {}, CONFIRM_STOP), ' ',
        h('details', null, h('summary', null, 'מתקדם'), h('p', null,
          actionButton('השהה וקטע עובדים רצים', 'pause', 'pause_interrupt', {}, CONFIRM_INTERRUPT), ' ',
          actionButton('עצירת חירום מיידית', 'stop', 'kill', {}, CONFIRM_KILL), ' ',
          m.emergency_stop ? actionButton('נקה חירום והמשך', '', 'resume', { clear: true }) : null)));
    }
    const status = h('div', null, pill(cls, label), ` pid של הדמון ${m.daemon_pid || '-'} · גל `, h('b', null, m.wave ?? '-'),
      m.idle_reason ? ` · ${m.idle_reason}` : null,
      m.next_wakeup_at ? ` · התעוררות הבאה ${fmtTime(m.next_wakeup_at)}` : null);
    setChildren(head, h('div', null, h('h1', null, 'WWII Build Manager'), status), controls);
  }

  function renderCounts() {
    const history = new Set(['הושלמו', 'בוטלו']);
    const problems = new Set(['לבדיקה', 'חסומות', 'נכשלו']);
    const states = new Map(COUNT_GROUPS);
    setChildren(counts, countTiles(overview().counts).map(([label, n]) =>
      h('a', { class: 'count count-link', href: history.has(label) ? pageHash('tasks', { view: 'history', state: states.get(label)?.join(',') })
        : problems.has(label) ? pageHash('tasks', { view: 'problems', state: states.get(label)?.join(',') })
          : pageHash('tasks', { view: 'active', state: states.get(label)?.join(',') }) },
      h('span', { class: 'muted' }, label), h('b', null, n))));
  }

  function renderUnstick() {
    const report = store.meta('unstick').report;
    const list = (items) => h('ul', null, items.map((x) => h('li', null, x)));
    if (!report) {
      setChildren(unstickBody, h('p', { class: 'muted' },
        'לחיצה מאבחנת את המצב (מתזמן, השהיה, אישורים, המתנות, מכסות, תלויות שנכשלו, התנגשויות merge) ' +
        'ומבצעת את מה שאפשר כדי שהריצה תמשיך. כל פעולה נרשמת ביומן.'));
      return;
    }
    setChildren(unstickBody,
      h('p', { class: 'muted' }, `בדיקה אחרונה: ${fmtTime(report.at)}`),
      report.findings?.length ? [h('b', null, 'מה מצאתי'), list(report.findings)] : null,
      report.actions?.length ? [h('b', null, 'מה עשיתי'), list(report.actions)] : null,
      report.needs_you?.length ? [h('b', { style: 'color:var(--warn)' }, 'דורש החלטה שלך'), list(report.needs_you)] : null);
  }

  function renderAuto() {
    const m = overview();
    const on = !!m.review_auto_approve_all;
    const signature = sig(on, m.auto_max_per_task);
    if (autoCard._sig === signature) return;
    autoCard._sig = signature;
    autoCard.style.borderColor = on ? '#67d9bf' : '#ffd85a';
    setChildren(autoCard, h('div', { class: 'bar' }, h('div', null,
      h('h2', { style: 'margin:0' }, 'אישור אוטומטי לכל המשימות'),
      h('p', { class: 'muted' },
        (on ? 'פעיל: כל אישור מאושר אוטומטית — review, מודלים פרימיום (Opus/Astra), הצעות מתכנן, escalation, תיקונים וסקירות ארכיטקטורה.'
          : 'כבוי: אישורים ממתינים לך.') +
        ` כשל בבדיקות עדיין עוצר משימה; אישור שמוביל לסבב תיקון נוסף מאושר עד ${m.auto_max_per_task ?? 3} פעמים למשימה ` +
        'ואז נדחה אוטומטית — שום דבר לא מחכה לך; הכפתור \'למה תקוע? המשך\' מנסה שוב משימות שנתקעו. ' +
        'חיוב API ושימוש נוסף בתשלום לעולם לא מאושרים.')),
      actionButton(on ? 'כבה אישור אוטומטי' : 'הפעל אישור אוטומטי להכול', `big ${on ? 'bad' : 'go'}`,
        'set_auto_approve_all', { enabled: !on })));
  }

  function modelOptions() {
    return Object.entries(models).map(([key, m]) => [key, `${key} — ${m.provider} · ${m.model}`]);
  }

  function renderModels() {
    models = overview().models || {};
    const signature = JSON.stringify(models);
    if (signature === modelsSig) return;
    modelsSig = signature;
    const chosen = chatModel.value;
    setChildren(chatModel, h('option', { value: '' }, AUTOMATIC),
      modelOptions().map(([key, label]) => h('option', { value: key }, label)));
    chatModel.value = [...chatModel.options].some((o) => o.value === chosen) ? chosen : '';
    renderApprovals();
  }

  function renderWorkers() {
    const rows = store.items('workers').sort((a, b) => String(a.started_at).localeCompare(String(b.started_at)));
    syncList(workersBody, rows, {
      key: (w) => w.attempt_id,
      sig: (w) => sig(w),
      empty: emptyRow(7, 'אין עובדים שרצים כרגע'),
      build: (w) => h('tr', null,
        h('td', null, h('a', { href: taskHash(w.task_id) }, w.task_id)),
        h('td', null, w.provider), h('td', { class: 'mono' }, w.model),
        h('td', { dataset: { started: w.started_at || '' } }, fmtRuntime(w.started_at)),
        h('td', null, w.pid || '-'),
        h('td', null, w.context_bytes ? `${w.context_bytes} B` : 'לא ידוע'),
        h('td', { class: 'mono' }, w.worktree || '')),
    });
  }

  function renderApprovals() {
    const choices = modelOptions();
    syncList(approvalsBody, store.items('approvals').sort((a, b) => a.id - b.id), {
      key: (a) => a.id,
      sig: (a) => sig(a, modelsSig),
      empty: emptyRow(6, 'שום דבר לא מחכה לך'),
      build: (a) => {
        const modelSelect = MODEL_CHOICE_KINDS.includes(a.kind)
          ? h('select', { 'aria-label': 'מודל להמשך' }, h('option', { value: '' }, 'אותו מסלול'),
            choices.map(([key]) => h('option', { value: key }, key)))
          : null;
        const note = h('input', { type: 'text', class: 'inline-note', placeholder: 'הערה', 'aria-label': 'הערת דחייה' });
        const task = a.task_id
          ? [h('a', { href: taskHash(a.task_id) }, a.task_id),
            a.kind === 'plan_proposal' ? [' · ', h('a', { href: '#/plan' }, 'משימות מוצעות')] : null,
            ['review', 'architecture_review', 'repair_limit'].includes(a.kind)
              ? [h('br'), h('a', { class: 'btnlink', href: `/classic/review?id=${encodeURIComponent(a.task_id)}` }, 'צפה במה שנוצר')] : null]
          : '-';
        return h('tr', null, h('td', null, `#${a.id}`), h('td', null, task), h('td', null, a.kind),
          h('td', { class: 'mono' }, a.subject || ''), h('td', null, a.reason || ''),
          h('td', null,
            h('div', { class: 'ctl-row' }, modelSelect,
              actionButton('אשר', 'go', 'approve', () => ({ approval_id: a.id, model_key: modelSelect ? modelSelect.value : '' }))),
            h('div', { class: 'ctl-row' }, note,
              actionButton('דחה', '', 'reject', () => ({ approval_id: a.id, note: note.value })))));
      },
    });
  }

  function renderQuota() {
    const now = Date.now();
    syncList(quotaBody, store.items('quota'), {
      key: (q) => q.provider,
      sig: (q) => sig(q, quotaWindow(q.session_used_percent, q.session_reset_at, now),
        quotaWindow(weeklyUsed(q), q.weekly_reset_at, now)),
      empty: emptyRow(10, 'אין עדיין נתונים (לא ידוע)'),
      build: (q) => {
        const win = (used, reset) => {
          const w = quotaWindow(used, reset, now);
          return h('td', null, h('b', null, w.text), w.note ? [' ', h('span', { class: 'muted' }, `(${w.note})`)] : null);
        };
        const when = (iso) => h('td', null, iso ? fmtTime(iso) : 'לא ידוע');
        return h('tr', null, h('td', null, q.provider),
          h('td', null, pill(q.status), (q.notes || []).map((n) => [h('br'), h('small', { class: 'muted' }, n)])),
          win(q.session_used_percent, q.session_reset_at), when(q.session_reset_at),
          win(weeklyUsed(q), q.weekly_reset_at), when(q.weekly_reset_at),
          h('td', null, q.blocked_until ? fmtTime(q.blocked_until) : '-'),
          h('td', { dataset: { ago: q.data_at || q.last_checked_at || '' } }, fmtAgo(q.data_at || q.last_checked_at)),
          h('td', { class: 'muted' }, `${q.source || '-'} (${q.confidence})`),
          h('td', null,
            actionButton('רענן', '', 'refresh', { provider: q.provider }), ' ',
            actionButton('ביצעתי reset באפליקציה', 'go', 'reset_done', { provider: q.provider },
              `לאשר שביצעת reset של השימוש של ${q.provider} באפליקציה שלו? המנהל ינקה את חסימת המכסה של ${q.provider} ויבדוק שוב. ` +
              'המנהל עצמו לעולם לא מבצע reset ולא קונה.')));
      },
    });
  }

  function renderTasks() {
    syncList(tasksBody, store.items('tasks.active'), {
      key: (task) => task.task_id,
      sig: (task) => sig(task),
      empty: emptyRow(7, 'אין משימות'),
      build: (t) => {
        const priority = Number(t.dispatch_priority || 0);
        const reason = (t.wait_summary || '').slice(0, 240) + (t.repairs_count ? ` · תיקונים ${t.repairs_count}` : '') +
          (priority ? ` · עדיפות ${priority}` : '');
        return h('tr', null, h('td', null, t.wave),
          h('td', null, taskPanelLink(taskPanel, t.task_id), t.allow_web ? [' ', webBadge()] : null, h('br'),
            h('small', null, (t.description_he || '').slice(0, 240)),
            t.repairs?.length ? h('div', { class: 'nested-repairs' }, t.repairs.map((r) =>
              h('div', null, `↳ תיקון #${r.repair_no} · ${r.model || 'מודל לא ידוע'} `, pill(r.state)))) : null),
          h('td', null, t.owner), h('td', null, pill(t.state)), h('td', { class: 'mono' }, t.model || ''),
          h('td', null, reason),
          h('td', null, t.state === 'READY'
            ? [actionButton(priority ? 'דחוף שוב' : 'דחוף עכשיו', 'go', 'expedite', { task_id: t.task_id }), ' '] : null,
            h('a', { class: 'btnlink', href: taskHash(t.task_id) }, 'ניהול מודל, קונטקסט ותלויות')));
      },
    });
  }

  function renderProblems() {
    const items = store.items('tasks.problems').slice(0, 5);
    setChildren(problemsBody, h('div', { class: 'card overview-problems' },
      items.length ? items.map((t) => h('div', { class: 'problem-preview' }, taskPanelLink(taskPanel, t.task_id), ' ', pill(t.state),
        ` · ${t.reason?.summary || t.state_reason || ''}`)) : h('p', { class: 'muted' }, 'אין בעיות שעדיין דורשות טיפול.'),
      h('p', null, h('a', { class: 'btnlink', href: pageHash('tasks', { view: 'problems' }) },
        `פתח נכשלו / נחסמו (${overview().problem_count ?? store.items('tasks.problems').length})`))));
  }

  function renderChat() {
    const items = chatTopic ? store.items(chatTopic) : [];
    const bubbles = items.slice(-20).map((m) => h('div', { class: `chat-msg ${m.role}` },
      h('small', { class: 'muted' }, `${m.role === 'user' ? 'אתה' : `${m.model_key || ''} · ${m.model || ''}`} · ${fmtTime(m.created_at)}`),
      h('div', { style: 'white-space:pre-wrap' }, m.content)));
    if (sending) bubbles.push(h('div', { class: 'chat-msg assistant chat-wait' }, 'המודל חושב…'));
    setChildren(chatMessages, bubbles.length ? bubbles : h('p', { class: 'muted' },
      'שאל כל דבר על המצב: מה רץ, מה תקוע ולמה, מה לעשות עכשיו. התשובה מיידית, לקריאה בלבד, ולא נכנסת לתור המשימות.'));
    setChildren(chatNew, items.length ? actionButton('שיחה חדשה', '', 'state_chat_new', {}) : null);
    chatSend.disabled = sending;
  }

  async function sendChat() {
    const text = chatInput.value;
    if (!text.trim() || sending) return;
    sending = true;
    renderChat();
    const conv = overview().chat_conversation_id;
    const result = await ctx.act('state_chat', { message: text.trim(), model_key: chatModel.value, conversation_id: conv ?? '' });
    sending = false;
    if (result.ok && chatInput.value === text) chatInput.value = '';   // keep anything typed while the model answered
    renderChat();
  }
  chatSend.addEventListener('click', sendChat);
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendChat(); }
  });

  /** The overview names the current conversation; follow it with a chat:<id> subscription. */
  function followChat() {
    const id = overview().chat_conversation_id;
    const topic = id === null || id === undefined ? null : `chat:${id}`;
    if (topic === chatTopic) return;
    chatTopic = topic;
    ctx.setTopics(topic ? [...BASE_TOPICS, topic] : BASE_TOPICS);
    watch(topic, renderChat);
    renderChat();
  }

  // ------------------------------------------------------------------ wiring
  const watched = new Map();
  function watch(topic, fn) {
    if (!topic || watched.has(topic)) return;
    const run = frameBatch(fn);
    watched.set(topic, store.on(topic, run));
  }
  function onOverview() {
    renderHead(); renderCounts(); renderAuto(); renderModels(); followChat();
  }
  const sections = {
    overview: onOverview, 'tasks.active': renderTasks, 'tasks.problems': renderProblems, workers: renderWorkers, quota: renderQuota,
    approvals: renderApprovals, unstick: renderUnstick,
  };
  for (const [topic, fn] of Object.entries(sections)) watch(topic, fn);

  onOverview(); renderTasks(); renderProblems(); renderWorkers(); renderQuota(); renderApprovals(); renderUnstick(); renderChat();
  ctx.setTopics(BASE_TOPICS);

  // runtimes and "updated … ago" tick client-side; quota windows are re-evaluated every 30 seconds
  let ticks = 0;
  const timer = setInterval(() => {
    const now = Date.now();
    for (const cell of root.querySelectorAll('[data-started]')) {
      const text = fmtRuntime(cell.dataset.started, now);
      if (cell.textContent !== text) cell.textContent = text;
    }
    for (const cell of root.querySelectorAll('[data-ago]')) {
      const text = fmtAgo(cell.dataset.ago, now);
      if (cell.textContent !== text) cell.textContent = text;
    }
    if (++ticks % 30 === 0) renderQuota();
  }, 1000);

  return () => {
    clearInterval(timer);
    for (const off of watched.values()) off();
    watched.clear();
  };
}
