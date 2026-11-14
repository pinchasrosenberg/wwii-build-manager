import copy
import json
import re
import zlib

from .interpreter import MOODS, interpret_world_rules
from .lexicon import COLORS, has_any, tokens
from .models import ask_json

DIRS = ('center', 'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw')
HILL_DIRS = tuple(f'hill_{d}' for d in DIRS[1:])
TERRAINS = ('sharp_mountains', 'mountains', 'hills', 'plains', 'valley', 'islands', 'coast', 'canyon', 'desert', 'cliff_port')
MATERIALS = ('stone', 'wood', 'marble', 'sandstone', 'brick', 'ice', 'dark_stone', 'plaster')
ROOFS = ('gable', 'hip', 'pointed', 'dome', 'flat', 'curved')
PITCHES = ('low', 'normal', 'steep')
WINDOWS = ('arched', 'rect', 'round')
STREETS = ('winding', 'grid', 'radial')
SIZES = ('small', 'medium', 'large')
LANDMARKS = ('amphitheater', 'temple', 'round_temple', 'triumphal_arch', 'aqueduct', 'basilica', 'tower', 'lighthouse', 'windmill',
             'fountain', 'statue', 'obelisk', 'column', 'garden', 'market', 'theater', 'circus', 'forum', 'bath', 'pantheon', 'castle',
             'market_stalls', 'church', 'lime_kiln', 'vegetable_garden')
SPECIES = ('pine', 'broadleaf', 'palm', 'cypress', 'umbrella_pine', 'shrub')
TIMES = ('dawn', 'day', 'golden', 'dusk', 'night')
PALACE_KINDS = ('castle', 'classical')
BASEMAPS = ('none', 'rome_476', 'rome_315')
GLORY_WORDS = ['תפארת', 'בתפארתה', 'בתפארת', 'שיא', 'בשיאה', 'קיסרות', 'הקיסרות', 'קיסרית', 'קונסטנטינוס', 'אוגוסטוס', 'glory', 'imperial', 'empire', 'constantine', 'augustus', 'golden', 'peak', '315']
FALL_WORDS = ['נפילה', 'הנפילה', 'שנפלה', 'מוזנח', 'מוזנחת', 'מוזנחים', 'חורבות', 'החשוכה', 'fall', 'fallen', 'dark', 'ruined', '476']

HOUSE_STYLE = {
    'material': 'stone', 'roof': 'gable', 'roof_pitch': 'normal', 'window': 'rect',
    'wall_colors': [], 'roof_colors': [], 'floors': [1, 3],
    'timber': False, 'balconies': False, 'arcades': False, 'chimneys': True, 'towers': 0.05, 'shutters': False,
}

DEFAULT_PLAN = {
    'title': '', 'basemap': 'none',
    'terrain': {'kind': 'mountains', 'relief': 0.5, 'sharpness': 0.4, 'hills': 0},
    'water': {'sea_side': 'none', 'rivers': [], 'lakes': [], 'falls': False},
    'climate': {'precip': 'none', 'fog': False, 'vegetation': 'temperate', 'snow_roofs': False, 'snow_ground': False},
    'nature': {'trees': 0.35, 'species': []},
    'mood': 'realistic', 'time_of_day': 'day',
    'city': {'at': 'center', 'size': 'medium', 'density': 0.55, 'street': 'winding', 'walls': False, 'stairs': False, 'bridges': True},
    'condition': {'decay': 0.0, 'overgrowth': 0.0, 'ruins': 0.0},
    'style': HOUSE_STYLE,
    'districts': [],
    'palace': {'at': 'center', 'kind': 'castle', 'wall_color': None, 'roof_color': None, 'roof': None},
    'landmarks': [],
}

DIR_WORDS = [
    ('ne', ['צפון-מזרח', 'צפון־מזרח', 'צפונמזרח', 'northeast', 'north-east']),
    ('nw', ['צפון-מערב', 'צפון־מערב', 'צפונמערב', 'northwest', 'north-west']),
    ('se', ['דרום-מזרח', 'דרום־מזרח', 'דרוםמזרח', 'southeast', 'south-east']),
    ('sw', ['דרום-מערב', 'דרום־מערב', 'דרוםמערב', 'southwest', 'south-west']),
    ('n', ['צפון', 'צפוני', 'צפונית', 'צפוניים', 'north', 'northern']),
    ('s', ['דרום', 'דרומי', 'דרומית', 'דרומיים', 'south', 'southern']),
    ('e', ['מזרח', 'מזרחי', 'מזרחית', 'מזרחיים', 'east', 'eastern']),
    ('w', ['מערב', 'מערבי', 'מערבית', 'מערביים', 'west', 'western']),
    ('center', ['מרכז', 'מרכזי', 'מרכזית', 'אמצע', 'center', 'centre', 'middle', 'central']),
]

