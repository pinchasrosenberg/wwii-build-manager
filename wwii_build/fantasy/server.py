import json
import mimetypes
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import models
from .cartography import map_svg
from .deliver_link import now_iso
from .service import Service

HERE = Path(__file__).parent
STATIC = HERE / 'static'
THREE = HERE.parent / 'static' / 'game'
PORT = 8790
TOKEN_PLACEHOLDER = '__FANTASY_TOKEN__'
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile('^' + pattern + '$'), fn))
        return fn
    return deco


def safe_file(root, rel):
    path = (root / urllib.parse.unquote(rel)).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def persistent_token():
    from .store import DATA_DIR
    path = DATA_DIR / 'server.token'
    if not path.is_file():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(16))
        path.chmod(0o600)
    return path.read_text().strip()


MANAGER_ORIGINS = ('http://127.0.0.1:8765', 'http://localhost:8765')
JOB_KINDS = ('create_world', 'rebuild_life')


class App:
    def __init__(self, service=None, port=PORT):
        self.service = service or Service()
        self.token = persistent_token()
        self.port = port
        self.lock = threading.Lock()
        self.jobs = {}
        self.job_lock = threading.Lock()

    def start_job(self, kind, body):
        if not self.job_lock.acquire(blocking=False):
            return None
        job = {'id': 'job' + secrets.token_hex(5), 'kind': kind, 'status': 'running', 'started': now_iso(), 'started_ts': time.time(),
               'description': (body.get('description') or '')[:300], 'world_id': body.get('world_id'), 'error': None, 'finished': None}
        self.jobs[job['id']] = job

        def work():
            try:
                if kind == 'create_world':
                    job['world_id'] = self.service.create_world((body.get('name') or '')[:80], job['description'], bool(body.get('use_llm', True)), None, (), body.get('basemap') or None)
                else:
                    self.service.build_life(job['world_id'], bool(body.get('use_llm', False)))
                job['status'] = 'done'
            except Exception as exc:
                job['status'] = 'failed'
                job['error'] = repr(exc)[:400]
            finally:
                job['finished'] = now_iso()
                self.job_lock.release()

        threading.Thread(target=work, daemon=True).start()
        return job

    def job_runs(self, job):
        link = self.service.link
        rows = link.db.q("SELECT run_id, deliver_id, status, detail_json, started_at, completed_at FROM deterministic_deliver_runs WHERE deliver_id LIKE 'fantasy.%' AND started_at >= ? ORDER BY started_at",
                         (job['started'],)) if link.enabled else self.service.store.q('SELECT run_id, deliver_id, \'COMPLETED\' AS status, detail_json, started_at, finished_at AS completed_at FROM deliver_runs WHERE started_at >= ? ORDER BY started_at', (job['started'],))
        out = []
        for r in rows:
            detail = json.loads(r['detail_json'] or '{}')
            out.append({'run_id': r['run_id'], 'deliver': r['deliver_id'], 'status': r['status'], 'model': detail.get('model'), 'seconds': detail.get('seconds'),
                        'rag': detail.get('rag', []), 'related': detail.get('related', []), 'tools': detail.get('tools', []), 'error': detail.get('error'), 'started': r['started_at'], 'completed': r['completed_at']})
        return out

    def make_handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def host_ok(self):
                return (self.headers.get('Host') or '').split(':')[0] in ('127.0.0.1', 'localhost', '[::1]')

            def send_bytes(self, status, body, ctype):
                self.send_response(status)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                origin = self.headers.get('Origin', '')
                self.send_header('Access-Control-Allow-Origin', origin if origin in MANAGER_ORIGINS else 'null')
                self.send_header('Vary', 'Origin')
                self.end_headers()
                self.wfile.write(body)

            def send_json(self, status, obj):
                self.send_bytes(status, json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

            def serve_static(self, path):
                if path in ('/', '/index.html'):
                    page = (STATIC / 'index.html').read_text(encoding='utf-8').replace(TOKEN_PLACEHOLDER, app.token)
                    return self.send_bytes(200, page.encode(), 'text/html; charset=utf-8')
                root, rel = (THREE, path[len('/three/'):]) if path.startswith('/three/') else (STATIC, path[len('/static/'):] if path.startswith('/static/') else path.lstrip('/'))
                target = safe_file(root, rel)
                if target is None:
                    return self.send_bytes(404, b'not found', 'text/plain')
                ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
                return self.send_bytes(200, target.read_bytes(), 'text/javascript' if target.suffix == '.js' else ctype)

            def dispatch(self, method):
                if not self.host_ok():
                    return self.send_bytes(403, b'forbidden host', 'text/plain')
                url = urllib.parse.urlparse(self.path)
                if method == 'GET' and url.path.startswith('/models/'):
                    root = app.service.store.path.parent / 'models'
                    target = safe_file(root, url.path[len('/models/'):])
                    return self.send_bytes(200, target.read_bytes(), 'model/gltf-binary') if target else self.send_bytes(404, b'not found', 'text/plain')
                if method == 'GET' and not url.path.startswith('/api/'):
                    return self.serve_static(url.path)
                svg = re.match(r'^/api/worlds/([\w]+)/map\.svg$', url.path) if method == 'GET' else None
                if svg:
                    world = app.service.store.world(svg.group(1))
                    return self.send_bytes(200, map_svg(world['scene']).encode(), 'image/svg+xml') if world else self.send_bytes(404, b'not found', 'text/plain')
                if method == 'GET' and url.path == '/api/link-token':
                    allowed = self.headers.get('Origin', '') in MANAGER_ORIGINS
                    return self.send_json(200, {'token': app.token}) if allowed else self.send_json(403, {'error': 'origin not allowed'})
                body = {}
                if method == 'POST':
                    if not secrets.compare_digest(self.headers.get('X-Fantasy-Token', ''), app.token):
                        return self.send_json(403, {'error': 'bad token'})
                    n = int(self.headers.get('Content-Length') or 0)
                    if n > 16_000_000:
                        return self.send_json(413, {'error': 'too large'})
                    body = json.loads(self.rfile.read(n) or b'{}')
                for m, pat, fn in ROUTES:
                    hit = pat.match(url.path) if m == method else None
                    if hit:
                        try:
                            status, payload = fn(app, body, *hit.groups())
                        except Exception as exc:
                            return self.send_json(500, {'error': repr(exc)})
                        return self.send_json(status, payload)
                return self.send_json(404, {'error': 'no route'})

            def do_OPTIONS(self):
                origin = self.headers.get('Origin', '')
                self.send_response(204 if origin in MANAGER_ORIGINS and self.host_ok() else 403)
                if origin in MANAGER_ORIGINS:
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Access-Control-Allow-Methods', 'GET, POST')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Fantasy-Token')
                    self.send_header('Access-Control-Max-Age', '600')
                    self.send_header('Vary', 'Origin')
                self.end_headers()

            def do_GET(self):
                self.dispatch('GET')

            def do_POST(self):
                self.dispatch('POST')

        return Handler

    def serve(self):
        httpd = ThreadingHTTPServer(('127.0.0.1', self.port), self.make_handler())
        httpd.serve_forever()


