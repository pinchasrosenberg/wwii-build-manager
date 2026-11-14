import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from .store import DATA_DIR

FOUNDRY_FILE = DATA_DIR / 'foundry_root.txt'
BODY_KINDS = ('resident', 'roman_resident')
CLIPS = {'walk', 'idle', 'talk', 'sit'}
GARMENT = {'tunic': 'Dyed linen', 'stola': 'Dyed linen', 'cloak': 'Wool outer drape', 'palla': 'Wool outer drape', 'toga': 'Wool outer drape'}
FEMALE_KINDS = {'matron', 'woman', 'vestal'}
DRAPED_KINDS = {'senator', 'matron', 'vestal'}
NO_BODY_KINDS = {'child', 'soldier', 'vigil'}
SIMPLIFY = '0.45'


def digest(path):
    with open(path, 'rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def glb_json(path):
    with open(path, 'rb') as fh:
        head = fh.read(20)
        magic, _, _, length, tag = struct.unpack('<4sIII4s', head)
        if magic != b'glTF' or tag != b'JSON':
            raise ValueError(f'not a GLB: {path}')
        return json.loads(fh.read(length))


def hex_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


class Foundry:
    def __init__(self, project='auto'):
        configured = FOUNDRY_FILE.read_text().strip() if FOUNDRY_FILE.is_file() else None
        chosen = (os.environ.get('WORLD_FOUNDRY') or configured) if project == 'auto' else project
        self.project = Path(chosen).expanduser() if chosen else None
        self.root = self.project.parents[1] / 'outputs' / 'world-foundry' if self.project else None
        self._catalog = None
        self._stamp = None
        self._verified = {}

    @property
    def enabled(self):
        return bool(self.project and (self.project / 'foundry.py').is_file() and (self.root / 'library').is_dir())

    @property
    def gltfpack(self):
        tool = self.project / '.tools' / 'gltfpack' if self.project else None
        return tool if tool and tool.is_file() else None

    def tools(self):
        if not self.enabled:
            return {}
        tools = self.project / '.tools'
        return {name: (tools / path).exists() for name, path in (('mpfb', 'blender/extensions'), ('makehuman_skins', 'human-assets/skins'), ('gltfpack', 'gltfpack'),
                                                                   ('poly_haven_grass', 'terrain/grass-diff.jpg'), ('triposr', 'triposr'), ('mflux', 'mflux'), ('beasts', 'beasts'))}

    def catalog(self):
        if not self.enabled:
            return []
        library = self.root / 'library'
        stamp = library.stat().st_mtime_ns
        if self._catalog is not None and self._stamp == stamp:
            return self._catalog
        rows = []
        for folder in library.iterdir():
            manifest = folder / 'manifest.json'
            if folder.is_symlink() or not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text())
            except (OSError, ValueError):
                continue
            if data.get('asset_id') != 'asset:' + folder.name:
                continue
            rows.append({**data, 'folder': str(folder), 'built': manifest.stat().st_mtime})
        rows.sort(key=lambda r: -r['built'])
        self._catalog, self._stamp = rows, stamp
        return rows

    def find(self, kind, **params):
        return next((r for r in self.catalog() if r['kind'] == kind and all(r['params'].get(k) == v for k, v in params.items())), None)

    def verified(self, asset, name):
        meta = asset['files'].get(name)
        path = Path(asset['folder']) / name
        if not meta or Path(name).name != name or path.is_symlink() or not path.is_file():
            return None
        key = (asset['asset_id'], name, path.stat().st_size, path.stat().st_mtime_ns)
        if key not in self._verified:
            self._verified[key] = path.stat().st_size == meta['bytes'] and digest(path) == meta['sha256']
        return path if self._verified[key] else None

    def bodies(self):
        seen = {}
        for row in self.catalog():
            if row['kind'] not in BODY_KINDS:
                continue
            tech = row.get('technical') or {}
            if not tech.get('skins') or tech.get('animations', 0) < len(CLIPS):
                continue
            variant = row['params'].get('role') or row['params'].get('name') or row['asset_id']
            if variant in seen:
                continue
            path = self.verified(row, 'asset.glb')
            if not path:
                continue
            seen[variant] = {**self.features(path), 'variant': variant, 'asset_id': row['asset_id'], 'path': str(path), 'kind': row['kind'],
                             'licenses': row.get('library_license_sources', []), 'review': row.get('review_status'), 'triangles': tech.get('triangles')}
        return list(seen.values())

    @staticmethod
    def features(path):
        gltf = glb_json(path)
        names = {m.get('name', ''): m for m in gltf.get('materials', [])}
        skin = next((n for n in names if n.lower().startswith('skin')), '')
        linen = names.get('Dyed linen', {}).get('pbrMetallicRoughness', {}).get('baseColorFactor', [0.5, 0.5, 0.5, 1])
        clips = {a.get('name') for a in gltf.get('animations', [])}
        return {'female': 'female' in skin.lower(), 'old': 'old' in skin.lower(), 'dark': 'african' in skin.lower(), 'draped': 'Wool outer drape' in names,
                'garments': sorted(n for n in names if n in GARMENT.values()), 'linen': linen[:3], 'clips': sorted(clips & CLIPS)}

    def simplified(self, body, out_dir):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        key = body['asset_id'].split(':')[1][:16]
        target = out_dir / f"{key}-s{SIMPLIFY.replace('.', '')}.glb"
        whole = out_dir / f'{key}.glb'
        done = next((p for p in (target, whole) if p.is_file() and p.stat().st_size > 0), None)
        if done:
            return done, 'cached'
        with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
            staging = Path(tmp) / target.name
            tool = self.gltfpack
            result = subprocess.run([str(tool), '-i', body['path'], '-o', str(staging), '-si', SIMPLIFY, '-kn', '-km', '-ke', '-noq'], capture_output=True, text=True, timeout=180) if tool else None
            gltf = glb_json(staging) if result and not result.returncode and staging.is_file() else {}
            if gltf.get('skins') and {a['name'] for a in gltf.get('animations', [])} >= CLIPS and not gltf.get('extensionsRequired'):
                staging.replace(target)
                return target, 'gltfpack'
            shutil.copyfile(body['path'], whole)
        return whole, 'copied'

    def request(self, brief, tasks, seconds=900):
        if not self.enabled or not tasks:
            return None
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            json.dump({'version': 1, 'brief': brief, 'tasks': tasks, 'gaps': [], 'provenance_class': 'Reconstruction'}, fh)
        try:
            result = subprocess.run([sys.executable, 'bridge.py', 'world3d: ' + brief, '--plan', fh.name], cwd=self.project, capture_output=True, text=True, timeout=seconds)
        finally:
            Path(fh.name).unlink(missing_ok=True)
        self._catalog = None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return {'status': 'failed', 'error': (result.stderr or result.stdout)[-600:]}


