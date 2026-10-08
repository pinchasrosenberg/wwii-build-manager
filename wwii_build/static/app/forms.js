// Forms that submit as socket actions: the same action names and field names as the classic <form> POSTs.
// A form is built once; live updates only change option lists and *untouched* defaults, so text being typed survives.
import { h } from './dom.js';

/** A button that confirms (when asked), runs one action over the socket and shows the result toast. */
export function actionButton(ctx, label, cls, name, args, confirmText, title) {
  const button = h('button', { type: 'button', class: cls || null, title }, label);
  button.addEventListener('click', async () => {
    if (confirmText && !window.confirm(confirmText)) return;
    button.disabled = true;
    try { await ctx.act(name, typeof args === 'function' ? args() : args); } finally { button.disabled = false; }
  });
  return button;
}

export class Form {
  /**
   * @param {object} ctx                  page context (act, toast)
   * @param {string} action               action name (the classic form's hidden "action" value)
   * @param {object} [o]
   * @param {object} [o.fixed]            hidden fields (the classic forms' hidden inputs)
   * @param {string} [o.submit]           submit button label
   * @param {string} [o.cls]              submit button class ('go' by default)
   * @param {boolean} [o.reset]           clear the fields after an accepted action
   * @param {string} [o.confirm]          confirmation text
   * @param {(args: object) => Promise<{ok: boolean, message: string}>} [o.send]   replaces ctx.act (multipart uploads)
   * @param {(result: object, args: object) => void} [o.onResult]
   */
  constructor(ctx, action, o = {}) {
    this.ctx = ctx;
    this.action = action;
    this.o = o;
    this.fixed = o.fixed || {};
    this.fields = [];
    this.busy = false;
    this.el = h('form', { class: o.class || null, novalidate: true });
    this.button = h('button', { type: 'submit', class: o.cls === undefined ? 'go' : o.cls }, o.submit || 'שמור');
    this.el.addEventListener('submit', (e) => { e.preventDefault(); this.submit(); });
  }

  _add(name, kind, el, extra = {}) {
    const field = { name, kind, el, initial: extra.initial, label: extra.label, required: !!extra.required, dirty: false };
    const touched = () => { field.dirty = true; };
    el.addEventListener('input', touched);
    el.addEventListener('change', touched);
    this.fields.push(field);
    return field;
  }

  field(name) { return this.fields.find((f) => f.name === name); }

  _label(text) { return text ? h('label', { class: 'blk' }, text) : null; }

  /** @returns {Node[]} label + input */
  text(name, { label, value = '', placeholder, required, dir, type = 'text', cls, min, max, attrs } = {}) {
    const el = h('input', { type, name, placeholder, dir, class: cls, min, max, 'aria-label': label, ...attrs });
    el.value = value;
    this._add(name, 'text', el, { initial: value, label, required });
    return [this._label(label), el];
  }

  area(name, { label, value = '', placeholder, required, rows, dir, cls } = {}) {
    const el = h('textarea', { name, placeholder, rows, dir, class: cls, 'aria-label': label });
    el.value = value;
    this._add(name, 'text', el, { initial: value, label, required });
    return [this._label(label), el];
  }

  /** options: [[value, label]] */
  select(name, options, { label, value = '', cls = 'w', required } = {}) {
    const el = h('select', { name, class: cls, 'aria-label': label });
    for (const [v, text] of options) el.append(h('option', { value: v }, text));
    el.value = value;
    this._add(name, 'select', el, { initial: value, label, required });
    return [this._label(label), el];
  }

  check(name, text, { checked = false } = {}) {
    const el = h('input', { type: 'checkbox', name, value: '1' });
    el.checked = checked;
    this._add(name, 'check', el, { initial: checked, label: text });
    return h('label', null, el, ' ', text);
  }