@route('GET', r'/api/health')
def health(app, body):
    return 200, {'ok': True, 'service': 'fantasy-world-builder', 'worlds': len(app.service.store.list_worlds()), 'manager_link': app.service.link.enabled, 'manager_db': app.service.link.db_path}


@route('POST', r'/api/worlds/([\w]+)/clock')
def world_clock(app, body, wid):
    result = app.service.set_clock(wid, body.get('hour'), body.get('month'), body.get('day'), body.get('weather'))
    return (200, result) if result else (404, {'error': 'לעולם הזה אין שעון (רק לרומא ההיסטורית)'})


@route('POST', r'/api/jobs')
def start_job(app, body):
    kind = body.get('kind', 'create_world')
    if kind not in JOB_KINDS:
        return 400, {'error': 'unknown job'}
    if kind == 'create_world' and not (body.get('description') or '').strip():
        return 400, {'error': 'חסר תיאור'}
    if kind == 'rebuild_life' and not app.service.store.world(body.get('world_id') or ''):
        return 404, {'error': 'world not found'}
    job = app.start_job(kind, body)
    return (200, {k: v for k, v in job.items() if k != 'started_ts'}) if job else (409, {'error': 'כבר רצה בנייה — חכו שתסתיים'})


@route('GET', r'/api/jobs')
def list_jobs(app, body):
    return 200, {'jobs': [{k: v for k, v in j.items() if k != 'started_ts'} for j in sorted(app.jobs.values(), key=lambda j: -j['started_ts'])][:20]}


