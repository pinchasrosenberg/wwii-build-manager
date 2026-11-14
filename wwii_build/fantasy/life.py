import math
from datetime import date

from .population import COSTUMES, DYES

LIFE_VERSION = 5

ERA_LIFE = {
    'rome_315': {'agents': 2600, 'litters': 10, 'carts_day': 6, 'carts_night': 46, 'boats': 16, 'exclude': (),
                 'label': 'רומא בתפארתה — כמיליון תושבים (הערכה), 46,602 אינסולות לפי הקטלוג האזורי'},
    'rome_476': {'agents': 900, 'litters': 3, 'carts_day': 2, 'carts_night': 10, 'boats': 6, 'exclude': ('senator', 'senator_young', 'equestrian', 'vestal'),
                 'label': 'רומא אחרי הנפילה — העיר התרוקנה; הטוגה כבר טקסית בלבד והווסטליות בוטלו ב־394'},
}

CROWD_BY_HOUR = [0.03, 0.02, 0.02, 0.03, 0.06, 0.18, 0.45, 0.75, 0.9, 1.0, 1.0, 0.95, 0.7, 0.55, 0.6, 0.7, 0.75, 0.7, 0.55, 0.35, 0.18, 0.1, 0.06, 0.04]

WEATHER_KINDS = ('clear', 'cloudy', 'rain', 'storm', 'fog', 'snow')
WEATHER_BY_MONTH = [
    [0.35, 0.25, 0.25, 0.03, 0.07, 0.05], [0.38, 0.25, 0.24, 0.03, 0.06, 0.04], [0.45, 0.25, 0.22, 0.03, 0.04, 0.01], [0.50, 0.22, 0.22, 0.04, 0.02, 0.0],
    [0.62, 0.18, 0.14, 0.05, 0.01, 0.0], [0.78, 0.10, 0.06, 0.06, 0.0, 0.0], [0.85, 0.07, 0.03, 0.05, 0.0, 0.0], [0.80, 0.08, 0.05, 0.07, 0.0, 0.0],
    [0.62, 0.15, 0.14, 0.08, 0.01, 0.0], [0.45, 0.20, 0.24, 0.07, 0.04, 0.0], [0.35, 0.25, 0.30, 0.04, 0.06, 0.0], [0.33, 0.27, 0.26, 0.02, 0.08, 0.04],
]
SUN_BY_MONTH = [[7.6, 16.9], [7.2, 17.5], [6.5, 18.1], [5.7, 18.7], [5.0, 19.3], [4.6, 19.8], [4.8, 19.8], [5.3, 19.2], [5.9, 18.3], [6.5, 17.4], [7.1, 16.7], [7.6, 16.6]]
MONTHS_HE = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר']
WEATHER_HE = {'clear': 'בהיר', 'cloudy': 'מעונן', 'rain': 'גשם', 'storm': 'סערה', 'fog': 'ערפל', 'snow': 'שלג'}
START_HOUR = {'dawn': 6.0, 'day': 9.0, 'golden': 17.0, 'dusk': 18.5, 'night': 22.0}

MARKET_HOURS = {'market_stalls': [5.5, 13.0], 'market': [7.0, 17.0]}
GATHER_KINDS = {'forum': 8, 'basilica': 5, 'temple': 3, 'bath': 6, 'round_temple': 2, 'triumphal_arch': 2, 'amphitheater': 4, 'theater': 3, 'fountain': 3, 'statue': 2}
CARGO = [
    {'kind': 'amphorae', 'label': 'אמפורות יין ושמן', 'animal': 'ox'},
    {'kind': 'grain', 'label': 'שקי חיטה לנחתומים', 'animal': 'mule'},
    {'kind': 'stone', 'label': 'גושי שיש לבנייה ציבורית', 'animal': 'ox'},
    {'kind': 'timber', 'label': 'קורות עץ', 'animal': 'ox'},
    {'kind': 'bricks', 'label': 'לבנים ורעפים', 'animal': 'mule'},
    {'kind': 'barrels', 'label': 'חביות', 'animal': 'mule'},
]
BOATS = [
    {'kind': 'caudicaria', 'label': 'דוברת משא (נאוויס קאודיקאריה) עם אמפורות מאוסטיה', 'weight': 5},
    {'kind': 'linter', 'label': 'סירת חתירה קטנה (לינטר)', 'weight': 6},
    {'kind': 'sail', 'label': 'סירת מפרש קטנה', 'weight': 3},
    {'kind': 'ferry', 'label': 'מעבורת בין הגדות', 'weight': 2},
]


COLOR_DEFAULTS = {'senator': '#ebe5d6', 'vestal': '#f2f0ea', 'soldier': '#8a8c90', 'vigil': '#6b4c33', 'bearer': '#8c1f26', 'porter': '#73583c'}


def type_color(name):
    c = next((c for c in COSTUMES if c['name'] == name), None)
    if not c:
        return '#c9b48f'
    dye = c['dyes'].get('tunic') or c['dyes'].get('stola')
    return DYES[dye] if dye else COLOR_DEFAULTS.get(c['kind'], COLOR_DEFAULTS.get(c['name'], '#c9b48f'))


