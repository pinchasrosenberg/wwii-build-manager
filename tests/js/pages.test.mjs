// The pages of task 4 (task, events, rag, plan, new, subtasks), the router table and the new format helpers, against the
// fake DOM. All data below is synthetic.
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';

import { createdTarget, eventDetailText, eventMatches, eventsQuery, fmtTokens, pageHash, parseDiff, reusePercent } from '../../wwii_build/static/app/format.js';
import { NAV, PAGES, activeNav } from '../../wwii_build/static/app/router.js';
import { Store } from '../../wwii_build/static/app/store.js';
import { buttonByText, byTag, findAll, installDom } from './fake_dom.mjs';

let dom;
beforeEach(() => { dom = installDom(); });
afterEach(() => { dom.uninstall(); delete globalThis.location; });

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const snapshot = (store, topic, key, items, meta = {}, rev = 1) => store.applySnapshot({ type: 'snapshot', topic, rev, data: { key, items, meta } });
const MODELS = { sonnet: { provider: 'claude', model: 'claude-sonnet' }, codex: { provider: 'codex', model: 'gpt-x' } };

async function setup(page, { params = {}, fetchJson, request } = {}) {
  const { mount } = await import(`../../wwii_build/static/app/pages/${page}.js`);
  const store = new Store();
  const calls = [];
  const uploads = [];
  const toasts = [];
  const topics = [];
  const fetched = [];
  const requests = [];
  const ctx = {
    store, root: document.createElement('div'), params,
    act: async (name, args) => { calls.push([name, args]); return { ok: true, message: 'בוצע' }; },
    upload: async (name, args, files) => { uploads.push([name, args, files]); return { ok: true, message: 'הועלה' }; },
    fetchJson: async (url) => { fetched.push(url); return fetchJson ? fetchJson(url) : {}; },
    toast: (message, ok) => toasts.push([message, ok]),
    request: async (type, payload) => { requests.push([type, payload]); return request ? request(type, payload) : { ok: false }; },
    setTopics: (t) => topics.push([...t]),
  };
  return { store, ctx, calls, uploads, toasts, topics, fetched, requests, mount: () => mount(ctx), text: () => ctx.root.textContent };
}

const formWith = (root, ...names) => findAll(root, (e) => e.tagName === 'FORM'
  && names.every((n) => findAll(e, (c) => c.attrs.name === n).length > 0))[0];
const field = (form, name) => findAll(form, (c) => c.attrs.name === name)[0];
const fill = (form, values) => { for (const [k, v] of Object.entries(values)) field(form, k).value = v; };
const submit = async (form) => { form.fire('submit'); await settle(); };

// ---------------------------------------------------------------------------------------------------- helpers
test('router: every page is registered, the nav only points at pages, tasks and Delivers keep their nav entry lit', () => {
  for (const name of ['overview', 'tasks', 'delivers', 'deliver', 'task', 'events', 'rag', 'plan', 'new', 'battle', 'subtasks']) assert.ok(PAGES[name], name);
  for (const [route] of NAV) assert.ok(PAGES[route], route);
  assert.deepEqual(NAV.map(([r]) => r), ['overview', 'tasks', 'delivers', 'subtasks', 'rag', 'new', 'battle', 'plan', 'events']);
  assert.equal(activeNav('task'), 'tasks');
  assert.equal(activeNav('deliver'), 'delivers');
  assert.equal(activeNav('events'), 'events');
  assert.equal(activeNav('nope'), null);
});

test('pageHash, createdTarget and reusePercent', () => {
  assert.equal(pageHash('events', { task_id: 'A/1', search: '' }), '#/events?task_id=A%2F1');
  assert.equal(pageHash('plan'), '#/plan');
  assert.equal(createdTarget('created MANUAL/x-1'), '#/task?id=MANUAL%2Fx-1');
  assert.equal(createdTarget('context plan queued PLAN/7'), '#/plan');
  assert.equal(createdTarget('error: nope'), null);
  assert.equal(reusePercent(1, 3), 33);
  assert.equal(reusePercent(5, 3), 100);
  assert.equal(reusePercent(1, 0), 100);
});

test('task views use bounded topics and open the server-built dependency panel on click', async () => {
  const t = await setup('tasks', { params: { view: 'active' }, request: async (type, payload) => ({
    ok: true, detail: { exists: true, task_id: payload.task_id, task: { state: 'WAITING_DEPENDENCY', model: 'sol', reason: 'ממתינה' },
      prerequisites: [{ task_id: 'dep', state: 'FAILED', model: 'sonnet', reason: 'synthetic failure', blocking: true,
        blocking_root: true, missing: false, cycle: false, children: [] }], blocking_roots: ['dep'], dependents: [], downstream_more: 0 },
  }) });
  snapshot(t.store, 'tasks.active', 'task_id', [{ task_id: 'A/1', state: 'WAITING_DEPENDENCY', model: 'sol', owner: 'o',
    wait_summary: 'ממתינה ל־dep', repairs: [], description_he: 'synthetic' }]);
  snapshot(t.store, 'tasks.problems', 'task_id', []);
  t.mount();
  dom.flush();
  assert.deepEqual(t.topics[0], ['tasks.active', 'tasks.problems']);
  const link = findAll(t.ctx.root, (e) => e.tagName === 'A' && e.textContent === 'A/1')[0];
  link.click();
  await settle();
  assert.deepEqual(t.requests[0], ['task.detail', { task_id: 'A/1' }]);
  assert.match(t.text(), /החסימה המדויקת: dep/);
  assert.match(t.text(), /synthetic failure/);
});

