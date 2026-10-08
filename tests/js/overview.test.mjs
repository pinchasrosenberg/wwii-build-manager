// The overview page against the fake DOM. All data below is synthetic.
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';

import { Store } from '../../wwii_build/static/app/store.js';
import { buttonByText, byTag, findAll, installDom } from './fake_dom.mjs';

const NOW = Date.parse('2026-01-01T12:00:00Z');
let dom;
let realNow;

beforeEach(() => {
  dom = installDom();
  realNow = Date.now;
  Date.now = () => NOW;
});
afterEach(() => {
  Date.now = realNow;
  dom.uninstall();
});

const META = {
  status: 'RUNNING', daemon_pid: 4242, paused: false, emergency_stop: null, idle_reason: null, next_wakeup_at: null,
  review_auto_approve_all: false, auto_max_per_task: 3, wave: 2, task_total: 4, counts: { PASSED: 1, READY: 2, RUNNING: 1 },
  models: { sonnet: { provider: 'claude', model: 'claude-sonnet' }, codex: { provider: 'codex', model: 'gpt-x' } },
  chat_conversation_id: null,
};

function snapshot(store, topic, key, items, meta = {}, rev = 1) {
  store.applySnapshot({ type: 'snapshot', topic, rev, data: { key, items, meta } });
}

async function setup(overrides = {}) {
  const { mount } = await import('../../wwii_build/static/app/pages/overview.js');
  const store = new Store();
  const calls = [];
  const topics = [];
  let pending = null;
  const ctx = {
    store, root: document.createElement('div'), params: {},
    act: (name, args) => {
      calls.push([name, args]);
      return pending ? pending.promise : Promise.resolve({ ok: true, message: 'בוצע' });
    },
    setTopics: (t) => topics.push([...t]),
    ...overrides,
  };
  return {
    store, ctx, calls, topics,
    holdActions() {
      let resolve;
      pending = { promise: new Promise((r) => { resolve = r; }), resolve: (v) => { pending = null; resolve(v); } };
      return pending;
    },
    mount: () => mount(ctx),
    text: () => ctx.root.textContent,
  };
}

test('subscribes to the page topics and renders status, counts and controls from the overview topic', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  const unmount = t.mount();
  dom.flush();
  assert.deepEqual(t.topics[0], ['overview', 'tasks.active', 'tasks.problems', 'workers', 'quota', 'approvals', 'unstick']);
  const text = t.text();
  assert.match(text, /רץ/);
  assert.match(text, /pid של הדמון 4242/);
  assert.match(text, /גל 2/);
  const counts = findAll(t.ctx.root, (e) => String(e.className).includes('count')).map((c) => c.textContent);
  assert.ok(counts.includes('הושלמו1') && counts.includes('מוכנות2') && counts.includes('רצות1'), counts.join('|'));
  assert.ok(buttonByText(t.ctx.root, 'השהה') && buttonByText(t.ctx.root, 'עצור'));
  assert.ok(!buttonByText(t.ctx.root, 'המשך'));
  unmount();
});

