import assert from 'node:assert/strict';
import { test } from 'node:test';

import { LiveSocket } from '../../wwii_build/static/app/socket.js';
import { Store } from '../../wwii_build/static/app/store.js';

class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  send(text) { this.sent.push(JSON.parse(text)); }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  // test controls
  open() { this.readyState = 1; this.onopen(); }
  receive(obj) { this.onmessage({ data: JSON.stringify(obj) }); }
  drop(code = 1006) { this.readyState = 3; this.onclose({ code }); }
  sentTypes() { return this.sent.map((m) => m.type); }
}

function harness(extra = {}) {
  FakeWebSocket.instances = [];
  const timers = [];
  const status = [];
  const errors = [];
  const store = new Store();
  const sock = new LiveSocket({
    store, WebSocketImpl: FakeWebSocket, url: () => 'ws://x/ws', getToken: () => extra.token || 'tok',
    onStatus: (o) => status.push(o), onError: (m) => errors.push(m), random: () => 0, now: () => 1000,
    setTimer: (fn, ms) => { const t = { fn, ms, live: true }; timers.push(t); return t; },
    clearTimer: (t) => { if (t) t.live = false; },
    renewToken: extra.renewToken,
    reload: extra.reload,
  });
  const last = () => FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  const retries = () => timers.filter((t) => t.live && t.ms !== 20000);
  const welcome = (ws = last()) => { ws.open(); ws.receive({ type: 'welcome' }); };
  return { sock, store, timers, status, errors, last, retries, welcome };
}

test('hello with the token, then subscribe for the page topics', () => {
  const { sock, last } = harness();
  sock.setTopics(['overview', 'tasks']);            // before the socket is up: remembered
  sock.connect();
  const ws = last();
  assert.equal(ws.url, 'ws://x/ws');
  ws.open();
  assert.deepEqual(ws.sent, [{ type: 'hello', token: 'tok' }]);
  ws.receive({ type: 'welcome' });
  assert.deepEqual(ws.sent[1], { type: 'subscribe', topics: ['overview', 'tasks'], revs: {} });
});

test('snapshots and patches land in the store; a rev gap re-subscribes that topic without a rev', () => {
  const { sock, store, last, welcome } = harness();
  sock.setTopics(['tasks']);
  sock.connect();
  welcome();
  const ws = last();
  ws.receive({ type: 'snapshot', topic: 'tasks', rev: 4, data: { key: 'task_id', items: [{ task_id: 'a' }], meta: {} } });
  ws.receive({ type: 'patch', topic: 'tasks', rev: 5, upsert: [{ task_id: 'b' }], remove: [] });
  assert.deepEqual(store.items('tasks').map((t) => t.task_id), ['a', 'b']);
  ws.receive({ type: 'patch', topic: 'tasks', rev: 9, upsert: [{ task_id: 'z' }], remove: [] });
  assert.deepEqual(store.items('tasks').map((t) => t.task_id), ['a', 'b']);
  assert.deepEqual(ws.sent.at(-1), { type: 'subscribe', topics: ['tasks'], revs: {} });
});

test('reconnect: banner status, exponential backoff, revs resent, backoff reset after welcome', () => {
  const { sock, status, retries, last, welcome } = harness();
  sock.setTopics(['overview', 'tasks']);
  sock.connect();
  welcome();
  last().receive({ type: 'snapshot', topic: 'overview', rev: 7, data: { key: null, items: [], meta: { a: 1 } } });
  assert.deepEqual(status, [true]);
  last().drop();
  assert.deepEqual(status, [true, false]);
  assert.equal(retries().length, 1);
  assert.equal(retries()[0].ms, 500);
  // two failed attempts (never welcomed): 1s then 2s, status not toggled again
  for (const expected of [1000, 2000]) {
    retries().at(-1).fn();
    last().drop();
    assert.equal(retries().at(-1).ms, expected);
  }
  assert.deepEqual(status, [true, false]);
  retries().at(-1).fn();
  welcome();
  assert.deepEqual(status, [true, false, true]);
  assert.deepEqual(last().sent.at(-1), { type: 'subscribe', topics: ['overview', 'tasks'], revs: { overview: 7 } });
  last().drop();
  assert.equal(retries().at(-1).ms, 500);               // reset after a successful welcome
});

test('backoff is capped at 15 seconds', () => {
  const { sock, retries, last } = harness();
  sock.connect();
  const delays = [];
  for (let i = 0; i < 8; i++) {
    last().drop();
    delays.push(retries().at(-1).ms);
    retries().at(-1).fn();
  }
  assert.deepEqual(delays, [500, 1000, 2000, 4000, 8000, 15000, 15000, 15000]);
});

