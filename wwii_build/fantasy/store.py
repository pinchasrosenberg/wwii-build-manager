import base64
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get('FANTASY_DATA_DIR', Path.home() / '.wwii-fantasy'))

SCHEMA = """
CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
    spec_json TEXT NOT NULL, scene_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS room_designs (
    world_id TEXT NOT NULL, room_id TEXT NOT NULL, version INTEGER NOT NULL, design_json TEXT NOT NULL,
    summary TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (world_id, room_id, version));
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, world_id TEXT NOT NULL, room_id TEXT NOT NULL, request_text TEXT NOT NULL, source TEXT NOT NULL,
    components_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, params_json TEXT NOT NULL,
    source_world TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS player_state (world_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS world_versions (
    world_id TEXT NOT NULL, version INTEGER NOT NULL, plan_json TEXT NOT NULL, scene_json TEXT NOT NULL, summary TEXT NOT NULL,
    created_at REAL NOT NULL, PRIMARY KEY (world_id, version));
CREATE TABLE IF NOT EXISTS plan_proposals (
    id TEXT PRIMARY KEY, world_id TEXT NOT NULL, request_text TEXT NOT NULL, source TEXT NOT NULL, plan_json TEXT NOT NULL,
    scene_json TEXT NOT NULL, changes_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS world_objects (
    world_id TEXT NOT NULL, object_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL, params_json TEXT NOT NULL,
    model TEXT, created_at REAL NOT NULL, PRIMARY KEY (world_id, object_id, version));
CREATE TABLE IF NOT EXISTS object_proposals (
    id TEXT PRIMARY KEY, world_id TEXT NOT NULL, object_id TEXT NOT NULL, kind TEXT NOT NULL, request_text TEXT NOT NULL, source TEXT NOT NULL,
    params_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS deliver_runs (
    run_id TEXT PRIMARY KEY, deliver_id TEXT NOT NULL, episode_id TEXT, model TEXT NOT NULL, detail_json TEXT NOT NULL, started_at TEXT NOT NULL, finished_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS world_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, world_id TEXT NOT NULL, kind TEXT NOT NULL, detail_json TEXT NOT NULL, created_at REAL NOT NULL);
"""


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else DATA_DIR / 'fantasy.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.lock = threading.RLock()
        for stmt in [s for s in SCHEMA.split(';') if s.strip()]:
            self.conn.execute(stmt)

    def q(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def x(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).rowcount

    def event(self, world_id, kind, detail):
        self.x('INSERT INTO world_events (world_id, kind, detail_json, created_at) VALUES (?,?,?,?)', (world_id, kind, json.dumps(detail, ensure_ascii=False), time.time()))

    def create_world(self, name, description, spec, scene, designs):
        wid = 'w' + uuid.uuid4().hex[:10]
        now = time.time()
        self.x('INSERT INTO worlds VALUES (?,?,?,?,?,?,?)', (wid, name, description, json.dumps(spec, ensure_ascii=False), json.dumps(scene), now, now))
        for room_id, design in designs.items():
            self.x('INSERT INTO room_designs VALUES (?,?,?,?,?,?)', (wid, room_id, 1, json.dumps(design, ensure_ascii=False), 'חדר ריק (ברירת מחדל)', now))
        self.event(wid, 'world_created', {'description': description})
        return wid

    def list_worlds(self):
        return [{'id': r['id'], 'name': r['name'], 'description': r['description'], 'updated_at': r['updated_at']}
                for r in self.q('SELECT id,name,description,updated_at FROM worlds ORDER BY updated_at DESC')]

    def world(self, wid):
        row = self.one('SELECT * FROM worlds WHERE id=?', (wid,))
        return None if row is None else {'id': row['id'], 'name': row['name'], 'description': row['description'], 'spec': json.loads(row['spec_json']),
                                         'scene': json.loads(row['scene_json']), 'created_at': row['created_at'], 'updated_at': row['updated_at']}

    def save_scene(self, wid, scene):
        self.x('UPDATE worlds SET scene_json=?, updated_at=? WHERE id=?', (json.dumps(scene), time.time(), wid))

    def room_latest(self, wid, room_id):
        row = self.one('SELECT version, design_json FROM room_designs WHERE world_id=? AND room_id=? ORDER BY version DESC LIMIT 1', (wid, room_id))
        return None if row is None else {'version': row['version'], 'design': json.loads(row['design_json'])}

    def rooms_latest(self, wid):
        ids = [r['room_id'] for r in self.q('SELECT DISTINCT room_id FROM room_designs WHERE world_id=?', (wid,))]
        return {rid: self.room_latest(wid, rid) for rid in ids}

    def save_room(self, wid, room_id, design, summary):
        latest = self.room_latest(wid, room_id)
        version = (latest['version'] if latest else 0) + 1
        self.x('INSERT INTO room_designs VALUES (?,?,?,?,?,?)', (wid, room_id, version, json.dumps(design, ensure_ascii=False), summary, time.time()))
        self.x('UPDATE worlds SET updated_at=? WHERE id=?', (time.time(), wid))
        self.event(wid, 'room_saved', {'room': room_id, 'version': version, 'summary': summary})
        return version

    def room_history(self, wid, room_id):
        return [{'version': r['version'], 'summary': r['summary'], 'created_at': r['created_at']}
                for r in self.q('SELECT version, summary, created_at FROM room_designs WHERE world_id=? AND room_id=? ORDER BY version DESC', (wid, room_id))]

    def room_version(self, wid, room_id, version):
        row = self.one('SELECT design_json FROM room_designs WHERE world_id=? AND room_id=? AND version=?', (wid, room_id, version))
        return None if row is None else json.loads(row['design_json'])

    def add_proposal(self, wid, room_id, text, source, comps):
        pid = 'p' + uuid.uuid4().hex[:10]
        self.x('INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,NULL)', (pid, wid, room_id, text, source, json.dumps(comps, ensure_ascii=False), 'PENDING', time.time()))
        return pid

    def proposal(self, pid):
        row = self.one('SELECT * FROM proposals WHERE id=?', (pid,))
        return None if row is None else {'id': row['id'], 'world_id': row['world_id'], 'room_id': row['room_id'], 'text': row['request_text'],
                                         'source': row['source'], 'components': json.loads(row['components_json']), 'status': row['status']}

    def resolve_proposal(self, pid, status):
        self.x('UPDATE proposals SET status=?, resolved_at=? WHERE id=?', (status, time.time(), pid))

    def save_asset(self, kind, name, params, world_id=None):
        aid = 'a' + uuid.uuid4().hex[:10]
        self.x('INSERT INTO assets VALUES (?,?,?,?,?,?)', (aid, kind, name, json.dumps(params, ensure_ascii=False), world_id, time.time()))
        return aid

    def assets(self, kind=None):
        rows = self.q('SELECT * FROM assets WHERE kind=? ORDER BY created_at DESC', (kind,)) if kind else self.q('SELECT * FROM assets ORDER BY created_at DESC')
        return [{'id': r['id'], 'kind': r['kind'], 'name': r['name'], 'params': json.loads(r['params_json']), 'source_world': r['source_world'], 'created_at': r['created_at']} for r in rows]

    def latest_asset(self, kind):
        found = self.assets(kind)
        return found[0] if found else None

    def save_player(self, wid, state):
        self.x('INSERT INTO player_state VALUES (?,?,?) ON CONFLICT(world_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at', (wid, json.dumps(state), time.time()))

    def player(self, wid):
        row = self.one('SELECT state_json FROM player_state WHERE world_id=?', (wid,))
        return json.loads(row['state_json']) if row else None

    def save_world_version(self, wid, plan, scene, summary):
        row = self.one('SELECT MAX(version) v FROM world_versions WHERE world_id=?', (wid,))
        version = (row['v'] or 0) + 1
        self.x('INSERT INTO world_versions VALUES (?,?,?,?,?,?)', (wid, version, json.dumps(plan, ensure_ascii=False), json.dumps(scene), summary, time.time()))
        self.x('UPDATE worlds SET spec_json=?, scene_json=?, updated_at=? WHERE id=?', (json.dumps(plan, ensure_ascii=False), json.dumps(scene), time.time(), wid))
        self.event(wid, 'world_version', {'version': version, 'summary': summary})
        return version

    def world_versions(self, wid):
        return [{'version': r['version'], 'summary': r['summary'], 'created_at': r['created_at']}
                for r in self.q('SELECT version, summary, created_at FROM world_versions WHERE world_id=? ORDER BY version DESC', (wid,))]

    def world_version(self, wid, version):
        row = self.one('SELECT plan_json, scene_json FROM world_versions WHERE world_id=? AND version=?', (wid, version))
        return None if row is None else (json.loads(row['plan_json']), json.loads(row['scene_json']))

    def add_plan_proposal(self, wid, text, source, plan, scene, changes):
        pid = 'q' + uuid.uuid4().hex[:10]
        self.x('INSERT INTO plan_proposals VALUES (?,?,?,?,?,?,?,?,?)', (pid, wid, text, source, json.dumps(plan, ensure_ascii=False), json.dumps(scene),
                                                                         json.dumps(changes, ensure_ascii=False), 'PENDING', time.time()))
        return pid

    def plan_proposal(self, pid):
        row = self.one('SELECT * FROM plan_proposals WHERE id=?', (pid,))
        return None if row is None else {'id': row['id'], 'world_id': row['world_id'], 'text': row['request_text'], 'source': row['source'], 'status': row['status'],
                                         'plan': json.loads(row['plan_json']), 'scene': json.loads(row['scene_json']), 'changes': json.loads(row['changes_json'])}

    def resolve_plan_proposal(self, pid, status):
        self.x('UPDATE plan_proposals SET status=? WHERE id=?', (status, pid))

    def save_image(self, data_url):
        head, _, b64 = data_url.partition(',')
        ext = 'png' if 'png' in head else 'jpg'
        folder = self.path.parent / 'images'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{uuid.uuid4().hex[:12]}.{ext}'
        path.write_bytes(base64.b64decode(b64))
        return path.name

    def save_object(self, wid, oid, kind, params, model):
        row = self.one('SELECT MAX(version) v FROM world_objects WHERE world_id=? AND object_id=?', (wid, oid))
        version = (row['v'] or 0) + 1
        self.x('INSERT INTO world_objects VALUES (?,?,?,?,?,?,?)', (wid, oid, version, kind, json.dumps(params, ensure_ascii=False), model, time.time()))
        self.event(wid, 'object_detailed', {'object': oid, 'kind': kind, 'version': version})
        return version

    def objects(self, wid):
        rows = self.q('SELECT o.* FROM world_objects o JOIN (SELECT object_id, MAX(version) v FROM world_objects WHERE world_id=? GROUP BY object_id) m '
                      'ON o.object_id=m.object_id AND o.version=m.v WHERE o.world_id=?', (wid, wid))
        return [{'object_id': r['object_id'], 'version': r['version'], 'kind': r['kind'], 'params': json.loads(r['params_json']), 'model': r['model']} for r in rows]

    def add_object_proposal(self, wid, oid, kind, text, source, params):
        pid = 'o' + uuid.uuid4().hex[:10]
        self.x('INSERT INTO object_proposals VALUES (?,?,?,?,?,?,?,?,?)', (pid, wid, oid, kind, text, source, json.dumps(params, ensure_ascii=False), 'PENDING', time.time()))
        return pid

    def object_proposal(self, pid):
        row = self.one('SELECT * FROM object_proposals WHERE id=?', (pid,))
        return None if row is None else {'id': row['id'], 'world_id': row['world_id'], 'object_id': row['object_id'], 'kind': row['kind'], 'params': json.loads(row['params_json']), 'status': row['status']}

    def resolve_object_proposal(self, pid, status):
        self.x('UPDATE object_proposals SET status=? WHERE id=?', (status, pid))