test('unknown token counts are shown as unknown, not as zero', () => {
  assert.equal(fmtTokens({ input_tokens: 5, cached_input_tokens: null, output_tokens: 2 }), '5 / לא ידוע / 2');
});

test('event filters match like the journal query (case-insensitive search over event, task, provider, detail)', () => {
  const e = { id: 1, event: 'TASK_PASSED', task_id: 'A/1', provider: 'codex', detail: { note: 'Hello World' } };
  assert.ok(eventMatches(e, {}));
  assert.ok(eventMatches(e, { task_id: 'A/1', provider: 'codex', event: 'TASK_PASSED', search: 'hello' }));
  assert.ok(!eventMatches(e, { task_id: 'A/2' }));
  assert.ok(!eventMatches(e, { provider: 'claude' }));
  assert.ok(!eventMatches(e, { event: 'X' }));
  assert.ok(!eventMatches(e, { search: 'absent' }));
  assert.ok(eventMatches({ id: 2, event: 'E', detail: null }, { search: 'e' }));
  assert.equal(eventsQuery({ search: 'a b', event: '', provider: 'codex', task_id: '' }, { before: 40, limit: 50 }),
    'limit=50&search=a+b&provider=codex&before_id=40');
  assert.equal(eventDetailText({ a: 1 }), '{\n  "a": 1\n}');
  assert.equal(eventDetailText('x'.repeat(5000)).length, 3000);
  assert.equal(eventDetailText(null), '');
});

test('parseDiff splits per file and counts additions and deletions', () => {
  const blocks = parseDiff('summary line\ndiff --git a/x.py b/x.py\nindex 1..2\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n+more\ndiff --git a/y b/y\n+z');
  assert.deepEqual(blocks.map((b) => [b.name, b.adds, b.dels]), [['summary', 0, 0], ['x.py', 2, 1], ['y', 1, 0]]);
  assert.deepEqual(blocks[1].lines.map((l) => l.cls), ['meta', 'meta', 'meta', 'meta', 'hunk', 'del', 'add', 'add']);
  assert.deepEqual(parseDiff(''), []);
});

// ---------------------------------------------------------------------------------------------------- subtasks
const PATTERN = (over = {}) => ({ pattern_hash: 'a'.repeat(64), title: 'בדיקת יחידה', spec: { instructions: 'הרץ בדיקות', model_key: 'sonnet', owner: 'qa', context_files: ['a.md'], mcp_servers: [], tool_names: ['Read'] },
  reuse_count: 3, promotion_threshold: 3, promotion_status: 'eligible', promoted_deliver_id: null, suggestion: 'reusable.bdikat.yehida',
  occurrences: [{ parent_task_id: 'P/1', child_task_id: 'P/1-sub', source: 'dashboard' }], ...over });

test('subtasks: counts, pattern cards, create form and promotion of an eligible pattern', async () => {
  const t = await setup('subtasks');
  snapshot(t.store, 'subtasks', 'pattern_hash', [PATTERN(), PATTERN({ pattern_hash: 'b'.repeat(64), title: 'דפוס שקודם', promotion_status: 'promoted', promoted_deliver_id: 'reusable.x' })],
    { parents: [{ task_id: 'P/1', title: 'אב', note: '' }], models: MODELS, default_threshold: 3 });
  const unmount = t.mount();
  dom.flush();
  assert.deepEqual(t.topics[0], ['subtasks']);
  const counts = findAll(t.ctx.root, (e) => e.className === 'count').map((c) => c.textContent);
  assert.ok(counts.some((c) => c.includes('דפוסים שנלמדו') && c.endsWith('2')), counts.join('|'));
  assert.ok(counts.some((c) => c.includes('ממתינים להחלטת קידום') && c.endsWith('1')));
  assert.match(t.text(), /3 שימושים בפועל מתוך 3 שנדרשים לקידום/);
  assert.match(t.text(), /ל־reusable\.x/);

  const create = formWith(t.ctx.root, 'parent_task_id', 'instructions');
  assert.equal(field(create, 'parent_task_id').value, 'P/1');
  assert.equal(field(create, 'fallback').checked, true);
  fill(create, { title: 'בדיקות', instructions: 'עשה', write_scope: 'a/\nb/', mcp_servers: 'x, y' });
  field(create, 'read_only').checked = true;
  await submit(create);
  const [name, args] = t.calls.at(-1);
  assert.equal(name, 'create_subtask');
  assert.equal(args.parent_task_id, 'P/1');
  assert.equal(args.title, 'בדיקות');
  assert.equal(args.write_scope, 'a/\nb/');
  assert.equal(args.read_only, true);
  assert.equal(args.fallback, true);
  assert.equal(args.model_key, '');

  const promote = formWith(t.ctx.root, 'deliver_id', 'domain');
  assert.equal(field(promote, 'deliver_id').value, 'reusable.bdikat.yehida');
  assert.equal(field(promote, 'owner').value, 'qa');
  await submit(promote);
  assert.deepEqual(t.calls.at(-1), ['promote_subtask', { pattern_hash: 'a'.repeat(64), deliver_id: 'reusable.bdikat.yehida', owner: 'qa', domain: '', description: 'בדיקת יחידה' }]);
  unmount();
});