@route('GET', r'/api/jobs/([\w]+)')
def job_status(app, body, jid):
    job = app.jobs.get(jid)
    if job is None:
        return 404, {'error': 'no such job'}
    world = app.service.store.world(job['world_id']) if job['world_id'] and job['status'] == 'done' else None
    summary = {'name': world['name'], 'era': world['spec'].get('basemap'), 'stats': world['scene'].get('stats'), 'life': bool((world['scene'].get('life') or {}).get('agents')),
               'map': world['scene'].get('map')} if world else None
    return 200, {**{k: v for k, v in job.items() if k != 'started_ts'}, 'runs': app.job_runs(job), 'world': summary}


@route('GET', r'/api/worlds')
def list_worlds(app, body):
    return 200, {'worlds': app.service.store.list_worlds()}


@route('POST', r'/api/worlds')
def create_world(app, body):
    text = (body.get('description') or '').strip()
    if len(text) < 3:
        return 400, {'error': 'חסר תיאור'}
    image = body.get('image') if isinstance(body.get('image'), str) and body.get('image', '').startswith('data:image/') else None
    palette = [c for c in (body.get('palette') or []) if isinstance(c, str)][:8]
    if image and bool(body.get('use_llm', True)) and not models.vlm_up():
        models.start_vlm()
        return 503, {'error': 'מודל הראייה נטען עכשיו (כחצי דקה). נסו שוב בעוד רגע.', 'starting': True}
    wid = app.service.create_world((body.get('name') or '').strip(), text[:4000], bool(body.get('use_llm', True)), image, palette, body.get('basemap'))
    return 200, {'id': wid}


@route('GET', r'/api/worlds/([\w]+)')
def get_world(app, body, wid):
    payload = app.service.world_payload(wid)
    return (200, payload) if payload else (404, {'error': 'not found'})


@route('POST', r'/api/worlds/([\w]+)/player')
def save_player(app, body, wid):
    app.service.store.save_player(wid, body)
    return 200, {'ok': True}


@route('POST', r'/api/worlds/([\w]+)/rooms/([\w]+)/propose')
def propose(app, body, wid, room_id):
    text = (body.get('text') or '').strip()
    if not text:
        return 400, {'error': 'חסרה בקשה'}
    result = app.service.propose(wid, room_id, text[:1000], bool(body.get('use_llm', True)))
    return (200, result) if result else (404, {'error': 'room not found'})


@route('POST', r'/api/proposals/([\w]+)/preview')
def preview(app, body, pid):
    return 200, {'preview': app.service.preview(pid, body.get('selected') or [])}


@route('POST', r'/api/proposals/([\w]+)/resolve')
def resolve(app, body, pid):
    result = app.service.resolve(pid, body.get('action', 'apply'), body.get('selected') or [], body.get('scopes') or ['room'])
    return (200, result) if result else (409, {'error': 'proposal not pending'})


@route('GET', r'/api/worlds/([\w]+)/rooms/([\w]+)/history')
def history(app, body, wid, room_id):
    return 200, {'history': app.service.store.room_history(wid, room_id)}


