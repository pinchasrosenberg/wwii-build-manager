// Shared task-row click behavior. Dependency graphs are requested only when a
// task is opened, never embedded in active/problem/history list payloads.
import { h, setChildren } from './dom.js';
import { taskHash } from './format.js';
import { pill } from './ui.js';

function treeNode(panel, open, node) {
  const label = node.missing ? `${node.task_id} — לא נמצא` : node.cycle ? `${node.task_id} — מחזור` : node.task_id;
  const link = h('button', { type: 'button', class: 'dep-link' }, label);
  link.addEventListener('click', () => open(node.task_id));
  const head = h('div', { class: `dep-node-head${node.blocking_root ? ' blocking-root' : ''}` },
    link, ' ', node.state ? pill(node.state) : null,
    node.model ? ` · ${node.model}` : '', node.reason ? h('small', { class: 'muted' }, ` — ${node.reason}`) : null);
  if (!node.children?.length) return h('li', { class: node.blocking_root ? 'blocking-root' : '' }, head);
  return h('li', { class: node.blocking_root ? 'blocking-root' : '' },
    h('details', { open: !!node.blocking }, h('summary', null, head), h('ul', { class: 'dep-tree' }, node.children.map((c) => treeNode(panel, open, c)))));
}

export function dependencyPanel(ctx) {
  const content = h('div');
  const close = h('button', { type: 'button', class: 'dep-close', 'aria-label': 'סגירה' }, '×');
  const panel = h('aside', { class: 'task-detail-panel', hidden: true },
    h('div', { class: 'bar' }, h('h2', null, 'תלויות המשימה'), close), content);
  let serial = 0;
  close.addEventListener('click', () => { panel.hidden = true; });

  async function open(taskId) {
    const mine = ++serial;
    panel.hidden = false;
    setChildren(content, h('p', { class: 'muted' }, 'טוען את עץ התלויות…'));
    const response = await ctx.request('task.detail', { task_id: taskId });
    if (mine !== serial) return;
    if (!response.ok || !response.detail?.exists) {
      setChildren(content, h('p', { class: 'err' }, 'רשומת המשימה לא נמצאה.'));
      return;
    }
    const d = response.detail;
    const deps = d.prerequisites?.length
      ? h('ul', { class: 'dep-tree' }, d.prerequisites.map((n) => treeNode(panel, open, n)))
      : h('p', { class: 'muted' }, 'אין דרישות קדם.');
    const waiting = d.dependents?.length
      ? h('ul', null, d.dependents.map((x) => h('li', null,
        h('button', { type: 'button', class: 'dep-link', onclick: () => open(x.task_id) }, x.task_id), ' ', x.state ? pill(x.state) : null,
        ` · ${x.model || 'מודל לא ידוע'}${x.reason ? ` — ${x.reason}` : ''}`)))
      : h('p', { class: 'muted' }, 'אין משימות שממתינות לה.');
    setChildren(content,
      h('div', { class: 'task-panel-title' }, h('b', { class: 'mono' }, taskId), ' ', pill(d.task.state),
        ` · ${d.task.model || 'מודל לא ידוע'}`, h('br'), h('span', { class: 'muted' }, d.task.reason || '')),
      d.blocking_roots?.length ? h('p', { class: 'blocking-note' }, `החסימה המדויקת: ${d.blocking_roots.join(', ')}`) : null,
      h('h3', null, 'דרישות קדם'), deps,
      h('h3', null, 'משימות שממתינות לה'), waiting,
      d.downstream_more ? h('p', { class: 'muted' }, `ועוד ${d.downstream_more} משימות בהמשך השרשרת`) : null,
      h('p', null, h('a', { class: 'btnlink', href: taskHash(taskId) }, 'פתיחת דף המשימה המלא')));
  }
  return { el: panel, open };
}

export function taskPanelLink(panel, taskId, label = taskId) {
  const link = h('a', { href: taskHash(taskId), class: 'mono' }, label);
  link.addEventListener('click', (event) => { event.preventDefault(); panel.open(taskId); });
  return link;
}