test('subtasks: an empty store shows the empty state', async () => {
  const t = await setup('subtasks');
  t.mount();
  dom.flush();
  assert.match(t.text(), /עדיין אין דפוסי שימוש/);
  assert.equal(formWith(t.ctx.root, 'deliver_id', 'domain'), undefined);
});

// ---------------------------------------------------------------------------------------------------- rag
test('rag: Cypher and natural queries are actions; results are shown inline; health comes from /api/rag/health', async () => {
  const t = await setup('rag', { fetchJson: async () => ({ status: 'OK', nodes: 12, relationships: null, model: 'local-m' }) });
  snapshot(t.store, 'rag', 'id', [
    { id: 2, status: 'READY', mode: 'cypher', model_key: null, query_text: 'MATCH (n) RETURN n', task_id: null, elapsed_ms: 5, generated_cypher: 'MATCH (n) RETURN n', tokens: [0, 0, 0], created_at: '2026-01-01T00:00:00+00:00',
      result: { kind: 'table', columns: ['n'], rows: [['1'], ['2']], total: 2 } },
    { id: 1, status: 'READY', mode: 'natural', model_key: 'local', query_text: 'שאלה', task_id: null, elapsed_ms: 9, generated_cypher: '', tokens: [1, 2, 3], created_at: '2026-01-01T00:00:00+00:00',
      result: { kind: 'answer', text: 'התשובה היא 42', entities: ['סטלינגרד'], evidence_ids: ['s1'] } },
    { id: 3, status: 'FAILED', mode: 'cypher', model_key: null, query_text: 'bad', task_id: null, elapsed_ms: 0, generated_cypher: '', tokens: [0, 0, 0], created_at: '2026-01-01T00:00:00+00:00',
      result: { kind: 'error', text: 'נחסם' } },
  ], { access: [{ deliver_id: 'weather.x', owner: 'o', domain: 'd', execution_kind: 'worker', access_mode: 'limited', scope_text: 'טנקים', max_chunks: 6, max_chars: 6000 }],
    history: [{ id: 1, created_at: '2026-01-01T00:00:00+00:00', scope_id: 'planner', access_mode: 'full', candidate_count: 5, selected_count: 2, status: 'OK', latency_ms: 30 }],
    models: MODELS, graph_rag_url: 'https://ww2-atlas-api.example.workers.dev', graph_cypher_url: 'https://ww2-atlas-api.example.workers.dev' });
  const unmount = t.mount();
  dom.flush();
  await settle();
  assert.deepEqual(t.topics[0], ['rag']);
  assert.deepEqual(t.fetched, ['/api/rag/health']);
  const text = t.text();
  assert.match(text, /מצב השירות\s*OK/);
  assert.match(text, /קשרים\s*לא ידוע/);                       // null is unknown, not zero
  assert.match(text, /התשובה היא 42/);
  assert.match(text, /ישויות שנעשה בהן שימוש: סטלינגרד/);
  assert.match(text, /נחסם/);
  assert.equal(byTag(t.ctx.root, 'th').filter((th) => th.textContent === 'n').length, 1);
  const order = findAll(t.ctx.root, (e) => e.tagName === 'ARTICLE' && e.className.includes('graph-result')).map((a) => a.textContent.slice(0, 2));
  assert.deepEqual(order, ['#3', '#2', '#1']);                  // newest first

  const cypher = formWith(t.ctx.root, 'parameters');
  fill(cypher, { query: 'MATCH (n) RETURN n LIMIT 1', parameters: '{"a": 1}' });
  await submit(cypher);
  assert.deepEqual(t.calls.at(-1), ['graph_console_query', { query_mode: 'cypher', query: 'MATCH (n) RETURN n LIMIT 1', parameters: '{"a": 1}', max_rows: '100' }]);
  assert.equal(field(cypher, 'query').value, 'MATCH (n) RETURN n LIMIT 1');   // the query stays for the next iteration

  const natural = formWith(t.ctx.root, 'query', 'model_key');
  assert.deepEqual(natural.querySelectorAll('option').map((o) => o.attrs.value), ['local', 'sonnet', 'codex']);
  fill(natural, { query: 'מה קרה?', model_key: 'sonnet' });
  await submit(natural);
  assert.deepEqual(t.calls.at(-1), ['graph_console_query', { query_mode: 'natural', query: 'מה קרה?', model_key: 'sonnet' }]);

  const access = formWith(t.ctx.root, 'access_mode');
  assert.equal(field(access, 'scope_text').value, 'טנקים');
  await submit(access);
  assert.deepEqual(t.calls.at(-1), ['save_deliver_graph_access', { deliver_id: 'weather.x', access_mode: 'limited', scope_text: 'טנקים', max_chunks: '6', max_chars: '6000' }]);

  const config = formWith(t.ctx.root, 'graph_rag_url');
  assert.equal(field(config, 'graph_cypher_url').value, 'https://ww2-atlas-api.example.workers.dev');
  await submit(config);
  assert.deepEqual(t.calls.at(-1)[0], 'save_graph_rag_config');
  assert.equal(t.fetched.length, 2);                            // health re-read after saving the connection
  buttonByText(t.ctx.root, 'הרץ בדיקת תקינות').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['graph_rag_health', {}]);
  unmount();
});