LANDMARK_WORDS = [
    ('amphitheater', ['קולוסיאום', 'קולוסאום', 'אמפיתיאטרון', 'זירה', 'colosseum', 'amphitheater', 'amphitheatre', 'arena']),
    ('triumphal_arch', ['שער-ניצחון', 'קשת-ניצחון', 'triumphal', 'arch']),
    ('aqueduct', ['אמת-מים', 'אמות-מים', 'אקוודוקט', 'aqueduct', 'aqueducts']),
    ('pantheon', ['פנתיאון', 'pantheon']),
    ('round_temple', ['מקדש-עגול', 'tholos']),
    ('temple', ['מקדש', 'מקדשים', 'היכל', 'temple', 'temples']),
    ('basilica', ['בזיליקה', 'basilica']),
    ('lighthouse', ['מגדלור', 'lighthouse']),
    ('windmill', ['טחנת-רוח', 'טחנה', 'windmill']),
    ('tower', ['מגדל', 'מגדלים', 'tower', 'towers']),
    ('fountain', ['מזרקה', 'מזרקות', 'fountain']),
    ('obelisk', ['אובליסק', 'obelisk']),
    ('statue', ['פסל', 'פסלים', 'statue', 'statues']),
    ('garden', ['גן', 'גנים', 'גינה', 'גינות', 'garden', 'gardens', 'park']),
    ('market_stalls', ['שוק', 'שווקים', 'דוכנים', 'דוכן', 'market', 'bazaar', 'stalls']),
    ('church', ['כנסייה', 'כנסיה', 'כנסיות', 'church', 'churches', 'basilica-church']),
    ('lime_kiln', ['כבשן', 'כבשני', 'kiln', 'kilns']),
    ('vegetable_garden', ['גן-ירק', 'גני-ירק', 'ירקות', 'vegetable', 'orchard']),
    ('theater', ['תיאטרון', 'theater', 'theatre']),
    ('circus', ['היפודרום', 'circus', 'hippodrome']),
    ('forum', ['פורום', 'forum', 'agora', 'אגורה']),
    ('bath', ['מרחץ', 'מרחצאות', 'bath', 'baths', 'thermae']),
]


def merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


FEATURE_STEMS = ['נהר', 'נהרות', 'river', 'ארמון', 'מבצר', 'טירה', 'palace', 'castle', 'רובע', 'רבע', 'שכונה', 'שכונת', 'district', 'quarter', 'אגם', 'lake', 'ים', 'sea']


def clauses(text):
    parts = [c for c in re.split(r'[.,;:\n!?]|\s(?:גם|וכן|and)\s', text) if c.strip()]
    stems = FEATURE_STEMS + [w for _, ws in LANDMARK_WORDS for w in ws if '-' not in w]
    out = []
    for part in parts:
        words = part.split()
        current = []
        for word in words:
            if current and has_any(tokens(word), stems) and has_any(tokens(' '.join(current)), stems):
                out.append(' '.join(current))
                current = []
            current.append(word)
        out.append(' '.join(current))
    return [c for c in out if c.strip()]


def dir_in(toks):
    joined = ' '.join(toks)
    compound = next((d for d, words in DIR_WORDS[:4] for w in words if w.replace('-', ' ') in joined or w in joined), None)
    return compound or next((d for d, words in DIR_WORDS[4:] if has_any(toks, words)), None)


def flow_dirs(text):
    m = re.search(r'מ(צפון|דרום|מזרח|מערב)\S*\s+ל(צפון|דרום|מזרח|מערב)', text) or re.search(r'from (north|south|east|west)\w* to (north|south|east|west)', text.lower())
    names = {'צפון': 'n', 'דרום': 's', 'מזרח': 'e', 'מערב': 'w', 'north': 'n', 'south': 's', 'east': 'e', 'west': 'w'}
    return (names[m.group(1)], names[m.group(2)]) if m else None


def hexes(toks):
    return [COLORS[t] for t in toks if t in COLORS]


