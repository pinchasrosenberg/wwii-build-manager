import json
import math
import struct
import time
import urllib.request
import uuid
from pathlib import Path

from .lexicon import tokens
from .models import OLLAMA_URL

EMBED_MODEL = 'nomic-embed-text'
KNOWLEDGE = Path(__file__).parent / 'knowledge'

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_docs (
    id TEXT PRIMARY KEY, collection TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
    tags_json TEXT NOT NULL, ref TEXT, embedding BLOB, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_rag_collection ON rag_docs(collection, kind);
CREATE TABLE IF NOT EXISTS rag_links (
    src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (src, rel, dst));
CREATE INDEX IF NOT EXISTS idx_rag_links_dst ON rag_links(dst, rel)
"""


def embed(text, kind='document'):
    body = json.dumps({'model': EMBED_MODEL, 'prompt': f'search_{kind}: {text}'}).encode()
    req = urllib.request.Request(f'{OLLAMA_URL}/api/embeddings', data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            vec = json.loads(resp.read()).get('embedding') or []
    except OSError:
        vec = []
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def pack(vec):
    return struct.pack(f'{len(vec)}f', *vec) if vec else None


def unpack(blob):
    return list(struct.unpack(f'{len(blob) // 4}f', blob)) if blob else []


def overlap(query, text):
    q = set(tokens(query))
    t = set(tokens(text))
    return len(q & t) / (len(q) or 1)


class Rag:
    def __init__(self, store):
        self.store = store
        for stmt in [s for s in SCHEMA.split(';') if s.strip()]:
            self.store.x(stmt)

    def add(self, collection, kind, title, text, source, tags=(), ref=None, doc_id=None):
        did = doc_id or f'{kind}:{uuid.uuid4().hex[:10]}'
        vec = embed(f'{title}. {text}')
        self.store.x('INSERT OR REPLACE INTO rag_docs VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (did, collection, kind, title, text, source, json.dumps(list(tags), ensure_ascii=False), ref, pack(vec), time.time()))
        return did

    def link(self, src, rel, dst):
        self.store.x('INSERT OR IGNORE INTO rag_links VALUES (?,?,?,?)', (src, rel, dst, time.time()))

    def seed(self, collection, path):
        if self.store.one('SELECT 1 FROM rag_docs WHERE collection=? AND kind=? LIMIT 1', (collection, 'fact')):
            return 0
        docs = json.loads(Path(path).read_text(encoding='utf-8'))
        for k, d in enumerate(docs):
            did = self.add(collection, 'fact', d['title'], d['text'], d['source'], d['tags'], None, f'fact:{collection}:{k}')
            self.link(did, 'in_period', f'period:{collection}')
        return len(docs)

    def seed_all(self):
        return {p.stem: self.seed(p.stem, p) for p in KNOWLEDGE.glob('*.json')}

    def docs(self, collections, kinds=None):
        marks = ','.join('?' * len(collections))
        rows = self.store.q(f'SELECT * FROM rag_docs WHERE collection IN ({marks})', tuple(collections))
        return [r for r in rows if not kinds or r['kind'] in kinds]

    def search(self, query, collections, k=5, kinds=None, tags=()):
        rows = self.docs(collections, kinds)
        if not rows:
            return []
        qv = embed(query, 'query')
        scored = []
        for r in rows:
            dv = unpack(r['embedding'])
            sim = sum(a * b for a, b in zip(qv, dv)) if qv and dv else 0.0
            tag_bonus = 0.08 * len(set(tags) & set(json.loads(r['tags_json'])))
            scored.append((sim + 0.25 * overlap(query, r['title'] + ' ' + r['text']) + tag_bonus, r))
        scored.sort(key=lambda x: -x[0])
        return [{'id': r['id'], 'title': r['title'], 'text': r['text'], 'source': r['source'], 'kind': r['kind'], 'ref': r['ref'],
                 'score': round(s, 3), 'tags': json.loads(r['tags_json'])} for s, r in scored[:k]]

    def related(self, object_id, kind, collections, query, k=4):
        direct = [dict(r) for r in self.store.q('SELECT d.* FROM rag_docs d JOIN rag_links l ON l.src=d.id WHERE l.rel=? AND l.dst=? ORDER BY d.created_at DESC', ('describes', f'object:{object_id}'))]
        similar = self.search(query, collections, k + len(direct), kinds=('built',), tags=(kind,))
        seen = {d['id'] for d in direct}
        out = [{'id': d['id'], 'title': d['title'], 'text': d['text'], 'source': d['source'], 'kind': 'built', 'ref': d['ref'], 'score': 1.0, 'tags': json.loads(d['tags_json'])} for d in direct]
        return (out + [s for s in similar if s['id'] not in seen])[:k]

    def links_of(self, node):
        return [dict(r) for r in self.store.q('SELECT * FROM rag_links WHERE src=? OR dst=?', (node, node))]