test('rag: an empty Cypher query is refused before anything is sent', async () => {
  const t = await setup('rag');
  t.mount();
  dom.flush();
  await submit(formWith(t.ctx.root, 'parameters'));
  assert.equal(t.calls.length, 0);
  assert.match(t.toasts.at(-1)[0], /יש למלא/);
  assert.equal(t.toasts.at(-1)[1], false);
});

// ---------------------------------------------------------------------------------------------------- plan
test('plan: prompt modes, send over the socket without files and as a multipart upload with files', async () => {
  const { MAX_FILES, uploadProblem } = await import('../../wwii_build/static/app/pages/plan.js');
  assert.equal(uploadProblem([]), null);
  assert.match(uploadProblem(Array.from({ length: MAX_FILES + 1 }, () => ({ name: 'f', size: 1 }))), /עד 8 קבצים/);
  assert.match(uploadProblem([{ name: 'big.png', size: 11 * 1024 * 1024 }]), /גדול מ־10MB/);
  assert.match(uploadProblem([{ name: 'e.txt', size: 0 }]), /ריק/);
  assert.match(uploadProblem([1, 2, 3].map((i) => ({ name: `f${i}`, size: 9 * 1024 * 1024 }))), /25MB/);

  const t = await setup('plan');
  snapshot(t.store, 'plan', 'task_id', [
    { task_id: 'PLAN/1', state: 'PASSED', state_reason: '', created_at: '2026-01-01T00:00:00+00:00', prompt: 'תכנן מזג אוויר',
      attachments: [{ name: 'map.png', media_type: 'image/png', size_bytes: 2048, selected: true }],
      proposals: [{ id: 4, status: 'pending', summary: 'הצעה', questions: ['איזה אזור?'], validation: [{ level: 'error', key: 'k', message: 'חסר' }], approval_id: 9, created_task_ids: ['MANUAL/a'],
        tasks: [{ key: 'k', title: 'משימה', instructions: 'עשה', model_key: 'sonnet', depends_on: [], write_scope: ['a/'], read_only: true, context_files: [], context_source_ids: [], mcp_servers: [], acceptance_commands: ['make'] }] }] },
  ], { models: MODELS });
  t.mount();
  dom.flush();
  assert.deepEqual(t.topics[0], ['plan']);
  const text = t.text();
  assert.match(text, /PLAN\/1/);
  assert.match(text, /map\.png · 2\.0KB · נבחר/);
  assert.match(text, /\[k\] חסר/);
  assert.match(text, /\(read-only\)/);
  const form = formWith(t.ctx.root, 'prompt', 'prompt_mode');
  assert.deepEqual(form.querySelectorAll('option').filter((o) => ['plan_build', 'advise_next', 'graph_query'].includes(o.attrs.value)).map((o) => o.attrs.value),
    ['plan_build', 'advise_next', 'graph_query']);
  fill(form, { prompt: 'תכנן', prompt_mode: 'advise_next' });
  await submit(form);
  assert.deepEqual(t.calls.at(-1), ['plan', { prompt: 'תכנן', prompt_mode: 'advise_next', model_key: '', mcp_servers: '' }]);
  assert.equal(t.uploads.length, 0);
  assert.equal(field(form, 'prompt').value, '');                // accepted: the form is cleared

  buttonByText(t.ctx.root, 'Approve').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['approve', { approval_id: 9 }]);
  buttonByText(t.ctx.root, 'Reject').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['reject', { approval_id: 9 }]);
});

test('plan: with files selected the request is a multipart upload, over-limit files are refused', async () => {
  const t = await setup('plan');
  t.mount();
  dom.flush();
  const form = formWith(t.ctx.root, 'prompt', 'prompt_mode');
  const picker = findAll(t.ctx.root, (e) => e.tagName === 'INPUT' && e.attrs.type === 'file')[0];
  picker.files = [{ name: 'a.md', size: 100 }];
  picker.fire('change');
  assert.match(t.text(), /a\.md · 0\.1KB/);
  fill(form, { prompt: 'עם קובץ' });
  await submit(form);
  assert.equal(t.calls.length, 0);
  assert.equal(t.uploads.length, 1);
  assert.equal(t.uploads[0][0], 'plan');
  assert.equal(t.uploads[0][1].prompt, 'עם קובץ');
  assert.deepEqual(t.uploads[0][2].map((f) => f.name), ['a.md']);
  assert.doesNotMatch(t.text(), /a\.md · 0\.1KB/);              // the chips are cleared after an accepted upload

  picker.files = [{ name: 'huge.bin', size: 50 * 1024 * 1024 }];
  picker.fire('change');
  fill(form, { prompt: 'גדול' });
  await submit(form);
  assert.equal(t.uploads.length, 1);
  assert.match(t.toasts.at(-1)[0], /גדול מ־10MB/);
});

