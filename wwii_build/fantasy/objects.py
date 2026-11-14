import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from .models import ask_json

HERE = Path(__file__).parent
ADDITIONS = ['tower', 'bell_tower', 'dome', 'statues', 'colonnade', 'portico', 'balcony', 'arcade', 'stairs', 'banner', 'fountain', 'obelisk', 'crenellation', 'roof_garden', 'vines', 'windows', 'buttress', 'apse']
POSITIONS = ['front', 'back', 'left', 'right', 'top', 'corners', 'around']
SPECIES = ['umbrella_pine', 'cypress', 'olive', 'oak', 'fig', 'plane', 'pine', 'palm', 'laurel']
CROWNS = ['umbrella', 'column', 'round', 'spreading', 'cone', 'fan']

TREE_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['species', 'height', 'trunk_ratio', 'lean', 'crown_shape', 'crown_width', 'branches', 'levels', 'foliage', 'leaf_color', 'bark_color', 'notes'],
               'properties': {'species': {'type': 'string', 'enum': SPECIES}, 'height': {'type': 'number', 'minimum': 3, 'maximum': 30}, 'trunk_ratio': {'type': 'number', 'minimum': 0.1, 'maximum': 0.8},
                              'lean': {'type': 'number', 'minimum': 0, 'maximum': 25}, 'crown_shape': {'type': 'string', 'enum': CROWNS}, 'crown_width': {'type': 'number', 'minimum': 1, 'maximum': 25},
                              'branches': {'type': 'integer', 'minimum': 3, 'maximum': 9}, 'levels': {'type': 'integer', 'minimum': 1, 'maximum': 3}, 'foliage': {'type': 'number', 'minimum': 0, 'maximum': 1},
                              'leaf_color': {'type': 'string', 'pattern': '^#[0-9a-f]{6}$'}, 'bark_color': {'type': 'string', 'pattern': '^#[0-9a-f]{6}$'}, 'notes': {'type': 'string', 'maxLength': 400}}}

LANDMARK_SCHEMAS = {
    'amphitheater': {'orders': {'type': 'array', 'items': {'type': 'string', 'enum': ['tuscan', 'ionic', 'corinthian']}, 'minItems': 3, 'maxItems': 3},
                     'statues_in_arches': {'type': 'boolean'}, 'velarium_masts': {'type': 'boolean'}, 'attic_windows': {'type': 'boolean'}, 'hypogeum': {'type': 'boolean'}, 'collapsed_sector': {'type': 'boolean'}},
    'temple': {'order': {'type': 'string', 'enum': ['tuscan', 'ionic', 'corinthian']}, 'columns_front': {'type': 'integer', 'minimum': 4, 'maximum': 12}, 'fluting': {'type': 'boolean'},
               'pediment_relief': {'type': 'boolean'}, 'acroteria': {'type': 'boolean'}},
    'triumphal_arch': {'reliefs': {'type': 'boolean'}, 'statues_on_attic': {'type': 'boolean'}, 'attic_inscription': {'type': 'boolean'}},
    'palace': {'portico_columns': {'type': 'integer', 'minimum': 6, 'maximum': 16}, 'upper_story': {'type': 'boolean'}},
    'house': {'floors': {'type': 'integer', 'minimum': 1, 'maximum': 7}, 'roof': {'type': 'string', 'enum': ['hip', 'gable']}, 'balcony': {'type': 'boolean'},
              'shop_front': {'type': 'boolean'}, 'shutters': {'type': 'boolean'}},
}

ADDITION_SCHEMA = {'type': 'array', 'maxItems': 8, 'items': {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'position', 'size', 'count', 'color'],
                   'properties': {'kind': {'type': 'string', 'enum': ADDITIONS}, 'position': {'type': 'string', 'enum': POSITIONS},
                                  'size': {'type': 'string', 'enum': ['small', 'medium', 'large']}, 'count': {'type': 'integer', 'minimum': 1, 'maximum': 16},
                                  'color': {'type': ['string', 'null'], 'pattern': '^#[0-9a-f]{6}$'}}}}

