import copy
import math

from .interpreter import FLOOR_COLORS, WALL_MATERIALS, interpret_room

ITEM_DEFAULTS = {
    'long_table': {'w': 7.5, 'd': 1.6, 'h': 0.95, 'color': '#6b4423', 'material': 'wood', 'name': 'שולחן עץ ארוך'},
    'table': {'w': 2.2, 'd': 1.2, 'h': 0.9, 'color': '#6b4423', 'material': 'wood', 'name': 'שולחן'},
    'chair': {'w': 0.6, 'd': 0.6, 'h': 1.05, 'color': '#5a3a1f', 'material': 'wood', 'name': 'כיסא'},
    'chandelier': {'w': 1.6, 'd': 1.6, 'h': 1.2, 'color': '#d4a93a', 'material': 'gold', 'name': 'נברשת'},
    'curtains': {'w': 1.5, 'd': 0.2, 'h': 3.4, 'color': '#7a1f2b', 'material': 'cloth', 'name': 'וילון'},
    'rug': {'w': 4.0, 'd': 2.8, 'h': 0.03, 'color': '#8a2a2a', 'material': 'cloth', 'name': 'שטיח'},
    'throne': {'w': 1.5, 'd': 1.3, 'h': 2.8, 'color': '#c9a227', 'material': 'gold', 'name': 'כס מלכות'},
    'bookshelf': {'w': 2.4, 'd': 0.5, 'h': 2.7, 'color': '#5a3a1f', 'material': 'wood', 'name': 'ספרייה'},
    'bed': {'w': 2.0, 'd': 2.5, 'h': 1.1, 'color': '#6e2433', 'material': 'cloth', 'name': 'מיטה'},
    'column': {'w': 0.9, 'd': 0.9, 'h': 0.0, 'color': '#e6e2d8', 'material': 'marble', 'name': 'עמוד'},
    'fireplace': {'w': 2.6, 'd': 0.9, 'h': 2.4, 'color': '#6c6a64', 'material': 'stone', 'name': 'אח'},
    'banner': {'w': 0.9, 'd': 0.05, 'h': 2.6, 'color': '#2f5d9e', 'material': 'cloth', 'name': 'דגל'},
    'candelabra': {'w': 0.4, 'd': 0.4, 'h': 1.5, 'color': '#d4a93a', 'material': 'gold', 'name': 'פמוט'},
    'plant': {'w': 0.7, 'd': 0.7, 'h': 1.3, 'color': '#3f7a4a', 'material': 'leaf', 'name': 'עציץ'},
    'statue': {'w': 0.9, 'd': 0.9, 'h': 2.2, 'color': '#b9bec7', 'material': 'marble', 'name': 'פסל'},
    'couch': {'w': 2.4, 'd': 1.1, 'h': 0.9, 'color': '#7a1f2b', 'material': 'cloth', 'name': 'מיטת הסבה (לקטוס)'},
    'fountain_oct': {'w': 12.0, 'd': 12.0, 'h': 1.0, 'color': '#e4ddcc', 'material': 'marble', 'name': 'מזרקה מתומנת'},
    'fountain': {'w': 2.4, 'd': 2.4, 'h': 1.2, 'color': '#e4ddcc', 'material': 'marble', 'name': 'מזרקה'},
}

DEFAULT_COUNTS = {'chandelier': 1, 'column': 4, 'banner': 2, 'candelabra': 2, 'statue': 2, 'plant': 2, 'bookshelf': 2, 'chair': 4}


def spread(n, length, margin):
    usable = max(0.1, length - 2 * margin)
    return [0.0] if n == 1 else [-usable / 2 + usable * k / (n - 1) for k in range(n)]


def window_slots(design):
    count = int(design['windows'].get('count') or 0)
    w, d = design['w'], design['d']
    slots = []
    for wall, length in (('e', d), ('w', d)):
        slots += [{'wall': wall, 'along': (k + 1) / (count + 1) * length - length / 2} for k in range(count)]
    if not design.get('door_north', True):
        slots += [{'wall': 'n', 'along': (k + 1) / (count + 1) * w - w / 2} for k in range(max(1, count - 1))]
    return slots


def of_kind(items, kind):
    return [it for it in items if it['kind'] == kind]


def new_item(kind, base, params, counter):
    item = dict(ITEM_DEFAULTS[kind])
    item.update({k: v for k, v in (base or {}).items() if k in ITEM_DEFAULTS[kind]})
    item.update({k: v for k, v in params.items() if v})
    item.update({'id': f'{kind}-{counter}', 'kind': kind, 'x': 0.0, 'z': 0.0, 'y': 0.0, 'rot': 0.0})
    return item


