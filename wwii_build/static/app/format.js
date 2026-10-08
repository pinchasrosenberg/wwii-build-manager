// Pure formatting helpers (no DOM): shared by the pages and unit-tested under node.

const pad = (n) => String(n).padStart(2, '0');

/** Date.parse for the ISO strings the manager writes (microsecond fractions are trimmed to milliseconds). */
export function parseIso(value) {
  if (!value || typeof value !== 'string') return null;
  const t = Date.parse(value.replace(/(\.\d{3})\d+/, '$1'));
  return Number.isNaN(t) ? null : t;
}

/** "YYYY-MM-DD HH:MM" in the browser's time zone, "לא ידוע" when missing (unknown is not a number). */
export function fmtTime(value) {
  const t = parseIso(value);
  if (t === null) return 'לא ידוע';
  const d = new Date(t);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Elapsed milliseconds -> "H:MM:SS" (hours are not wrapped at 24). */
export function fmtDuration(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 3600)}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
}

/** Runtime of a worker started at an ISO time, "-" when the start is unknown. */
export function fmtRuntime(started, now = Date.now()) {
  const t = parseIso(started);
  return t === null ? '-' : fmtDuration(now - t);
}

/** "לפני N שנ׳/דק׳/שע׳" like the server-rendered pages. */
export function fmtAgo(value, now = Date.now()) {
  const t = parseIso(value);
  if (t === null) return 'לא ידוע';
  const sec = Math.max(0, Math.floor((now - t) / 1000));
  if (sec < 90) return `לפני ${sec} שנ׳`;
  if (sec < 5400) return `לפני ${Math.floor(sec / 60)} דק׳`;
  return `לפני ${Math.floor(sec / 3600)} שע׳`;
}

/** Used percent of one quota window; a window whose reset time already passed is back to unused. */
export function quotaWindow(used, resetAt, now = Date.now()) {
  const reset = parseIso(resetAt);
  if (reset !== null && reset <= now) return { text: '0%', note: 'אופס' };
  if (typeof used === 'number') return { text: `${Math.round(used)}%`, note: '' };
  return { text: 'לא ידוע', note: '' };
}

/** The weekly figure of a quota row: the explicit weekly percent, else the overall one when there is no session figure. */
export function weeklyUsed(q) {
  if (q.weekly_used_percent !== null && q.weekly_used_percent !== undefined) return q.weekly_used_percent;
  return q.session_used_percent === null || q.session_used_percent === undefined ? q.used_percent : null;
}

export const STATE_ORDER = ['RUNNING', 'PAUSING', 'REVIEWING', 'CODE_READY', 'WAITING_REPAIR',
  'ARCHITECTURE_REVIEW_REQUIRED', 'READY', 'WAITING_APPROVAL', 'REVIEW_REQUIRED', 'WAITING_QUOTA',
  'WAITING_PROVIDER', 'BLOCKED', 'PENDING', 'WAITING_DEPENDENCY', 'PAUSED', 'FAILED', 'CANCELLED', 'PASSED'];

export const COUNT_GROUPS = [
  ['הושלמו', ['PASSED']],
  ['רצות', ['RUNNING', 'PAUSING', 'REVIEWING', 'CODE_READY']],
  ['מוכנות', ['READY']],
  ['ממתינות', ['WAITING_DEPENDENCY', 'WAITING_QUOTA', 'WAITING_PROVIDER', 'WAITING_APPROVAL', 'PENDING', 'PAUSED']],
  ['בתיקון', ['WAITING_REPAIR']],
  ['לבדיקה', ['REVIEW_REQUIRED', 'ARCHITECTURE_REVIEW_REQUIRED']],
  ['חסומות', ['BLOCKED']],
  ['נכשלו', ['FAILED']],
  ['בוטלו', ['CANCELLED']],
];

/** [[label, total]] for the overview count tiles from the overview topic's `counts`. */
export function countTiles(counts) {
  const c = counts || {};
  return COUNT_GROUPS.map(([label, states]) => [label, states.reduce((n, s) => n + (c[s] || 0), 0)]);
}

const byId = (a, b) => (a.task_id < b.task_id ? -1 : a.task_id > b.task_id ? 1 : 0);

/** Plan tasks ordered by wave / state / id, each followed by its repair tasks (as the classic overview shows them). */
export function taskRows(tasks) {
  const repairs = new Map();
  for (const t of tasks) {
    if (t.kind === 'repair') {
      if (!repairs.has(t.parent_task_id)) repairs.set(t.parent_task_id, []);
      repairs.get(t.parent_task_id).push(t);
    }
  }
  const rank = (s) => { const i = STATE_ORDER.indexOf(s); return i < 0 ? 99 : i; };
  const plan = tasks.filter((t) => t.kind !== 'repair').sort((a, b) =>
    (a.wave ?? 0) - (b.wave ?? 0) || rank(a.state) - rank(b.state) || byId(a, b));
  const rows = [];
  for (const t of plan) {
    rows.push({ task: t, repair: false });
    for (const r of (repairs.get(t.task_id) || []).sort((a, b) => (a.repair_no ?? 0) - (b.repair_no ?? 0))) {
      rows.push({ task: r, repair: true });
    }
  }
  return rows;
}

