import copy
import math
import random

from .rome315 import ROME_315
from .rome476 import ROME_476

ERAS = {'rome_476': ROME_476, 'rome_315': ROME_315}

M_PER_LAT = 110950.0
DIR_VEC = {'center': (0.0, 0.0), 'n': (0.0, -1.0), 'ne': (0.7071, -0.7071), 'e': (1.0, 0.0), 'se': (0.7071, 0.7071),
           's': (0.0, 1.0), 'sw': (-0.7071, 0.7071), 'w': (-1.0, 0.0), 'nw': (-0.7071, -0.7071)}
HE_KINDS = {'amphitheater': 'אמפיתיאטרון', 'temple': 'מקדש', 'round_temple': 'מקדש עגול', 'triumphal_arch': 'שער ניצחון', 'basilica': 'בזיליקה', 'tower': 'מגדל',
            'lighthouse': 'מגדלור', 'windmill': 'טחנת רוח', 'fountain': 'מזרקה', 'statue': 'פסל', 'obelisk': 'אובליסק', 'column': 'עמוד', 'garden': 'גן', 'market': 'שוק',
            'theater': 'תיאטרון', 'circus': 'היפודרום', 'forum': 'פורום', 'bath': 'מרחצאות', 'pantheon': 'פנתיאון', 'castle': 'מבצר', 'aqueduct': 'אמת מים',
            'market_stalls': 'שוק', 'church': 'כנסייה', 'lime_kiln': 'כבשן סיד', 'vegetable_garden': 'גן ירק'}
CITY_SIZES = {'small': 440.0, 'medium': 600.0, 'large': 800.0}
LANDMARK_SIZES = {
    'amphitheater': (110, 90, 32), 'temple': (24, 40, 20), 'round_temple': (14, 14, 12), 'triumphal_arch': (20, 7, 18), 'aqueduct': (0, 0, 18),
    'basilica': (70, 32, 22), 'tower': (10, 10, 34), 'lighthouse': (12, 12, 40), 'windmill': (9, 9, 18), 'fountain': (12, 12, 5), 'statue': (5, 5, 12),
    'obelisk': (4, 4, 24), 'column': (5, 5, 30), 'garden': (60, 45, 0), 'market': (60, 40, 9), 'theater': (90, 90, 24), 'circus': (300, 70, 10),
    'forum': (90, 45, 0), 'bath': (110, 80, 24), 'pantheon': (45, 60, 36), 'castle': (40, 40, 22),
    'market_stalls': (44, 22, 3), 'church': (50, 22, 18), 'lime_kiln': (7, 7, 5), 'vegetable_garden': (70, 45, 0),
}


def projector(origin):
    lat0, lon0 = origin['lat'], origin['lon']
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    return lambda lat, lon: (round((lon - lon0) * m_lon, 2), round(-(lat - lat0) * M_PER_LAT, 2))


def axis_vec(bearing):
    b = math.radians(bearing)
    return (math.sin(b), -math.cos(b))


def is_rome(plan_or_id):
    key = plan_or_id.get('basemap') if isinstance(plan_or_id, dict) else plan_or_id
    return key in ERAS


