import { h, setChildren } from '../dom.js';
import { deliverLink } from '../widgets.js';

const BASE = 'http://127.0.0.1:8790';
const CHAIN = [
  ['fantasy.world_planner', 'מתכנן העולם', 'פרומפט ← תוכנית עולם, עם ידע התקופה'],
  ['fantasy.cartographer', 'הקרטוגרף', 'קודם מפה: שבילים, בתים, ארמונות ושווקים — בדיקת התנגשויות ומילוי צפוף'],
  ['fantasy.world_generator', 'מחולל העולם', 'בונה את התלת־ממד רק לפי המפה הבדוקה'],
  ['fantasy.costume_designer', 'מעצב התלבושות', 'סוגי האנשים ולבושם לפי התקופה'],
  ['fantasy.character_builder', 'בונה הדמויות', 'דמויות עם שלד ואנימציות ב־Blender'],
  ['fantasy.climate_master', 'אדון מזג האוויר', 'עונות, גשם, שלג, זריחה ושקיעה'],
  ['fantasy.life_director', 'במאי החיים בעיר', 'המון, שווקים, עגלות, אפריונים, סירות'],
  ['fantasy.librarian', 'הספרן', 'כל מה שנבנה נכנס לספרייה ולידע (RAG)'],
];
const ERAS = [['', 'אוטומטי לפי התיאור'], ['rome_315', 'רומא בתפארתה, 315 — עיר חיה'], ['rome_476', 'רומא אחרי הנפילה, 476']];
const STATUS = { running: 'בבנייה…', done: 'הושלם', failed: 'נכשל' };

