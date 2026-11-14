import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import models
from .store import DATA_DIR

MODEL_PROFILES = {
    'vlm': {'name': 'Qwen3-VL-30B-A3B (llama.cpp, מקומי)', 'why': 'מודל ראייה+טקסט חזק; קורא תמונות ומחזיר JSON לפי סכמה'},
    'ollama': {'name': f'{models.OLLAMA_MODEL} (Ollama, מקומי)', 'why': 'מודל טקסט מקומי כגיבוי'},
    'embed': {'name': 'nomic-embed-text (Ollama, מקומי)', 'why': 'הטמעות לחיפוש בידע של התקופה (RAG)'},
    'blender': {'name': 'Blender 5.3 (bpy, ללא מודל)', 'why': 'בונה את הדגם התלת־ממדי בפועל'},
    'code': {'name': 'קוד דטרמיניסטי (ללא מודל)', 'why': 'חישוב קבוע'},
}

DELIVERS = {
    'fantasy.world_planner': {'title': 'מתכנן העולם', 'model': 'vlm', 'rag': True, 'tags': ('history', 'architecture', 'colors', 'condition'),
                              'desc': 'פרומפט ותמונה -> תוכנית עולם (שטח, מים, רבעים, סגנון, מצב), מבוסס על ידע התקופה.'},
    'fantasy.cartographer': {'title': 'הקרטוגרף', 'model': 'code', 'rag': True, 'tags': ('street', 'paving', 'insula', 'domus', 'population', 'market', 'taberna'),
                             'desc': 'תמיד קודם מפה: שבילים, בתים, ארמונות, מונומנטים ושווקים כמלבנים ורצועות מדויקים; בדיקת התנגשויות (שביל בתוך בניין, בניין על בניין, בניין במים), עקיפת מונומנטים, מילוי צפוף לפי מפות התקופה. רק מפה נקייה עוברת לבנייה.'},
    'fantasy.world_generator': {'title': 'מחולל העולם', 'model': 'code', 'rag': False, 'tags': (), 'desc': 'בונה את התלת־ממד רק לפי המפה הבדוקה של הקרטוגרף.'},
    'fantasy.architect': {'title': 'אדריכל התקופה', 'model': 'vlm', 'rag': True, 'tags': ('architecture', 'house', 'church', 'palace', 'amphitheater', 'materials', 'colors'),
                          'desc': 'בקשה על בניין/אנדרטה/ארמון -> פרטים ותוספות, לפי מה שידוע על התקופה ועל מה שכבר נבנה.'},
    'fantasy.botanist': {'title': 'בוטנאי התקופה', 'model': 'vlm', 'rag': True, 'tags': ('tree', 'botany'), 'desc': 'בקשה על עץ -> מין, צורה וצבעים לפי הצמחייה של התקופה.'},
    'fantasy.interior_designer': {'title': 'מעצב הפנים', 'model': 'vlm', 'rag': True, 'tags': ('interior', 'room', 'house', 'domus'), 'desc': 'בקשה על חדר -> רכיבים לאישור, לפי פנים הבתים של התקופה.'},
    'fantasy.palace_historian': {'title': 'היסטוריון הארמון', 'model': 'code', 'rag': True, 'tags': ('palace', 'history'), 'desc': 'שחזור פנים הארמון לפי המקורות (דומוס פלאוויה).'},
    'fantasy.blender_builder': {'title': 'בונה הדגמים', 'model': 'blender', 'rag': False, 'tags': (), 'desc': 'פרמטרים -> דגם glb ב־Blender.'},
    'fantasy.librarian': {'title': 'הספרן', 'model': 'embed', 'rag': False, 'tags': (), 'desc': 'כל מה שנבנה נכנס לספרייה ולידע (RAG) עם קשרים למקור, לתקופה ולאובייקט.'},
    'fantasy.costume_designer': {'title': 'מעצב התלבושות', 'model': 'vlm', 'rag': True, 'tags': ('clothing', 'toga', 'tunic', 'stola', 'palla', 'dye', 'paenula', 'soldier', 'vigiles', 'child', 'vestal'),
                                 'desc': 'ידע התקופה -> סוגי האנשים ולבושם: טוגה עם פס ארגמן, סטולה ופאלה, טוניקות צבועות, חיילים, ויגילים, נושאי אפריון.'},
    'fantasy.character_builder': {'title': 'בונה הדמויות', 'model': 'blender', 'rag': False, 'tags': (), 'desc': 'תלבושות -> דמויות עם שלד ואנימציות (הליכה, עמידה, דיבור, ישיבה) ב־Blender, קובצי glb.'},
    'fantasy.life_director': {'title': 'במאי החיים בעיר', 'model': 'code', 'rag': True, 'tags': ('schedule', 'market', 'cart', 'lex_julia', 'lectica', 'boat', 'tiber', 'night', 'taberna', 'population'),
                              'desc': 'עולם + ידע התקופה -> מי מסתובב איפה ומתי: המון ברחובות, שווקים, כרכרות בלילה (חוק יוליוס), אפריונים, סירות בטיבר, משמר לילה.'},
    'fantasy.climate_master': {'title': 'אדון מזג האוויר', 'model': 'code', 'rag': True, 'tags': ('climate', 'weather', 'rain', 'snow', 'fog', 'season'),
                               'desc': 'אקלים רומא לפי חודשים -> הסתברויות לבהיר, מעונן, גשם, סערה, ערפל ושלג, וזריחה ושקיעה.'},
}

