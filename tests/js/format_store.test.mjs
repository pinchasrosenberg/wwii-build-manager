import assert from 'node:assert/strict';
import { test } from 'node:test';

import { STATE_ORDER, backoffDelay, countTiles, fmtAgo, fmtDuration, fmtRuntime, parseIso, quotaWindow, taskRows, weeklyUsed }
  from '../../wwii_build/static/app/format.js';
import { Store } from '../../wwii_build/static/app/store.js';
import { parseHash } from '../../wwii_build/static/app/router.js';

const T0 = Date.parse('2026-01-01T00:00:00Z');

test('parseIso handles microseconds, offsets and junk', () => {
  assert.equal(parseIso('2026-01-01T00:00:00+00:00'), T0);
  assert.equal(parseIso('2026-01-01T00:00:00.123456+00:00'), T0 + 123);
  assert.equal(parseIso(null), null);
  assert.equal(parseIso('nope'), null);
});

test('durations, runtime and ago', () => {
  assert.equal(fmtDuration(0), '0:00:00');
  assert.equal(fmtDuration(65_000), '0:01:05');
  assert.equal(fmtDuration(26 * 3600_000 + 5000), '26:00:05');
  assert.equal(fmtDuration(-5000), '0:00:00');
  assert.equal(fmtRuntime('2026-01-01T00:00:00+00:00', T0 + 3725_000), '1:02:05');
  assert.equal(fmtRuntime(null), '-');
  assert.equal(fmtAgo('2026-01-01T00:00:00+00:00', T0 + 30_000), 'לפני 30 שנ׳');
  assert.equal(fmtAgo('2026-01-01T00:00:00+00:00', T0 + 600_000), 'לפני 10 דק׳');
  assert.equal(fmtAgo('2026-01-01T00:00:00+00:00', T0 + 3 * 3600_000), 'לפני 3 שע׳');
  assert.equal(fmtAgo(null), 'לא ידוע');
});

test('quota windows: unknown is not a number, a passed reset means unused', () => {
  assert.deepEqual(quotaWindow(null, null, T0), { text: 'לא ידוע', note: '' });
  assert.deepEqual(quotaWindow(41.6, '2026-01-02T00:00:00+00:00', T0), { text: '42%', note: '' });
  assert.deepEqual(quotaWindow(99, '2025-12-31T00:00:00+00:00', T0), { text: '0%', note: 'אופס' });
  assert.equal(weeklyUsed({ weekly_used_percent: 7, session_used_percent: 1, used_percent: 3 }), 7);
  assert.equal(weeklyUsed({ weekly_used_percent: null, session_used_percent: null, used_percent: 3 }), 3);
  assert.equal(weeklyUsed({ weekly_used_percent: null, session_used_percent: 1, used_percent: 3 }), null);
});

test('count tiles group states like the classic overview', () => {
  const tiles = Object.fromEntries(countTiles({ PASSED: 4, RUNNING: 1, REVIEWING: 2, WAITING_QUOTA: 1, PAUSED: 1, FAILED: 3 }));
  assert.equal(tiles['הושלמו'], 4);
  assert.equal(tiles['רצות'], 3);
  assert.equal(tiles['ממתינות'], 2);
  assert.equal(tiles['נכשלו'], 3);
  assert.equal(tiles['חסומות'], 0);
  assert.equal(countTiles(undefined).length, 9);
});

test('task rows: wave, state order, id; repairs follow their parent', () => {
  const mk = (task_id, wave, state, extra = {}) => ({ task_id, wave, state, kind: 'plan', ...extra });
  const rows = taskRows([
    mk('B/2', 1, 'PASSED'), mk('A/1', 1, 'RUNNING'), mk('C/3', 0, 'READY'), mk('A/1/repair2', 1, 'READY', { kind: 'repair', parent_task_id: 'A/1', repair_no: 2 }),
    mk('A/1/repair1', 1, 'FAILED', { kind: 'repair', parent_task_id: 'A/1', repair_no: 1 }), mk('Z/9', 1, 'WEIRD'),
  ]);
  assert.deepEqual(rows.map((r) => r.task.task_id), ['C/3', 'A/1', 'A/1/repair1', 'A/1/repair2', 'B/2', 'Z/9']);
  assert.deepEqual(rows.map((r) => r.repair), [false, false, true, true, false, false]);
  assert.ok(STATE_ORDER.indexOf('RUNNING') < STATE_ORDER.indexOf('PASSED'));
});

