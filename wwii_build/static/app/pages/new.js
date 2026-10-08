// New task form (action add_task, the same field names as the classic form) plus the global auto-approval switch.
// Option lists: owners / context documents / MCP servers from /api/new-task-options, dependencies from the tasks
// topic, model profiles and the auto-approval flag from the overview topic.
import { h, setChildren } from '../dom.js';
import { createdTarget } from '../format.js';
import { Form, actionButton } from '../forms.js';
import { pill } from '../ui.js';
import { card, makeWatcher, modelChoices, sig } from '../widgets.js';

const AUTOMATIC = 'אוטומטי: המודל המתאים ביותר';

export function mount(ctx) {
  const { store, root } = ctx;
  const { watch, stop } = makeWatcher(store);
  const sigs = {};
  let options = null;
  let alive = true;

  const form = new Form(ctx, 'add_task', {
    submit: 'צור משימה', cls: 'big go', reset: true,
    onResult: (result) => {
      const target = result.ok ? createdTarget(result.message) : null;
      if (target) location.hash = target;
    },
  });
  const auto = h('section', { class: 'card' });
  const mcpNote = h('div', { class: 'muted' }, 'שרתי MCP נבחרים לפי הספק של המודל שנבחר למשימה; שרתים של ספק אחר מתעלמים ונרשמים ביומן.');
  const accessExplainer = h('details', { class: 'hold' }, h('summary', null, 'מה משתנה כשנותנים למתכנן יותר גישה?'));

  const formEl = form.build(
    h('section', { class: 'card', style: 'border-color:#5b91d1' }, h('h2', null, 'יעד המשימה'),
      form.select('task_target', [['project', 'פרויקט המשחק והתוכן'], ['task_manager', 'תיקון מערכת ניהול המשימות']], { value: 'project' }),
      h('p', { class: 'muted' }, h('b', null, 'תיקון מערכת'), ' מצלם את מנהל המשימות הפעיל לעותק מבודד, מגביל כתיבה ל־',
        h('span', { class: 'mono' }, 'tools/build_manager/'), ', מריץ קומפילציה, את כל בדיקות המנהל ובדיקת עלייה של ה־CLI. ' +
        'רק אחרי הצלחה הוא מוודא שהמקור לא השתנה, ממתין ששאר העובדים יסיימו, מפעיל עם גיבוי ומבצע restart חינני.')),
    form.text('title', { label: 'כותרת', required: true }),
    form.area('description_he', { label: 'מה המשימה עושה — הסבר ברור בעברית', rows: 3, required: true,
      placeholder: 'לדוגמה: בונה מערכת מזג אוויר שמייצגת הצטברות שלג והשפעתה על הקרקע.' }),
    form.text('name', { label: 'מזהה קצר (לא חובה)', dir: 'ltr' }),
    form.area('instructions', { label: 'הוראות ביצוע לעובד — מה עליו להשלים במשימה הזאת?', rows: 7,
      placeholder: 'לדוגמה: הוסף למנוע מזג האוויר הצטברות שלג לפי הטמפרטורה והמשקעים, ועדכן את בדיקות היחידה.' }),
    h('p', { class: 'muted' }, 'זהו חוזה הביצוע של עובד יחיד: תאר תוצאה רצויה, מגבלות וקריטריונים. אם עדיין צריך להחליט אילו משימות נדרשות, השתמש ב־',
      h('a', { href: '#/plan' }, 'מתכנן המערכת'), '.'),
    form.select('model_key', [['', AUTOMATIC]], { label: 'מודל' }),
    form.check('fallback', 'אפשר חזרה לשרשרת הניתוב אם המודל אינו זמין', { checked: true }),
    form.select('owner', [['', '(אחראי חדש למשימה הזו)']], { label: 'אחראי' }),
    form.group('deps', [], { label: 'תלויות', empty: 'אין משימות' }),
    form.area('write_scope', { label: 'תחום כתיבה (נתיב בכל שורה; תיקייה מסתיימת ב־/)', rows: 3, dir: 'ltr' }),
    form.check('read_only', 'קריאה בלבד (דוח בלבד; המנהל מגיש אותו)'),
    form.check('allow_web', 'מחקר עם גישה לרשת'),
    h('div', { class: 'muted' }, 'כבוי כברירת מחדל. כשמסומן, העובד מקבל חיפוש ושליפת דפי רשת לריצה הזו בלבד; תוכן מהרשת הוא מידע ולא הוראות, ' +
      'כל טענה מצוטטת עם URL, ותוכן המאגר, סודות והרשאות לעולם אינם נשלחים לאתר. לא זמין לתיקון מערכת ניהול המשימות.'),
    form.group('ctx', [], { label: 'קובצי קונטקסט (נכנסים לפרומפט)', empty: 'אין קובצי קונטקסט' }),
    h('section', { class: 'card', style: 'margin-top:18px;border-color:#ffd85a' }, h('h2', null, 'בקשת קונטקסט בשפה חופשית'),
      h('p', { class: 'muted' }, 'כתוב איזה ידע המשימה צריכה. מודל התכנון יחפש ב־Neo4j Graph RAG ובקובצי Markdown, Jev יבחר את המועמדים המינימליים, ' +
        'ורק המקורות שנבחרו יצורפו למשימה עם מקור מלא.'),
      form.area('context_request', { rows: 5, placeholder: 'לדוגמה: תן למשימה את מצב מזג האוויר, השלג, הקרקע והיחידות באזור ובתאריך הרלוונטיים בלבד.' }),
      form.select('context_planner_model_key', [['', 'בחירה אוטומטית לפי נתיב PLAN']], { label: 'מודל תכנון הקונטקסט' }), accessExplainer),
    form.area('ctx_extra', { label: 'נתיבי קונטקסט נוספים (נתיב בכל שורה)', rows: 2, dir: 'ltr' }),
    form.area('refs', { label: 'נתיבי עזר (מוצגים, לא מוטמעים)', rows: 2, dir: 'ltr' }),
    h('label', { class: 'blk' }, 'שרתי MCP'), mcpNote,
    form.group('mcp', [], { empty: 'אין שרתי MCP מוגדרים' }),
    form.text('tool_names', { label: 'כלים ייעודיים למשימה, מופרדים בפסיק', dir: 'ltr', placeholder: 'Read, Grep, Bash(pytest *)' }),
    form.area('checks', { label: 'פקודות קבלה (פקודת shell בכל שורה)', rows: 3, dir: 'ltr' }),
    h('div', { class: 'muted' }, form.check('auto_approve', 'אשר את המשימה הזו אוטומטית אחרי שכל הבדיקות הזמינות עברו'),
      h('div', { class: 'muted' }, 'בלי פקודת קבלה אפשר לבחור אישור אוטומטי למשימה, או להפעיל את המצב הגלובלי למעלה. בדיקות בעלות, diff וסודות תמיד נשארות פעילות.')));

  setChildren(root,
    h('section', null, h('h1', null, 'יצירת משימת ביצוע'),
      h('p', { class: 'muted' }, 'המסך הזה מיועד לעובד אחד שמבצע עבודה מוגדרת. לבקשה רחבה שצריך לפרק, משתמשים במתכנן המערכת.'),
      h('div', { class: 'role-guide' },
        h('article', { class: 'role-card' }, h('h3', null, '1. מתכנן המערכת'), h('p', null, h('strong', null, 'מקבל יעד רחב.'),
          ' הוא מציע משימות, סדר, תלויות, מודלים וכלים. הוא אינו משנה קוד בעצמו; ההצעה הופכת למשימות רק לאחר אישור או מדיניות אישור אוטומטי.')),
        h('article', { class: 'role-card context' }, h('h3', null, '2. מתכנן הקונטקסט'), h('p', null, h('strong', null, 'מקבל בקשת ידע למשימה הזאת בלבד.'),
          ' הוא מאתר מקורות ב־Neo4j וב־Markdown. מותר לו לבחור מקורות בלבד; הוראות העובד, המודל, הכלים, התלויות והרשאות הכתיבה נשארים נעולים.')),
        h('article', { class: 'role-card worker' }, h('h3', null, '3. העובד'), h('p', null, h('strong', null, 'מבצע משימה אחת.'),
          ' הוא מקבל את ההוראות שלמטה ואת הקונטקסט ש־Jev אישר, ועובד רק עם המודל, הכלים ותחום הכתיבה שהוגדרו לו.')))),
    auto, formEl);

  // ------------------------------------------------------------------ sections
  function renderAuto() {
    const on = !!store.meta('overview').review_auto_approve_all;
    const signature = sig(on);
    if (sigs.auto === signature) return;
    sigs.auto = signature;
    auto.style.borderColor = on ? '#67d9bf' : '#ffd85a';
    setChildren(auto, h('h2', null, 'מצב אישור אוטומטי לכל המשימות'),
      h('p', null, h('b', null, on ? 'פעיל' : 'כבוי'), ' — כשהמצב פעיל, הצעות תקינות של המתכנן יוצרות משימות אוטומטית, ומשימות עוברות אחרי שהבדיקות עברו. ' +
        'כשל בדיקה עדיין עוצר את המשימה. כשהמצב כבוי, המתכנן עוצר ומבקש את אישורך לפני יצירת המשימות.'),
      actionButton(ctx, on ? 'כבה מצב גלובלי' : 'הפעל אישור אוטומטי להכול', `big ${on ? 'bad' : 'go'}`, 'set_auto_approve_all', { enabled: !on }));
  }

  /** Replace an option list only when its source data changed; `data` is what the list is built from. */
  function setItems(name, data, build) {
    const key = sig(data);
    if (sigs[name] === key) return;
    sigs[name] = key;
    form.setItems(name, build(data));
  }

  function renderOptions() {
    const models = modelChoices(store.meta('overview').models || (options && options.models));
    setItems('model_key', models, (m) => [['', AUTOMATIC], ...m]);
    setItems('context_planner_model_key', models, (m) => [['', 'בחירה אוטומטית לפי נתיב PLAN'], ...m]);
    const tasks = store.items('tasks.active').filter((t) => t.kind === 'task')
      .sort((a, b) => (a.wave ?? 0) - (b.wave ?? 0) || (a.task_id < b.task_id ? -1 : a.task_id > b.task_id ? 1 : 0));
    setItems('deps', tasks.map((t) => [t.task_id, t.state]),
      (rows) => rows.map(([id, state]) => ({ value: id, label: [h('span', { class: 'mono' }, id), ' ', pill(state)] })));
    if (!options) return;
    setItems('owner', options.owners, (owners) => [['', '(אחראי חדש למשימה הזו)'], ...owners.map((o) => [o.owner, `${o.owner} (${o.domain})`])]);
    setItems('ctx', options.context_files, (paths) => paths.map((p) => ({ value: p, label: h('span', { class: 'mono' }, p) })));
    const mcp = [];
    for (const [provider, servers] of Object.entries(options.mcp)) {
      for (const [name, d] of Object.entries(servers).sort(([a], [b]) => (a < b ? -1 : 1))) mcp.push([provider, name, !!d.writes]);
    }
    setItems('mcp', mcp, (rows) => rows.map(([provider, name, writes]) => ({ value: `${provider}:${name}`,
      label: [`${provider}: `, h('span', { class: 'mono' }, name), writes ? h('span', { class: 'warn' }, ' (כותב)') : null] })));
    const signature = sig(options.planner_max_chunks, options.planner_max_chars);
    if (sigs.explainer !== signature) {
      sigs.explainer = signature;
      setChildren(accessExplainer, h('summary', null, 'מה משתנה כשנותנים למתכנן יותר גישה?'),
        h('div', { class: 'permission-table' },
          h('div', { class: 'permission-level' }, h('b', null, 'ללא גישה'), h('small', null, 'לא מתבצעת שאילתת Graph RAG.')),
          h('div', { class: 'permission-level' }, h('b', null, 'גישה מוגבלת'), h('small', null, 'חיפוש וקטורי רק בתחום שהוגדר ובמגבלת גודל.')),
          h('div', { class: 'permission-level' }, h('b', null, 'גישה מלאה'), h('small', null, 'חיפוש וקטורי וגם Cypher בכל הגרף, עדיין בתוך מגבלות.'))),
        h('ul', { class: 'boundary-list' },
          h('li', null, `למתכנן הקונטקסט יש כרגע גישת חיפוש מלאה, עד ${options.planner_max_chunks} מקטעים ו־${Number(options.planner_max_chars).toLocaleString('en-US')} תווים לפני סינון.`),
          h('li', null, 'יותר גישה מגדילה רק את מאגר המועמדים. Jev מחליט מה נכנס בפועל לפרומפט.'),
          h('li', null, 'החלפת מודל משנה יכולת ועלות, לא הרשאות. אישור אוטומטי משנה את שלב האישור, לא את הגישה לגרף.'),
          h('li', null, 'גישה לגרף לעולם אינה מעניקה סודות, shell או הרשאת כתיבה.')));
    }
  }

  function render() {
    renderAuto();
    renderOptions();
  }

  watch('overview', render);
  watch('tasks.active', render);
  render();
  ctx.setTopics(['overview', 'tasks.active']);
  ctx.fetchJson('/api/new-task-options').then((data) => { if (alive) { options = data; render(); } })
    .catch(() => ctx.toast('טעינת אפשרויות המשימה נכשלה', false));
  return () => { alive = false; stop(); };
}