test('pause/resume/stop use the same confirmations and actions', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  t.mount();
  dom.flush();
  buttonByText(t.ctx.root, 'השהה').click();
  await Promise.resolve();
  assert.deepEqual(t.calls.at(-1), ['pause', {}]);
  assert.equal(dom.confirms.asked.length, 0);
  dom.confirms.answer = false;
  buttonByText(t.ctx.root, 'עצור').click();
  assert.equal(t.calls.length, 1);                                  // declined: nothing sent
  assert.match(dom.confirms.asked[0], /עצירה: לא יתחילו משימות חדשות/);
  dom.confirms.answer = true;
  buttonByText(t.ctx.root, 'עצור').click();
  assert.deepEqual(t.calls.at(-1), ['stop', {}]);
  // paused -> the button becomes resume
  t.store.applyPatch({ topic: 'overview', rev: 2, upsert: [], remove: [], meta: { ...META, paused: true, status: 'PAUSED' } });
  dom.flush();
  assert.match(t.text(), /מושהה/);
  buttonByText(t.ctx.root, 'המשך').click();
  assert.deepEqual(t.calls.at(-1), ['resume', {}]);
  assert.ok(!buttonByText(t.ctx.root, 'השהה'));
  // emergency: the advanced section offers "clear emergency and resume"
  t.store.applyPatch({ topic: 'overview', rev: 3, upsert: [], remove: [], meta: { ...META, paused: true, emergency_stop: '2026-01-01', status: 'EMERGENCY STOP' } });
  dom.flush();
  assert.match(t.text(), /עצירת חירום/);
  buttonByText(t.ctx.root, 'נקה חירום והמשך').click();
  assert.deepEqual(t.calls.at(-1), ['resume', { clear: true }]);
  buttonByText(t.ctx.root, 'עצירת חירום מיידית').click();
  assert.deepEqual(t.calls.at(-1), ['kill', {}]);
  assert.match(dom.confirms.asked.at(-1), /SIGKILL/);
});

test('"why is the run stuck" card shows the last report and the button sends unstick', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  snapshot(t.store, 'unstick', null, [], { report: null });
  t.mount();
  dom.flush();
  assert.match(t.text(), /למה הריצה תקועה\?/);
  buttonByText(t.ctx.root, '⟳ בדוק למה הריצה תקועה והמשך').click();
  assert.deepEqual(t.calls.at(-1), ['unstick', {}]);
  t.store.applySnapshot({ topic: 'unstick', rev: 2, data: { key: null, items: [], meta: { report: {
    at: '2026-01-01T10:00:00+00:00', findings: ['המתזמן מושהה'], actions: ['שוחררה משימה'], needs_you: ['אשר תיקון'] } } } });
  dom.flush();
  assert.match(t.text(), /מה מצאתי/);
  assert.match(t.text(), /המתזמן מושהה/);
  assert.match(t.text(), /שוחררה משימה/);
  assert.match(t.text(), /דורש החלטה שלך/);
});

test('auto-approval card toggles with set_auto_approve_all', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  t.mount();
  dom.flush();
  assert.match(t.text(), /כבוי: אישורים ממתינים לך/);
  assert.match(t.text(), /עד 3 פעמים למשימה/);
  buttonByText(t.ctx.root, 'הפעל אישור אוטומטי להכול').click();
  assert.deepEqual(t.calls.at(-1), ['set_auto_approve_all', { enabled: true }]);
  t.store.applyPatch({ topic: 'overview', rev: 2, upsert: [], remove: [], meta: { ...META, review_auto_approve_all: true } });
  dom.flush();
  assert.match(t.text(), /פעיל: כל אישור מאושר אוטומטית/);
  buttonByText(t.ctx.root, 'כבה אישור אוטומטי').click();
  assert.deepEqual(t.calls.at(-1), ['set_auto_approve_all', { enabled: false }]);
});

test('workers table: runtime ticks every second without rebuilding the row', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  snapshot(t.store, 'workers', 'attempt_id', [{ attempt_id: 7, task_id: 'A/1', provider: 'codex', model: 'gpt-x', started_at: '2026-01-01T11:58:30+00:00',
    pid: 99, context_bytes: null, worktree: '/tmp/wt' }]);
  t.mount();
  dom.flush();
  const cell = () => findAll(t.ctx.root, (e) => 'started' in e.dataset)[0];
  assert.equal(cell().textContent, '0:01:30');
  const row = cell().parentNode;
  Date.now = () => NOW + 5000;
  dom.tick();
  assert.equal(cell().textContent, '0:01:35');
  assert.equal(cell().parentNode, row);
  assert.match(t.text(), /לא ידוע/);                               // unknown context size is not a number
  assert.equal(byTag(row, 'a')[0].attrs.href, '#/task?id=A%2F1');
  t.store.applyPatch({ topic: 'workers', rev: 2, upsert: [], remove: ['7'] });
  dom.flush();
  assert.match(t.text(), /אין עובדים שרצים כרגע/);
});