// ---------------------------------------------------------------------------------------------------- new task
test('new task: same field names as the classic form, options from the endpoint, dependencies from the tasks topic', async () => {
  globalThis.location = { hash: '' };
  const options = { owners: [{ owner: 'qa', domain: 'quality' }], context_files: ['context/game/a.md'], mcp: { claude: { fs: { writes: true } }, codex: {} },
    planner_max_chunks: 24, planner_max_chars: 24000, models: MODELS };
  const t = await setup('new', { fetchJson: async (url) => { assert.equal(url, '/api/new-task-options'); return options; } });
  snapshot(t.store, 'overview', null, [], { review_auto_approve_all: false, models: MODELS });
  snapshot(t.store, 'tasks.active', 'task_id', [
    { task_id: 'B/2', kind: 'task', wave: 1, state: 'READY' },
    { task_id: 'R/1', kind: 'repair', wave: 0, state: 'READY' }]);
  const unmount = t.mount();
  dom.flush();
  await settle();
  dom.flush();
  assert.deepEqual(t.topics[0], ['overview', 'tasks.active']);
  const form = formWith(t.ctx.root, 'description_he', 'ctx_extra');
  const deps = findAll(form, (c) => c.attrs.name === 'deps').map((c) => c.attrs.value);
  assert.deepEqual(deps, ['B/2']);                              // only unfinished plan tasks
  assert.deepEqual(findAll(form, (c) => c.attrs.name === 'mcp').map((c) => c.attrs.value), ['claude:fs']);
  assert.deepEqual(findAll(form, (c) => c.attrs.name === 'ctx').map((c) => c.attrs.value), ['context/game/a.md']);
  assert.deepEqual(form.querySelectorAll('option').map((o) => o.attrs.value).filter((v) => v === 'qa'), ['qa']);
  assert.match(t.text(), /עד 24 מקטעים ו־24,000 תווים/);
  assert.match(t.text(), /כבוי/);

  buttonByText(t.ctx.root, 'הפעל אישור אוטומטי להכול').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['set_auto_approve_all', { enabled: true }]);

  fill(form, { title: 'כותרת', description_he: 'הסבר', instructions: 'הוראות', write_scope: 'x/', task_target: 'task_manager' });
  findAll(form, (c) => c.attrs.name === 'deps' && c.attrs.value === 'B/2')[0].checked = true;
  findAll(form, (c) => c.attrs.name === 'mcp')[0].checked = true;
  await submit(form);
  const [name, args] = t.calls.at(-1);
  assert.equal(name, 'add_task');
  assert.equal(args.title, 'כותרת');
  assert.equal(args.task_target, 'task_manager');
  assert.deepEqual(args.deps, ['B/2']);
  assert.deepEqual(args.mcp, ['claude:fs']);
  assert.deepEqual(args.ctx, []);
  assert.equal(args.fallback, true);
  assert.equal(args.read_only, false);
  assert.equal(args.auto_approve, false);
  for (const k of ['name', 'model_key', 'owner', 'ctx_extra', 'refs', 'tool_names', 'checks', 'context_request', 'context_planner_model_key']) assert.ok(k in args, k);
  unmount();
});

test('new task: a created task opens its page, a context plan opens the planner, a refusal keeps the form', async () => {
  globalThis.location = { hash: '' };
  const t = await setup('new', { fetchJson: async () => ({ owners: [], context_files: [], mcp: {}, planner_max_chunks: 1, planner_max_chars: 1, models: {} }) });
  t.mount();
  dom.flush();
  const form = formWith(t.ctx.root, 'description_he', 'ctx_extra');
  const send = async () => { fill(form, { title: 't', description_he: 'd' }); await submit(form); };
  t.ctx.act = async () => ({ ok: true, message: 'created MANUAL/new-1' });
  await send();
  assert.equal(globalThis.location.hash, '#/task?id=MANUAL%2Fnew-1');
  t.ctx.act = async () => ({ ok: true, message: 'context plan queued PLAN/3' });
  await send();
  assert.equal(globalThis.location.hash, '#/plan');
  globalThis.location.hash = '';
  t.ctx.act = async () => ({ ok: false, message: 'error: no' });
  fill(form, { title: 'נשאר', description_he: 'd' });
  await submit(form);
  assert.equal(globalThis.location.hash, '');
  assert.equal(field(form, 'title').value, 'נשאר');
});

// ---------------------------------------------------------------------------------------------------- battle request
test('battle request: the form sends the battle_request action, the chain comes from the options endpoint, a created chain opens its first task', async () => {
  globalThis.location = { hash: '' };
  const options = { error: '', chains: [{ battle_key: 'k', title: 'synthetic', tasks: [{ task_id: 'MANUAL/battle-k-evidence', stage: 'evidence', state: 'PENDING' }] }],
    stages: [{ stage: 'evidence', title: 'תיק ראיות', deliver: 'game.battle_builder.evidence', model_key: 'sonnet', allow_web: false, depends_on: [] },
      { stage: 'web_research', title: 'מחקר', deliver: 'game.battle_builder.llm_research', model_key: '', allow_web: true, depends_on: ['evidence'] }] };
  const t = await setup('battle', { fetchJson: async (url) => { assert.equal(url, '/api/battle-request-options'); return options; } });
  snapshot(t.store, 'tasks.active', 'task_id', [{ task_id: 'MANUAL/battle-k-evidence', kind: 'task', state: 'RUNNING' }]);
  const unmount = t.mount();
  dom.flush();
  await settle();
  dom.flush();
  assert.deepEqual(t.topics[0], ['tasks.active']);
  assert.match(t.text(), /game\.battle_builder\.llm_research/);
  assert.match(t.text(), /בקשה כפולה לשרשרת פעילה/);
  const form = formWith(t.ctx.root, 'battle_key', 'bbox', 'notes');
  t.ctx.act = async (name, args) => { t.calls.push([name, args]); return { ok: true, message: 'נוצרה שרשרת הקרב k: MANUAL/battle-k-evidence, MANUAL/battle-k-map_research' }; };
  fill(form, { title: 'Brécourt Manor assault', date: '1944-06-06', bbox: '-1.3,49.3,-1.1,49.5' });
  await submit(form);
  const [name, args] = t.calls.at(-1);
  assert.equal(name, 'battle_request');
  assert.deepEqual(Object.keys(args).sort(), ['battle_key', 'bbox', 'date', 'notes', 'place', 'title']);
  assert.equal(args.date, '1944-06-06');
  assert.equal(globalThis.location.hash, '#/task?id=MANUAL%2Fbattle-k-evidence');
  unmount();
});

