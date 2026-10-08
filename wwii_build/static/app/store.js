// Client-side store of the live topics. Pure (no DOM, no socket): the socket client feeds it
// snapshot/patch messages and the pages read from it. See wwii_build/live.py for the protocol.

export class Store {
  constructor() {
    this.topics = new Map();      // topic -> {rev, key, map: Map(key -> item), meta}
    this.listeners = new Map();   // topic -> Set(fn)
  }

  has(topic) { return this.topics.has(topic); }

  /** Items of a topic (insertion order), [] when nothing arrived yet. */
  items(topic) {
    const t = this.topics.get(topic);
    return t ? [...t.map.values()] : [];
  }

  meta(topic) {
    const t = this.topics.get(topic);
    return t ? t.meta : {};
  }

  /** {topic: rev} of everything held: sent on (re)subscribe so the server skips snapshots that are still current. */
  revs() {
    const out = {};
    for (const [name, t] of this.topics) out[name] = t.rev;
    return out;
  }

  on(topic, fn) {
    if (!this.listeners.has(topic)) this.listeners.set(topic, new Set());
    this.listeners.get(topic).add(fn);
    return () => this.listeners.get(topic)?.delete(fn);
  }

  _emit(topic) {
    for (const fn of [...(this.listeners.get(topic) || [])]) fn(this.topics.get(topic));
  }

  applySnapshot(msg) {
    const data = msg.data || {};
    const key = data.key ?? null;
    const map = new Map();
    for (const item of data.items || []) map.set(key ? String(item[key]) : map.size, item);
    this.topics.set(msg.topic, { rev: msg.rev, key, map, meta: data.meta || {} });
    this._emit(msg.topic);
    return 'ok';
  }

  /** 'ok' | 'gap' (missed a revision: the caller must resubscribe without a rev) | 'unknown' (no snapshot yet). */
  applyPatch(msg) {
    const t = this.topics.get(msg.topic);
    if (!t) return 'unknown';
    if (msg.rev !== t.rev + 1) return 'gap';
    for (const k of msg.remove || []) t.map.delete(String(k));
    for (const item of msg.upsert || []) t.map.set(t.key ? String(item[t.key]) : t.map.size, item);
    if (msg.meta !== undefined) t.meta = msg.meta;
    t.rev = msg.rev;
    this._emit(msg.topic);
    return 'ok';
  }

  drop(topic) {
    this.topics.delete(topic);
  }
}
