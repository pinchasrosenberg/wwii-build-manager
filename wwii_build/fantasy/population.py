import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from .models import ask_json
from .objects import blender_binary

HERE = Path(__file__).parent

DYES = {
    'undyed': '#cbb895', 'bleached': '#ebe5d6', 'madder': '#9c3b2e', 'woad': '#4b6283', 'weld': '#b8963a', 'green': '#5f6b3a',
    'brown': '#6e5238', 'murex': '#5b2a4a', 'ochre': '#b0763a', 'dark': '#3a3430', 'saffron': '#c99a3a', 'rose': '#b0645c',
}
SKINS = ['#c8946e', '#b07a55', '#d9a682', '#8f6043', '#a8724e']
HAIRS = ['#2a1d12', '#3b2a1a', '#4a3524', '#8a8580', '#1a120c']

COSTUMES = [
    {'name': 'senator', 'kind': 'senator', 'role': 'walker', 'weight': 3, 'hours': [7, 16], 'skin': 2, 'hair': 3, 'dyes': {},
     'label': 'סנאטור בטוגה לבנה, טוניקה עם פס ארגמן רחב (latus clavus)', 'tags': ['toga', 'clavus', 'senator']},
    {'name': 'senator_young', 'kind': 'senator', 'role': 'gossip', 'weight': 2, 'hours': [7, 15], 'skin': 0, 'hair': 1, 'dyes': {},
     'label': 'סנאטור צעיר בטוגה בדרכו לפורום', 'tags': ['toga', 'clavus', 'senator']},
    {'name': 'equestrian', 'kind': 'citizen', 'role': 'walker', 'weight': 3, 'hours': [7, 17], 'skin': 1, 'hair': 0, 'clavus': True, 'dyes': {'tunic': 'bleached'},
     'label': 'פרש (אקווס) — טוניקה לבנה עם פסים צרים (angustus clavus)', 'tags': ['clavus', 'equestrian']},
    {'name': 'citizen_undyed', 'kind': 'citizen', 'role': 'walker', 'weight': 9, 'hours': [5, 21], 'skin': 0, 'hair': 0, 'dyes': {'tunic': 'undyed'},
     'label': 'אזרח בטוניקת צמר לא צבועה', 'tags': ['tunic', 'plebs']},
    {'name': 'citizen_red', 'kind': 'citizen', 'role': 'walker', 'weight': 6, 'hours': [5, 21], 'skin': 1, 'hair': 1, 'dyes': {'tunic': 'madder'},
     'label': 'אזרח בטוניקה צבועה בפואה (אדום)', 'tags': ['tunic', 'dye', 'plebs']},
    {'name': 'citizen_blue', 'kind': 'citizen', 'role': 'gossip', 'weight': 5, 'hours': [6, 20], 'skin': 4, 'hair': 2, 'dyes': {'tunic': 'woad'},
     'label': 'אזרח בטוניקה כחולה (איסטיס)', 'tags': ['tunic', 'dye', 'plebs']},
    {'name': 'citizen_cloak', 'kind': 'citizen', 'role': 'walker', 'weight': 5, 'hours': [5, 21], 'skin': 3, 'hair': 0, 'dyes': {'tunic': 'ochre', 'cloak': 'brown'},
     'label': 'אזרח בגלימת פאנולה חומה עם ברדס — לבוש לגשם ולקור', 'tags': ['paenula', 'cloak', 'rain']},
    {'name': 'matron', 'kind': 'matron', 'role': 'walker', 'weight': 4, 'hours': [8, 17], 'skin': 2, 'hair': 1, 'dyes': {'stola': 'bleached', 'palla': 'madder'},
     'label': 'מטרונה בסטולה ופאלה אדומה המכסה את הראש', 'tags': ['stola', 'palla', 'matron']},
    {'name': 'matron_rich', 'kind': 'matron', 'role': 'gossip', 'weight': 3, 'hours': [9, 16], 'skin': 2, 'hair': 0, 'dyes': {'stola': 'murex', 'palla': 'saffron'},
     'label': 'אשת אצולה בסטולה סגולה ופאלה זהובה', 'tags': ['stola', 'palla', 'murex', 'noble']},
    {'name': 'woman_blue', 'kind': 'woman', 'role': 'shopper', 'weight': 5, 'hours': [6, 19], 'skin': 0, 'hair': 2, 'dyes': {'tunic': 'woad', 'palla': 'undyed'},
     'label': 'אישה עובדת בטוניקה ארוכה ומטפחת', 'tags': ['tunic', 'palla', 'plebs']},
    {'name': 'woman_green', 'kind': 'woman', 'role': 'shopper', 'weight': 4, 'hours': [6, 19], 'skin': 1, 'hair': 1, 'dyes': {'tunic': 'green', 'palla': 'rose'},
     'label': 'אישה בשוק בטוניקה ירוקה', 'tags': ['tunic', 'palla', 'market']},
    {'name': 'porter', 'kind': 'slave', 'role': 'porter', 'weight': 6, 'hours': [4, 21], 'skin': 3, 'hair': 0, 'dyes': {},
     'label': 'סבל/עבד נושא אמפורה — אקסומיס פשוטה', 'tags': ['exomis', 'slave', 'porter']},
    {'name': 'porter_light', 'kind': 'slave', 'role': 'porter', 'weight': 4, 'hours': [4, 21], 'skin': 2, 'hair': 1, 'dyes': {},
     'label': 'עבד בית בשליחות', 'tags': ['exomis', 'slave']},
    {'name': 'merchant', 'kind': 'merchant', 'role': 'vendor', 'weight': 4, 'hours': [5, 19], 'skin': 1, 'hair': 1, 'dyes': {'tunic': 'weld'},
     'label': 'סוחר בטוניקה צהובה, סינר וכובע לבד', 'tags': ['merchant', 'market', 'taberna']},
    {'name': 'merchant_brown', 'kind': 'merchant', 'role': 'vendor', 'weight': 3, 'hours': [5, 19], 'skin': 4, 'hair': 3, 'dyes': {'tunic': 'brown'},
     'label': 'בעל טברנה בטוניקה חומה', 'tags': ['merchant', 'taberna']},
    {'name': 'soldier', 'kind': 'soldier', 'role': 'patrol', 'weight': 2, 'hours': [0, 24], 'skin': 1, 'hair': 4, 'dyes': {},
     'label': 'חייל הקוהורטות העירוניות — שריון קשקשים, קסדה, חנית ומגן', 'tags': ['soldier', 'cohortes_urbanae']},
    {'name': 'vigil', 'kind': 'vigil', 'role': 'night', 'weight': 2, 'hours': [18, 7], 'skin': 0, 'hair': 0, 'dyes': {},
     'label': 'ויגיל (שומר לילה וכבאי) עם לפיד ודלי', 'tags': ['vigiles', 'night', 'torch']},
    {'name': 'child', 'kind': 'child', 'role': 'walker', 'weight': 4, 'hours': [8, 18], 'skin': 2, 'hair': 1, 'scale': 0.62, 'dyes': {'tunic': 'undyed'},
     'label': 'ילד בטוניקה עם בולה (קמע) על הצוואר', 'tags': ['child', 'bulla']},
    {'name': 'vestal', 'kind': 'vestal', 'role': 'gossip', 'weight': 0.4, 'hours': [8, 15], 'skin': 2, 'hair': 0, 'dyes': {},
     'label': 'בתולת וסטה בלבן עם סופיבולום', 'tags': ['vestal', 'religion']},
    {'name': 'bearer', 'kind': 'bearer', 'role': 'bearer', 'weight': 0, 'hours': [7, 18], 'skin': 3, 'hair': 0, 'dyes': {},
     'label': 'נושא אפריון (לקטיקריוס) בטוניקה אדומה אחידה', 'tags': ['lectica', 'bearer']},
]

