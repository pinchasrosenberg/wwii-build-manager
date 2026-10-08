// App shell: socket + store + hash router + navigation. No page reloads anywhere.
import { h, setChildren } from './dom.js';
import { NAV, PAGES, Router, activeNav } from './router.js';
import { ALREADY_RUNNING, Operations } from './operations.js';
import { LiveSocket } from './socket.js';
import { Store } from './store.js';
import { setOffline, setStateLabels, toast } from './ui.js';

const tokenMeta = () => document.querySelector('meta[name="wwii-token"]');
const store = new Store();
const root = document.getElementById('app');

// after a dashboard restart the old page holds a stale token: take the new one from the freshly served index.html
async function renewToken() {
  const res = await fetch('/app/index.html', { cache: 'no-store' });
  const m = /name="wwii-token" content="([^"]*)"/.exec(await res.text());
  if (m) tokenMeta().content = m[1];
}

const socket = new LiveSocket({
  store,
  getToken: () => tokenMeta().content,
  renewToken,
  onStatus: (online) => setOffline(!online),
  onError: (msg) => toast(msg.message_he || msg.error || 'שגיאה', false),
});

const ops = new Operations(document.getElementById('ops'));

/**
 * Run an action over the socket and show its action.result message as a toast. A long action (unstick, onboarding,
 * state chat, graph queries) also gets a live progress panel fed by the server's progress lines.
 */
async function act(name, args = {}) {
  const op = ops.begin(name);
  if (op && op.refused) {
    toast(ALREADY_RUNNING, false);
    return { ok: false, message: ALREADY_RUNNING };
  }
  let result;
  try {
    result = await socket.action(name, args, op ? op.line : null);
  } finally {
    if (op) op.end(result || { ok: false, message: 'הפעולה נכשלה' });
  }
  toast(result.message, result.ok);
  return result;
}

/** GET a JSON endpoint (the read-only /api/... routes the pages use besides the socket topics). */
async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store', headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

/**
 * A multipart action (the planner's file upload) is still an HTTP POST to /action; the server answers JSON with the
 * same {ok, message} an action.result has, and whatever it created reaches the page through the socket topics.
 */
async function upload(name, args = {}, files = []) {
  const send = () => {
    const body = new FormData();
    body.append('token', tokenMeta().content);
    body.append('action', name);
    for (const [key, value] of Object.entries(args)) {
      for (const v of Array.isArray(value) ? value : [value]) body.append(key, typeof v === 'boolean' ? (v ? '1' : '0') : String(v ?? ''));
    }
    for (const file of files) body.append('planner_files', file, file.name);
    return fetch('/action', { method: 'POST', body, headers: { Accept: 'application/json' } });
  };
  let result;
  try {
    let res = await send();
    if (res.status === 403) { await renewToken(); res = await send(); }   // the dashboard restarted: new token
    result = res.ok ? await res.json() : { ok: false, message: `error: ${(await res.text()).slice(0, 300)}` };
  } catch (e) {
    result = { ok: false, message: 'אין חיבור לשרת כרגע; הפעולה לא נשלחה' };
  }
  toast(result.message, result.ok);
  return { ok: !!result.ok, message: String(result.message ?? '') };
}

function buildNav() {
  const unstick = h('button', { class: 'go', title: 'מאבחן למה הריצה תקועה ומשחרר את מה שאפשר אוטומטית' }, '⟳ למה תקוע? המשך');
  unstick.addEventListener('click', async () => {
    unstick.disabled = true;
    try { await act('unstick'); } finally { unstick.disabled = false; }
  });
  ops.bind(unstick, 'unstick');      // also disabled while the overview's own button (or another tab's click) runs it
  const links = new Map(NAV.map(([route, label]) =>
    [route, h('a', { href: route === 'overview' ? '#/' : `#/${route}`, dataset: { route } }, label)]));
  return {
    links,
    el: h('nav', { class: 'top' }, [...links.values()], h('span', { class: 'nav-spacer' }), unstick),
  };
}

const nav = buildNav();
const page = h('div', { id: 'page' });
setChildren(root, nav.el, page);

function markActive(name) {
  const active = activeNav(name);
  for (const [route, link] of nav.links) link.classList.toggle('active', route === active);
}

async function loadLabels() {
  try {
    const res = await fetch('/api/i18n', { cache: 'no-store' });
    setStateLabels((await res.json()).states.he);
  } catch (e) { /* labels fall back to the raw state names */ }
}

const router = new Router(async (name, route) => {
  markActive(name);
  const topicsOf = { current: [] };
  const unbinds = [];
  const ctx = {
    root: page, store, act, upload, fetchJson, toast, params: route.params,
    request: (type, payload) => socket.request(type, payload),
    setTopics: (topics) => { topicsOf.current = topics; socket.setTopics(topics); },
    // disable a page's button while a long action of that name runs (released when the page is left)
    bindBusy: (button, ...names) => { unbinds.push(ops.bind(button, ...names)); return button; },
    running: (name) => ops.running(name),
  };
  setChildren(page);
  const loader = Object.hasOwn(PAGES, name) ? PAGES[name] : null;
  if (!loader) {
    setChildren(page, h('div', { class: 'card pending-page' },
      h('h2', null, 'הדף לא נמצא'), h('p', null, h('a', { class: 'btnlink', href: '#/' }, 'חזרה לסקירה'))));
    socket.setTopics([]);
    return null;
  }
  const mod = await loader();
  const cleanup = mod.mount(ctx);
  return () => {
    if (cleanup) cleanup();
    unbinds.forEach((fn) => fn());
    socket.setTopics([]);
  };
});

await loadLabels();
socket.connect();
router.start();