test('unmounting stops the ticker and the topic listeners', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  const unmount = t.mount();
  dom.flush();
  assert.equal(dom.intervals.size, 1);
  unmount();
  assert.equal(dom.intervals.size, 0);
  t.store.applyPatch({ topic: 'overview', rev: 2, upsert: [], remove: [], meta: { ...META, wave: 9 } });
  dom.flush();
  assert.doesNotMatch(t.text(), /גל 9/);
});

test('quotas: one row per provider with 5-hour and weekly windows; unknown stays unknown', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  snapshot(t.store, 'quota', 'provider', [
    { provider: 'codex', status: 'AVAILABLE', notes: ['מקור: synthetic'], session_used_percent: 40, session_reset_at: '2026-01-01T15:00:00+00:00',
      weekly_used_percent: 12.4, weekly_reset_at: '2026-01-05T00:00:00+00:00', used_percent: 40, blocked_until: null,
      data_at: '2026-01-01T11:59:00+00:00', last_checked_at: null, source: 'cli', confidence: 'high' },
    { provider: 'claude', status: 'UNKNOWN', notes: [], session_used_percent: 80, session_reset_at: '2026-01-01T09:00:00+00:00',
      weekly_used_percent: null, weekly_reset_at: null, used_percent: null, blocked_until: null,
      data_at: null, last_checked_at: null, source: null, confidence: 'none' },
  ]);
  t.mount();
  dom.flush();
  const rows = findAll(t.ctx.root, (e) => e.tagName === 'TR' && e.textContent.includes('synthetic') || e.tagName === 'TR' && e.textContent.startsWith('claude'));
  assert.equal(rows.length, 2);
  const [codex, claude] = rows;
  assert.match(codex.textContent, /40%/);
  assert.match(codex.textContent, /12%/);
  assert.match(codex.textContent, /מקור: synthetic/);
  assert.match(codex.textContent, /לפני 60 שנ׳/);
  assert.match(claude.textContent, /0%\s*\(אופס\)/);                  // 5-hour window already reset
  assert.match(claude.textContent, /לא ידוע/);                        // weekly unknown, never invented
  buttonByText(claude, 'רענן').click();
  assert.deepEqual(t.calls.at(-1), ['refresh', { provider: 'claude' }]);
  dom.confirms.answer = false;
  buttonByText(claude, 'ביצעתי reset באפליקציה').click();
  assert.equal(t.calls.length, 1);
  dom.confirms.answer = true;
  buttonByText(claude, 'ביצעתי reset באפליקציה').click();
  assert.deepEqual(t.calls.at(-1), ['reset_done', { provider: 'claude' }]);
});