def style_from_tokens(toks):
    style = {}
    mats = [('marble', ['שיש', 'marble']), ('brick', ['לבנים', 'brick', 'bricks']), ('sandstone', ['אבן-חול', 'sandstone']),
            ('wood', ['עץ', 'wood', 'wooden', 'timber']), ('plaster', ['טיח', 'plaster', 'stucco']), ('stone', ['אבן', 'stone'])]
    style['material'] = next((m for m, w in mats if has_any(toks, w)), None)
    roofs = [('dome', ['כיפה', 'כיפות', 'dome', 'domes']), ('flat', ['שטוח', 'שטוחים', 'flat']), ('pointed', ['מחודד', 'מחודדים', 'pointed', 'spire']),
             ('hip', ['רעפים', 'tiles', 'tiled', 'hip']), ('curved', ['קמור', 'קמורים', 'pagoda'])]
    style['roof'] = next((r for r, w in roofs if has_any(toks, w)), None)
    style['timber'] = has_any(toks, ['קורות', 'half-timbered', 'timbered', 'פכוורק', 'fachwerk']) or None
    style['balconies'] = has_any(toks, ['מרפסת', 'מרפסות', 'balcony', 'balconies']) or None
    style['arcades'] = has_any(toks, ['קשתות', 'ארקדות', 'arcades', 'arches']) or None
    colors = hexes(toks)
    style['wall_colors'] = colors or None
    return {k: v for k, v in style.items() if v}


def read_layout(text, plan, explicit):
    toks_all = tokens(text)
    lower = text.lower()
    if has_any(toks_all, ['רומא', 'רומי', 'רומית', 'רומיים', 'rome', 'roma', 'roman']):
        glory = (has_any(toks_all, GLORY_WORDS) or '315' in text) and not has_any(toks_all, FALL_WORDS)
        plan['basemap'] = 'rome_315' if glory else 'rome_476'
        explicit.add('basemap')
    hills = re.search(r'(שבע|שש|חמש|ארבע|שלוש|שתי|\d+)\s+גבעות', text)
    words = {'שתי': 2, 'שלוש': 3, 'ארבע': 4, 'חמש': 5, 'שש': 6, 'שבע': 7}
    if hills:
        plan['terrain']['hills'] = int(hills.group(1)) if hills.group(1).isdigit() else words[hills.group(1)]
        explicit.add('terrain.hills')
    elif has_any(toks_all, ['גבעות', 'גבעה', 'hills', 'hilly']):
        plan['terrain']['hills'] = max(plan['terrain']['hills'], 3)
    for clause in clauses(text):
        toks = tokens(clause)
        where = dir_in(toks)
        if has_any(toks, ['נהר', 'נהרות', 'river', 'rivers']):
            flow = flow_dirs(clause)
            through = has_any(toks, ['חוצה', 'חוצים', 'דרך', 'באמצע', 'through', 'across', 'crosses']) or 'בתוך העיר' in clause or where == 'center'
            start, end = flow or (({'n': 'w', 's': 'w', 'e': 'n', 'w': 'n'}.get(where, 'n')), ({'n': 'e', 's': 'e', 'e': 's', 'w': 's'}.get(where, 's')))
            river = {'from': start, 'to': end, 'via': 'center' if through or not where else where, 'width': 26 if has_any(toks, ['רחב', 'גדול', 'wide', 'broad', 'big']) else 16,
                     'quays': has_any(toks, ['רציף', 'רציפים', 'סוללה', 'quay', 'quays', 'embankment']) or plan['basemap'] in ('rome_476', 'rome_315')}
            plan['water']['rivers'] = [river]
            explicit.add('water.rivers')
        if has_any(toks, ['ים', 'חוף', 'נמל', 'sea', 'coast', 'harbor', 'port']) and where and where != 'center':
            plan['water']['sea_side'] = where
            explicit.add('water.sea_side')
        if has_any(toks, ['אגם', 'lake']):
            plan['water']['lakes'] = [{'at': where or 'ne'}]
            explicit.add('water.lakes')
        if has_any(toks, ['ארמון', 'מבצר', 'טירה', 'palace', 'castle', 'citadel', 'fortress']):
            on_hill = has_any(toks, ['גבעה', 'גבעת', 'הר', 'ההר', 'פסגה', 'hill', 'hilltop', 'summit'])
            site = ((f'hill_{where}' if where and where != 'center' else 'hilltop') if on_hill else
                    'riverside' if has_any(toks, ['נהר', 'river']) else 'coast' if has_any(toks, ['ים', 'חוף', 'sea', 'coast']) else where)
            if site:
                plan['palace']['at'] = site
                explicit.add('palace.at')
            if has_any(toks, ['טירה', 'מבצר', 'castle', 'fortress']):
                plan['palace']['kind'] = 'castle'
                explicit.add('palace.kind')
            if has_any(toks, ['עמודים', 'קלאסי', 'רומי', 'יווני', 'columns', 'classical', 'roman', 'greek']):
                plan['palace']['kind'] = 'classical'
                explicit.add('palace.kind')
        if has_any(toks, ['רובע', 'רבע', 'שכונה', 'שכונת', 'district', 'quarter', 'neighborhood']):
            style = style_from_tokens(toks)
            plan['districts'].append({'name': clause.strip()[:40], 'at': where or 'center', 'style': style, 'density': 0.85 if has_any(toks, ['צפוף', 'צפופה', 'dense']) else 0.55})
            explicit.add('districts')
        for kind, words_ in LANDMARK_WORDS:
            if has_any(toks, [w for w in words_ if '-' not in w]) or any(w.replace('-', ' ') in clause for w in words_ if '-' in w):
                if kind == 'tower' and has_any(toks, ['ארמון', 'palace', 'castle']):
                    continue
                plan['landmarks'].append({'kind': kind, 'at': where or 'center', 'name': ''})
                explicit.add('landmarks')
                break
    if has_any(toks_all, ['חומה', 'חומות', 'walls', 'walled', 'ramparts']):
        plan['city']['walls'] = True
        explicit.add('city.walls')
    decay = has_any(toks_all, ['מוזנח', 'מוזנחת', 'מוזנחים', 'נטוש', 'נטושה', 'נטושים', 'עזוב', 'עזובה', 'מתפורר', 'מתפוררים', 'abandoned', 'decaying', 'neglected', 'weathered'])
    fall = 'אחרי הנפילה' in text or 'לא מתוחזק' in text or 'after the fall' in lower or 'unmaintained' in lower
    ruins = has_any(toks_all, ['הרוס', 'הרוסה', 'הרוסים', 'חורבות', 'הריסות', 'ruins', 'ruined', 'ruin'])
    vines = has_any(toks_all, ['קיסוס', 'מטפסת', 'מטפסים', 'ivy', 'vines', 'overgrown'])
    if decay or fall or ruins or vines:
        plan['condition'] = {'decay': 0.6 if (decay or fall) else 0.3, 'overgrowth': 0.7 if (vines or fall) else 0.4, 'ruins': 0.5 if ruins else (0.2 if fall else 0.1)}
        explicit.add('condition')
    time = next((t for t, w in (('golden', ['שקיעה', 'זהב', 'זהובה', 'golden', 'sunset']), ('dawn', ['זריחה', 'שחר', 'dawn', 'sunrise']),
                                ('night', ['לילה', 'לילי', 'night', 'moonlight']), ('dusk', ['בין-ערביים', 'dusk', 'twilight'])) if has_any(toks_all, w)), None)
    if time:
        plan['time_of_day'] = time
        explicit.add('time_of_day')
    size = 'large' if has_any(toks_all, ['ענקית', 'גדולה', 'עצומה', 'huge', 'large', 'big', 'metropolis']) else ('small' if has_any(toks_all, ['קטנה', 'כפר', 'small', 'village', 'town']) else None)
    if size:
        plan['city']['size'] = size
        explicit.add('city.size')
    trees = [s for s, w in (('cypress', ['ברוש', 'ברושים', 'cypress', 'cypresses']), ('umbrella_pine', ['אורן-מטרייה', 'אורנים', 'umbrella', 'stone-pine']),
                            ('palm', ['דקל', 'דקלים', 'palm', 'palms']), ('pine', ['אורן', 'pine', 'pines'])) if has_any(toks_all, w)]
    if trees:
        plan['nature']['species'] = trees
        explicit.add('nature.species')


