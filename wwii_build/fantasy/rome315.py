import copy

from .rome476 import ROME_476

DARK_AGE_KINDS = ('church', 'lime_kiln', 'vegetable_garden')
DARK_AGE_IDS = ('market_forum',)

GLORY_LANDMARKS = [
    {'id': 'baths_constantine', 'kind': 'bath', 'name': 'מרחצאות קונסטנטינוס (נחנכו בערך 315)', 'lat': 41.89930, 'lon': 12.48860, 'w': 120, 'd': 80, 'h': 26, 'axis': 15},
    {'id': 'temple_sol', 'kind': 'temple', 'name': 'מקדש סול אינויקטוס של אורליאנוס', 'lat': 41.89950, 'lon': 12.48140, 'w': 40, 'd': 60, 'h': 26, 'axis': 0},
    {'id': 'equus_constantini', 'kind': 'statue', 'name': 'פסל הפרש של קונסטנטינוס בפורום', 'lat': 41.89235, 'lon': 12.48520, 'w': 6, 'd': 6, 'h': 11, 'axis': 122},
    {'id': 'obelisk_circus', 'kind': 'obelisk', 'name': 'האובליסק של אוגוסטוס בקירקוס מקסימוס', 'lat': 41.88620, 'lon': 12.48520, 'w': 4, 'd': 4, 'h': 24, 'axis': 0},
    {'id': 'macellum_magnum', 'kind': 'market', 'name': 'המקלום מגנום — השוק המקורה הגדול', 'lat': 41.88480, 'lon': 12.49560, 'w': 60, 'd': 60, 'h': 12, 'axis': 0},
    {'id': 'forum_cuppedinis', 'kind': 'market_stalls', 'name': 'פורום קופדיניס — שוק המעדנים', 'lat': 41.89300, 'lon': 12.48900, 'w': 44, 'd': 18, 'h': 3, 'axis': 120},
    {'id': 'forum_piscarium', 'kind': 'market_stalls', 'name': 'פורום פיסקריום — שוק הדגים', 'lat': 41.89170, 'lon': 12.48100, 'w': 36, 'd': 16, 'h': 3, 'axis': 20},
]

RENAMES = {
    'market_boarium': 'פורום בואריום — שוק הבקר והבשר',
    'market_holitorium': 'פורום הוליטוריום — שוק הירקות',
    'market_quay': 'פורטוס טיבריניוס — נמל הנהר והרציפים',
    'market_subura': 'הטברנות של הסובורה',
    'temple_peace': 'מקדש השלום והגנים שלו',
    'temple_claudius': 'מתחם מקדש קלאודיוס האלוהי',
}

SOURCES = [
    'Notitia urbis Romae / Curiosum urbis Romae (המאה ה־4) — מניין הבתים, האינסולות, המחסנים והמרחצאות',
    'Filippo Coarelli, Rome and Environs: An Archaeological Guide — מיקום המבנים בימי קונסטנטינוס',
    'Amanda Claridge, Rome: An Oxford Archaeological Guide — מצב המבנים והחומרים',
    'שווקי התקופה: De Ruyt, Macellum (1983); Holleran, Shopping in Ancient Rome (2012) — המיקום המדויק של חלק מהשווקים משוער',
]


def glory_era():
    era = copy.deepcopy(ROME_476)
    era['id'] = 'rome_315'
    era['name'] = 'רומא בתפארתה, 315 לספירה — ימי קונסטנטינוס'
    era['sources'] = [s for s in era['sources'] if 'כנסיות' not in s and 'כבשני' not in s] + SOURCES
    keep = [m for m in era['landmarks'] if m['kind'] not in DARK_AGE_KINDS and m['id'] not in DARK_AGE_IDS]
    era['landmarks'] = [{**m, 'name': RENAMES.get(m['id'], m['name'])} for m in keep] + copy.deepcopy(GLORY_LANDMARKS)
    era['mills'] = []
    era['flocks'] = [{'name': 'בקר בשוק הבקר', 'lat': 41.88905, 'lon': 12.48170, 'r': 16, 'count': 10}]
    era['districts'] = [{**d, 'density': min(1.0, round(d['density'] + 0.12, 2))} for d in era['districts']] + [
        {'id': 'regiones', 'name': 'שאר העיר — 14 הרגיונות (צפיפות לפי הקטלוג האזורי)', 'lat': era['origin']['lat'], 'lon': era['origin']['lon'], 'r': 1600, 'density': 0.88,
         'style': {'floors': [3, 5], 'balconies': True, 'arcades': True}, 'fallback': True}]
    era['plan'] = {
        **copy.deepcopy(ROME_476['plan']),
        'basemap': 'rome_315',
        'title': 'רומא בתפארתה',
        'nature': {'trees': 0.35, 'species': ['cypress', 'umbrella_pine']},
        'mood': 'ancient', 'time_of_day': 'day',
        'city': {'at': 'center', 'size': 'large', 'density': 0.9, 'street': 'winding', 'walls': False, 'stairs': True, 'bridges': True},
        'condition': {'decay': 0.03, 'overgrowth': 0.04, 'ruins': 0.0},
        'style': {**ROME_476['plan']['style'], 'wall_colors': ['#e3c79a', '#d8a56c', '#c98a5a', '#ecd9b6', '#b8693f', '#d9b98f'], 'roof_colors': ['#b0573a', '#c06640', '#a24e30', '#bd6a45'],
                  'floors': [3, 5]},
        'palace': {'at': 'palatine', 'kind': 'classical', 'wall_color': '#ece2cc', 'roof_color': '#b0573a', 'roof': 'hip'},
    }
    return era


ROME_315 = glory_era()
