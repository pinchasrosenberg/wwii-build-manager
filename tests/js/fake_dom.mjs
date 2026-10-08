// A just-big-enough DOM for the app's pages under node (no jsdom: stdlib-only project). Test support, not product code.

export class FakeNode {
  constructor() { this.parentNode = null; }
  get nextSibling() {
    const sibs = this.parentNode?.childNodes;
    return sibs ? sibs[sibs.indexOf(this) + 1] ?? null : null;
  }
  remove() { this.parentNode?._detach(this); }
}

export class FakeText extends FakeNode {
  constructor(text) { super(); this.data = String(text); }
  get textContent() { return this.data; }
}

export class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.tagName = tag.toUpperCase();
    this.attrs = {};
    this.childNodes = [];
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.disabled = false;
    this.className = '';
    this._value = '';
  }

  get children() { return this.childNodes.filter((n) => n instanceof FakeElement); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get firstElementChild() { return this.children[0] ?? null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] ?? null; }
  get options() { return this.children.filter((c) => c.tagName === 'OPTION'); }

  get value() {
    if (this.tagName === 'SELECT') {
      const opts = this.options;
      return opts.some((o) => o.attrs.value === this._value) ? this._value : (opts[0]?.attrs.value ?? '');
    }
    return this._value;
  }
  set value(v) { this._value = String(v); }

  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(t) { this.replaceChildren(new FakeText(t)); }

  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }

  _detach(node) {
    const i = this.childNodes.indexOf(node);
    if (i >= 0) this.childNodes.splice(i, 1);
    node.parentNode = null;
  }
  _adopt(node) {
    node.parentNode?._detach(node);
    node.parentNode = this;
  }
  append(...nodes) {
    for (const n of nodes) {
      const node = typeof n === 'string' ? new FakeText(n) : n;
      this._adopt(node);
      this.childNodes.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const n of [...this.childNodes]) this._detach(n);
    this.append(...nodes);
  }
  insertBefore(node, ref) {
    this._adopt(node);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    if (i < 0) this.childNodes.push(node);
    else this.childNodes.splice(i, 0, node);
    return node;
  }

  /** Supports `[data-name]` and `tag` / `.class` selectors, which is all the pages use. */
  querySelectorAll(selector) {
    const out = [];
    const attr = /^\[data-([a-z-]+)\]$/.exec(selector);
    const walk = (el) => {
      for (const c of el.children) {
        const hit = attr ? attr[1] in c.dataset
          : selector.startsWith('.') ? c.className.split(/\s+/).includes(selector.slice(1))
            : c.tagName === selector.toUpperCase();
        if (hit) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }

  fire(type, extra = {}) {
    const event = { type, target: this, preventDefault() {}, ...extra };
    for (const fn of this.listeners[type] || []) fn(event);
    return event;
  }
  click() { return this.fire('click'); }
}

/** Install document/window/rAF/interval stubs; returns controls and an uninstall function. */
export function installDom() {
  const saved = {};
  const names = ['document', 'window', 'Node', 'requestAnimationFrame', 'setInterval', 'clearInterval'];
  for (const n of names) saved[n] = Object.getOwnPropertyDescriptor(globalThis, n);
  const frames = [];
  const intervals = new Map();
  let nextTimer = 1;
  const confirms = { answer: true, asked: [] };
  const define = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  define('document', {
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (t) => new FakeText(t),
    getElementById: () => null,
  });
  define('Node', FakeNode);
  define('window', { confirm: (text) => { confirms.asked.push(text); return confirms.answer; } });
  define('requestAnimationFrame', (fn) => { frames.push(fn); return frames.length; });
  define('setInterval', (fn) => { intervals.set(nextTimer, fn); return nextTimer++; });
  define('clearInterval', (id) => { intervals.delete(id); });
  return {
    confirms,
    intervals,
    /** Run every queued animation frame (callbacks queued while flushing run too). */
    flush() { while (frames.length) frames.shift()(); },
    tick() { for (const fn of [...intervals.values()]) fn(); },
    uninstall() {
      for (const n of names) {
        if (saved[n]) Object.defineProperty(globalThis, n, saved[n]);
        else delete globalThis[n];
      }
    },
  };
}

export function findAll(root, pred) {
  const out = [];
  const walk = (el) => { for (const c of el.children) { if (pred(c)) out.push(c); walk(c); } };
  walk(root);
  return out;
}

export const byTag = (root, tag) => findAll(root, (e) => e.tagName === tag.toUpperCase());
export const buttonByText = (root, text) => findAll(root, (e) => e.tagName === 'BUTTON' && e.textContent === text)[0];