def rules_plan(text):
    spec = interpret_world_rules(text)
    plan = copy.deepcopy(DEFAULT_PLAN)
    explicit = set()
    plan['terrain'] = {**plan['terrain'], **spec['terrain']}
    plan['climate'] = spec['climate']
    plan['nature']['trees'] = spec['nature']['trees']
    plan['mood'] = spec['mood']
    arch = spec['architecture']
    plan['style'] = {**HOUSE_STYLE, 'material': arch['material'], 'roof': arch['roof'], 'window': arch['window'],
                     'wall_colors': [arch['wall_color']] if arch['wall_color'] else [], 'roof_colors': [arch['roof_color']] if arch['roof_color'] else [],
                     'balconies': 'balconies' in arch['ornament']}
    plan['city'] = {**plan['city'], 'density': spec['urban']['density'], 'street': spec['urban']['street'], 'stairs': spec['urban']['stairs'], 'bridges': spec['urban']['bridges'] or True}
    if spec['water']['sea']:
        plan['water']['sea_side'] = 'e'
    if spec['water']['river']:
        plan['water']['rivers'] = [{'from': 'n', 'to': 's', 'via': 'center', 'width': 16, 'quays': False}]
    if spec['water']['lake']:
        plan['water']['lakes'] = [{'at': 'ne'}]
    plan['water']['falls'] = spec['water'].get('falls', False)
    read_layout(text, plan, explicit)
    if has_any(tokens(text), ['קורות-עץ', 'half-timbered', 'timbered', 'פכוורק', 'fachwerk']) or 'קורות עץ' in text:
        plan['style']['timber'] = True
        explicit.add('style.timber')
    if any(note.startswith('שטח') for note in spec['notes']):
        explicit.add('terrain.kind')
    return plan, explicit