def layout(design):
    items = design['items']
    w, d, h = design['w'], design['d'], design['h']
    tables = of_kind(items, 'long_table') + of_kind(items, 'table')
    shift = 1.5 if of_kind(items, 'throne') else 0.0
    if of_kind(items, 'fountain_oct'):
        shift = d / 2 - 6
    for k, it in enumerate(tables):
        it['x'], it['z'], it['rot'] = 0.0, (k - (len(tables) - 1) / 2) * 3.2 + shift, 0.0
    chairs = of_kind(items, 'chair')
    if tables and chairs:
        per_table = max(1, math.ceil(len(chairs) / len(tables)))
        for k, it in enumerate(chairs):
            table = tables[min(len(tables) - 1, k // per_table)]
            slot = k % per_table
            sides = [-1, 1] * per_table
            side = sides[slot]
            row = slot // 2
            half_slots = max(1, math.ceil(per_table / 2))
            xs = spread(half_slots, table['w'], 0.6)
            it['x'] = table['x'] + xs[min(row, len(xs) - 1)]
            it['z'] = table['z'] + side * (table['d'] / 2 + 0.55)
            it['rot'] = math.pi if side < 0 else 0.0
    else:
        for k, it in enumerate(chairs):
            it['x'], it['z'], it['rot'] = spread(max(1, len(chairs)), w, 2.0)[k], -d / 2 + 1.0, 0.0
    chandeliers = of_kind(items, 'chandelier')
    for k, it in enumerate(chandeliers):
        it['x'], it['z'], it['y'] = 0.0, spread(len(chandeliers), d, 2.5)[k], h - it['h'] - 0.2
    for it in of_kind(items, 'rug'):
        if tables:
            it['w'], it['d'] = tables[0]['w'] + 2.4, max(it.get('d', 2.8), tables[0]['d'] + 3.0 + 1.2 * (len(tables) - 1))
            it['x'], it['z'] = 0.0, sum(t['z'] for t in tables) / len(tables)
        else:
            it['x'], it['z'] = 0.0, 0.0
    for it in of_kind(items, 'throne'):
        it['x'], it['z'], it['rot'] = 0.0, -d / 2 + 1.1, 0.0
    cols = of_kind(items, 'column')
    per_side = max(1, math.ceil(len(cols) / 2))
    for k, it in enumerate(cols):
        side = -1 if k % 2 == 0 else 1
        it['x'], it['z'], it['h'] = side * (w / 2 - 1.3), spread(per_side, d, 2.0)[min(k // 2, per_side - 1)], h
    shelves = of_kind(items, 'bookshelf')
    for k, it in enumerate(shelves):
        it['x'], it['z'], it['rot'] = -w / 2 + it['d'] / 2 + 0.05, spread(len(shelves), d, 3.0)[k], math.pi / 2
    for it in of_kind(items, 'fireplace'):
        it['x'], it['z'], it['rot'] = w / 2 - it['d'] / 2 - 0.05, 0.0, -math.pi / 2
    banners = of_kind(items, 'banner')
    for k, it in enumerate(banners):
        it['x'], it['z'], it['y'], it['rot'] = spread(len(banners), w, 2.5)[k], -d / 2 + 0.1, min(1.6, h - it['h'] - 0.3), 0.0
    cand = of_kind(items, 'candelabra')
    for k, it in enumerate(cand):
        side = -1 if k % 2 == 0 else 1
        it['x'], it['z'] = side * (w / 2 - 0.8), -d / 2 + 0.9 + (k // 2) * 2.0
    couches = of_kind(items, 'couch')
    for k, it in enumerate(couches):
        side = k % 3
        slot = k // 3
        positions = [(-3.2, 0.0, math.pi / 2), (0.0, -3.2, 0.0), (3.2, 0.0, -math.pi / 2)]
        bx, bz, rot = positions[side]
        off = (slot - 1) * 2.6
        it['x'], it['z'], it['rot'] = bx + (off if side == 1 else 0), bz + (off if side != 1 else 0), rot
    for it in of_kind(items, 'fountain_oct') + of_kind(items, 'fountain'):
        it['x'], it['z'] = 0.0, 0.0 if it['kind'] == 'fountain_oct' else -d / 2 + 2.5
    for k, it in enumerate(of_kind(items, 'bed')):
        it['x'], it['z'] = -w / 2 + 1.4, -d / 2 + 1.5 + k * 3.0
    plants = of_kind(items, 'plant') + of_kind(items, 'statue')
    per_side = max(1, math.ceil(len(plants) / 2))
    for k, it in enumerate(plants):
        side = -1 if k % 2 == 0 else 1
        it['x'], it['z'] = side * (w / 2 - 0.9), spread(per_side, d, 2.0)[min(k // 2, per_side - 1)]
    windows = window_slots(design)
    curtains = [it for it in items if it['kind'] == 'curtains']
    if curtains:
        proto = curtains[0]
        design['items'] = [it for it in items if it['kind'] != 'curtains']
        for k, slot in enumerate(windows):
            c = dict(proto)
            c.update({'id': f'curtains-{k}', 'wall': slot['wall'], 'along': slot['along'], 'h': min(3.6, h - 0.8), 'w': 1.8 if design['windows'].get('size') == 'large' else 1.4})
            design['items'].append(c)
    return design


def counter_for(design, kind):
    return max([int(it['id'].rsplit('-', 1)[-1]) for it in design['items'] if it['kind'] == kind and it['id'].rsplit('-', 1)[-1].isdigit()] + [-1]) + 1


def apply_one(design, comp, library_lookup):
    t = comp['type']
    if t == 'item':
        kind = comp['kind']
        if comp['action'] == 'remove':
            keep = [it for it in design['items'] if it['kind'] != kind]
            removed = [it for it in design['items'] if it['kind'] == kind]
            n = comp['count'] if comp['count'] > 1 else len(removed)
            design['items'] = keep + removed[:max(0, len(removed) - n)]
            return
        if kind == 'curtains':
            asset = comp.get('asset') or library_lookup(kind)
            design['items'] = [it for it in design['items'] if it['kind'] != 'curtains']
            design['items'].append(new_item(kind, asset['params'] if asset else None, {'color': comp.get('color'), 'material': comp.get('material')}, 0))
            return
        existing = of_kind(design['items'], kind)
        want = comp['count'] if comp['count'] > 1 else (DEFAULT_COUNTS.get(kind, 1) if kind in DEFAULT_COUNTS and kind != 'chair' else 1)
        asset = comp.get('asset') or library_lookup(kind)
        base = asset['params'] if asset else None
        start = counter_for(design, kind)
        for k in range(want):
            item = new_item(kind, base, {'color': comp.get('color'), 'material': comp.get('material'), 'h': comp.get('h')}, start + k)
            if asset:
                item['asset_id'] = asset['id']
            design['items'].append(item)
        return
    if t == 'floor':
        design['floor'] = {'material': comp['material'], 'color': comp.get('color') or FLOOR_COLORS.get(comp['material'], '#7d7a74')}
    elif t == 'walls':
        design['walls'] = {'material': comp.get('material') or design['walls']['material'], 'color': comp.get('color') or WALL_MATERIALS.get(comp.get('material'), design['walls']['color'])}
    elif t == 'ceiling':
        design['ceiling'] = {'style': comp['style'], 'color': comp.get('color') or design['ceiling']['color']}
    elif t == 'windows':
        win = design['windows']
        win['style'] = comp.get('style') or win['style']
        win['size'] = comp.get('size') or win['size']
        win['count'] = comp.get('count') or win['count']
        win['color'] = comp.get('color') or win['color']
        win['stained'] = bool(comp.get('stained')) if comp.get('stained') is not None else win.get('stained', False)
    elif t == 'light':
        design['light'] = {'tone': comp['tone'], 'intensity': comp.get('intensity', 1.0)}


def apply_components(design, comps, library_lookup=lambda kind: None):
    out = copy.deepcopy(design)
    for comp in comps:
        apply_one(out, comp, library_lookup)
    return layout(out)


def describe(comps):
    return ' · '.join(c['label'] for c in comps) or 'ללא שינוי'


def propose(design, text, library_lookup, use_llm=True, context=''):
    comps, source, notes = interpret_room(text, design, use_llm, context)
    for comp in comps:
        comp['selected'] = True
        if comp['type'] == 'item':
            asset = library_lookup(comp['kind'])
            if asset and comp['action'] == 'add':
                comp['asset'] = {'id': asset['id'], 'name': asset['name'], 'params': asset['params']}
                comp['label'] += f" · מהספרייה: {asset['name']}"
    return comps, source, notes


def split_scopes(comps):
    surface = [c for c in comps if c['type'] != 'item']
    return surface, [c for c in comps if c['type'] == 'item']
