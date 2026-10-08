// Long socket actions: one live progress panel per running operation, and a busy state buttons can follow.
// The server streams {"type":"progress","id","line"} before the action.result (wwii_build/live.py); only one
// unstick / system_onboard may run at a time, so a second request is refused here as well as on the server.
import { h, setChildren } from './dom.js';

export const ALREADY_RUNNING = 'כבר רץ';
export const LONG_ACTIONS = {
  unstick: { title: 'למה הריצה תקועה?', single: true },
  system_onboard: { title: 'הטמעת מערכת', single: true },
  state_chat: { title: 'שיחה על המצב', single: false },
  graph_console_query: { title: 'שאילתת גרף', single: false },
};
const MAX_LINES = 200;
const LABELS = { thinking: 'המודל חושב…' };   // lines the server sends as codes
const LINGER_MS = { ok: 8000, bad: 15000 };

export class Operations {
  /**
   * @param {HTMLElement|null} box                     where the panels go (null: only the busy state is tracked)
   * @param {object} [o]
   * @param {(fn: () => void, ms: number) => any} [o.setTimer]
   */
  constructor(box, o = {}) {
    this.box = box;
    this.setTimer = o.setTimer || ((fn, ms) => setTimeout(fn, ms));
    this.counts = new Map();      // action name -> number of runs in flight
    this.listeners = new Set();
  }

  isLong(name) { return Object.hasOwn(LONG_ACTIONS, name); }

  running(name) { return (this.counts.get(name) || 0) > 0; }

  /** Call fn() whenever an operation starts or ends; returns the unsubscribe function. */
  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  _notify() { for (const fn of [...this.listeners]) fn(); }

  /**
   * Disable `button` while any of `names` runs (anywhere in the app); returns the unsubscribe function.
   * A button the user already disabled is left alone when the operation ends.
   */
  bind(button, ...names) {
    let locked = false;
    const apply = () => {
      const busy = names.some((n) => this.running(n));
      if (busy && !button.disabled) { button.disabled = true; locked = true; }
      else if (!busy && locked) { button.disabled = false; locked = false; }
    };
    apply();
    return this.subscribe(apply);
  }

  /**
   * Start tracking one run. Returns null for an action that is not long-running, `{refused: true}` when a
   * single-flight action is already running, otherwise `{line(text), end({ok, message})}`.
   */
  begin(name) {
    if (!this.isLong(name)) return null;
    const spec = LONG_ACTIONS[name];
    if (spec.single && this.running(name)) return { refused: true };
    this.counts.set(name, (this.counts.get(name) || 0) + 1);
    const lines = h('ul', { class: 'op-lines' });
    const status = h('span', { class: 'op-status' }, 'רץ…');
    const close = h('button', { type: 'button', class: 'op-close', 'aria-label': 'סגור' }, '×');
    const panel = h('section', { class: 'op-panel running', dataset: { op: name }, role: 'status' },
      h('div', { class: 'op-head' }, h('b', null, spec.title), status, close), lines);
    const remove = () => panel.remove();
    close.addEventListener('click', remove);
    if (this.box) this.box.append(panel);
    this._notify();
    let finished = false;
    return {
      panel,
      line: (text) => {
        if (finished) return;
        lines.append(h('li', null, LABELS[text] || text));
        while (lines.children.length > MAX_LINES) lines.firstChild.remove();
      },
      end: (result) => {
        if (finished) return;
        finished = true;
        this.counts.set(name, Math.max(0, (this.counts.get(name) || 1) - 1));
        const ok = !!(result && result.ok);
        panel.className = `op-panel ${ok ? 'ok' : 'bad'}`;
        setChildren(status, `${ok ? '✓ ' : '✗ '}${(result && result.message) || ''}`);
        this._notify();
        this.setTimer(remove, ok ? LINGER_MS.ok : LINGER_MS.bad);
      },
    };
  }
}
