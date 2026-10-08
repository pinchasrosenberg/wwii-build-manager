// Battle request ('בקשת קרב'): one action (battle_request, the same field names as the classic form) creates the whole
// battle-builder task chain. The chain shown is described by /api/battle-request-options (the templates file); task
// states come live from the tasks topic.
import { h, setChildren } from '../dom.js';
import { taskHash } from '../format.js';
import { Form } from '../forms.js';
import { pill } from '../ui.js';
import { makeWatcher } from '../widgets.js';

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  let options = { stages: [], chains: [], error: '' };
  let alive = true;

  const form = new Form(ctx, 'battle_request', {
    submit: 'צור שרשרת קרב', cls: 'big go', reset: true,
    onResult: (result) => {
      if (!result.ok) return;
      load();
      const first = /MANUAL\/[^\s,]+/.exec(String(result.message || ''));
      if (first) location.hash = taskHash(first[0]);
    },
  });
  const stagesBox = h('section', { class: 'card' });
  const chainsBox = h('section', null);

  const formEl = form.build(
    form.text('title', { label: 'שם הקרב', required: true, placeholder: 'Brécourt Manor assault' }),
    form.text('battle_key', { label: 'battle_key (slug; נוצר מהכותרת אם ריק)', dir: 'ltr', placeholder: 'brecourt-manor-assault' }),
    form.text('date', { label: 'תאריך או טווח (YYYY-MM-DD או YYYY-MM-DD..YYYY-MM-DD)', required: true, dir: 'ltr', placeholder: '1944-06-06' }),
    form.text('bbox', { label: 'bbox (מערב,דרום,מזרח,צפון; לא חובה)', dir: 'ltr', placeholder: '-1.3,49.3,-1.1,49.5' }),
    form.text('place', { label: 'מקום (לא חובה)' }),
    form.area('notes', { label: 'הערות לחוקרים (לא חובה)', rows: 4 }));

  setChildren(root,
    h('section', null, h('h1', null, 'בקשת קרב — שרשרת הבנייה המלאה בפעולה אחת'),
      h('p', { class: 'muted' }, 'הקלט הוא כותרת, תאריך (או טווח) ואופציונלית מקום, bbox והערות. הפעולה יוצרת את כל השרשרת: תיק ראיות ← מחקר מפות (חובה) ← ' +
        'מחקר LLM ברשת עם חיפוש מונחה פערים ← שחזור ← חבילת אפיזודה. לכל משימה תחום כתיבה תחת ',
        h('span', { class: 'mono' }, 'game/episodes/<battle_key>/'), ' בלבד, מודל לפי התאמה ובדיקות קבלה על הקבצים שנוצרו. רק משימת המחקר מקבלת גישה לרשת. ' +
        'בקשה כפולה לשרשרת פעילה של אותו battle_key נדחית. התבניות נערכות בקובץ ',
        h('span', { class: 'mono' }, 'tools/build_manager/systems/battle_request_templates.toml'), '.')),
    h('section', { class: 'card', style: 'border-color:#5b91d1' }, formEl),
    h('h2', null, 'השרשרת שתיווצר'), stagesBox,
    h('h2', null, 'שרשראות שנוצרו'), chainsBox);

  function renderStages() {
    if (options.error) return setChildren(stagesBox, h('div', { class: 'banner' }, options.error));
    setChildren(stagesBox, h('table', null,
      h('tr', null, ['שלב', 'משימה', 'מודול', 'מודל', 'גישה לרשת', 'אחרי'].map((c) => h('th', null, c))),
      options.stages.map((s) => h('tr', null, h('td', { class: 'mono' }, s.stage), h('td', null, s.title), h('td', { class: 'mono' }, s.deliver),
        h('td', { class: 'mono' }, s.model_key || 'auto'), h('td', null, s.allow_web ? 'כן' : 'לא'), h('td', { class: 'mono' }, s.depends_on.join(', ') || '-')))));
  }

  function renderChains() {
    const live = new Map(store.items('tasks.active').map((t) => [t.task_id, t.state]));
    if (!options.chains.length) return setChildren(chainsBox, h('div', { class: 'muted' }, 'עוד לא נוצרו שרשראות קרב.'));
    setChildren(chainsBox, options.chains.map((c) => h('div', { class: 'card' }, h('b', { class: 'mono' }, c.battle_key), ' ', c.title,
      h('div', null, c.tasks.map((t) => [h('a', { href: taskHash(t.task_id) }, t.stage), ' ', pill(live.get(t.task_id) || t.state), ' '])))));
  }

  function load() {
    return ctx.fetchJson('/api/battle-request-options').then((data) => { if (alive) { options = data; renderStages(); renderChains(); } })
      .catch(() => ctx.toast('טעינת תבניות הקרב נכשלה', false));
  }

  watch('tasks.active', renderChains);
  renderStages();
  renderChains();
  ctx.setTopics(['tasks.active']);
  load();
  return () => { alive = false; stop(); };
}