test('battle request: a refusal keeps what was typed and does not navigate', async () => {
  globalThis.location = { hash: '' };
  const t = await setup('battle', { fetchJson: async () => ({ error: '', chains: [], stages: [] }) });
  t.mount();
  dom.flush();
  const form = formWith(t.ctx.root, 'battle_key', 'bbox', 'notes');
  t.ctx.act = async () => ({ ok: false, message: 'error: an active battle chain for k already exists' });
  fill(form, { title: 'נשאר', date: '1944-06-06' });
  await submit(form);
  assert.equal(globalThis.location.hash, '');
  assert.equal(field(form, 'title').value, 'נשאר');
});

// ---------------------------------------------------------------------------------------------------- events
const EV = (id, over = {}) => ({ id, at: '2026-01-01T00:00:00+00:00', event: 'TASK_STARTED', task_id: 'A/1', provider: 'codex', attempt_id: null, detail: { n: id }, ...over });
const FACETS = { total: 3, type_count: 2, task_count: 1, latest: { id: 12, at: '2026-01-01T00:00:00+00:00' }, types: ['TASK_PASSED', 'TASK_STARTED'], providers: ['codex'] };

function eventsFetch(pages) {
  return async (url) => {
    if (url === '/api/events/facets') return FACETS;
    const q = new URL(url, 'http://x').searchParams;
    return pages(q);
  };
}
const eventRows = (root) => findAll(root, (e) => e.tagName === 'TR' && e.parentNode?.tagName === 'TBODY').filter((r) => r.className !== 'app-empty');

test('events: first page from /api/events, live rows that match the filters, older rows by before_id', async () => {
  const t = await setup('events', { fetchJson: eventsFetch((q) => (q.get('before_id') === '10'
    ? { total: 3, next_before_id: null, events: [EV(9)] } : { total: 3, next_before_id: 10, events: [EV(12), EV(10)] })) });
  snapshot(t.store, 'events', 'id', [EV(8), EV(10), EV(12)]);
  const unmount = t.mount();
  dom.flush();
  await settle();
  dom.flush();
  assert.deepEqual(t.topics[0], ['events']);
  assert.ok(t.fetched.includes('/api/events/facets'));
  assert.ok(t.fetched.includes('/api/events?limit=100'));
  assert.deepEqual(eventRows(t.ctx.root).map((r) => r.children[0].textContent), ['#12', '#10']);   // the snapshot's #8 is older than the page
  assert.match(t.text(), /אירועים \(3\)/);
  assert.match(t.text(), /אירועים שמורים/);

  t.store.applyPatch({ topic: 'events', rev: 2, upsert: [EV(13, { event: 'TASK_PASSED' })], remove: [] });
  dom.flush();
  assert.deepEqual(eventRows(t.ctx.root).map((r) => r.children[0].textContent), ['#13', '#12', '#10']);
  assert.match(t.text(), /אירועים \(4\)/);

  buttonByText(t.ctx.root, 'אירועים ישנים יותר ←').click();
  await settle();
  assert.ok(t.fetched.includes('/api/events?limit=100&before_id=10'));
  assert.deepEqual(eventRows(t.ctx.root).map((r) => r.children[0].textContent), ['#13', '#12', '#10', '#9']);
  assert.ok(buttonByText(t.ctx.root, 'אירועים ישנים יותר ←').hidden);
  unmount();
});

test('events: filters go to the server, live rows that do not match are not shown', async () => {
  const t = await setup('events', { params: { task_id: 'A/1' }, fetchJson: eventsFetch(() => ({ total: 1, next_before_id: null, events: [EV(5)] })) });
  snapshot(t.store, 'events', 'id', []);
  t.mount();
  dom.flush();
  await settle();
  assert.ok(t.fetched.includes('/api/events?limit=100&task_id=A%2F1'));       // the page was opened with a task filter
  t.store.applyPatch({ topic: 'events', rev: 2, upsert: [EV(6, { task_id: 'B/2' }), EV(7)], remove: [] });
  dom.flush();
  assert.deepEqual(eventRows(t.ctx.root).map((r) => r.children[0].textContent), ['#7', '#5']);

  const form = formWith(t.ctx.root, 'search', 'task_id');
  fill(form, { search: 'abc', task_id: '' });
  field(form, 'provider').value = 'codex';
  form.fire('submit');
  await settle();
  assert.ok(t.fetched.includes('/api/events?limit=100&search=abc&provider=codex'));
  assert.match(t.text(), /מסוננים/);
  buttonByText(t.ctx.root, 'נקה סינון').click();
  await settle();
  assert.equal(t.fetched.at(-1), '/api/events?limit=100');
});