test('backoff doubles from 0.5s and is capped at 15s', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 10].map((n) => backoffDelay(n)), [500, 1000, 2000, 4000, 8000, 15000, 15000, 15000]);
  assert.equal(backoffDelay(2, 0.999), Math.round(2000 * (1 - 0.3 * 0.999)));
  assert.ok(backoffDelay(0, 0.5) < 500);
});

test('hash router parsing', () => {
  assert.equal(parseHash('').name, 'overview');
  assert.equal(parseHash('#/').name, 'overview');
  assert.equal(parseHash('#/overview').name, 'overview');
  const r = parseHash('#/tasks/A%2F1?tab=x&n=2');
  assert.equal(r.name, 'tasks');
  assert.deepEqual(r.rest, ['A%2F1']);
  assert.deepEqual(r.params, { tab: 'x', n: '2' });
});

test('store: snapshot, patch, remove, meta, revs', () => {
  const store = new Store();
  const seen = [];
  store.on('tasks', (t) => seen.push(t.rev));
  assert.deepEqual(store.items('tasks'), []);
  assert.equal(store.applyPatch({ topic: 'tasks', rev: 2 }), 'unknown');
  store.applySnapshot({ type: 'snapshot', topic: 'tasks', rev: 10, data: { key: 'task_id', items: [{ task_id: 'a', n: 1 }, { task_id: 'b', n: 1 }], meta: { x: 1 } } });
  assert.deepEqual(store.revs(), { tasks: 10 });
  assert.equal(store.applyPatch({ topic: 'tasks', rev: 11, upsert: [{ task_id: 'b', n: 2 }, { task_id: 'c', n: 1 }], remove: ['a'] }), 'ok');
  assert.deepEqual(store.items('tasks').map((i) => `${i.task_id}${i.n}`), ['b2', 'c1']);
  assert.deepEqual(store.meta('tasks'), { x: 1 });                       // no meta in the patch: unchanged
  store.applyPatch({ topic: 'tasks', rev: 12, upsert: [], remove: [], meta: { x: 2 } });
  assert.deepEqual(store.meta('tasks'), { x: 2 });
  assert.deepEqual(seen, [10, 11, 12]);
});

test('store: a missed revision is a gap and changes nothing; key-less topics keep only meta', () => {
  const store = new Store();
  store.applySnapshot({ topic: 'quota', rev: 5, data: { key: 'provider', items: [{ provider: 'p' }], meta: {} } });
  assert.equal(store.applyPatch({ topic: 'quota', rev: 7, upsert: [{ provider: 'q' }], remove: [] }), 'gap');
  assert.equal(store.applyPatch({ topic: 'quota', rev: 5, upsert: [], remove: ['p'] }), 'gap');
  assert.deepEqual(store.items('quota').map((i) => i.provider), ['p']);
  store.applySnapshot({ topic: 'overview', rev: 1, data: { key: null, items: [], meta: { paused: false } } });
  assert.equal(store.applyPatch({ topic: 'overview', rev: 2, upsert: [], remove: [], meta: { paused: true } }), 'ok');
  assert.equal(store.meta('overview').paused, true);
  assert.deepEqual(store.items('overview'), []);
});

test('store: listeners can be removed; a new snapshot replaces everything', () => {
  const store = new Store();
  let calls = 0;
  const off = store.on('t', () => { calls++; });
  store.applySnapshot({ topic: 't', rev: 1, data: { key: 'id', items: [{ id: 1 }], meta: {} } });
  off();
  store.applySnapshot({ topic: 't', rev: 9, data: { key: 'id', items: [{ id: 2 }], meta: {} } });
  assert.equal(calls, 1);
  assert.deepEqual(store.items('t'), [{ id: 2 }]);
});