test('approvals: approve/reject keep a typed note when other rows change', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  snapshot(t.store, 'approvals', 'id', [
    { id: 1, task_id: 'A/1', kind: 'escalation', subject: 'opus', reason: 'צריך מודל חזק' },
    { id: 2, task_id: 'B/2', kind: 'review', subject: '', reason: 'סקירה' },
  ]);
  t.mount();
  dom.flush();
  const rows = () => findAll(t.ctx.root, (e) => e.tagName === 'TR' && /^#\d/.test(e.textContent));
  const [first, second] = rows();
  assert.equal(byTag(first, 'select').length, 1);                   // escalation lets you pick a model
  assert.equal(byTag(second, 'select').length, 0);
  assert.deepEqual(byTag(first, 'option').map((o) => o.attrs.value), ['', 'sonnet', 'codex']);
  byTag(first, 'input')[0].value = 'לא עכשיו';
  byTag(first, 'select')[0].value = 'codex';
  assert.match(second.textContent, /צפה במה שנוצר/);
  t.store.applyPatch({ topic: 'approvals', rev: 2, upsert: [{ id: 2, task_id: 'B/2', kind: 'review', subject: '', reason: 'סקירה עודכנה' }], remove: [] });
  dom.flush();
  const [first2, second2] = rows();
  assert.equal(first2, first);                                      // untouched row is the same node
  assert.notEqual(second2, second);
  assert.equal(byTag(first2, 'input')[0].value, 'לא עכשיו');
  buttonByText(first2, 'דחה').click();
  assert.deepEqual(t.calls.at(-1), ['reject', { approval_id: 1, note: 'לא עכשיו' }]);
  buttonByText(first2, 'אשר').click();
  assert.deepEqual(t.calls.at(-1), ['approve', { approval_id: 1, model_key: 'codex' }]);
  buttonByText(second2, 'אשר').click();
  assert.deepEqual(t.calls.at(-1), ['approve', { approval_id: 2, model_key: '' }]);
  t.store.applyPatch({ topic: 'approvals', rev: 3, upsert: [], remove: ['1', '2'] });
  dom.flush();
  assert.match(t.text(), /שום דבר לא מחכה לך/);
});

test('active tasks table: ordered, repairs nested, expedite only for READY', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  const task = (task_id, wave, state, extra = {}) => ({ task_id, wave, state, kind: 'plan', owner: 'o', last_model_key: 'sonnet',
    state_reason: 'סיבה', description_he: `תיאור ${task_id}`, repairs_count: 0, dispatch_priority: 0, ...extra });
  snapshot(t.store, 'tasks.active', 'task_id', [
    task('X/run', 1, 'RUNNING', { repairs_count: 1, model: 'sonnet', repairs: [
      task('X/run/r1', 1, 'FAILED', { kind: 'repair', parent_task_id: 'X/run', repair_no: 1, failure_class: 'tests', model: 'sol' })] }),
    task('R/ready', 1, 'READY', { dispatch_priority: 2, model: 'sonnet' }),
  ]);
  t.mount();
  dom.flush();
  const ids = findAll(t.ctx.root, (e) => e.tagName === 'A' && e.attrs.href?.startsWith('#/task?id=') && e.textContent !== 'ניהול מודל, קונטקסט ותלויות')
    .map((a) => a.textContent);
  assert.deepEqual(ids, ['X/run', 'R/ready']);
  assert.match(t.text(), /תיקונים 1/);
  assert.match(t.text(), /עדיפות 2/);
  assert.equal(findAll(t.ctx.root, (e) => e.tagName === 'BUTTON' && e.textContent.startsWith('דחוף')).length, 1);
  buttonByText(t.ctx.root, 'דחוף שוב').click();
  assert.deepEqual(t.calls.at(-1), ['expedite', { task_id: 'R/ready' }]);
});