FACTS = {
    'colosseum': 'Facts: four storeys; engaged half-columns bottom to top are Tuscan, Ionic, Corinthian; the attic has Corinthian pilasters, small square windows and stone corbels that held the velarium masts. In 476 the building still stood complete (games continued until c. 523); the great collapse of the south side came with the earthquake of 1349, so in 476 only minor damage, weeds and missing bronze clamps. Statues in the 2nd and 3rd storey arches are attested on coins of Titus; by 476 many were probably gone. The velarium was no longer operated by the 5th century, but the corbels/mast sockets remained. The hypogeum under the arena existed.',
    'arch_constantine': 'Facts: triple arch (315 AD), eight free-standing Corinthian columns of giallo antico, Dacian prisoner statues on the attic, reused Trajanic, Hadrianic and Aurelian reliefs, dedicatory inscription in bronze letters on the attic.',
    'arch_titus': 'Facts: single-bay arch (81 AD), engaged composite columns, interior reliefs of the triumph and the spoils of Jerusalem, attic inscription.',
    'arch_severus': 'Facts: triple arch (203 AD) of marble, free-standing composite columns, large panel reliefs of the Parthian wars, inscription on the attic.',
    'jupiter': 'Facts: Temple of Jupiter Optimus Maximus on the Capitoline, rebuilt by Domitian with Corinthian columns of Pentelic marble, six columns across the front, gilded roof tiles (stripped by the Vandals in 455).',
    'venus_roma': 'Facts: Hadrian\'s temple, the largest in Rome, decastyle Corinthian, two back-to-back cellae with apses, roof restored by Maxentius after a fire in 307.',
    'palace': 'Facts: Domus Flavia on the Palatine by Rabirius (92 AD): tall facade toward the Area Palatina with a portico of columns of coloured marble, upper storey, tiled roof; still the seat of the emperors and later of Ostrogothic kings in the 5th-6th centuries.',
}

FACTS_HE = {
    'colosseum': 'ב־476 הקולוסיאום עדיין עמד שלם: ארבע קומות, עמודים טוסקניים, יוניים וקורינתיים מלמטה למעלה, וקומה עליונה עם חלונות קטנים ותושבות לתרני הסוכך. משחקים נערכו בו עד בערך 523. הסוכך (velarium) כבר לא הופעל, ורוב הפסלים שבקשתות כבר לא היו. הקריסה הגדולה של הצד הדרומי באה רק ברעידת האדמה של 1349.',
    'arch_constantine': 'שער משולש מ־315 לספירה: שמונה עמודים קורינתיים מאבן ג׳אלו אנטיקו, פסלי שבויים דאקים על העליה, תבליטים ממונומנטים קודמים, וכתובת הקדשה באותיות ברונזה.',
    'arch_titus': 'שער בעל פתח אחד מ־81 לספירה, עם עמודים צמודים, תבליטי הניצחון ושלל ירושלים בתוך המעבר, וכתובת על העליה.',
    'arch_severus': 'שער משולש משיש מ־203 לספירה, עם עמודים חופשיים, תבליטים גדולים ממלחמות פרתיה וכתובת על העליה.',
    'jupiter': 'מקדש יופיטר על הקפיטולין, בנייתו של דומיטיאנוס: שישה עמודים קורינתיים משיש פנטלי בחזית. רעפי הזהב של הגג נשדדו בידי הוונדלים ב־455.',
    'venus_roma': 'המקדש הגדול ברומא, של אדריאנוס: עשרה עמודים קורינתיים בחזית ושני תאים גב אל גב עם אפסיסים. מקסנטיוס שיקם את הגג אחרי שריפה ב־307.',
    'palace': 'דומוס פלאוויה על הפלטין (92 לספירה): חזית גבוהה עם אכסדרת עמודים משיש צבעוני, קומה עליונה וגג רעפים. במאות ה־5–6 ישבו בו הקיסרים ואחריהם מלכי האוסטרוגותים.',
}