def rome_basemap(era='rome_476'):
    src = ERAS.get(era, ROME_476)
    xz = projector(src['origin'])
    pt = lambda item: dict(zip(('x', 'z'), xz(item['lat'], item['lon'])))
    landmarks = [{**{k: v for k, v in m.items() if k not in ('lat', 'lon')}, **pt(m)} for m in src['landmarks']]
    out = {
        'id': src['id'], 'name': src['name'], 'historical': True, 'size': src['size'], 'cell': src['cell'], 'origin': src['origin'], 'sources': src['sources'],
        'floor': src['floor'], 'river_level': src['river_level'],
        'hills': [{**{k: v for k, v in h.items() if k not in ('lat', 'lon')}, **pt(h)} for h in src['hills']],
        'rivers': [{'id': src['river']['id'], 'name': src['river']['name'], 'quays': src['river']['quays'],
                    'pts': [[*xz(lat, lon), w] for lat, lon, w in src['river']['points']]}],
        'islands': [{**{k: v for k, v in i.items() if k not in ('lat', 'lon')}, **pt(i)} for i in src['islands']],
        'bridges': [{**{k: v for k, v in b.items() if k not in ('lat', 'lon')}, **pt(b)} for b in src['bridges']],
        'palace': {**{k: v for k, v in src['palace'].items() if k not in ('lat', 'lon')}, **pt(src['palace'])},
        'landmarks': landmarks,
        'aqueducts': [{'id': a['id'], 'name': a['name'], 'h': a['h'], 'pts': [list(xz(lat, lon)) for lat, lon in a['points']]} for a in src['aqueducts']],
        'roads': [{'name': r['name'], 'width': r['width'], 'main': r['main'], 'pts': [list(xz(lat, lon)) for lat, lon in r['points']]} for r in src['roads']],
        'districts': [{**{k: v for k, v in d.items() if k not in ('lat', 'lon')}, **pt(d)} for d in src['districts']],
        'keepout': [{**{k: v for k, v in k_.items() if k not in ('lat', 'lon')}, **pt(k_)} for k_ in src['keepout']],
        'city': {'x': 0.0, 'z': 0.0, 'r': 950.0},
        'mills': [{'id': x['id'], 'name': x['name'], **pt(x)} for x in src.get('mills', [])],
        'flocks': [{'name': f['name'], 'r': f['r'], 'count': f['count'], **pt(f)} for f in src.get('flocks', [])],
    }
    out['named'] = named_places(out)
    out['named_labels'] = {**{h['id']: h['name'] for h in out['hills']}, **{m['id']: m['name'] for m in out['landmarks']}, **{d['id']: d['name'] for d in out['districts']}, **{i['id']: i['name'] for i in out['islands']}}
    return out


def named_places(bm):
    places = {h['id']: (h['x'], h['z']) for h in bm['hills']}
    places.update({m['id']: (m['x'], m['z']) for m in bm['landmarks']})
    places.update({d['id']: (d['x'], d['z']) for d in bm['districts']})
    places.update({i['id']: (i['x'], i['z']) for i in bm['islands']})
    places.update({b['id']: (b['x'], b['z']) for b in bm['bridges']})
    places['forum'] = places.get('forum_romanum', places.get('forum', (bm['city']['x'], bm['city']['z'])))
    places['tiber'] = tuple(bm['rivers'][0]['pts'][len(bm['rivers'][0]['pts']) // 2][:2]) if bm['rivers'] else (0.0, 0.0)
    return places


def edge_point(direction, half, rng):
    dx, dz = DIR_VEC[direction]
    scale = half / max(abs(dx), abs(dz), 1e-6)
    jitter = rng.uniform(-0.15, 0.15) * half
    return (dx * scale * 1.02 + (jitter if abs(dz) > 0.5 else 0.0), dz * scale * 1.02 + (jitter if abs(dx) > 0.5 else 0.0))


def bezier(a, b, c, step):
    length = math.hypot(b[0] - a[0], b[1] - a[1]) + math.hypot(c[0] - b[0], c[1] - b[1])
    n = max(8, int(length / step))
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1]) for t in (k / n for k in range(n + 1))]


def meander(pts, amp, rng):
    phase = rng.uniform(0, 6.28)
    out = []
    for k, (x, z) in enumerate(pts):
        nx_, nz_ = pts[min(k + 1, len(pts) - 1)]
        px, pz = pts[max(k - 1, 0)]
        dx, dz = nx_ - px, nz_ - pz
        norm = math.hypot(dx, dz) or 1.0
        off = amp * math.sin(k * 0.35 + phase)
        out.append((x - dz / norm * off, z + dx / norm * off))
    return out