def dress(result, costumes, foundry, out_dir, dyes, skins):
    if not result.get('ok') or not foundry.enabled:
        return {**result, 'realistic': 0, 'foundry': None}
    bodies = foundry.bodies()
    by_name = {c['name']: c for c in costumes}
    types, used = [], {}
    for t in result['types']:
        body = match_body(by_name.get(t['name'], t), bodies, dyes, skins)
        if not body:
            types.append({**t, 'body': None})
            continue
        if body['asset_id'] not in used:
            used[body['asset_id']] = foundry.simplified(body, Path(out_dir) / 'foundry')
        path, how = used[body['asset_id']]
        types.append({**t, 'file': f'foundry/{path.name}', 'procedural_file': t['file'], 'bytes': path.stat().st_size, 'tint': tint_for(by_name.get(t['name'], t), body, dyes),
                      'body': {'source': 'world3d.assets', 'asset_id': body['asset_id'], 'variant': body['variant'], 'licenses': body['licenses'], 'review': body['review'],
                               'triangles': body['triangles'], 'lod': how}})
    realistic = sum(1 for t in types if t['body'])
    return {**result, 'types': types, 'realistic': realistic,
            'foundry': {'bodies': len(bodies), 'used': len(used), 'simplify': SIMPLIFY, 'tools': [k for k, v in foundry.tools().items() if v]}}


def costume_wants(costume, dyes, skins):
    kind = costume['kind']
    parts = costume.get('dyes', {})
    tunic = parts.get('tunic') or parts.get('stola')
    return {'female': kind in FEMALE_KINDS, 'draped': kind in DRAPED_KINDS or 'cloak' in parts or 'palla' in parts, 'dark': luminance(hex_rgb(skins[costume['skin']])) < 0.42,
            'linen': hex_rgb(dyes[tunic]) if tunic else hex_rgb(dyes.get('bleached', '#ebe5d6') if kind in DRAPED_KINDS else dyes.get('undyed', '#cbb895'))}


def match_body(costume, bodies, dyes, skins):
    exact = next((b for b in bodies if b['variant'] == costume['name']), None)
    if exact or costume['kind'] in NO_BODY_KINDS or costume.get('scale', 1.0) < 0.9:
        return exact
    want = costume_wants(costume, dyes, skins)
    fits = [b for b in bodies if b['female'] == want['female'] and b['draped'] == want['draped']]
    score = lambda b: (b['dark'] != want['dark']) * 0.4 + sum((x - y) ** 2 for x, y in zip(b['linen'], want['linen'])) + (0.05 if b['old'] else 0) + (0 if b['variant'].split('_')[0] == costume['name'].split('_')[0] else 0.2)
    return min(fits, key=score) if fits else None


def tint_for(costume, body, dyes):
    out = {}
    for part, dye in costume.get('dyes', {}).items():
        material = GARMENT.get(part)
        if material in body['garments'] and dye in dyes:
            out.setdefault(material, dyes[dye])
    if costume['kind'] in DRAPED_KINDS:
        for material in ('Wool outer drape', 'Dyed linen'):
            if material in body['garments'] and material not in out:
                out[material] = dyes.get('bleached', '#ebe5d6')
    return out