export const mount = (ctx) => {
  const { root } = ctx;
  const state = { alive: true, token: null, job: null, timer: null };
  const status = h('p', { class: 'muted' }, 'מתחבר לשרת בניית העולמות…');
  const name = h('input', { type: 'text', placeholder: 'רומא בתפארתה', style: 'width:100%' });
  const desc = h('textarea', { rows: 4, style: 'width:100%', placeholder: 'אני רוצה את רומא בתפארתה: אנשים לבושים כמו אז, שווקים עם מסחר, עגלות, סירות בנהר, הכל חי' });
  const era = h('select', null, ERAS.map(([v, l]) => h('option', { value: v }, l)));
  const llm = h('input', { type: 'checkbox', checked: true });
  const message = h('p', { class: 'muted' });
  const go = h('button', { class: 'big go', type: 'button' }, 'בנה דרך ה־Delivers');
  const chainBox = h('section', { class: 'card' });
  const worldsBox = h('section', { class: 'card' });

  const send = (method, path, body) =>
    fetch(`${BASE}${path}`, { method, mode: 'cors', headers: method === 'POST' ? { 'Content-Type': 'application/json', 'X-Fantasy-Token': state.token || '' } : {}, body: body ? JSON.stringify(body) : undefined })
      .then((res) => res.json().then((data) => ({ ok: res.ok, status: res.status, data })));

  const call = (method, path, body) => send(method, path, body).then((r) => (r.status === 403 && method === 'POST'
    ? fetch(`${BASE}/api/link-token`, { mode: 'cors' }).then((res) => res.json()).then((t) => {
      state.token = t.token;
      return send(method, path, body);
    })
    : r)).then((r) => (r.ok ? r.data : Promise.reject(new Error(r.data.error || String(r.status)))));

  const jobLine = (job) => h('p', null, h('b', null, `${STATUS[job.status] || job.status}`), ` · התחיל ${new Date(job.started).toLocaleTimeString('he-IL')}`,
    job.world ? [' · ', h('a', { href: `${BASE}/?world=${job.world_id}`, target: '_blank', rel: 'noopener' }, `פתח את "${job.world.name}"`),
      ` · ${job.world.stats ? job.world.stats.houses : 0} בתים · ${job.world.life ? 'עיר חיה' : 'בלי תוכנית חיים'}`] : null,
    job.error ? h('div', { class: 'banner' }, job.error) : null,
    job.world && job.world.map ? h('div', null,
      h('p', null, h('b', null, job.world.map.clean ? 'המפה נקייה: 0 התנגשויות' : 'נשארו התנגשויות במפה'),
        ` · ${job.world.map.rerouted_streets} דרכים עקפו מונומנטים · ${job.world.map.cut_streets} דרכים נחתכו · ${job.world.map.filled_buildings} מבנים מולאו לפי צפיפות התקופה · ${job.world.map.houses_removed} בתים שהתנגשו הוסרו`),
      h('img', { src: `${BASE}/api/worlds/${job.world_id}/map.svg`, alt: 'מפת העולם', style: 'width:100%;max-width:820px;border:1px solid #32618c;border-radius:10px;background:#d9cfb4' })) : null);

  const renderChain = (job) => {
    const runs = job ? job.runs || [] : [];
    const rows = CHAIN.map(([id, title, what]) => {
      const mine = runs.filter((r) => r.deliver === id);
      const running = mine.some((r) => r.status === 'RUNNING');
      const failed = mine.some((r) => r.status === 'FAILED');
      const secs = mine.reduce((s, r) => s + (r.seconds || 0), 0);
      const facts = [...new Set(mine.flatMap((r) => r.rag || []))].slice(0, 3);
      const label = failed ? 'נכשל' : running ? 'רץ עכשיו…' : mine.length ? `הושלם${mine.length > 1 ? ` ×${mine.length}` : ''}` : job && job.status === 'running' ? 'ממתין' : '—';
      return h('tr', null, h('td', null, deliverLink(id)), h('td', null, h('b', null, title), h('div', { class: 'muted' }, what)), h('td', null, label),
        h('td', { class: 'mono' }, mine.length ? `${secs.toFixed(1)} שנ׳` : ''), h('td', null, [(mine.find((r) => r.model) || {}).model || '', ...new Set(mine.flatMap((r) => r.tools || []))].filter(Boolean).join(' · ')), h('td', null, facts.join(' · ')));
    });
    setChildren(chainBox, h('table', null, h('tr', null, ['Deliver', 'תפקיד', 'מצב', 'זמן', 'מודל', 'ידע תקופה שנשלף (RAG)'].map((c) => h('th', null, c))), rows),
      job ? jobLine(job) : h('p', { class: 'muted' }, 'כל בנייה עוברת בשרשרת הזו. כל שלב נרשם כהרצה של ה־Deliver במערכת, בעלות $0 (מודלים מקומיים).'));
  };

  const renderWorlds = (worlds) => setChildren(worldsBox, worlds.length ? h('table', null,
    h('tr', null, ['עולם', 'תיאור', '', ''].map((c) => h('th', null, c))),
    worlds.slice(0, 15).map((w) => h('tr', null, h('td', null, h('b', null, w.name)), h('td', { class: 'muted' }, (w.description || '').slice(0, 90)),
      h('td', null, h('a', { href: `${BASE}/?world=${w.id}`, target: '_blank', rel: 'noopener' }, 'פתח')),
      h('td', null, h('button', { type: 'button', onclick: () => start({ kind: 'rebuild_life', world_id: w.id }) }, 'בנה מחדש את החיים'))))) : h('p', { class: 'muted' }, 'עוד אין עולמות.'));

  const loadWorlds = () => call('GET', '/api/worlds').then((d) => state.alive && renderWorlds(d.worlds)).catch(() => null);

  const poll = () => {
    if (!state.alive || !state.job) return;
    call('GET', `/api/jobs/${state.job.id}`).then((job) => {
      state.job = job;
      renderChain(job);
      if (job.status === 'running') state.timer = setTimeout(poll, 1500);
      else {
        go.disabled = false;
        loadWorlds();
      }
    }).catch((err) => {
      message.textContent = `שגיאה: ${err.message}`;
      go.disabled = false;
    });
  };

  const start = (extra) => {
    const body = extra || { kind: 'create_world', name: name.value.trim(), description: desc.value.trim(), basemap: era.value || undefined, use_llm: llm.checked };
    if (!extra && !body.description) {
      message.textContent = 'כתבו תיאור של העולם';
      return;
    }
    go.disabled = true;
    message.textContent = body.kind === 'create_world' ? (body.use_llm ? 'בונה עם המודל המקומי — בערך דקה.' : 'בונה לפי חוקים — כמה שניות.') : 'בונה מחדש את החיים בעיר…';
    call('POST', '/api/jobs', body).then((job) => {
      state.job = job;
      poll();
    }).catch((err) => {
      message.textContent = `שגיאה: ${err.message}`;
      go.disabled = false;
    });
  };

  go.addEventListener('click', () => start());
  setChildren(root,
    h('section', null, h('h1', null, 'בניית עולמות — דרך ה־Delivers'),
      h('p', { class: 'muted' }, 'כותבים מה רוצים, והבנייה עוברת דרך שרשרת ה־Delivers: כל אחד עם מודל מקומי משלו וידע תקופה משלו. אפשר לפתוח כל Deliver ולראות את ההרצות שלו.'), status),
    h('section', { class: 'card', style: 'border-color:#5b91d1' },
      h('label', null, 'שם העולם', name), h('label', null, 'מה לבנות', desc),
      h('div', null, h('label', null, 'מפת פרויקט ', era), ' ', h('label', null, llm, ' לתכנן עם המודל המקומי (Qwen3-VL)')), go, message),
    h('h2', null, 'שרשרת ה־Delivers'), chainBox,
    h('h2', null, 'עולמות שנבנו'), worldsBox);
  renderChain(null);

  fetch(`${BASE}/api/health`, { mode: 'cors' }).then((res) => res.json())
    .then((info) => {
      if (!state.alive) return null;
      status.textContent = `שרת בניית העולמות פעיל · ${info.worlds} עולמות · מחובר ל־Delivers: ${info.manager_link ? 'כן' : 'לא'}`;
      return call('GET', '/api/link-token').then((d) => {
        state.token = d.token;
        loadWorlds();
        return call('GET', '/api/jobs').then((d2) => {
          const running = d2.jobs.find((j) => j.status === 'running');
          if (running) {
            state.job = running;
            go.disabled = true;
            poll();
          }
        });
      });
    })
    .catch(() => state.alive && (status.textContent = 'שרת בניית העולמות לא רץ. מפעילים אותו: python3 -m wwii_build.fantasy (פורט 8790).'));
  return () => {
    state.alive = false;
    clearTimeout(state.timer);
  };
};