SPECIES_FACTS = {
    'umbrella_pine': {'en': 'Italian stone pine (Pinus pinea): straight tall trunk, clear of branches for 55-75% of its height, reddish-brown bark in deep plates, flat wide umbrella crown of dark green needles, 12-25 m tall; planted in Roman gardens, sanctuaries and along roads, pine nuts eaten.',
                      'he': 'אורן הצנובר (אורן המטרייה) גדל ברומא כבר בימי קדם. יש לו גזע ישר וגבוה עם קליפה חומה־אדמדמה בלוחות עבים, וצמרת שטוחה ורחבה כמו מטרייה. הרומאים שתלו אותו בגנים, במקדשים ולאורך דרכים, ואכלו את הצנוברים שלו.',
                      'fix': {'crown_shape': 'umbrella', 'bark_color': '#8a5a3c', 'leaf_color': '#3a5530'}, 'range': {'height': (12, 25), 'trunk_ratio': (0.55, 0.75)}},
    'cypress': {'en': 'Mediterranean cypress (Cupressus sempervirens): narrow columnar evergreen 10-25 m, dark green, planted by tombs and in gardens.',
                'he': 'הברוש הים־תיכוני צר וגבוה כמו עמוד, וירוק כהה כל השנה. הרומאים שתלו אותו ליד קברים ובגנים.',
                'fix': {'crown_shape': 'column', 'bark_color': '#6a4a32', 'leaf_color': '#2c4a2b'}, 'range': {'height': (10, 25), 'trunk_ratio': (0.05, 0.15)}},
    'olive': {'en': 'Olive (Olea europaea): low 5-9 m, twisted grey trunk, rounded silvery-green crown.',
              'he': 'עץ הזית נמוך (5–9 מ׳), עם גזע אפור ומפותל וצמרת עגולה בצבע ירוק־כסוף.',
              'fix': {'crown_shape': 'round', 'bark_color': '#7a7266', 'leaf_color': '#7d8a5a'}, 'range': {'height': (5, 9), 'trunk_ratio': (0.25, 0.45)}},
}

TREE_DEFAULTS = {
    'umbrella_pine': {'species': 'umbrella_pine', 'height': 16, 'trunk_ratio': 0.62, 'lean': 8, 'crown_shape': 'umbrella', 'crown_width': 13, 'branches': 6, 'levels': 2, 'foliage': 0.8, 'leaf_color': '#3d5a33', 'bark_color': '#6a4a32'},
    'cypress': {'species': 'cypress', 'height': 15, 'trunk_ratio': 0.1, 'lean': 1, 'crown_shape': 'column', 'crown_width': 2.6, 'branches': 8, 'levels': 1, 'foliage': 0.95, 'leaf_color': '#2c4a2b', 'bark_color': '#5a3d24'},
}


def tree_prompt(tree, text):
    facts = SPECIES_FACTS.get(tree.get('kind'), {}).get('en', '')
    return f"""You are a botanist and historian of ancient Rome. The user is looking at a tree of type "{tree.get('kind')}" in Rome around 476 AD (or a fantasy world) and asks (Hebrew or English): {text}
{facts}
Describe how such a tree really looked (species typical of the place and era, height, trunk, crown shape, branching, colours) and return JSON following the schema. "notes" is 1-2 short Hebrew sentences about what is known."""


def landmark_prompt(kind, name, text, facts=''):
    return f"""You are an expert in Roman architecture. The user is looking at "{name}" (kind: {kind}) in Rome around 476 AD and asks (Hebrew or English): {text}
{facts}
The parameters must agree with the facts and with your notes (do not say something is missing and then enable it).
Decide, from what is historically known, which architectural details the detailed 3D model should have, and return JSON following the schema. "notes" is 2-3 short Hebrew sentences: what is known about how it really looked at that time and in what state."""


def species_fix(kind, params):
    facts = SPECIES_FACTS.get(params.get('species')) or SPECIES_FACTS.get(kind)
    if not facts:
        return params
    out = {**params, **facts['fix'], 'notes': facts['he']}
    for key, (lo, hi) in facts['range'].items():
        out[key] = max(lo, min(hi, float(out.get(key, lo))))
    return out


