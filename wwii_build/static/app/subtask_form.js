// The "create a saved subtask" form (action create_subtask), shared by the task page (parent fixed) and the
// subtasks page (parent chosen). Same field names as the classic form.
import { h } from './dom.js';
import { Form } from './forms.js';
import { modelChoices } from './widgets.js';

export const AUTOMATIC_MODEL = 'אוטומטי: המודל המתאים ביותר';

/** @returns {{form: Form, el: HTMLElement, update: (o: {models?: object, parents?: object[]}) => void}} */
export function subtaskForm(ctx, { parentId = null } = {}) {
  const form = new Form(ctx, 'create_subtask', { fixed: parentId ? { parent_task_id: parentId } : {}, submit: 'צור תת־משימה שמורה', reset: true });
  const advanced = h('details', { class: 'hold' }, h('summary', null, 'קונטקסט וכלים ייחודיים לתת־המשימה'),
    form.area('context_files', { label: 'קבצי קונטקסט — אחד בכל שורה', rows: 3, dir: 'ltr' }),
    form.area('reference_files', { label: 'קבצי עזר — אחד בכל שורה', rows: 2, dir: 'ltr' }),
    form.text('mcp_servers', { label: 'שרתי MCP — מופרדים בפסיק', dir: 'ltr' }),
    form.text('tool_names', { label: 'כלים מורשים — מופרדים בפסיק', dir: 'ltr', placeholder: 'Read, Grep, Bash(pytest *)' }),
    form.area('acceptance_commands', { label: 'בדיקות קבלה — פקודה בכל שורה', rows: 3, dir: 'ltr' }));
  const el = form.build(
    parentId ? null : form.select('parent_task_id', [], { label: 'משימת אב', required: true }),
    form.text('title', { label: 'שם תת־המשימה', required: true }),
    form.area('instructions', { label: 'הוראות ממוקדות', rows: 5, required: true }),
    h('div', { class: 'grid2' },
      h('div', null, form.select('model_key', [['', AUTOMATIC_MODEL]], { label: 'מודל' })),
      h('div', null, form.text('owner', { label: 'אחראי', placeholder: 'ריק = אחראי חדש לתת־המשימה' }))),
    form.check('fallback', 'אפשר ניתוב חלופי אם המודל אינו זמין', { checked: true }),
    form.area('write_scope', { label: 'תחום כתיבה — נתיב יחסי אחד בכל שורה', rows: 2, dir: 'ltr' }),
    form.check('read_only', 'קריאה בלבד'),
    advanced,
    h('p', { class: 'section-note' }, 'תת־המשימה נשמרת בתור עם חוזה עצמאי. היא אינה הופכת ל־Deliver. קונטקסט שיגיע למודל עדיין עובר דרך שער Jev.'));
  return {
    form,
    el,
    update({ models, parents }) {
      if (models) form.setItems('model_key', [['', AUTOMATIC_MODEL], ...modelChoices(models)]);
      if (parents && !parentId) form.setItems('parent_task_id', parents.map((p) => [p.task_id, `${p.task_id} · ${p.title || p.note || ''}`]));
    },
  };
}