PALETTE_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['choices'],
    'properties': {'choices': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'part', 'dye'],
                                                          'properties': {'name': {'type': 'string', 'enum': [c['name'] for c in COSTUMES]},
                                                                         'part': {'type': 'string', 'enum': ['tunic', 'cloak', 'stola', 'palla']},
                                                                         'dye': {'type': 'string', 'enum': list(DYES)}}}}},
}

PALETTE_SYSTEM = """You are a costume historian for Rome in the age of Constantine (c. 315 CE).
Given the costume list and the period knowledge, choose period-correct dyes for the coloured garments. Senators keep the white toga.
Only purple (murex) for the rich. Return JSON {"choices":[{"name","part","dye"}]} using only the allowed names, parts and dyes."""


def resolved(costume):
    out = {'name': costume['name'], 'kind': costume['kind'], 'skin': SKINS[costume['skin']], 'hair': HAIRS[costume['hair']], 'scale': costume.get('scale', 1.0)}
    out.update({part: DYES[dye] for part, dye in costume['dyes'].items()})
    costume.get('clavus') and out.update({'clavus': True})
    return out


def design_costumes(context='', use_llm=False):
    costumes = [{**c, 'dyes': dict(c['dyes'])} for c in COSTUMES]
    notes = ['צבעי הבגדים נקבעו לפי טבלת הצבעים של התקופה (פואה, איסטיס, ריסדה, ארגמן)']
    if use_llm:
        listing = '\n'.join(f"{c['name']}: {c['label']} parts={list(c['dyes'])}" for c in costumes if c['dyes'])
        try:
            data, _ = ask_json(PALETTE_SYSTEM, f'Period knowledge:\n{context}\n\nCostumes:\n{listing}', schema=PALETTE_SCHEMA)
        except (OSError, RuntimeError, ValueError):
            data = None
        picks = [ch for ch in (data or {}).get('choices', []) if ch.get('dye') in DYES]
        by_name = {c['name']: c for c in costumes}
        applied = [by_name[ch['name']]['dyes'].update({ch['part']: ch['dye']}) or ch for ch in picks if ch['name'] in by_name and ch['part'] in by_name[ch['name']]['dyes'] and not (ch['dye'] == 'murex' and by_name[ch['name']]['kind'] not in ('matron', 'senator'))]
        notes = [f'המודל המקומי בחר {len(applied)} צבעים לפי ידע התקופה'] if applied else ['המודל המקומי לא החזיר בחירה תקינה — נשארו צבעי ברירת המחדל של התקופה']
    return costumes, notes