test('state chat: model select, send, keeps what was typed meanwhile, follows the conversation topic', async () => {
  const t = await setup();
  snapshot(t.store, 'overview', null, [], META);
  t.mount();
  dom.flush();
  const root = t.ctx.root;
  const textarea = byTag(root, 'textarea')[0];
  const select = findAll(root, (e) => e.tagName === 'SELECT' && e.attrs['aria-label'] === 'מודל לשיחה')[0];
  assert.deepEqual(select.options.map((o) => [o.attrs.value, o.textContent]), [
    ['', 'אוטומטי: המודל המתאים ביותר'], ['sonnet', 'sonnet — claude · claude-sonnet'], ['codex', 'codex — codex · gpt-x']]);
  assert.match(t.text(), /שאל כל דבר על המצב/);

  // empty message: nothing is sent
  buttonByText(root, 'שלח').click();
  assert.equal(t.calls.length, 0);

  // a long answer: text typed while waiting survives, and the first text is cleared only when unchanged
  textarea.value = 'למה שום דבר לא רץ?';
  select.value = 'sonnet';
  const held = t.holdActions();
  buttonByText(root, 'שלח').click();
  assert.deepEqual(t.calls.at(-1), ['state_chat', { message: 'למה שום דבר לא רץ?', model_key: 'sonnet', conversation_id: '' }]);
  assert.ok(buttonByText(root, 'שלח').disabled);
  assert.match(t.text(), /המודל חושב…/);
  textarea.value = 'למה שום דבר לא רץ? ועוד שאלה';
  held.resolve({ ok: true, message: 'תשובה התקבלה' });
  await new Promise((r) => setImmediate(r));
  assert.equal(textarea.value, 'למה שום דבר לא רץ? ועוד שאלה');
  assert.ok(!buttonByText(root, 'שלח').disabled);
  assert.doesNotMatch(t.text(), /המודל חושב…/);

  // the overview names the conversation -> subscribe to chat:<id>, render its messages
  t.store.applyPatch({ topic: 'overview', rev: 2, upsert: [], remove: [], meta: { ...META, chat_conversation_id: 5 } });
  dom.flush();
  assert.deepEqual(t.topics.at(-1), ['overview', 'tasks.active', 'tasks.problems', 'workers', 'quota', 'approvals', 'unstick', 'chat:5']);
  snapshot(t.store, 'chat:5', 'id', [
    { id: 1, role: 'user', content: 'שאלה קודמת', model_key: null, model: null, created_at: '2026-01-01T10:00:00+00:00' },
    { id: 2, role: 'assistant', content: 'התשובה <b>לא</b> HTML', model_key: 'sonnet', model: 'claude-sonnet', created_at: '2026-01-01T10:00:05+00:00' },
  ]);
  dom.flush();
  assert.match(t.text(), /אתה/);
  assert.match(t.text(), /התשובה <b>לא<\/b> HTML/);                  // text, never markup
  assert.equal(textarea.value, 'למה שום דבר לא רץ? ועוד שאלה');
  textarea.value = 'המשך';
  buttonByText(root, 'שלח').click();
  assert.deepEqual(t.calls.at(-1), ['state_chat', { message: 'המשך', model_key: 'sonnet', conversation_id: 5 }]);
  await new Promise((r) => setImmediate(r));
  assert.equal(textarea.value, '');                                  // answered with nothing typed meanwhile
  // streaming patch
  t.store.applyPatch({ topic: 'chat:5', rev: 2, upsert: [{ id: 3, role: 'assistant', content: 'עוד תשובה', model_key: 'sonnet', model: 'm', created_at: '2026-01-01T10:01:00+00:00' }], remove: [] });
  dom.flush();
  assert.match(t.text(), /עוד תשובה/);
  buttonByText(root, 'שיחה חדשה').click();
  assert.deepEqual(t.calls.at(-1), ['state_chat_new', {}]);
  t.store.applyPatch({ topic: 'overview', rev: 3, upsert: [], remove: [], meta: { ...META, chat_conversation_id: null } });
  dom.flush();
  assert.match(t.text(), /שאל כל דבר על המצב/);
});

test('a failed chat action keeps the message; ctrl+enter sends', async () => {
  const t = await setup({ act: async () => ({ ok: false, message: 'error: המודל לא זמין' }) });
  snapshot(t.store, 'overview', null, [], META);
  t.mount();
  dom.flush();
  const textarea = byTag(t.ctx.root, 'textarea')[0];
  textarea.value = 'שלום';
  textarea.fire('keydown', { key: 'Enter', ctrlKey: true });
  await new Promise((r) => setImmediate(r));
  assert.equal(textarea.value, 'שלום');
  assert.ok(!buttonByText(t.ctx.root, 'שלח').disabled);
});

test('renders safely before any snapshot arrived', async () => {
  const t = await setup();
  t.mount();
  dom.flush();
  assert.match(t.text(), /טוען…/);
  assert.match(t.text(), /אין עובדים שרצים כרגע/);
  assert.match(t.text(), /שום דבר לא מחכה לך/);
});
