// Planner: a prompt with a mode, optional files (the multipart upload stays an HTTP POST) and the plan requests with
// their proposals (approve / reject). The result of a request arrives through the plan topic.
// Topic: plan (plan tasks as items, model profiles in meta).
import { h, setChildren, syncList } from '../dom.js';
import { Form, actionButton } from '../forms.js';
import { pill } from '../ui.js';
import { card, makeWatcher, modelChoices, sig, table, taskLink } from '../widgets.js';

export const MAX_FILES = 8;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 25 * 1024 * 1024;
const MODES = [['plan_build', 'תכנן משימה רחבה לביצוע'], ['advise_next', 'ייעוץ בלבד: הצעד הבא'], ['graph_query', 'תשובה מהגרף']];

/** The first reason the selected files cannot be sent (the same limits the server enforces), or null. */
export function uploadProblem(files) {
  if (files.length > MAX_FILES) return `אפשר לצרף עד ${MAX_FILES} קבצים בכל בקשה`;
  let total = 0;
  for (const f of files) {
    if (!f.size) return `הקובץ ${f.name} ריק`;
    if (f.size > MAX_FILE_BYTES) return `הקובץ ${f.name} גדול מ־10MB`;
    total += f.size;
  }
  return total > MAX_TOTAL_BYTES ? 'סך הקבצים גדול מ־25MB' : null;
}

const list = (xs) => (xs || []).join(', ');

function proposalView(ctx, p) {
  const validation = p.validation.map((m) => h('li', { class: m.level === 'error' ? 'err' : 'warn' }, `[${m.key}] ${m.message}`));
  return h('div', null, h('h2', null, `#${p.id} · משימות מוצעות `, pill(String(p.status).toUpperCase())), h('p', null, p.summary),
    p.questions.length ? h('ul', null, p.questions.map((q) => h('li', null, q))) : null,
    table(['key', 'title', 'model', 'deps', 'scope', 'context', 'MCP servers', 'checks'], h('tbody', null, p.tasks.map((t) => h('tr', null,
      h('td', { class: 'mono' }, t.key), h('td', null, t.title, h('div', { class: 'muted' }, t.instructions)), h('td', { class: 'mono' }, t.model_key),
      h('td', { class: 'mono' }, list(t.depends_on)), h('td', { class: 'mono' }, list(t.write_scope) + (t.read_only ? ' (read-only)' : '')),
      h('td', { class: 'mono' }, list(t.context_files), h('div', { class: 'muted' }, list(t.context_source_ids))),
      h('td', { class: 'mono' }, list(t.mcp_servers)), h('td', { class: 'mono' }, (t.acceptance_commands || []).join(' | ')))))),
    validation.length ? h('ul', null, validation) : null,
    p.approval_id ? h('p', null, actionButton(ctx, 'Approve', 'go', 'approve', { approval_id: p.approval_id }), ' ',
      actionButton(ctx, 'Reject', '', 'reject', { approval_id: p.approval_id })) : null,
    p.created_task_ids.length ? h('p', null, 'נוצרו: ', p.created_task_ids.map((id) => [taskLink(id), ' '])) : null);
}

