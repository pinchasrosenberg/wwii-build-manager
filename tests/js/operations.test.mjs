// Progress streaming on the client: socket progress messages and the live operation panels. All data is synthetic.
import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';

import { ALREADY_RUNNING, Operations } from '../../wwii_build/static/app/operations.js';
import { LiveSocket } from '../../wwii_build/static/app/socket.js';
import { Store } from '../../wwii_build/static/app/store.js';
import { byTag, findAll, installDom } from './fake_dom.mjs';

let dom;
beforeEach(() => { dom = installDom(); });
afterEach(() => { dom.uninstall(); });

class FakeWebSocket {
  static last = null;
  constructor() { this.readyState = 1; this.sent = []; FakeWebSocket.last = this; }
  send(text) { this.sent.push(JSON.parse(text)); }
  close() { this.readyState = 3; }
  receive(obj) { this.onmessage({ data: JSON.stringify(obj) }); }
}

function readySocket() {
  const sock = new LiveSocket({
    store: new Store(), WebSocketImpl: FakeWebSocket, url: () => 'ws://x/ws', getToken: () => 't',
    setTimer: () => 0, clearTimer: () => {},
  });
  sock.connect();
  const ws = FakeWebSocket.last;
  ws.onopen();
  ws.receive({ type: 'welcome' });
  return { sock, ws };
}

test('socket: progress lines reach only the action they belong to, in order, before the result', async () => {
  const { sock, ws } = readySocket();
  const heard = [];
  const other = [];
  const first = sock.action('unstick', {}, (line) => heard.push(line));
  const second = sock.action('system_onboard', {}, (line) => other.push(line));
  const [a, b] = ws.sent.filter((m) => m.type === 'action');
  ws.receive({ type: 'progress', id: a.id, line: 'ממצא: א' });
  ws.receive({ type: 'progress', id: b.id, line: 'טוען' });
  ws.receive({ type: 'progress', id: a.id, line: 'פעולה: ב' });
  ws.receive({ type: 'progress', id: 'unknown', line: 'ignored' });
  assert.deepEqual(heard, ['ממצא: א', 'פעולה: ב']);
  assert.deepEqual(other, ['טוען']);
  ws.receive({ type: 'action.result', id: a.id, ok: true, message: 'סיום' });
  assert.deepEqual(await first, { ok: true, message: 'סיום' });
  ws.receive({ type: 'progress', id: a.id, line: 'late' });          // after the result: nobody is listening
  assert.deepEqual(heard, ['ממצא: א', 'פעולה: ב']);
  ws.receive({ type: 'action.result', id: b.id, ok: false, message: 'כבר רץ' });
  assert.deepEqual(await second, { ok: false, message: 'כבר רץ' });
});

test('socket: an action without a progress listener still works', async () => {
  const { sock, ws } = readySocket();
  const result = sock.action('pause', {});
  const sent = ws.sent.find((m) => m.type === 'action');
  ws.receive({ type: 'progress', id: sent.id, line: 'x' });
  ws.receive({ type: 'action.result', id: sent.id, ok: true, message: 'ok' });
  assert.equal((await result).ok, true);
});

test('operations: a long action gets a panel with its lines, the thinking code is shown in Hebrew, the result closes it', () => {
  const timers = [];
  const box = document.createElement('div');
  const ops = new Operations(box, { setTimer: (fn, ms) => { timers.push([fn, ms]); } });
  assert.equal(ops.begin('pause'), null);                              // not a long action: no panel
  const op = ops.begin('state_chat');
  assert.equal(box.children.length, 1);
  op.line('thinking');
  op.line('נבחר המודל sol');
  const text = () => box.textContent;
  assert.match(text(), /שיחה על המצב/);
  assert.match(text(), /המודל חושב…/);
  assert.doesNotMatch(text(), /thinking/);
  assert.equal(findAll(box, (e) => e.tagName === 'LI').length, 2);
  assert.ok(ops.running('state_chat'));
  op.end({ ok: true, message: 'תשובה התקבלה' });
  assert.ok(!ops.running('state_chat'));
  assert.match(text(), /✓ תשובה התקבלה/);
  assert.equal(box.children[0].className, 'op-panel ok');
  op.line('late');                                                      // ignored after the end
  assert.equal(findAll(box, (e) => e.tagName === 'LI').length, 2);
  timers[0][0]();                                                       // the linger timer removes the panel
  assert.equal(box.children.length, 0);
});

test('operations: a failed run lingers longer and the close button removes the panel', () => {
  const timers = [];
  const box = document.createElement('div');
  const ops = new Operations(box, { setTimer: (fn, ms) => { timers.push(ms); } });
  const ok = ops.begin('graph_console_query');
  ok.end({ ok: true, message: 'x' });
  const bad = ops.begin('graph_console_query');
  bad.end({ ok: false, message: 'y' });
  assert.ok(timers[1] > timers[0]);
  assert.equal(box.children[1].className, 'op-panel bad');
  byTag(box, 'button')[1].click();
  assert.equal(box.children.length, 1);
});

test('operations: unstick and system_onboard run one at a time, chat and graph queries may overlap', () => {
  const ops = new Operations(null, { setTimer: () => {} });
  const first = ops.begin('unstick');
  assert.deepEqual(ops.begin('unstick'), { refused: true });
  assert.ok(ops.begin('system_onboard'));                                // another operation: allowed
  assert.deepEqual(ops.begin('system_onboard'), { refused: true });
  first.end({ ok: true, message: '' });
  assert.ok(ops.begin('unstick').line);                                  // free again
  assert.ok(ops.begin('state_chat') && ops.begin('state_chat'));
  assert.equal(ALREADY_RUNNING, 'כבר רץ');
});

test('operations: a bound button is disabled while the operation runs anywhere, then released', () => {
  const ops = new Operations(null, { setTimer: () => {} });
  const button = document.createElement('button');
  const untouched = document.createElement('button');
  const disabledByUser = document.createElement('button');
  disabledByUser.disabled = true;
  const unbind = ops.bind(button, 'unstick');
  ops.bind(untouched, 'system_onboard');
  ops.bind(disabledByUser, 'unstick');
  const op = ops.begin('unstick');
  assert.equal(button.disabled, true);
  assert.equal(untouched.disabled, false);
  op.end({ ok: true, message: '' });
  assert.equal(button.disabled, false);
  assert.equal(disabledByUser.disabled, true);                           // it was not ours to enable
  unbind();
  ops.begin('unstick');
  assert.equal(button.disabled, false);                                  // unbound: left alone
});

test('operations: a button is disabled at bind time when the operation is already running', () => {
  const ops = new Operations(null, { setTimer: () => {} });
  ops.begin('system_onboard');
  const button = document.createElement('button');
  ops.bind(button, 'system_onboard');
  assert.equal(button.disabled, true);
});