def pick(value, allowed, fallback):
    return value if value in allowed else fallback


def unit(value, fallback):
    return max(0.0, min(1.0, float(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def color(value):
    ok = isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)
    return value.lower() if ok else None


def colors(values):
    return [c for c in (color(v) for v in (values if isinstance(values, list) else [])) if c][:6]


def norm_style(raw, base):
    raw = raw if isinstance(raw, dict) else {}
    floors = raw.get('floors') if isinstance(raw.get('floors'), list) and len(raw.get('floors')) == 2 else base['floors']
    lo, hi = sorted(int(max(1, min(7, f))) for f in floors)
    return {
        'material': pick(raw.get('material'), MATERIALS, base['material']),
        'roof': pick(raw.get('roof'), ROOFS, base['roof']),
        'roof_pitch': pick(raw.get('roof_pitch'), PITCHES, base['roof_pitch']),
        'window': pick(raw.get('window'), WINDOWS, base['window']),
        'wall_colors': colors(raw.get('wall_colors')) or base['wall_colors'],
        'roof_colors': colors(raw.get('roof_colors')) or base['roof_colors'],
        'floors': [lo, hi],
        **{k: bool(raw.get(k, base[k])) for k in ('timber', 'balconies', 'arcades', 'chimneys', 'shutters')},
        'towers': unit(raw.get('towers'), base['towers']),
    }


def at_value(value, named):
    return value if value in DIRS or value in HILL_DIRS or value in named or value in ('hilltop', 'riverside', 'coast') else 'center'


def normalize(raw, named=()):
    d = DEFAULT_PLAN
    raw = raw if isinstance(raw, dict) else {}
    t, w, c, n, city, cond, pal = (raw.get(k) if isinstance(raw.get(k), dict) else {} for k in ('terrain', 'water', 'climate', 'nature', 'city', 'condition', 'palace'))
    rivers = [r for r in (w.get('rivers') or []) if isinstance(r, dict)][:3]
    style = norm_style(raw.get('style'), HOUSE_STYLE)
    return {
        'title': str(raw.get('title') or '')[:80],
        'basemap': pick(raw.get('basemap'), BASEMAPS, 'none'),
        'terrain': {'kind': pick(t.get('kind'), TERRAINS, d['terrain']['kind']), 'relief': unit(t.get('relief'), 0.5), 'sharpness': unit(t.get('sharpness'), 0.4),
                    'hills': int(max(0, min(9, t.get('hills') or 0))) if isinstance(t.get('hills'), (int, float)) else 0},
        'water': {'sea_side': pick(w.get('sea_side'), DIRS[1:] + ('none',), 'none'),
                  'rivers': [{'from': pick(r.get('from'), DIRS[1:], 'n'), 'to': pick(r.get('to'), DIRS[1:], 's'), 'via': at_value(r.get('via'), named),
                              'width': max(6.0, min(90.0, float(r.get('width') or 16))), 'quays': bool(r.get('quays'))} for r in rivers],
                  'lakes': [{'at': at_value(l.get('at'), named)} for l in (w.get('lakes') or []) if isinstance(l, dict)][:3],
                  'falls': bool(w.get('falls'))},
        'climate': {'precip': pick(c.get('precip'), ('none', 'snow', 'rain'), 'none'), 'fog': bool(c.get('fog')),
                    'vegetation': pick(c.get('vegetation'), ('temperate', 'alpine', 'tropical', 'desert', 'none'), 'temperate'),
                    'snow_roofs': bool(c.get('snow_roofs')), 'snow_ground': bool(c.get('snow_ground'))},
        'nature': {'trees': unit(n.get('trees'), 0.35), 'species': [s for s in (n.get('species') or []) if s in SPECIES][:4]},
        'mood': pick(raw.get('mood'), MOODS, 'realistic'),
        'time_of_day': pick(raw.get('time_of_day'), TIMES, 'day'),
        'city': {'at': pick(city.get('at'), DIRS, 'center'), 'size': pick(city.get('size'), SIZES, 'medium'), 'density': unit(city.get('density'), 0.55),
                 'street': pick(city.get('street'), STREETS, 'winding'), 'walls': bool(city.get('walls')), 'stairs': bool(city.get('stairs')), 'bridges': bool(city.get('bridges', True))},
        'condition': {k: unit(cond.get(k), 0.0) for k in ('decay', 'overgrowth', 'ruins')},
        'style': style,
        'districts': [{'name': str(x.get('name') or '')[:40], 'at': at_value(x.get('at'), named), 'style': norm_style(merge(style, x.get('style') or {}), style),
                       'density': unit(x.get('density'), 0.6)} for x in (raw.get('districts') or []) if isinstance(x, dict)][:6],
        'palace': {'at': at_value(pal.get('at'), named), 'kind': pick(pal.get('kind'), PALACE_KINDS, 'castle'), 'wall_color': color(pal.get('wall_color')),
                   'roof_color': color(pal.get('roof_color')), 'roof': pick(pal.get('roof'), ROOFS, None)},
        'landmarks': [{'kind': x['kind'], 'at': at_value(x.get('at'), named), 'name': str(x.get('name') or '')[:40]}
                      for x in (raw.get('landmarks') or []) if isinstance(x, dict) and x.get('kind') in LANDMARKS][:16],
    }


def json_schema(named):
    at = {'type': 'string', 'enum': list(DIRS) + list(HILL_DIRS) + ['hilltop', 'riverside', 'coast'] + list(named)}
    hexc = {'type': 'string', 'pattern': '^#[0-9a-f]{6}$'}
    unit_ = {'type': 'number', 'minimum': 0, 'maximum': 1}
    enum = lambda values: {'type': 'string', 'enum': list(values)}
    obj = lambda props: {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
    style = obj({'material': enum(MATERIALS), 'roof': enum(ROOFS), 'roof_pitch': enum(PITCHES), 'window': enum(WINDOWS),
                 'wall_colors': {'type': 'array', 'items': hexc, 'maxItems': 6}, 'roof_colors': {'type': 'array', 'items': hexc, 'maxItems': 4},
                 'floors': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1, 'maximum': 7}, 'minItems': 2, 'maxItems': 2},
                 'timber': {'type': 'boolean'}, 'balconies': {'type': 'boolean'}, 'arcades': {'type': 'boolean'}, 'chimneys': {'type': 'boolean'},
                 'towers': unit_, 'shutters': {'type': 'boolean'}})
    return obj({
        'title': {'type': 'string', 'maxLength': 60},
        'basemap': enum(BASEMAPS),
        'terrain': obj({'kind': enum(TERRAINS), 'relief': unit_, 'sharpness': unit_, 'hills': {'type': 'integer', 'minimum': 0, 'maximum': 9}}),
        'water': obj({'sea_side': enum(list(DIRS[1:]) + ['none']),
                      'rivers': {'type': 'array', 'maxItems': 3, 'items': obj({'from': enum(DIRS[1:]), 'to': enum(DIRS[1:]), 'via': at, 'width': {'type': 'number', 'minimum': 6, 'maximum': 90}, 'quays': {'type': 'boolean'}})},
                      'lakes': {'type': 'array', 'maxItems': 2, 'items': obj({'at': at})}, 'falls': {'type': 'boolean'}}),
        'climate': obj({'precip': enum(('none', 'snow', 'rain')), 'fog': {'type': 'boolean'}, 'vegetation': enum(('temperate', 'alpine', 'tropical', 'desert', 'none')),
                        'snow_roofs': {'type': 'boolean'}, 'snow_ground': {'type': 'boolean'}}),
        'nature': obj({'trees': unit_, 'species': {'type': 'array', 'items': enum(SPECIES), 'maxItems': 4}}),
        'mood': enum(MOODS), 'time_of_day': enum(TIMES),
        'city': obj({'at': enum(DIRS), 'size': enum(SIZES), 'density': unit_, 'street': enum(STREETS), 'walls': {'type': 'boolean'}, 'stairs': {'type': 'boolean'}, 'bridges': {'type': 'boolean'}}),
        'condition': obj({'decay': unit_, 'overgrowth': unit_, 'ruins': unit_}),
        'style': style,
        'districts': {'type': 'array', 'maxItems': 5, 'items': obj({'name': {'type': 'string', 'maxLength': 40}, 'at': at, 'style': style, 'density': unit_})},
        'palace': obj({'at': at, 'kind': enum(PALACE_KINDS), 'wall_color': hexc, 'roof_color': hexc, 'roof': enum(ROOFS)}),
        'landmarks': {'type': 'array', 'maxItems': 10, 'items': obj({'kind': enum(LANDMARKS), 'at': at, 'name': {'type': 'string', 'maxLength': 40}})},
    })


def schema_text(named):
    return json.dumps({
        'title': 'short Hebrew name for the world',
        'basemap': f'one of {list(BASEMAPS)}; use "rome_315" for Rome in its imperial glory (age of Constantine, everything maintained and alive) and "rome_476" for Rome right after the fall (late antiquity, neglected); both are real historical project maps with the Tiber, the seven hills and the monuments in their true places',
        'terrain': {'kind': list(TERRAINS), 'relief': '0..1', 'sharpness': '0..1', 'hills': '0..9 separate hills around the city'},
        'water': {'sea_side': list(DIRS[1:]) + ['none'], 'rivers': [{'from': list(DIRS[1:]), 'to': list(DIRS[1:]), 'via': 'direction from the city the river passes through, "center" = through the city, or a named place', 'width': 'meters 6..90', 'quays': 'stone embankments'}],
                  'lakes': [{'at': 'direction or named place'}], 'falls': 'bool'},
        'climate': {'precip': ['none', 'snow', 'rain'], 'fog': 'bool', 'vegetation': ['temperate', 'alpine', 'tropical', 'desert', 'none'], 'snow_roofs': 'bool', 'snow_ground': 'bool'},
        'nature': {'trees': '0..1', 'species': list(SPECIES)},
        'mood': list(MOODS), 'time_of_day': list(TIMES),
        'city': {'at': list(DIRS), 'size': list(SIZES), 'density': '0..1', 'street': list(STREETS), 'walls': 'bool', 'stairs': 'bool', 'bridges': 'bool'},
        'condition': {'decay': '0..1 weathering and lack of maintenance', 'overgrowth': '0..1 vines, moss, plants on buildings', 'ruins': '0..1 share of collapsed buildings'},
        'style': {'material': list(MATERIALS), 'roof': list(ROOFS), 'roof_pitch': list(PITCHES), 'window': list(WINDOWS), 'wall_colors': ['#rrggbb up to 6, sampled from the reference'],
                  'roof_colors': ['#rrggbb up to 4'], 'floors': '[min,max] 1..7', 'timber': 'bool', 'balconies': 'bool', 'arcades': 'bool ground-floor arches/shops', 'chimneys': 'bool', 'towers': '0..1 share of tower houses', 'shutters': 'bool'},
        'districts': [{'name': 'Hebrew', 'at': 'direction or named place', 'style': 'partial style overriding the city style', 'density': '0..1'}],
        'palace': {'at': f'direction, "hilltop", "hill_<direction>" (a hill on that side, e.g. hill_e), "riverside", "coast", or a named place {list(named)}', 'kind': list(PALACE_KINDS), 'wall_color': '#rrggbb or null', 'roof_color': '#rrggbb or null', 'roof': list(ROOFS) + [None]},
        'landmarks': [{'kind': list(LANDMARKS), 'at': 'direction or named place', 'name': 'Hebrew'}],
    }, ensure_ascii=False)


CREATE_SYSTEM = """You are the chief planner of a 3D world builder. You turn a user's fantasy (Hebrew or English text, and optionally a reference image) into a precise JSON plan for a procedural engine.
Read the reference image carefully when given: terrain and hills, water (rivers, bridges, quays, sea), architecture (materials, roof shapes and pitch, windows, arcades, balconies, floors), the real colours of walls and roofs as hex codes, monuments (amphitheaters, temples with columns, triumphal arches, aqueducts, basilicas), trees (cypress, umbrella pine...), light and time of day, and the state of repair (weathering, vines, ruins).
The user's text always wins over the image. Directions: n = north = top of the map.
When basemap is "rome_476" or "rome_315" the project map already contains the real Tiber, the seven hills, the bridges and the ancient monuments in their true places: do not invent rivers or duplicate those monuments; describe style, colours, condition, light and vegetation, and add landmarks only if the user explicitly asks for something new (use the named places for "at").
Return ONLY one JSON object that follows the provided schema; every field holds ONE chosen value (never a list of options).
Guide to the fields: %s"""

EDIT_SYSTEM = """You edit an existing JSON world plan for a 3D world builder according to the user's request (Hebrew or English, sometimes with a reference image).
Change only what the request asks for, keep every other value exactly as it is, and return the COMPLETE updated plan as JSON with the same keys.
To move something, change its "at". To add a river, district or landmark append it to its list. Directions: n = north = top of the map.
The output must follow the provided schema. Guide to the fields: %s"""


def apply_explicit(plan, rules, explicit):
    out = copy.deepcopy(plan)
    for path in explicit:
        keys = path.split('.')
        src, dst = rules, out
        for k in keys[:-1]:
            src, dst = src[k], dst[k]
        dst[keys[-1]] = copy.deepcopy(src[keys[-1]])
    return out


def create_plan(text, images=(), palette=(), use_llm=True, named=(), context=''):
    rules, explicit = rules_plan(text)
    plan = normalize(rules, named)
    notes = []
    source = 'rules'
    if use_llm:
        prompt = f'User fantasy:\n{text}\n' + (f'\nDominant colours measured in the reference image: {list(palette)}\n' if palette else '') + context
        try:
            data, source = ask_json(CREATE_SYSTEM % schema_text(named), prompt, images, json_schema(named))
            plan = normalize(apply_explicit(normalize(data, named), normalize(rules, named), explicit), named)
            source = f'{source}+rules'
        except Exception as exc:
            notes.append(f'המודל לא זמין ({type(exc).__name__}: {str(exc)[:80]}) — התוכנית נבנתה מחוקי מילים בלבד')
    if palette and not plan['style']['wall_colors']:
        plan['style']['wall_colors'] = colors(list(palette))[:4]
    plan['seed'] = zlib.crc32(text.encode('utf-8')) & 0x7FFFFFFF
    return plan, source, notes


def edit_plan(current, text, images=(), use_llm=True, named=(), context=''):
    rules, explicit = rules_plan(text)
    base = {k: v for k, v in current.items() if k != 'seed'}
    notes = []
    source = 'rules'
    plan = None
    if use_llm:
        try:
            data, source = ask_json(EDIT_SYSTEM % schema_text(named), f'Current plan:\n{json.dumps(base, ensure_ascii=False)}\n\nRequest:\n{text}\n{context}', images, json_schema(named))
            plan = normalize(data, named)
        except Exception as exc:
            notes.append(f'המודל לא זמין ({type(exc).__name__}) — השינוי פורש בחוקי מילים בלבד')
    if plan is None:
        plan = normalize(apply_explicit(base, normalize(rules, named), {p for p in explicit if p not in ('basemap',)}), named)
        if 'districts' in explicit:
            plan['districts'] = base['districts'] + normalize(rules, named)['districts']
        if 'landmarks' in explicit:
            plan['landmarks'] = base['landmarks'] + normalize(rules, named)['landmarks']
    plan['seed'] = current.get('seed', 1)
    return plan, source, notes


LABELS = {
    'basemap': 'מפת בסיס', 'terrain': 'שטח', 'water': 'מים', 'climate': 'אקלים', 'nature': 'צמחייה', 'mood': 'אווירה', 'time_of_day': 'שעה ביום',
    'city': 'העיר', 'condition': 'מצב תחזוקה', 'style': 'סגנון הבתים', 'districts': 'רבעים', 'palace': 'ארמון', 'landmarks': 'מבנים מרכזיים', 'title': 'שם',
}


def diff(old, new, prefix=''):
    keys = sorted(set(old) | set(new)) if isinstance(old, dict) and isinstance(new, dict) else []
    nested = [d for k in keys if k != 'seed' for d in diff(old.get(k), new.get(k), f'{prefix}{k}.')]
    return nested if keys else ([] if old == new else [(prefix.rstrip('.'), old, new)])


def describe_changes(old, new):
    lines = []
    for path, before, after in diff(old, new):
        head = LABELS.get(path.split('.')[0], path.split('.')[0])
        tail = '.'.join(path.split('.')[1:])
        lines.append(f"{head}{(' · ' + tail) if tail else ''}: {json.dumps(before, ensure_ascii=False)[:70]} ← {json.dumps(after, ensure_ascii=False)[:70]}")
    return lines


def summarize(plan):
    s = plan['style']
    rivers = '; '.join(f"נהר מ־{r['from']} ל־{r['to']} דרך {r['via']}" for r in plan['water']['rivers']) or 'בלי נהר'
    marks = ', '.join(f"{m['kind']}@{m['at']}" for m in plan['landmarks']) or 'אין'
    return [
        f"מפת בסיס: {plan['basemap']} · שטח: {plan['terrain']['kind']} · גבעות: {plan['terrain']['hills']}",
        f"מים: {rivers} · ים: {plan['water']['sea_side']}",
        f"עיר: {plan['city']['size']}, צפיפות {plan['city']['density']:.2f}, רחובות {plan['city']['street']}, חומות: {plan['city']['walls']}",
        f"בתים: {s['material']}, גג {s['roof']} ({s['roof_pitch']}), חלונות {s['window']}, קומות {s['floors'][0]}–{s['floors'][1]}, צבעים {', '.join(s['wall_colors']) or 'לפי חומר'}",
        f"ארמון: {plan['palace']['kind']} ב־{plan['palace']['at']} · מבנים מרכזיים: {marks}",
        f"מצב: בלאי {plan['condition']['decay']:.1f}, צמחייה {plan['condition']['overgrowth']:.1f}, הריסות {plan['condition']['ruins']:.1f} · אווירה: {plan['mood']}, {plan['time_of_day']}",
    ]