test('events: an empty journal shows the empty row; unmounting stops the live listener', async () => {
  const t = await setup('events', { fetchJson: eventsFetch(() => ({ total: 0, next_before_id: null, events: [] })) });
  snapshot(t.store, 'events', 'id', []);
  const unmount = t.mount();
  dom.flush();
  await settle();
  assert.match(t.text(), /לא נמצאו אירועים התואמים לסינון/);
  unmount();
  t.store.applyPatch({ topic: 'events', rev: 2, upsert: [EV(1)], remove: [] });
  dom.flush();
  assert.equal(eventRows(t.ctx.root).length, 0);
});

// ---------------------------------------------------------------------------------------------------- task
const TASK_META = (over = {}) => ({
  exists: true,
  task: { task_id: 'A/1', packet: 'A', owner: 'o', domain: 'd', mode: 'build', model_profile: 'IMPLEMENT', wave: 1, state: 'FAILED', state_reason: 'נכשל',
    attempts_count: 1, failed_attempts: 1, branch: 'wwii/a-1', kind: 'task', parent_task_id: null, repair_no: null, failure_class: 'TEST_FAILED', failure_summary: '',
    repairs_count: 1, dispatch_priority: 0, preferred_model_key: 'sonnet', last_model_key: null, write_scope: ['src/'] },
  description_he: 'עושה משהו', system: null, deps: [{ task_id: 'A/0', state: 'PASSED' }],
  task_options: [{ task_id: 'A/0', state: 'PASSED' }, { task_id: 'B/1', state: 'READY' }],
  context_options: [{ source_key: 'src.one', title: 'מקור' }],
  bindings: [{ source_key: 'src.one', active: 1, title: 'מקור', origin_kind: 'graph', origin_ref: 'g1' }],
  context_request: '', planned_files: [], approvals: [{ id: 5, kind: 'review', subject: 'A/1', reason: 'בדיקה' }],
  chain: { role: 'parent', repairs_count: 1, budget: 3, failure_class: 'TEST_FAILED', state: 'FAILED', steps: [
    { type: 'execute', attempt_no: 1, attempt: { provider: 'codex', model: 'gpt-x', status: 'FAILED', failure_class: 'TEST_FAILED', input_tokens: 1, cached_input_tokens: null, output_tokens: 2, reported_cost_usd: null }, checks: [{ name: 'lint', passed: false }] },
    { type: 'repair', task_id: 'REPAIR/A/1/1', repair_no: 1, state: 'PASSED', failure_class: 'TEST_FAILED', failure_summary: 'תוקן', attempts: [], checks: [{ name: 'lint', passed: true }] }] },
  lineage: { parents: [], children: [{ task_id: 'A/1-sub', state: 'READY', model_key: null, mcp: [], tools: ['Read'], reuse_count: 1, promotion_threshold: 3 }] },
  is_deliver: false, graph_access: null, handoff: { summary: 'סיכום' }, brief: 'תדריך',
  artifacts: [{ id: 3, task_id: 'A/1', kind: 'report', source_path: 'r.md', description: 'דוח', media: 'file' }],
  tests: [{ name: 'unit', kind: 'command', passed: false, exit_code: 1, duration_s: 2, output_tail: 'boom' }],
  context_pack: { total_bytes: 100, sha: 'abc', items: [{ mode: 'inline', layer: 'task', path: 'a.md', bytes: 10, reason: 'r' }] },
  models: MODELS, ...over });
const ATTEMPT = { id: 7, kind: 'execute', attempt_no: 1, provider: 'codex', model: 'gpt-x', effort: 'high', status: 'FAILED', failure_class: 'TEST_FAILED',
  started_at: '2026-01-01T00:00:00+00:00', ended_at: null, input_tokens: 5, cached_input_tokens: null, output_tokens: 2, reported_cost_usd: null, pid: null };

test('task: state, attempts with unknown values kept unknown, approvals, repair chain, artifacts, tests and actions', async () => {
  const t = await setup('task', { params: { id: 'A/1' }, fetchJson: async (url) => {
    assert.equal(url, '/api/task/diff?id=A%2F1');
    return { exists: true, files: ['src/a.py'], diff: 'diff --git a/src/a.py b/src/a.py\n+x\n-y\n' };
  } });
  snapshot(t.store, 'task:A/1', 'id', [ATTEMPT], TASK_META());
  const unmount = t.mount();
  dom.flush();
  await settle();
  dom.flush();
  assert.deepEqual(t.topics[0], ['task:A/1']);
  const text = t.text();
  assert.match(text, /עושה משהו/);
  assert.match(text, /5 \/ לא ידוע \/ 2/);                         // the unreported cached-token count is not a zero
  assert.match(text, /שרשרת תיקונים/);
  assert.match(text, /תיקונים 1 מתוך 3/);
  assert.match(text, /✗ lint/);
  assert.match(text, /✓ lint/);
  assert.match(text, /A\/1-sub/);
  assert.match(text, /קבצים שהשתנו \(1\)/);
  assert.match(text, /src\/a\.py/);
  assert.match(text, /\+1/);
  assert.ok(!buttonByText(t.ctx.root, 'דחוף עכשיו'));            // expedite only for READY
  assert.ok(findAll(t.ctx.root, (e) => e.tagName === 'A' && e.attrs.href === '#/events?task_id=A%2F1').length);
  assert.ok(findAll(t.ctx.root, (e) => e.tagName === 'A' && e.attrs.href === '#/task?id=A%2F0').length);

  buttonByText(t.ctx.root, 'נסה שוב').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['retry', { task_id: 'A/1' }]);
  buttonByText(t.ctx.root, 'הרץ בדיקות קבלה מחדש').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['recheck', { task_id: 'A/1' }]);
  dom.confirms.answer = false;
  buttonByText(t.ctx.root, 'בטל משימה').click();
  await settle();
  assert.notDeepEqual(t.calls.at(-1)[0], 'skip');                  // declined confirmation sends nothing
  assert.match(dom.confirms.asked.at(-1), /לבטל את המשימה/);
  dom.confirms.answer = true;
  buttonByText(t.ctx.root, 'בטל משימה').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['skip', { task_id: 'A/1' }]);
  buttonByText(t.ctx.root, 'Approve').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['approve', { approval_id: 5 }]);
  buttonByText(t.ctx.root, 'השבת גישה').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['toggle_task_context', { task_id: 'A/1', source_key: 'src.one', enabled: false }]);
  unmount();
});

