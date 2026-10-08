// Hash router: "#/" and "#/overview" -> overview; "#/<page>?a=b" -> page "<page>" with params.
// A page module exports mount(ctx) and returns its cleanup function. Every page of the manager lives in the app;
// NAV lists them in the order the navigation bar shows them.

export const PAGES = {
  overview: () => import('./pages/overview.js'),
  tasks: () => import('./pages/tasks.js'),
  delivers: () => import('./pages/delivers.js'),
  deliver: () => import('./pages/deliver.js'),
  task: () => import('./pages/task.js'),
  events: () => import('./pages/events.js'),
  rag: () => import('./pages/rag.js'),
  plan: () => import('./pages/plan.js'),
  new: () => import('./pages/new.js'),
  battle: () => import('./pages/battle.js'),
  subtasks: () => import('./pages/subtasks.js'),
};

/** [route, label, pages that keep this entry highlighted]. */
export const NAV = [
  ['overview', 'סקירה', []],
  ['tasks', 'משימות', ['task']],
  ['delivers', 'מרכז ה־Delivers', ['deliver']],
  ['subtasks', 'תתי־משימות ודפוסים', []],
  ['rag', 'גרף RAG', []],
  ['new', '+ משימה חדשה', []],
  ['battle', 'בקשת קרב', []],
  ['plan', 'פרומפט למשימות', []],
  ['events', 'יומן אירועים', []],
];

export function parseHash(hash) {
  const raw = String(hash || '').replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?', 2);
  const name = path.split('/')[0] || 'overview';
  return { name, rest: path.split('/').slice(1), params: Object.fromEntries(new URLSearchParams(query)) };
}

/** The navigation entry that is highlighted while page `name` is shown. */
export function activeNav(name) {
  const hit = NAV.find(([route, , also]) => route === name || also.includes(name));
  return hit ? hit[0] : null;
}

export class Router {
  /** @param {(name: string, route: object) => Promise<(() => void) | void>} mount  mounts a page, returns its cleanup */
  constructor(mount) {
    this.mount = mount;
    this.cleanup = null;
    this.current = null;
    this.token = 0;
  }

  async go(hash) {
    const route = parseHash(hash);
    const mine = ++this.token;
    if (this.cleanup) { this.cleanup(); this.cleanup = null; }
    this.current = route;
    const cleanup = await this.mount(route.name, route);
    if (mine !== this.token) { if (cleanup) cleanup(); return; }   // navigated again while loading
    this.cleanup = cleanup || null;
  }

  start() {
    window.addEventListener('hashchange', () => this.go(location.hash));
    return this.go(location.hash);
  }
}