  /** A list of checkboxes sharing one name (the classic multi-value fields); its value is the array of ticked values. */
  group(name, items, { label, empty } = {}) {
    const box = h('div', { class: 'picklist' });
    const field = this._add(name, 'group', box, { label });
    field.boxes = new Map();
    field.empty = empty;
    this._fillGroup(field, items);
    return [this._label(label), box];
  }

  _fillGroup(field, items) {
    const ticked = new Set([...field.boxes].filter(([, box]) => box.checked).map(([value]) => value));
    field.boxes = new Map();
    field.el.replaceChildren();
    for (const { value, label } of items) {
      const box = h('input', { type: 'checkbox', name: field.name, value });
      box.checked = ticked.has(value);
      box.addEventListener('change', () => { field.dirty = true; });
      field.boxes.set(value, box);
      field.el.append(h('label', null, box, ' ', label));
    }
    if (!items.length && field.empty) field.el.append(h('span', { class: 'muted' }, field.empty));
  }

  /** New option list for a select ([[value, label]]) or a group ([{value, label}]); the choice is kept when still offered. */
  setItems(name, items) {
    const field = this.field(name);
    if (!field) return;
    if (field.kind === 'group') return this._fillGroup(field, items);
    const chosen = field.el.value;
    field.el.replaceChildren();
    for (const [v, text] of items) field.el.append(h('option', { value: v }, text));
    const offered = (v) => items.some(([value]) => value === v);
    field.el.value = offered(chosen) ? chosen : offered(field.initial ?? '') ? (field.initial ?? '') : (items.length ? items[0][0] : '');
  }

  /** Server-side value for a field the user has not touched. */
  setDefault(name, value) {
    const field = this.field(name);
    if (!field || field.dirty) return;
    if (field.kind === 'check') field.el.checked = !!value;
    else field.el.value = value ?? '';
    field.initial = value ?? '';
  }

  values() {
    const out = { ...this.fixed };
    for (const f of this.fields) {
      if (f.kind === 'check') out[f.name] = f.el.checked;
      else if (f.kind === 'group') out[f.name] = [...f.boxes].filter(([, box]) => box.checked).map(([value]) => value);
      else out[f.name] = f.el.value;
    }
    return out;
  }

  clear() {
    for (const f of this.fields) {
      f.dirty = false;
      if (f.kind === 'check') f.el.checked = !!f.initial;
      else if (f.kind === 'group') f.boxes.forEach((box) => { box.checked = false; });
      else {
        f.el.value = f.initial ?? '';
        // a select whose initial value is not offered (a required parent picker) shows its first option, not a blank
        if (f.kind === 'select' && f.el.value !== String(f.initial ?? '') && f.el.options?.length) f.el.value = f.el.options[0].getAttribute('value');
      }
    }
  }

  /** Append the given nodes and the submit row; returns the <form>. */
  build(...children) {
    this.el.append(...children.flat(Infinity).filter((n) => n !== null && n !== undefined));
    this.el.append(h('div', { class: 'form-actions' }, this.button, ...(this.o.extraButtons || [])));
    return this.el;
  }

  async submit() {
    if (this.busy) return null;
    for (const f of this.fields) {
      if (f.required && !String(f.el.value).trim()) {
        this.ctx.toast(`יש למלא: ${f.label || f.name}`, false);
        if (f.el.focus) f.el.focus();
        return null;
      }
    }
    if (this.o.confirm && !window.confirm(this.o.confirm)) return null;
    this.busy = true;
    this.button.disabled = true;
    try {
      const args = this.values();
      const result = await (this.o.send ? this.o.send(args) : this.ctx.act(this.action, args));
      if (result.ok) {
        if (this.o.reset) this.clear();
        else this.fields.forEach((f) => { f.dirty = false; });   // the saved value is the server's value from now on
      }
      if (this.o.onResult) this.o.onResult(result, args);
      return result;
    } finally {
      this.busy = false;
      this.button.disabled = false;
    }
  }
}