def climate_plan(start_month=None, time_of_day='day', start_day=None):
    month = (start_month or date.today().month) - 1
    return {
        'start_day': start_day or date.today().day, 'days_in_month': [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31],
        'kinds': list(WEATHER_KINDS), 'by_month': WEATHER_BY_MONTH, 'sun': SUN_BY_MONTH, 'months_he': MONTHS_HE, 'weather_he': WEATHER_HE,
        'start_month': month, 'start_hour': START_HOUR.get(time_of_day, 9.0), 'minutes_per_hour': 1.0, 'calendar': 'real', 'change_every_hours': 3.0,
        'notes': ['גשם בעיקר מאוקטובר עד אפריל, סופות רעמים בסתיו', 'ערפל בוקר מעל עמק הטיבר בחורף', 'שלג נדיר — רק בחורפים קרים, ונמס מהר',
                  'כל יום במשחק = יום בלוח השנה; בוחרים תאריך ושעה בכפתור "תאריך ושעה"'],
    }


def market_spots(landmarks):
    out = []
    for m in landmarks:
        if m['kind'] not in MARKET_HOURS:
            continue
        per = max(2, int(m['w'] // 4.6))
        rows = max(1, int(m['d'] // 8))
        stalls = [[round((-0.5 + (k + 0.5) / per) * m['w'], 2), round(0 if rows == 1 else (-0.5 + (r + 0.5) / rows) * m['d'], 2), r % 2] for r in range(rows) for k in range(per)]
        if m['kind'] == 'market':
            stalls = [[round(m['w'] * 0.5 * math.cos(a), 2), round(m['d'] * 0.5 * math.sin(a) + 3, 2), 0] for a in [k * 2 * math.pi / 8 for k in range(8)]]
        out.append({'id': m['id'], 'name': m['name'], 'kind': m['kind'], 'x': m['x'], 'z': m['z'], 'y': m['y'], 'w': m['w'], 'd': m['d'], 'rot': m['rot'],
                    'open': MARKET_HOURS[m['kind']], 'stalls': stalls})
    return out


def gather_spots(landmarks, palace):
    out = []
    for m in landmarks:
        groups = GATHER_KINDS.get(m['kind'])
        if not groups:
            continue
        reach = (m['d'] / 2 + 6) if m['kind'] not in ('forum',) else 0
        fx, fz = math.sin(m['rot']), math.cos(m['rot'])
        out.append({'id': m['id'], 'name': m['name'], 'x': round(m['x'] + fx * reach, 1), 'z': round(m['z'] + fz * reach, 1), 'r': round(min(max(m['w'], m['d']) * 0.3, 30) if not reach else 8, 1),
                    'groups': groups, 'hours': [7.5, 16.0]})
    fx, fz = math.sin(palace['rot']), math.cos(palace['rot'])
    out.append({'id': 'palace', 'name': palace['name'], 'x': round(palace['x'] + fx * (palace['d'] / 2 + 10), 1), 'z': round(palace['z'] + fz * (palace['d'] / 2 + 10), 1), 'r': 8, 'groups': 3, 'hours': [6.0, 11.0]})
    return out


def plan_life(scene, plan, population, context=''):
    era = plan.get('basemap')
    cfg = ERA_LIFE.get(era)
    if not cfg or not population.get('ok'):
        return None
    types = [{**t, 'color': type_color(t['name'])} for t in population['types'] if t['name'] not in cfg['exclude']]
    routes = [{'street': k, 'main': s['main'], 'weight': round((3.0 if s['main'] else 1.0) * len(s['pts']), 1)} for k, s in enumerate(scene['streets']) if len(s['pts']) >= 4]
    main_routes = [r['street'] for r in routes if r['main']]
    rivers = [{'river': k, 'length': len(r['pts'])} for k, r in enumerate(scene['rivers']) if len(r['pts']) > 10]
    used_facts = [line[2:].split(':')[0] for line in context.splitlines() if line.startswith('- ')]
    return {
        'version': LIFE_VERSION, 'era': era, 'label': cfg['label'],
        'population': {'base': f"/models/population/{population['era']}/", 'types': types},
        'agents': cfg['agents'], 'crowd_by_hour': CROWD_BY_HOUR,
        'routes': routes, 'markets': market_spots(scene['landmarks']), 'gatherings': gather_spots(scene['landmarks'], scene['palace']),
        'carts': {'day': cfg['carts_day'], 'night': cfg['carts_night'], 'routes': main_routes, 'cargo': CARGO, 'day_hours': 10,
                  'rule': 'חוק יוליוס (Lex Julia municipalis): עגלות אסורות בעיר בעשר השעות הראשונות אחרי הזריחה, חוץ מעגלות לבנייה ציבורית — לכן רוב המשא נכנס בערב ובלילה'},
        'litters': {'count': cfg['litters'], 'hours': [7.5, 17.5], 'bearers': 4, 'riders': ['senator', 'matron_rich'] if era == 'rome_315' else ['matron_rich'], 'routes': main_routes},
        'boats': {'count': cfg['boats'], 'kinds': BOATS, 'rivers': rivers},
        'night': {'patrol_type': 'vigil', 'patrols': 24 if era == 'rome_315' else 8, 'window_lights': 0.35},
        'knowledge': used_facts,
    }