test('task: forms send the classic field names (model, scoped plan, dependency, context, subtask)', async () => {
  const t = await setup('task', { params: { id: 'A/1' }, fetchJson: async () => ({ exists: true, files: [], diff: '' }) });
  snapshot(t.store, 'task:A/1', 'id', [], TASK_META({ approvals: [] }));
  t.mount();
  dom.flush();
  await settle();

  const change = formWith(t.ctx.root, 'model_key');
  assert.equal(field(change, 'model_key').value, 'sonnet');         // the task's own model is preselected
  field(change, 'model_key').value = 'codex';
  await submit(change);
  assert.deepEqual(t.calls.at(-1), ['set_provider', { task_id: 'A/1', model_key: 'codex' }]);

  const scoped = formWith(t.ctx.root, 'prompt', 'mcp_servers');
  fill(scoped, { prompt: 'שנה' });
  await submit(scoped);
  assert.deepEqual(t.calls.at(-1), ['scoped_plan', { scope_kind: 'task', scope_id: 'A/1', prompt_mode: 'plan_build', prompt: 'שנה', model_key: '', mcp_servers: '' }]);

  const dependency = formWith(t.ctx.root, 'depends_on');
  assert.deepEqual(dependency.querySelectorAll('option').map((o) => o.attrs.value), ['A/0', 'B/1']);
  field(dependency, 'depends_on').value = 'B/1';
  await submit(dependency);
  assert.deepEqual(t.calls.at(-1), ['add_task_dependency', { task_id: 'A/1', depends_on: 'B/1' }]);

  const bind = findAll(t.ctx.root, (e) => e.tagName === 'FORM' && findAll(e, (c) => c.attrs.name === 'source_key').length === 1
    && findAll(e, (c) => c.attrs.name === 'title').length === 0)[0];
  await submit(bind);
  assert.deepEqual(t.calls.at(-1), ['bind_task_context', { task_id: 'A/1', source_key: 'src.one' }]);

  const context = formWith(t.ctx.root, 'source_key', 'excerpt');
  fill(context, { source_key: 'k.1', title: 'כותרת', excerpt: 'תוכן' });
  await submit(context);
  assert.deepEqual(t.calls.at(-1), ['add_context', { task_id: 'A/1', source_key: 'k.1', title: 'כותרת', origin_ref: '', excerpt: 'תוכן' }]);

  const sub = formWith(t.ctx.root, 'instructions', 'acceptance_commands');
  assert.equal(field(sub, 'parent_task_id'), undefined);            // the parent is the task being viewed
  fill(sub, { title: 'ת', instructions: 'ה' });
  await submit(sub);
  assert.equal(t.calls.at(-1)[0], 'create_subtask');
  assert.equal(t.calls.at(-1)[1].parent_task_id, 'A/1');
});

test('task: expedite for READY, system card, Deliver graph access section, unknown task', async () => {
  const t = await setup('task', { params: { id: 'D/1' }, fetchJson: async () => ({ exists: true, files: [], diff: '' }) });
  const meta = TASK_META({ system: { status: 'READY', changed_count: 4 }, is_deliver: true, chain: null,
    graph_access: { access_mode: 'limited', scope_text: 'טנקים', max_chunks: 7, max_chars: 7000 } });
  meta.task = { ...meta.task, task_id: 'D/1', state: 'READY' };
  snapshot(t.store, 'task:D/1', 'id', [], meta);
  t.mount();
  dom.flush();
  await settle();
  assert.match(t.text(), /תיקון מערכת מוגן/);
  assert.match(t.text(), /קבצים בחבילה: 4/);
  buttonByText(t.ctx.root, 'דחוף עכשיו').click();
  await settle();
  assert.deepEqual(t.calls.at(-1), ['expedite', { task_id: 'D/1' }]);
  const graph = formWith(t.ctx.root, 'access_mode');
  assert.equal(field(graph, 'scope_text').value, 'טנקים');

  const u = await setup('task', { params: { id: 'nope' } });
  snapshot(u.store, 'task:nope', 'id', [], { exists: false, task_id: 'nope' });
  u.mount();
  dom.flush();
  assert.match(u.text(), /משימה לא ידועה/);
});