EDGES = [('fantasy.world_planner', 'fantasy.cartographer'), ('fantasy.cartographer', 'fantasy.world_generator'), ('fantasy.architect', 'fantasy.blender_builder'), ('fantasy.blender_builder', 'fantasy.librarian'),
         ('fantasy.botanist', 'fantasy.librarian'), ('fantasy.interior_designer', 'fantasy.librarian'), ('fantasy.palace_historian', 'fantasy.librarian'),
         ('fantasy.world_generator', 'fantasy.librarian'), ('fantasy.costume_designer', 'fantasy.character_builder'), ('fantasy.character_builder', 'fantasy.librarian'),
         ('fantasy.world_generator', 'fantasy.life_director'), ('fantasy.climate_master', 'fantasy.life_director'), ('fantasy.character_builder', 'fantasy.life_director'),
         ('fantasy.life_director', 'fantasy.librarian')]

TOOLS = {
    'fantasy.character_builder': [('world3d.library', 'ספריית World Foundry', 'גופי אדם מאומתים (SHA-256) לשימוש חוזר בכל עולם'),
                                  ('world3d.assets', 'MPFB 2 + עור MakeHuman (CC0)', 'גוף אנושי ריאליסטי עם שלד והנפשות walk/idle/talk/sit'),
                                  ('gltfpack', 'gltfpack (meshoptimizer, MIT)', 'הקטנת הגוף לקהל גדול בלי לאבד שלד, הנפשות ועור')],
    'fantasy.costume_designer': [('dye_palette', 'טבלת צבעי בד לפי תקופה', 'הצבעים נצבעים על הגוף בדפדפן, כך שגוף אחד משרת הרבה תלבושות')],
}

FOREIGN_EDGES = [('world3d.assets', 'fantasy.character_builder'), ('world3d.library', 'fantasy.character_builder')]
SHARED_AREA = 'world-foundry'

PERIODS = {'rome_late_antiquity': 'ידע: רומא בשלהי העת העתיקה', 'rome_imperial': 'ידע: רומא בתפארתה (ימי קונסטנטינוס)', 'fantasy_generic': 'ידע: עולמות פנטזיה'}

MANAGER_DB_FILE = DATA_DIR / 'manager_db.txt'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def period_of(spec):
    return {'rome_476': 'rome_late_antiquity', 'rome_315': 'rome_imperial'}.get((spec or {}).get('basemap'), 'fantasy_generic')


def model_for(profile):
    return MODEL_PROFILES[profile]['name']