def resolve(at, bm, rng, radius):
    cx, cz = bm['city']['x'], bm['city']['z']
    named = bm['named']
    hills = sorted(bm['hills'], key=lambda h: math.hypot(h['x'] - cx, h['z'] - cz))
    if at in named:
        return named[at]
    if at.startswith('hill_'):
        dx, dz = DIR_VEC[at[5:]]
        side = [h for h in hills if (h['x'] - cx) * dx + (h['z'] - cz) * dz > 0.5 * math.hypot(h['x'] - cx, h['z'] - cz)]
        if not side:
            bm['hills'].append({'id': f'hill_{at[5:]}', 'name': 'גבעת הארמון', 'x': cx + dx * radius * 1.3, 'z': cz + dz * radius * 1.3, 'h': 26.0, 'a': 60.0, 'b': 48.0, 'axis': 90.0})
            side = [bm['hills'][-1]]
        best = min(side, key=lambda h: math.hypot(h['x'] - cx, h['z'] - cz))
        return best['x'], best['z']
    if at == 'hilltop' and not hills:
        bm['hills'].append({'id': 'palace_hill', 'name': 'גבעת הארמון', 'x': cx, 'z': cz - radius * 1.1, 'h': 26.0, 'a': 60.0, 'b': 48.0, 'axis': 90.0})
        hills = bm['hills']
    if at == 'hilltop' and hills:
        return hills[0]['x'], hills[0]['z']
    if at == 'riverside' and bm['rivers']:
        pts = bm['rivers'][0]['pts']
        best = min(pts, key=lambda p: math.hypot(p[0] - cx, p[1] - cz))
        dx, dz = cx - best[0], cz - best[1]
        norm = math.hypot(dx, dz) or 1.0
        return best[0] + dx / norm * (best[2] / 2 + 40), best[1] + dz / norm * (best[2] / 2 + 40)
    if at == 'coast' and bm.get('sea_side', 'none') != 'none':
        dx, dz = DIR_VEC[bm['sea_side']]
        return cx + dx * radius * 1.1, cz + dz * radius * 1.1
    dx, dz = DIR_VEC.get(at, (0.0, 0.0))
    spread = rng.uniform(0.75, 1.15) * radius
    return cx + dx * spread, cz + dz * spread


def avoid_rivers(x, z, rad, bm):
    for _ in range(12):
        hits = [(p, math.hypot(p[0] - x, p[1] - z)) for r in bm['rivers'] for p in r['pts'] if math.hypot(p[0] - x, p[1] - z) < rad + p[2] / 2 + 8]
        if not hits:
            return x, z
        p, d = min(hits, key=lambda h: h[1])
        dx, dz = (x - p[0], z - p[1]) if d > 1e-3 else (1.0, 0.0)
        norm = math.hypot(dx, dz)
        push = rad + p[2] / 2 + 10 - d
        x, z = x + dx / norm * push, z + dz / norm * push
    return x, z


def bearing_to(a, b):
    return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1]))) % 360