test('setTopics online sends only the difference', () => {
  const { sock, last, welcome } = harness();
  sock.setTopics(['overview']);
  sock.connect();
  welcome();
  const ws = last();
  sock.setTopics(['overview', 'chat:3']);
  assert.deepEqual(ws.sent.at(-1), { type: 'subscribe', topics: ['chat:3'], revs: {} });
  sock.setTopics(['chat:3']);
  assert.deepEqual(ws.sent.at(-1), { type: 'unsubscribe', topics: ['overview'] });
  const count = ws.sent.length;
  sock.setTopics(['chat:3']);
  assert.equal(ws.sent.length, count);
});

test('actions: id, result promise, offline refusal, drop while pending', async () => {
  const { sock, last, welcome } = harness();
  assert.deepEqual(await sock.action('pause', {}), { ok: false, message: 'אין חיבור לשרת כרגע; הפעולה לא נשלחה' });
  sock.connect();
  welcome();
  const ws = last();
  const first = sock.action('pause', { x: 1 });
  const second = sock.action('state_chat', { message: 'hi' });
  const sent = ws.sent.filter((m) => m.type === 'action');
  assert.deepEqual(sent[0], { type: 'action', id: sent[0].id, name: 'pause', args: { x: 1 } });
  assert.notEqual(sent[0].id, sent[1].id);
  ws.receive({ type: 'action.result', id: sent[1].id, ok: true, message: 'תשובה התקבלה' });
  assert.deepEqual(await second, { ok: true, message: 'תשובה התקבלה' });
  ws.drop();
  const lost = await first;
  assert.equal(lost.ok, false);
  assert.match(lost.message, /החיבור נותק/);
});

test('read-only requests correlate history and task detail responses and fail on disconnect', async () => {
  const { sock, last, welcome } = harness();
  assert.deepEqual(await sock.request('search', { topic: 'tasks.history' }), { ok: false, error: 'offline' });
  sock.connect();
  welcome();
  const ws = last();
  const history = sock.request('search', { topic: 'tasks.history', query: 'x', page: 2 });
  const sent = ws.sent.at(-1);
  assert.deepEqual(sent, { type: 'search', id: sent.id, topic: 'tasks.history', query: 'x', page: 2 });
  ws.receive({ type: 'search.result', id: sent.id, ok: true, items: [], page: 2, total: 0 });
  assert.equal((await history).page, 2);
  const detail = sock.request('task.detail', { task_id: 'A/1' });
  const detailSent = ws.sent.at(-1);
  ws.receive({ type: 'task.detail.result', id: detailSent.id, ok: true, detail: { task_id: 'A/1' } });
  assert.equal((await detail).detail.task_id, 'A/1');
  const lost = sock.request('task.detail', { task_id: 'B/2' });
  ws.drop();
  assert.deepEqual(await lost, { ok: false, error: 'disconnected' });
});

test('4401 after a dashboard restart refreshes the token before reconnecting', async () => {
  let token = 'old';
  const refreshed = [];
  const h = harness({ renewToken: async () => { token = 'new'; refreshed.push(true); } });
  h.sock.getToken = () => token;
  h.sock.connect();
  h.last().open();
  h.last().drop(4401);
  await h.retries().at(-1).fn();
  assert.deepEqual(refreshed, [true]);
  h.last().open();
  assert.deepEqual(h.last().sent[0], { type: 'hello', token: 'new' });
});

test('1012 reconnect reloads once only when the served app version changed', async () => {
  const reloads = [];
  const h = harness({ reload: () => reloads.push(true) });
  h.sock.connect();
  h.last().open();
  h.last().receive({ type: 'welcome', version: 'app-v1' });
  h.last().drop(1012);
  await h.retries().at(-1).fn();
  h.last().open();
  h.last().receive({ type: 'welcome', version: 'app-v2' });
  assert.deepEqual(reloads, [true]);
  h.last().receive({ type: 'welcome', version: 'app-v2' });
  assert.deepEqual(reloads, [true]);
});

test('ordinary reconnect never reloads, even if the welcome version differs', () => {
  const reloads = [];
  const h = harness({ reload: () => reloads.push(true) });
  h.sock.connect();
  h.last().open();
  h.last().receive({ type: 'welcome', version: 'app-v1' });
  h.last().drop(1006);
  h.retries().at(-1).fn();
  h.last().open();
  h.last().receive({ type: 'welcome', version: 'app-v2' });
  assert.deepEqual(reloads, []);
});

test('server error messages are surfaced; heartbeat pings and closes a silent socket', () => {
  let now = 1000;
  const h = harness();
  h.sock.now = () => now;
  h.sock.connect();
  h.welcome();
  h.last().receive({ type: 'error', error: 'bad_topics', message_he: 'רשימת נושאים לא תקינה' });
  assert.equal(h.errors[0].message_he, 'רשימת נושאים לא תקינה');
  const ping = h.timers.find((t) => t.live && t.ms === 20000);
  ping.fn();
  assert.equal(h.last().sent.at(-1).type, 'ping');
  now += 61000;
  h.timers.filter((t) => t.live && t.ms === 20000).at(-1).fn();
  assert.equal(h.last().readyState, 3);                  // half-open: closed so the reconnect logic takes over
});