export function planCard(ctx, pt) {
  const chips = pt.attachments.length
    ? h('div', { class: 'attachment-history' }, h('b', null, 'קבצים מצורפים:'), pt.attachments.map((a) =>
      h('span', { class: `upload-chip${a.selected ? ' selected' : ''}`, title: a.selected ? 'נבחר על ידי Jev' : 'לא נבחר עדיין' },
        `${a.name} · ${(a.size_bytes / 1024).toFixed(1)}KB${a.selected ? ' · נבחר' : ''}`))) : null;
  return card(h('b', { class: 'mono' }, pt.task_id), ' ', pill(pt.state), ' ', h('span', { class: 'muted' }, pt.state_reason || ''),
    h('pre', null, pt.prompt), chips, pt.proposals.map((p) => proposalView(ctx, p)));
}

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const sigs = {};
  let files = [];

  const form = new Form(ctx, 'plan', {
    submit: 'שלח למתכנן', cls: 'big go', class: 'prompt-grid', reset: true,
    // files go as a multipart POST; without files the same fields go over the socket
    send: async (args) => {
      const problem = uploadProblem(files);
      if (problem) { ctx.toast(problem, false); return { ok: false, message: problem }; }
      return files.length ? ctx.upload('plan', args, files) : ctx.act('plan', args);
    },
    onResult: (result) => { if (result.ok) { files = []; renderFiles(); } },
  });

  const picker = h('input', { type: 'file', name: 'planner_files', multiple: true, hidden: true,
    accept: 'image/png,image/jpeg,image/gif,image/webp,text/*,.md,.json,.yaml,.yml,.toml,.csv,.tsv,.pdf' });
  const chipsEl = h('div', { class: 'upload-list', 'aria-live': 'polite' });
  const zone = h('div', { class: 'upload-zone', role: 'button', tabindex: '0', 'aria-label': 'העלאת קבצים ותמונות למתכנן' },
    h('span', { class: 'upload-icon' }, '＋'), h('strong', null, 'גררו לכאן תמונות וקבצים, או לחצו לבחירה'),
    h('small', null, 'עד 8 קבצים, 10MB לקובץ ו־25MB בסך הכול. רק פריטים ש־Jev יבחר יגיעו למודל.'), picker, chipsEl);

  function renderFiles() {
    setChildren(chipsEl, files.map((f, i) => {
      const remove = h('button', { type: 'button', title: 'הסר' }, '×');
      remove.addEventListener('click', (e) => { e.stopPropagation(); files.splice(i, 1); renderFiles(); });
      return h('span', { class: 'upload-chip' }, `${f.name} · ${(f.size / 1024).toFixed(1)}KB `, remove);
    }));
  }
  function addFiles(picked) {
    files = [...files, ...picked].slice(0, MAX_FILES + 1);     // one over the limit is kept so the problem is reported
    renderFiles();
  }
  zone.addEventListener('click', () => picker.click());
  zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); picker.click(); } });
  picker.addEventListener('click', (e) => e.stopPropagation());
  picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', (e) => { e.preventDefault(); zone.classList.remove('dragging'); addFiles([...(e.dataTransfer?.files || [])]); });

  const formEl = form.build(
    form.area('prompt', { label: 'מה התוצאה הרחבה שצריך לתכנן?', required: true, rows: 8, cls: 'planner-main-prompt',
      placeholder: 'לדוגמה: תכנן את כל רכיבי הלגו הדרושים למערכת מזג אוויר היסטורית באפיזודה.' }),
    zone,
    h('div', { class: 'planner-controls' },
      form.select('prompt_mode', MODES, { value: 'plan_build', cls: null, label: 'מה המתכנן יעשה' }),
      h('span', { class: 'muted' }, 'האישור האוטומטי קובע אם ההצעה נעצרת לאישורך.'),
      h('details', null, h('summary', null, 'עקיפות מתקדמות — בדרך כלל המתכנן בוחר לבד'), h('div', { class: 'advanced-grid' },
        form.select('model_key', [['', 'אוטומטי: המודל המתאים ביותר']], { cls: null, label: 'עקיפת מודל המתכנן' }),
        form.text('mcp_servers', { placeholder: 'MCP ידני, רק אם חייבים', label: 'עקיפת שרתי MCP' })))));
  const plans = h('div');

  setChildren(root, h('h1', null, 'מתכנן המערכת — בקשה רחבה למשימות'),
    h('div', { class: 'section-note' }, 'כאן מתארים יעד שעדיין צריך לפרק. המתכנן מחזיר הצעה של משימות, תלויות, מודלים וכלים; עובדי המשימות יבצעו אותה רק אחרי אישור. ' +
      'לביצוע ישיר ומוגדר של משימה אחת משתמשים ב־', h('a', { href: '#/new' }, 'משימת ביצוע חדשה'), '.'),
    h('div', { class: 'card prompt-console' }, formEl),
    h('h2', null, 'בקשות תכנון'), plans);

  function render() {
    const key = sig(store.meta('plan').models);
    if (sigs.models !== key) {
      sigs.models = key;
      form.setItems('model_key', [['', 'אוטומטי: המודל המתאים ביותר'], ...modelChoices(store.meta('plan').models)]);
    }
    const items = store.items('plan').sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
    syncList(plans, items, {
      key: (p) => p.task_id, sig: (p) => sig(p), build: (p) => planCard(ctx, p),
      empty: () => h('p', { class: 'muted' }, 'אין עדיין בקשות תכנון.'),
    });
  }

  watch('plan', render);
  render();
  ctx.setTopics(['plan']);
  return stop;
}