def procedural_basemap(plan):
    rng = random.Random(plan.get('seed', 1))
    size = CITY_SIZES[plan['city']['size']]
    half = size / 2
    cdx, cdz = DIR_VEC[plan['city']['at']]
    city = {'x': cdx * size * 0.18, 'z': cdz * size * 0.18, 'r': size * 0.3}
    bm = {'id': 'procedural', 'name': 'מפת פרויקט שנוצרה מהתיאור', 'historical': False, 'size': size, 'cell': round(size / int(size / 3.6), 4),
          'origin': None, 'sources': ['נוצרה מהתוכנית (פרומפט ותמונה)'], 'sea_side': plan['water']['sea_side'], 'mills': [], 'flocks': [],
          'hills': [], 'rivers': [], 'islands': [], 'bridges': [], 'landmarks': [], 'aqueducts': [], 'roads': [], 'districts': [], 'keepout': [], 'city': city}
    for k in range(plan['terrain']['hills']):
        ang = k * 2 * math.pi / max(1, plan['terrain']['hills']) + rng.uniform(-0.3, 0.3)
        rad = size * rng.uniform(0.16, 0.3)
        bm['hills'].append({'id': f'hill{k + 1}', 'name': f'גבעה {k + 1}', 'x': city['x'] + math.cos(ang) * rad, 'z': city['z'] + math.sin(ang) * rad,
                            'h': rng.uniform(18, 34) * (0.6 + plan['terrain']['relief']), 'a': rng.uniform(45, 75), 'b': rng.uniform(32, 55), 'axis': rng.uniform(0, 180)})
    bm['named'] = named_places({**bm, 'rivers': []})
    for k, river in enumerate(plan['water']['rivers']):
        start = edge_point(river['from'], half, rng)
        end = edge_point(river['to'], half, rng)
        via = resolve(river['via'], bm, rng, size * 0.2) if river['via'] != 'center' else (city['x'] + rng.uniform(-10, 10), city['z'] + rng.uniform(-10, 10))
        pts = meander(bezier(start, via, end, 8.0), min(12.0, river['width'] * 0.5), rng)
        bm['rivers'].append({'id': f'river{k + 1}', 'name': f'נהר {k + 1}', 'quays': river['quays'], 'pts': [[round(x, 1), round(z, 1), river['width']] for x, z in pts]})
    bm['named'] = named_places(bm)
    pal = plan['palace']
    px, pz = resolve(pal['at'], bm, rng, size * 0.2) if pal['at'] != 'center' else (city['x'], city['z'] - 10)
    px, pz = avoid_rivers(px, pz, 24, bm)
    faces = bearing_to((px, pz), (city['x'], city['z'])) if math.hypot(px - city['x'], pz - city['z']) > 20 else 180.0
    bm['palace'] = {'id': 'palace', 'name': 'הארמון', 'x': round(px, 2), 'z': round(pz, 2), 'faces': round(faces, 1), 'w': 26.0, 'd': 20.0, 'h': 13.0, 'kind': pal['kind']}
    for k, mark in enumerate(plan['landmarks']):
        w, d, h = LANDMARK_SIZES[mark['kind']]
        mx, mz = resolve(mark['at'], bm, rng, size * rng.uniform(0.12, 0.26)) if mark['at'] != 'center' else (city['x'] + rng.uniform(-60, 60), city['z'] + rng.uniform(20, 60))
        if mark['kind'] == 'aqueduct':
            start = edge_point(mark['at'] if mark['at'] in DIR_VEC and mark['at'] != 'center' else 'e', half, rng)
            bm['aqueducts'].append({'id': f'aq{k}', 'name': mark['name'] or 'אמת מים', 'h': h, 'pts': [list(start), [city['x'] * 0.5 + start[0] * 0.5, city['z'] * 0.5 + start[1] * 0.5], [city['x'] + 30, city['z'] + 30]]})
            continue
        mx, mz = avoid_rivers(mx, mz, max(w, d) / 2, bm)
        bm['landmarks'].append({'id': f'lm{k}', 'kind': mark['kind'], 'name': mark['name'] or HE_KINDS.get(mark['kind'], mark['kind']), 'x': round(mx, 2), 'z': round(mz, 2), 'w': w, 'd': d, 'h': h,
                                'axis': round(bearing_to((mx, mz), (city['x'], city['z'])) + 90, 1)})
    districts = plan['districts'] + [{'name': 'העיר', 'at': 'center', 'style': plan['style'], 'density': plan['city']['density'], 'base': True}]
    for k, dist in enumerate(districts):
        dx, dz = (0.0, 0.0) if dist['at'] == 'center' else DIR_VEC.get(dist['at'], (0.0, 0.0))
        anchor = bm['named'].get(dist['at']) or (city['x'] + dx * size * 0.22, city['z'] + dz * size * 0.22)
        bm['districts'].append({'id': f'd{k}', 'name': dist['name'] or f'רובע {k + 1}', 'x': anchor[0], 'z': anchor[1],
                                'r': size * (0.36 if dist.get('base') else 0.2), 'density': dist['density'], 'style': dist['style']})
    bm['named'] = named_places(bm)
    return bm


def basemap_for(plan):
    return rome_basemap(plan['basemap']) if is_rome(plan) else procedural_basemap(plan)


def place_names(plan):
    return tuple(rome_basemap(plan['basemap'])['named']) if is_rome(plan) else ()


def rome_plan_defaults(era='rome_476'):
    return copy.deepcopy(ERAS.get(era, ROME_476)['plan'])
