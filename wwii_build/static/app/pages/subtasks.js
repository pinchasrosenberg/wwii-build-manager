// Subtasks and reuse patterns: create a saved subtask by hand, see the patterns learned from real subtasks and promote
// an eligible pattern to a Deliver. Topic: subtasks (patterns as items; parent candidates, models and the default
// promotion threshold in meta).
import { h, setChildren, syncList } from '../dom.js';
import { reusePercent, deliverHash } from '../format.js';
import { Form } from '../forms.js';
import { subtaskForm } from '../subtask_form.js';
import { pill } from '../ui.js';
import { card, count, details, makeWatcher, sig, taskLink } from '../widgets.js';

const tag = (text) => h('span', null, text);

function promotionForm(ctx, p) {
  const spec = p.spec || {};
  const form = new Form(ctx, 'promote_subtask', { fixed: { pattern_hash: p.pattern_hash }, submit: 'קדם ל־Deliver', reset: false });
  return h('div', { class: 'promotion-box' }, h('b', null, 'הדפוס כשיר לקידום'),
    h('p', { class: 'muted' }, 'בדוק את החוזה ובחר מזהה קבוע. הקידום ייצור Deliver אמיתי; הוא אינו מתבצע אוטומטית.'),
    form.build(form.text('deliver_id', { label: 'מזהה Deliver', value: p.suggestion, required: true, dir: 'ltr' }),
      h('div', { class: 'grid2' }, form.text('owner', { value: spec.owner || '', placeholder: 'אחראי' }), form.text('domain', { placeholder: 'תחום' })),
      form.text('description', { label: 'תיאור', value: p.title })));
}

/** One learned pattern as a card: contract tags, reuse meter, history and (when eligible) the promotion form. */
export function patternCard(ctx, p) {
  const spec = p.spec || {};
  const tags = [`מודל ${spec.model_key || 'אוטומטי'}`, `${(spec.context_files || []).length} קבצי קונטקסט`,
    `${(spec.mcp_servers || []).length} שרתי MCP`, `${(spec.tool_names || []).length} כלים`];
  return h('div', { class: `card pattern-card ${p.promotion_status}` },
    h('div', { class: 'bar' }, h('b', null, p.title), pill(String(p.promotion_status).toUpperCase())),
    h('p', null, spec.instructions || 'אין הוראות'), h('div', { class: 'contract-tags' }, tags.map(tag)),
    h('div', { class: 'reuse-meter' }, h('span', { style: `width:${reusePercent(p.reuse_count, p.promotion_threshold)}%` })),
    h('p', null, h('b', null, p.reuse_count), ' שימושים בפועל מתוך ', h('b', null, p.promotion_threshold), ' שנדרשים לקידום'),
    details('חוזה מלא והיסטוריית שימוש', h('pre', null, JSON.stringify(spec, null, 2)),
      h('ul', null, p.occurrences.map((o) => h('li', null, o.child_task_id ? taskLink(o.child_task_id) : '—', ' מתוך ',
        h('span', { class: 'mono' }, o.parent_task_id), ` · ${o.source}`)))),
    p.promotion_status === 'eligible' ? promotionForm(ctx, p) : null,
    p.promotion_status === 'promoted' ? h('p', { class: 'section-note' }, 'קוּדם ל־', h('a', { class: 'mono', href: deliverHash(p.promoted_deliver_id) }, p.promoted_deliver_id)) : null);
}

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const sigs = {};
  const sub = subtaskForm(ctx);
  const counts = h('div', { class: 'counts' });
  const grid = h('div', { class: 'pattern-grid' });

  setChildren(root,
    h('section', { class: 'control-hero' }, h('div', { class: 'eyebrow' }, 'למידה לפני הפיכה ליכולת קבועה'), h('h1', null, 'תתי־משימות ודפוסי שימוש חוזר'),
      h('p', null, 'סוכן רשאי לפרק עבודה לתתי־משימות שמורות, ולכל אחת לבחור מודל, קונטקסט, MCP וכלים אחרים. רק מופעים שנוצרו בפועל נספרים. ' +
        'אחרי שימוש חוזר הדפוס נעשה כשיר, ורק קידום מפורש יוצר ממנו Deliver עם חוזה קבוע.')),
    counts,
    h('div', { class: 'grid2' },
      h('div', null, h('h2', null, 'צור תת־משימה ידנית'), card(sub.el)),
      h('div', null, h('h2', null, 'כלל ההפרדה'), card(
        h('p', null, h('b', null, 'Task / Subtask'), ' הוא מופע עבודה עם הקשר וכלים נקודתיים.'),
        h('p', null, h('b', null, 'Pattern'), ' הוא חוזה זהה שנצפה בשימוש אמיתי כמה פעמים.'),
        h('p', null, h('b', null, 'Deliver'), ' הוא יכולת קבועה, מתומחרת ומנוהלת, שנוצרה רק לאחר בדיקה וקידום.'),
        h('p', { class: 'section-note' }, 'הספירה אינה כוללת הצעות שנדחו או שלא אושרו.')))),
    h('h2', null, 'דפוסים שנלמדו'), grid);

  function render() {
    const patterns = store.items('subtasks');
    const m = store.meta('subtasks');
    setChildren(counts, count('דפוסים שנלמדו', patterns.length),
      count('ממתינים להחלטת קידום', patterns.filter((p) => p.promotion_status === 'eligible').length),
      count('קודמו ל־Deliver', patterns.filter((p) => p.promotion_status === 'promoted').length),
      count('סף ברירת מחדל', `${m.default_threshold ?? 'לא ידוע'} שימושים`));
    const key = sig(m.parents, m.models);
    if (sigs.options !== key) {
      sigs.options = key;
      sub.update({ models: m.models, parents: m.parents || [] });
    }
    const rank = { eligible: 0, learning: 1 };
    syncList(grid, patterns.sort((a, b) => (rank[a.promotion_status] ?? 2) - (rank[b.promotion_status] ?? 2)), {
      key: (p) => p.pattern_hash, sig: (p) => sig(p), build: (p) => patternCard(ctx, p),
      empty: () => card(h('p', { class: 'muted' }, 'עדיין אין דפוסי שימוש. הם יופיעו לאחר שמתכנן או סוכן ייצרו תתי־משימות בפועל.')),
    });
  }

  watch('subtasks', render);
  render();
  ctx.setTopics(['subtasks']);
  return stop;
}