@route('POST', r'/api/worlds/([\w]+)/rooms/([\w]+)/revert')
def revert(app, body, wid, room_id):
    design = app.service.revert(wid, room_id, int(body.get('version', 0)))
    return (200, {'design': design}) if design else (404, {'error': 'version not found'})


@route('GET', r'/api/assets')
def assets(app, body):
    return 200, {'assets': app.service.store.assets()}


@route('POST', r'/api/worlds/([\w]+)/library/use')
def library_use(app, body, wid):
    result = app.service.use_library(wid, body.get('asset_id', ''), body.get('target'), body.get('place'), body.get('room_key'))
    return (200, result) if result else (404, {'error': 'asset not found'})


@route('GET', r'/api/models')
def models_status(app, body):
    return 200, models.status()


@route('POST', r'/api/models/start')
def models_start(app, body):
    return 200, {'up': models.start_vlm(), 'status': models.status()}


@route('POST', r'/api/worlds/([\w]+)/plan/propose')
def plan_propose(app, body, wid):
    text = (body.get('text') or '').strip()
    image = body.get('image') if isinstance(body.get('image'), str) and body.get('image', '').startswith('data:image/') else None
    if not text and not image:
        return 400, {'error': 'חסרה בקשה'}
    result = app.service.propose_plan(wid, text[:3000] or 'התאם את העולם לתמונה', image, bool(body.get('use_llm', True)))
    return (200, result) if result else (409, {'error': 'העולם הזה נוצר בגרסה הישנה; צרו עולם חדש כדי לערוך אותו בפרומפט'})


@route('POST', r'/api/plan_proposals/([\w]+)/resolve')
def plan_resolve(app, body, pid):
    result = app.service.resolve_plan(pid, body.get('action', 'apply'))
    return (200, result) if result else (409, {'error': 'proposal not pending'})


@route('GET', r'/api/worlds/([\w]+)/versions')
def world_versions(app, body, wid):
    return 200, {'versions': app.service.store.world_versions(wid)}


@route('POST', r'/api/worlds/([\w]+)/revert')
def world_revert(app, body, wid):
    version = app.service.revert_world(wid, int(body.get('version', 0)))
    return (200, {'version': version}) if version else (404, {'error': 'version not found'})


@route('GET', r'/api/worlds/([\w]+)/houses/([\w]+)')
def house(app, body, wid, hid):
    payload = app.service.house_payload(wid, hid)
    return (200, payload) if payload else (404, {'error': 'house not found'})


@route('POST', r'/api/worlds/([\w]+)/objects/propose')
def object_propose(app, body, wid):
    target = body.get('target') or {}
    if target.get('type') not in ('tree', 'landmark', 'palace', 'house', 'placed'):
        return 400, {'error': 'אין אובייקט נבחר'}
    result = app.service.propose_object(wid, target, (body.get('text') or 'פרט את זה כפי שהיה באמת')[:1000], bool(body.get('use_llm', True)))
    return (200, result) if result else (404, {'error': 'object not found'})


@route('POST', r'/api/object_proposals/([\w]+)/resolve')
def object_resolve(app, body, pid):
    result = app.service.resolve_object(pid, body.get('action', 'apply'))
    return (200, result) if result else (409, {'error': 'proposal not pending'})


@route('GET', r'/api/worlds/([\w]+)/knowledge')
def knowledge(app, body, wid):
    return 200, app.service.knowledge(wid)


@route('POST', r'/api/worlds/([\w]+)/life')
def rebuild_life(app, body, wid):
    life = app.service.build_life(wid, bool(body.get('use_llm', False)))
    return (200, {'life': life}) if life else (404, {'error': 'לעולם הזה אין תוכנית חיים (רק לרומא ההיסטורית)'})


@route('GET', r'/api/population')
def population(app, body):
    return 200, app.service.ensure_population(None, False)