def spec_hash(specs):
    return hashlib.sha1(json.dumps(specs, sort_keys=True).encode()).hexdigest()[:12]


def build_population(costumes, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [resolved(c) for c in costumes]
    digest = spec_hash(specs)
    manifest_path = out_dir / 'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get('hash') == digest and all((out_dir / f"{s['name']}.glb").exists() for s in specs):
            return {**old, 'cached': True}
    binary = blender_binary()
    if not binary:
        return {'ok': False, 'error': 'Blender לא מותקן', 'types': []}
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
        json.dump(specs, fh)
    result = subprocess.run([binary, '-b', '--factory-startup', '--python', str(HERE / 'blender_people.py'), '--', fh.name, str(out_dir)],
                            capture_output=True, text=True, timeout=600)
    Path(fh.name).unlink(missing_ok=True)
    missing = [s['name'] for s in specs if not (out_dir / f"{s['name']}.glb").exists()]
    if result.returncode != 0 or missing:
        return {'ok': False, 'error': (result.stderr or result.stdout)[-600:], 'types': [], 'missing': missing}
    types = [{'name': c['name'], 'kind': c['kind'], 'role': c['role'], 'weight': c['weight'], 'hours': c['hours'], 'label': c['label'], 'tags': c['tags'],
              'file': f"{c['name']}.glb", 'bytes': (out_dir / f"{c['name']}.glb").stat().st_size, 'animations': ['walk', 'idle', 'talk', 'sit']} for c in costumes]
    manifest = {'ok': True, 'hash': digest, 'types': types}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return {**manifest, 'cached': False}