/** "12.3 KB" like the server-rendered pages (bytes below 1 KB have no decimals). */
export function fmtBytes(value) {
  let size = Number(value) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  for (let i = 0; i < units.length; i++) {
    if (size < 1024 || i === units.length - 1) return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
    size /= 1024;
  }
  return '0 B';
}

/** Hash routes of the app's pages (ids contain "/" so they travel percent-encoded in the query). */
export const taskHash = (id) => `#/task?id=${encodeURIComponent(id)}`;
export const deliverHash = (id) => `#/deliver?id=${encodeURIComponent(id)}`;

/** Pretty JSON text of a value that may already be a string. */
export function jsonText(value) {
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch (e) { return String(value); }
}

/** Hash route of a page with query parameters: pageHash('events', {task_id: 'A/1'}) -> "#/events?task_id=A%2F1". */
export function pageHash(page, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined)).toString();
  return `#/${page}${query ? `?${query}` : ''}`;
}

/** A token count or cost that may be unknown: "לא ידוע" is shown instead of a made-up zero. */
export const known = (value) => (value === null || value === undefined ? 'לא ידוע' : String(value));

/** "in / cached / out" tokens of an attempt, each part "לא ידוע" when the provider did not report it. */
export const fmtTokens = (a) => [a.input_tokens, a.cached_input_tokens, a.output_tokens].map(known).join(' / ');

/** Event detail as the journal shows it: objects pretty-printed, text as is, at most `max` characters. */
export function eventDetailText(detail, max = 3000) {
  const text = detail !== null && typeof detail === 'object' ? jsonText(detail) : String(detail ?? '');
  return text.slice(0, max);
}

/** Does a live event satisfy the journal filters? Same fields as Database.events (LIKE is case-insensitive). */
export function eventMatches(item, f = {}) {
  if (f.task_id && item.task_id !== f.task_id) return false;
  if (f.provider && item.provider !== f.provider) return false;
  if (f.event && item.event !== f.event) return false;
  if (f.search) {
    const needle = String(f.search).toLowerCase();
    const raw = item.detail !== null && typeof item.detail === 'object' ? JSON.stringify(item.detail) : String(item.detail ?? '');
    if (![item.event, item.task_id, item.provider, raw].some((x) => String(x ?? '').toLowerCase().includes(needle))) return false;
  }
  return true;
}

/** Query string of /api/events for the filters, paging cursor and page size. */
export function eventsQuery(filters, { before, limit = 100 } = {}) {
  const q = new URLSearchParams({ limit: String(limit) });
  for (const k of ['search', 'event', 'provider', 'task_id']) if (filters[k]) q.set(k, filters[k]);
  if (before) q.set('before_id', String(before));
  return q.toString();
}

/** A unified diff -> [{name, adds, dels, lines: [{cls, text}]}], one entry per file (a "summary" block for leading text). */
export function parseDiff(diff) {
  const blocks = [];
  let cur = null;
  for (const line of String(diff || '').split('\n')) {
    if (line.startsWith('diff --git')) {
      cur = { name: line.split(' b/').pop(), adds: 0, dels: 0, lines: [] };
      blocks.push(cur);
    } else if (!cur) {
      if (!line) continue;
      cur = { name: 'summary', adds: 0, dels: 0, lines: [] };
      blocks.push(cur);
    }
    const add = line.startsWith('+') && !line.startsWith('+++');
    const del = line.startsWith('-') && !line.startsWith('---');
    if (add) cur.adds += 1;
    if (del) cur.dels += 1;
    const cls = add ? 'add' : del ? 'del' : line.startsWith('@@') ? 'hunk'
      : /^(diff|index|\+\+\+|---)/.test(line) ? 'meta' : '';
    cur.lines.push({ cls, text: line });
  }
  return blocks;
}

/** Where the "created <id>" action message leads: the new task's page (a context plan "PLAN/..." goes to the planner). */
export function createdTarget(message) {
  const m = /^(?:context plan queued|created) (\S+)/.exec(String(message || ''));
  if (!m) return null;
  return m[1].startsWith('PLAN/') ? pageHash('plan') : taskHash(m[1]);
}

/** Pattern reuse as a percentage of the promotion threshold (0..100). */
export const reusePercent = (count, threshold) => Math.min(100, Math.round((100 * (Number(count) || 0)) / Math.max(1, Number(threshold) || 1)));

/** Exponential reconnect delay in ms for attempt 0,1,2,...: 0.5s doubling up to 15s; `jitter` in [0,1) trims up to 30%. */
export function backoffDelay(attempt, jitter = 0) {
  return Math.round(Math.min(15000, 500 * 2 ** attempt) * (1 - 0.3 * jitter));
}
