// WebSocket client for /ws (protocol: wwii_build/ws.py and wwii_build/live.py).
// hello(token) -> welcome -> subscribe (with the revs already held) -> snapshots/patches into the Store.
// A dropped socket reconnects with exponential backoff and resubscribes with the same revs, so topics that did not
// change cost nothing. Only an explicit 1012 service restart may reload a newly versioned browser app.
import { backoffDelay } from './format.js';

const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_SERVICE_RESTART = 1012;
const PING_MS = 20000;
const SILENCE_MS = 60000;

export class LiveSocket {
  /**
   * @param {object} o
   * @param {import('./store.js').Store} o.store
   * @param {() => string} o.getToken                  token for hello
   * @param {() => Promise<void>} [o.renewToken]       called after a 4401 (the dashboard restarted: new token)
   * @param {(online: boolean) => void} [o.onStatus]
   * @param {(msg: object) => void} [o.onError]        server "error" messages
   * @param {() => string} [o.url]
   * @param {() => void} [o.reload]                    full reload after a versioned 1012 service restart
   */
  constructor(o) {
    this.store = o.store;
    this.getToken = o.getToken;
    this.renewToken = o.renewToken || (async () => {});
    this.onStatus = o.onStatus || (() => {});
    this.onError = o.onError || (() => {});
    this.reload = o.reload || (() => globalThis.location.reload());
    this.url = o.url || (() => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    this.WebSocketImpl = o.WebSocketImpl || globalThis.WebSocket;
    this.setTimer = o.setTimer || ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = o.clearTimer || ((t) => clearTimeout(t));
    this.random = o.random || Math.random;
    this.now = o.now || Date.now;
    this.desired = new Set();      // topics the visible page wants
    this.subscribed = new Set();   // topics subscribed on the current connection
    this.ws = null;
    this.ready = false;            // welcome received
    this.attempt = 0;
    this.nextId = 1;
    this.pending = new Map();      // action id -> {resolve}
    this.requests = new Map();     // read-only request id -> {resolve}
    this.lastRx = 0;
    this._retry = null;
    this._ping = null;
    this._stopped = false;
    this._needToken = false;
    this.version = null;
    this._restartVersion = undefined;
  }

  connect() {
    this._stopped = false;
    if (this.ws) return;
    let ws;
    try {
      ws = new this.WebSocketImpl(this.url());
    } catch (e) {
      return this._scheduleRetry();
    }
    this.ws = ws;
    ws.onopen = () => {
      this.lastRx = this.now();
      this._send({ type: 'hello', token: this.getToken() });
    };
    ws.onmessage = (ev) => this._onMessage(ev.data);
    ws.onclose = (ev) => this._onClose(ws, ev);
    ws.onerror = () => {};   // a close always follows
  }

  close() {
    this._stopped = true;
    this.clearTimer(this._retry);
    this.clearTimer(this._ping);
    if (this.ws) this.ws.close();
  }

  /** Replace the set of topics the page wants; sends only the difference when online. */
  setTopics(topics) {
    this.desired = new Set(topics);
    if (!this.ready) return;
    const add = [...this.desired].filter((t) => !this.subscribed.has(t));
    const drop = [...this.subscribed].filter((t) => !this.desired.has(t));
    if (drop.length) {
      this._send({ type: 'unsubscribe', topics: drop });
      drop.forEach((t) => this.subscribed.delete(t));
    }
    if (add.length) this._subscribe(add);
  }

  /**
   * Send {"type":"action"}; resolves {ok, message} (also when offline or when the connection drops meanwhile).
   * `onProgress(line)` hears the {"type":"progress"} lines a long action pushes before its result.
   */
  action(name, args = {}, onProgress = null) {
    if (!this.ready) return Promise.resolve({ ok: false, message: 'אין חיבור לשרת כרגע; הפעולה לא נשלחה' });
    const id = `a${this.nextId++}`;
    return new Promise((resolve) => {
      this.pending.set(id, { resolve, onProgress });
      if (!this._send({ type: 'action', id, name, args })) {
        this.pending.delete(id);
        resolve({ ok: false, message: 'אין חיבור לשרת כרגע; הפעולה לא נשלחה' });
      }
    });
  }

  /** A correlated, read-only socket request (history search or dependency detail). */
  request(type, payload = {}) {
    if (!this.ready) return Promise.resolve({ ok: false, error: 'offline' });
    const id = `q${this.nextId++}`;
    return new Promise((resolve) => {
      this.requests.set(id, { resolve });
      if (!this._send({ ...payload, type, id })) {
        this.requests.delete(id);
        resolve({ ok: false, error: 'offline' });
      }
    });
  }

  _subscribe(topics, withRevs = true) {
    const revs = withRevs ? this.store.revs() : {};
    topics.forEach((t) => this.subscribed.add(t));
    this._send({ type: 'subscribe', topics, revs: Object.fromEntries(topics.filter((t) => t in revs).map((t) => [t, revs[t]])) });
  }

  _send(obj) {
    if (!this.ws || this.ws.readyState !== 1) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }

  _onMessage(raw) {
    this.lastRx = this.now();
    let msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    switch (msg.type) {
      case 'welcome':
        {
          const version = typeof msg.version === 'string' ? msg.version : '';
          if (this._restartVersion !== undefined) {
            const beforeRestart = this._restartVersion;
            this._restartVersion = undefined;
            if (beforeRestart && version && version !== beforeRestart) {
              this.version = version;
              this.reload();
              return;
            }
          }
          if (version) this.version = version;
        }
        this.ready = true;
        this.attempt = 0;
        this.subscribed.clear();
        this.onStatus(true);
        this.clearTimer(this._ping);
        this._ping = this.setTimer(() => this._heartbeat(), PING_MS);
        if (this.desired.size) this._subscribe([...this.desired]);
        break;
      case 'snapshot':
        this.store.applySnapshot(msg);
        break;
      case 'patch':
        if (this.store.applyPatch(msg) !== 'ok') this._subscribe([msg.topic], false);   // missed a rev: fresh snapshot
        break;
      case 'progress': {
        const p = this.pending.get(msg.id);
        if (p && p.onProgress) p.onProgress(String(msg.line ?? ''));
        break;
      }
      case 'action.result': {
        const p = this.pending.get(msg.id);
        if (p) {
          this.pending.delete(msg.id);
          p.resolve({ ok: !!msg.ok, message: String(msg.message ?? '') });
        }
        break;
      }
      case 'search.result':
      case 'task.detail.result': {
        const p = this.requests.get(msg.id);
        if (p) {
          this.requests.delete(msg.id);
          p.resolve(msg);
        }
        break;
      }
      case 'error':
        this.onError(msg);
        break;
      default:   // subscribed / pong
    }
  }

  _heartbeat() {
    if (!this.ws || !this.ready) return;
    if (this.now() - this.lastRx > SILENCE_MS) return this.ws.close();   // half-open socket: reconnect
    this._send({ type: 'ping' });
    this._ping = this.setTimer(() => this._heartbeat(), PING_MS);
  }

  _onClose(ws, ev) {
    if (this.ws !== ws) return;
    this.ws = null;
    const wasReady = this.ready;
    this.ready = false;
    this.subscribed.clear();
    this.clearTimer(this._ping);
    for (const [, p] of this.pending) {
      p.resolve({ ok: false, message: 'החיבור נותק לפני שהתקבלה תשובה; ייתכן שהפעולה בוצעה — בדקו במצב הנוכחי' });
    }
    this.pending.clear();
    for (const [, p] of this.requests) p.resolve({ ok: false, error: 'disconnected' });
    this.requests.clear();
    if (wasReady || this.attempt === 0) this.onStatus(false);
    if (ev && ev.code === CLOSE_UNAUTHORIZED) this._needToken = true;
    if (ev && ev.code === CLOSE_SERVICE_RESTART) {
      if (this._restartVersion === undefined) this._restartVersion = this.version;
      this._needToken = true;
    }
    if (!this._stopped) this._scheduleRetry();
  }

  _scheduleRetry() {
    const delay = backoffDelay(this.attempt++, this.random());
    this.clearTimer(this._retry);
    this._retry = this.setTimer(async () => {
      if (this._needToken) {
        this._needToken = false;
        try { await this.renewToken(); } catch (e) { /* the next attempt will try again */ }
      }
      this.connect();
    }, delay);
  }
}