def plan_object(target, obj, text, use_llm=True, context=''):
    kind = target['type']
    if kind == 'tree':
        base = dict(TREE_DEFAULTS.get(obj.get('kind'), TREE_DEFAULTS['umbrella_pine']))
        if use_llm:
            data, source = ask_json('Return only JSON. Write "notes" in clear, simple Hebrew.', tree_prompt(obj, text) + context, (), TREE_SCHEMA)
            data['notes'] = re.sub(r'[\u3000-\u9fff]+', '', data.get('notes', ''))
            return species_fix(obj.get('kind'), {**base, **data}), source
        return species_fix(obj.get('kind'), {**base, 'notes': ''}), 'rules'
    lk = 'palace' if kind == 'palace' else ('house' if kind == 'house' else obj['kind'])
    props = {**LANDMARK_SCHEMAS.get(lk, {}), 'additions': ADDITION_SCHEMA, 'notes': {'type': 'string', 'maxLength': 600}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}
    if use_llm:
        data, source = ask_json('Return only JSON. Write "notes" in clear, simple Hebrew.', landmark_prompt(lk, obj.get('name', lk), text, FACTS.get(obj.get('id'), FACTS.get(lk, ''))) + context, (), schema)
        if lk == 'amphitheater':
            data['orders'] = ['tuscan', 'ionic', 'corinthian']
        known = FACTS_HE.get(obj.get('id')) or FACTS_HE.get(lk)
        data['notes'] = known or re.sub(r'[\u3000-\u9fff]+', '', data.get('notes', ''))
        return data, source
    return {'notes': FACTS_HE.get(obj.get('id'), ''), 'additions': rules_additions(text)}, 'rules'


ADDITION_WORDS = {'tower': ['מגדל', 'tower'], 'bell_tower': ['מגדל-פעמונים', 'פעמונים', 'campanile', 'bell'], 'dome': ['כיפה', 'dome'], 'statues': ['פסל', 'פסלים', 'statue', 'statues'],
                  'colonnade': ['עמודים', 'קולונדה', 'colonnade', 'columns'], 'portico': ['אכסדרה', 'פורטיקו', 'portico'], 'balcony': ['מרפסת', 'מרפסות', 'balcony'],
                  'arcade': ['קשתות', 'ארקדה', 'arcade', 'arches'], 'stairs': ['מדרגות', 'stairs', 'steps'], 'banner': ['דגל', 'דגלים', 'banner'], 'fountain': ['מזרקה', 'fountain'],
                  'obelisk': ['אובליסק', 'obelisk'], 'crenellation': ['חומה', 'צריחים', 'battlements', 'crenellations'], 'roof_garden': ['גן-על-הגג', 'גינה', 'garden'],
                  'vines': ['קיסוס', 'צמחייה', 'vines', 'ivy'], 'windows': ['חלונות', 'windows'], 'buttress': ['תמוכות', 'buttress'], 'apse': ['אפסיס', 'apse']}


def rules_additions(text):
    from .lexicon import has_any, tokens
    toks = tokens(text)
    found = [k for k, words in ADDITION_WORDS.items() if has_any(toks, words)]
    return [{'kind': k, 'position': 'top' if k in ('dome', 'roof_garden') else ('corners' if k in ('tower', 'bell_tower') else 'front'), 'size': 'medium', 'count': 1, 'color': None} for k in found]


def blender_binary():
    return shutil.which('blender') or ('/Applications/Blender.app/Contents/MacOS/Blender' if Path('/Applications/Blender.app').exists() else None)


def build_model(kind, obj, params, out_dir, decay):
    binary = blender_binary()
    if not binary:
        raise RuntimeError('Blender לא מותקן')
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{obj.get('id', kind)}-{uuid.uuid4().hex[:6]}.glb"
    spec = {'kind': kind, 'w': obj['w'], 'd': obj['d'], 'h': obj['h'], 'state': obj.get('state', decay), 'seed': abs(hash(obj.get('id', kind))) % 9999, 'params': params,
            **{k: obj[k] for k in ('wall_color', 'roof_color', 'floors') if obj.get(k) is not None}}
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
        json.dump(spec, fh)
    result = subprocess.run([binary, '-b', '--factory-startup', '--python', str(HERE / 'blender_detail.py'), '--', fh.name, str(out_dir / name)],
                            capture_output=True, text=True, timeout=600)
    if not (out_dir / name).exists():
        raise RuntimeError('Blender נכשל: ' + (result.stderr or result.stdout)[-400:])
    return name