class DeliverLink:
    def __init__(self, db_path='auto', store=None, rag=None):
        configured = MANAGER_DB_FILE.read_text().strip() if MANAGER_DB_FILE.is_file() else None
        self.db_path = (os.environ.get('FANTASY_MANAGER_DB') or configured) if db_path == 'auto' else db_path
        self.store = store
        self.rag = rag
        self.last = None
        self.conn = None
        if self.db_path:
            fresh = not Path(self.db_path).exists()
            if fresh:
                from ..db import DB
                DB(self.db_path).close()
            self.conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA busy_timeout=30000')

    @property
    def enabled(self):
        return self.conn is not None

    @property
    def db(self):
        link = self

        class Q:
            def q(self, sql, params=()):
                return link.conn.execute(sql, params).fetchall()

        return Q()

    def x(self, sql, params=()):
        return self.conn.execute(sql, params)

    def backup(self):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        target = Path(self.db_path).with_name(f'state.backup-before-fantasy-{stamp}.sqlite3')
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(str(target))
        src.backup(dst)
        src.close()
        dst.close()
        return str(target)

    def register(self):
        if not self.enabled:
            return 0
        now = now_iso()
        for did, d in DELIVERS.items():
            desc = f"{d['title']}: {d['desc']} מודל: {model_for(d['model'])}. עלות: 0 (מקומי, בלי טוקנים בתשלום)."
            self.x('INSERT INTO deliver_catalog (deliver_id, packet, owner, domain, description, source_kind, source_ref, execution_kind, implementation_ref, definition_hash, enabled, updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(deliver_id) DO UPDATE SET description=excluded.description, updated_at=excluded.updated_at',
                   (did, 'fantasy', 'fantasy-world-builder', 'fantasy', desc, 'fantasy', 'wwii_build/fantasy', 'deterministic', f'wwii_build.fantasy.deliver_link:{did}', None, now))
            caps = [('model', d['model'], model_for(d['model']), MODEL_PROFILES[d['model']]['why'])] + [('tool', *t) for t in TOOLS.get(did, [])]
            if d['rag']:
                caps += [('rag', key, label, 'מסמכי ידע ופריטים שנבנו') for key, label in PERIODS.items()]
            for group, name, label, why in caps:
                self.x('INSERT INTO deliver_capabilities (capability_id, deliver_id, system_id, group_name, name, kind, source_ref, description, active, updated_at) VALUES (?,?,?,?,?,?,?,?,1,?) '
                       'ON CONFLICT(capability_id) DO UPDATE SET description=excluded.description, updated_at=excluded.updated_at',
                       (f'{did}/{group}/{name}', did, 'fantasy', group, label, 'declared', 'wwii_build/fantasy', why, now))
        known = {r[0] for r in self.x("SELECT deliver_id FROM deliver_catalog WHERE deliver_id LIKE 'world3d.%'").fetchall()}
        for src, dst in EDGES + [e for e in FOREIGN_EDGES if e[0] in known]:
            self.x('INSERT INTO deliver_listener_edges (listener_id, source_deliver_id, target_deliver_id, event_type, source_kind, edge_type, jev_gate, enabled, updated_at) '
                   'VALUES (?,?,?,?,?,?,0,1,?) ON CONFLICT(listener_id) DO UPDATE SET updated_at=excluded.updated_at',
                   (f'fantasy:{src}->{dst}', src, dst, 'DELIVER_PASSED', 'fantasy', 'listener', now))
        tables = {r[0] for r in self.x("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if {'work_areas', 'deliver_areas'} <= tables and self.x('SELECT 1 FROM work_areas WHERE area_id=?', (SHARED_AREA,)).fetchone():
            for did in DELIVERS:
                self.x('INSERT OR IGNORE INTO deliver_areas (deliver_id, area_id, created_at) VALUES (?,?,?)', (did, SHARED_AREA, now))
        if self.rag:
            for did, d in DELIVERS.items():
                for doc in (self.rag.docs(['rome_late_antiquity', 'rome_imperial'], ('fact',)) if d['rag'] else []):
                    if set(d['tags']) & set(json.loads(doc['tags_json'])):
                        self.context(did, dict(doc))
        return len(DELIVERS)

    def context(self, did, doc):
        if not self.enabled:
            return
        now = now_iso()
        tags = json.loads(doc['tags_json']) if isinstance(doc.get('tags_json'), str) else list(doc.get('tags', []))
        self.x('INSERT INTO context_sources (source_key, task_id, origin_kind, origin_ref, graph_entity_id, graph_revision, title, excerpt, content_sha256, tags_json, active, created_at, updated_at, deliver_id) '
               'VALUES (?,NULL,?,?,?,NULL,?,?,?,?,1,?,?,?) ON CONFLICT(source_key) DO UPDATE SET excerpt=excluded.excerpt, updated_at=excluded.updated_at',
               (f"fantasy:{did}:{doc['id']}", 'fantasy_rag' if doc['kind'] == 'fact' else 'fantasy_built', str(doc['source'])[:200], doc['id'], str(doc['title'])[:200], str(doc['text'])[:600],
                str(abs(hash(doc['text']))), json.dumps(['fantasy', doc.get('collection', ''), doc['kind'], *tags], ensure_ascii=False), now, now, did))

    def retrieve(self, did, world_spec, query, object_id=None, kind=None):
        d = DELIVERS[did]
        if not (d['rag'] and self.rag):
            return [], []
        period = period_of(world_spec)
        facts = self.rag.search(query, [period], 5, ('fact',), d['tags'])
        related = self.rag.related(object_id or '-', kind or '', [period], query, 4)
        return facts, related

    def run(self, deliver_id, fn, payload, episode_id=None, world_spec=None, query=None, object_id=None, kind=None, tools=None):
        d = DELIVERS.get(deliver_id, {'model': 'code', 'rag': False, 'title': deliver_id, 'tags': ()})
        facts, related = self.retrieve(deliver_id, world_spec, query or json.dumps(payload, ensure_ascii=False, default=str)[:300], object_id, kind) if deliver_id in DELIVERS else ([], [])
        ctx = {'deliver': deliver_id, 'title': d['title'], 'model': model_for(d['model']), 'facts': facts, 'related': related, 'tools': list(tools or [])}
        run_id = 'fantasy-' + uuid.uuid4().hex[:12]
        started = now_iso()
        raw = json.dumps(payload, ensure_ascii=False, default=str)
        if self.enabled:
            self.x('INSERT INTO deterministic_deliver_runs (run_id, deliver_id, episode_id, status, input_bytes, output_bytes, cost_usd, detail_json, started_at) VALUES (?,?,?,?,?,0,0,?,?)',
                   (run_id, deliver_id, episode_id, 'RUNNING', len(raw.encode()), json.dumps({'model': ctx['model']}, ensure_ascii=False), started))
        t0 = time.time()
        try:
            result = fn(ctx) if fn.__code__.co_argcount else fn()
        except Exception as exc:
            if self.enabled:
                self.x('UPDATE deterministic_deliver_runs SET status=?, detail_json=?, completed_at=? WHERE run_id=?',
                       ('FAILED', json.dumps({'error': repr(exc)[:400], 'model': ctx['model']}, ensure_ascii=False), now_iso(), run_id))
            raise
        out = json.dumps(result, ensure_ascii=False, default=str)
        detail = {'seconds': round(time.time() - t0, 3), 'model': ctx['model'], 'rag': [f['title'] for f in facts], 'related': [r['title'] for r in related], 'cost': 0, **({'tools': ctx['tools']} if ctx['tools'] else {})}
        if self.enabled:
            self.x('UPDATE deterministic_deliver_runs SET status=?, output_bytes=?, detail_json=?, completed_at=? WHERE run_id=?',
                   ('COMPLETED', len(out.encode()), json.dumps(detail, ensure_ascii=False), now_iso(), run_id))
        if self.store:
            self.store.x('INSERT INTO deliver_runs VALUES (?,?,?,?,?,?,?)', (run_id, deliver_id, episode_id, ctx['model'], json.dumps(detail, ensure_ascii=False), started, time.time()))
        self.last = {**ctx, 'run_id': run_id, 'seconds': detail['seconds']}
        return result


def context_text(ctx):
    facts = '\n'.join(f"- {f['title']}: {f['text']} [{f['source']}]" for f in ctx.get('facts', []))
    related = '\n'.join(f"- {r['title']}: {r['text'][:300]}" for r in ctx.get('related', []))
    return (f"\nPeriod knowledge (retrieved, use it and stay consistent with it):\n{facts}\n" if facts else '') + \
           (f"\nItems already built in this world that are related (reuse their style and keep consistent):\n{related}\n" if related else '')


def public(ctx):
    return None if not ctx else {'deliver': ctx['deliver'], 'title': ctx['title'], 'model': ctx['model'], 'run_id': ctx.get('run_id'), 'tools': ctx.get('tools', []),
                                 'facts': [{'title': f['title'], 'source': f['source']} for f in ctx['facts']],
                                 'related': [{'title': r['title']} for r in ctx['related']]}
