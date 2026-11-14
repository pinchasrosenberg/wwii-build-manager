import math
import random

from .basemap import DIR_VEC, HE_KINDS, LANDMARK_SIZES, axis_vec, basemap_for, bearing_to, bezier, edge_point, meander, resolve
from .cartography import Occupancy, box as obox, corners, house_box, map_svg, occupancy, point_seg, repair, route_around, street_segments
from .city import PALACE_ROOMS, ROOF_DEFAULTS, Spatial, jitter
from .lexicon import MATERIAL_COLORS
from .terrain import Grid, build_heights, fbm, lerp, smooth

SPECIES_BY_VEG = {'temperate': ['broadleaf', 'pine'], 'alpine': ['pine'], 'tropical': ['palm', 'broadleaf'], 'desert': ['shrub', 'palm'], 'none': []}
PALACE_SIZES = {'castle': (26.0, 20.0, 13.0), 'classical': (36.0, 26.0, 15.0)}


def make_grid(bm):
    n = int(round(bm['size'] / bm['cell'])) + 1
    return Grid(bm['size'], n)


def ellipse_shape(x, z, item, plateau=0.5):
    ax, az = axis_vec(item.get('axis', 0.0))
    dx, dz = x - item['x'], z - item['z']
    u = dx * ax + dz * az
    v = -dx * az + dz * ax
    r = math.hypot(u / item['a'], v / item['b'])
    return 1.0 - smooth((r - plateau) / (1.0 - plateau))


def stamp_hills(grid, bm, plan, seed):
    for hill in bm['hills']:
        reach = max(hill['a'], hill['b']) * 1.05
        i0, i1 = grid_span(grid, hill['x'], reach)
        j0, j1 = grid_span(grid, hill['z'], reach)
        for j in range(j0, j1 + 1):
            z = grid.x_of(j)
            for i in range(i0, i1 + 1):
                x = grid.x_of(i)
                f = ellipse_shape(x, z, hill, 0.45 if bm['historical'] else 0.25)
                if f <= 0:
                    continue
                k = grid.idx(i, j)
                bump = (hill['h'] + 2.0 * (fbm(x / 40, z / 40, seed + 77, 3) - 0.5)) * f
                grid.h[k] = max(grid.h[k], bm['floor'] + (hill['h'] - bm['floor']) * f + 1.5 * (fbm(x / 30, z / 30, seed, 2) - 0.5) * f) if bm['historical'] else grid.h[k] + bump


def grid_span(grid, c, reach):
    lo = max(0, int((c - reach + grid.size / 2) / grid.step))
    hi = min(grid.n - 1, int((c + reach + grid.size / 2) / grid.step) + 1)
    return lo, hi


def base_terrain(plan, bm, rng):
    grid = make_grid(bm)
    if bm['historical']:
        seed = plan['seed'] % 10000
        for j in range(grid.n):
            z = grid.x_of(j)
            for i in range(grid.n):
                x = grid.x_of(i)
                grid.h[grid.idx(i, j)] = bm['floor'] + 2.2 * (fbm(x / 160, z / 160, seed, 4) - 0.5)
        stamp_hills(grid, bm, plan, seed)
        return grid, None
    spec = {'terrain': plan['terrain'], 'seed': plan['seed']}
    grid, info = build_heights(spec, rng, grid, (bm['city']['x'], bm['city']['z']))
    bm['floor'] = grid.at(bm['city']['x'], bm['city']['z'])
    stamp_hills(grid, bm, plan, plan['seed'] % 10000)
    sea = 0.0 if plan['water']['sea_side'] != 'none' or info['sea_level'] is not None else None
    if plan['water']['sea_side'] != 'none':
        dx, dz = DIR_VEC[plan['water']['sea_side']]
        half = grid.size / 2
        for j in range(grid.n):
            z = grid.x_of(j)
            for i in range(grid.n):
                x = grid.x_of(i)
                s = (x * dx + z * dz) / half
                k = grid.idx(i, j)
                grid.h[k] = lerp(-7.0, max(grid.h[k], 2.5), 1.0 - smooth((s - 0.42) / 0.26))
    c = bm['city']
    level = max(grid.at(c['x'], c['z']), (sea or -1e9) + 3.0)
    strength = 0.55 if plan['terrain']['kind'] in ('sharp_mountains', 'mountains', 'canyon') else 0.85
    grid.pull(c['x'], c['z'], level, c['r'] * 0.3, c['r'] * 0.55, strength)
    return grid, sea


def densify(pts, step):
    out = []
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(seg / step))
        for k in range(n):
            t = k / n
            out.append([a[q] + (b[q] - a[q]) * t for q in range(len(a))])
    return out + [list(pts[-1])]


def carve_rivers(grid, bm, plan):
    rivers = []
    for river in bm['rivers']:
        pts = densify(river['pts'], 4.0)
        surfaces = []
        level = bm.get('river_level')
        running = None
        for x, z, w in pts:
            ground = grid.at(x, z) if grid.inside(x, z, 0) else (running if running is not None else 0.0)
            running = (ground - 2.6) if running is None else min(running, ground - 2.6)
            surfaces.append(level if level is not None else running)
        bank = 3.0 if river['quays'] else 9.0
        best = {}
        for (x, z, w), surf in zip(pts, surfaces):
            reach = w / 2 + bank
            i0, i1 = grid_span(grid, x, reach)
            j0, j1 = grid_span(grid, z, reach)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    d = math.hypot(grid.x_of(i) - x, grid.x_of(j) - z)
                    if d <= reach:
                        k = grid.idx(i, j)
                        ratio = d / (w / 2)
                        if k not in best or ratio < best[k][0]:
                            best[k] = (ratio, surf, w)
        for k, (ratio, surf, w) in best.items():
            if ratio <= 1.0:
                grid.h[k] = surf - 2.0 - 0.025 * w * (1.0 - ratio)
            elif river['quays']:
                grid.h[k] = surf + 5.0 if grid.h[k] < surf + 9.0 else grid.h[k]
            else:
                t = (ratio - 1.0) * (w / 2) / bank
                grid.h[k] = lerp(surf + 0.9, max(grid.h[k], surf + 1.2), smooth(t))
        rivers.append({'id': river['id'], 'name': river['name'], 'quays': river['quays'],
                       'pts': [[round(x, 1), round(z, 1), round(s, 2), round(w, 1)] for (x, z, w), s in zip(pts[::2], surfaces[::2])]})
    for isl in bm['islands']:
        reach = max(isl['a'], isl['b']) + 8
        i0, i1 = grid_span(grid, isl['x'], reach)
        j0, j1 = grid_span(grid, isl['z'], reach)
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                f = ellipse_shape(grid.x_of(i), grid.x_of(j), isl, 0.8)
                if f > 0:
                    k = grid.idx(i, j)
                    grid.h[k] = lerp(grid.h[k], isl['h'], f)
    return rivers


def water_at(grid, rivers, sea, x, z):
    surf = water_surface(rivers, x, z)
    return (surf is not None and grid.at(x, z) < surf + 0.6) or (sea is not None and grid.at(x, z) < sea + 0.6)


def water_surface(rivers, x, z):
    hits = [p[2] for r in rivers for p in r['pts'] if abs(p[0] - x) < p[3] and abs(p[1] - z) < p[3] and math.hypot(p[0] - x, p[1] - z) < p[3] / 2 + 3]
    return max(hits) if hits else None


def river_frame(rivers, x, z):
    best = None
    for r in rivers:
        pts = r['pts']
        for k in range(len(pts) - 1):
            d = math.hypot(pts[k][0] - x, pts[k][1] - z)
            if best is None or d < best[0]:
                fx, fz = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
                norm = math.hypot(fx, fz) or 1.0
                best = (d, pts[k], (fx / norm, fz / norm))
    return best


def build_bridges(grid, bm, rivers):
    out = []
    for b in bm['bridges']:
        frame = river_frame(rivers, b['x'], b['z'])
        if frame is None:
            continue
        _, p, (fx, fz) = frame
        left = (fz, -fx)
        width = p[3]
        island = bm['islands'][0]['b'] + 3 if bm['islands'] else 0
        side = b.get('side')
        s0, s1 = ((island, width / 2 + 12) if side == 'left' else (-island, -(width / 2 + 12)) if side == 'right' else (-(width / 2 + 12), width / 2 + 12))
        ax, az = b['x'] + left[0] * s0, b['z'] + left[1] * s0
        bx, bz = b['x'] + left[0] * s1, b['z'] + left[1] * s1
        ya, yb = grid.at(ax, az), grid.at(bx, bz)
        deck = max(p[2] + 6.5, min(ya, yb))
        out.append({'id': b['id'], 'name': b['name'], 'style': b['style'], 'a': [round(ax, 2), round(az, 2), round(deck, 2)], 'b': [round(bx, 2), round(bz, 2), round(deck, 2)],
                    'width': 9.0 if b['style'] == 'arched_stone' else 6.0, 'water': round(p[2], 2), 'bed': round(p[2] - 2.5, 2)})
        for (x, z, y) in ((ax, az, ya), (bx, bz, yb)):
            if y < deck:
                grid.pull(x, z, deck, 4.0, 16.0, 1.0)
    return out


class Footprints:
    def __init__(self):
        self.items = []
        self.index = Spatial(40.0)

    def add(self, x, z, w, d, rot, margin, tag):
        item = {'x': x, 'z': z, 'hw': w / 2 + margin, 'hd': d / 2 + margin, 'rot': rot, 'tag': tag}
        self.items.append(item)
        reach = math.hypot(item['hw'], item['hd'])
        for dx in range(-int(reach // 40) - 1, int(reach // 40) + 2):
            for dz in range(-int(reach // 40) - 1, int(reach // 40) + 2):
                self.index.add(x + dx * 40, z + dz * 40, item)

    def hit(self, x, z, r=0.0):
        seen = set()
        for _, _, it in self.index.near(x, z, 60):
            if id(it) in seen:
                continue
            seen.add(id(it))
            c, s = math.cos(it['rot']), math.sin(it['rot'])
            dx, dz = x - it['x'], z - it['z']
            lx, lz = dx * c - dz * s, dx * s + dz * c
            if abs(lx) <= it['hw'] + r and abs(lz) <= it['hd'] + r:
                return True
        return False


def rot_from_axis(bearing):
    return math.pi / 2 - math.radians(bearing)


def rot_from_faces(bearing):
    return math.pi - math.radians(bearing)


def place_landmarks(grid, bm, plan, rng, foot, rivers):
    out = []
    decay = plan['condition']['decay']
    for m in bm['landmarks']:
        rot = rot_from_faces(m['faces']) if 'faces' in m else rot_from_axis(m.get('axis', 0))
        pad = sum(grid.at(m['x'] + dx, m['z'] + dz) for dx in (-m['w'] / 3, 0, m['w'] / 3) for dz in (-m['d'] / 3, 0, m['d'] / 3)) / 9
        if m['kind'] not in ('garden', 'forum', 'vegetable_garden', 'market_stalls') or m['w'] < 200:
            flatten_rect(grid, m['x'], m['z'], m['w'] + 6, m['d'] + 6, rot, pad)
        y = grid.at(m['x'], m['z'])
        foot.add(m['x'], m['z'], m['w'], m['d'], rot, 4.0 if m['kind'] not in ('garden', 'vegetable_garden', 'market_stalls', 'lime_kiln') else 0.5, m['kind'])
        out.append({'id': m['id'], 'kind': m['kind'], 'name': m['name'], 'x': round(m['x'], 2), 'z': round(m['z'], 2), 'y': round(y, 2),
                    'w': m['w'], 'd': m['d'], 'h': m['h'], 'rot': round(rot, 4), 'state': round(max(0.0, min(1.0, decay + rng.uniform(-0.15, 0.15))), 2)})
    return out


def flatten_rect(grid, x, z, w, d, rot, y):
    reach = math.hypot(w, d) / 2 + 6
    i0, i1 = grid_span(grid, x, reach)
    j0, j1 = grid_span(grid, z, reach)
    c, s = math.cos(rot), math.sin(rot)
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            dx, dz = grid.x_of(i) - x, grid.x_of(j) - z
            lx, lz = dx * c - dz * s, dx * s + dz * c
            ex = max(0.0, abs(lx) - w / 2)
            ez = max(0.0, abs(lz) - d / 2)
            e = math.hypot(ex, ez)
            if e < 6.0:
                k = grid.idx(i, j)
                grid.h[k] = lerp(y, grid.h[k], smooth(e / 6.0))


def place_palace(grid, bm, plan, rng, foot):
    p = dict(bm['palace'])
    pal_plan = plan['palace']
    if bm['historical'] and pal_plan['at'] not in ('palatine', 'domus_flavia', 'center'):
        p['x'], p['z'] = resolve(pal_plan['at'], bm, rng, 300.0)
        p['faces'] = bearing_to((p['x'], p['z']), (bm['city']['x'], bm['city']['z']))
    moved = bm['historical'] and pal_plan['at'] not in ('palatine', 'domus_flavia', 'center')
    kind = pal_plan['kind'] if not bm['historical'] or moved else p.get('kind', 'classical')
    if moved:
        p['name'] = f"הארמון ({bm['named_labels'].get(pal_plan['at'], pal_plan['at'])})" if 'named_labels' in bm else 'הארמון'
    w, d, h = PALACE_SIZES[kind]
    rot = rot_from_faces(p['faces'])
    pad = grid.at(p['x'], p['z'])
    flatten_rect(grid, p['x'], p['z'], w + 10, d + 34, rot, pad)
    foot.add(p['x'], p['z'], w, d, rot, 3.0, 'palace')
    fx, fz = math.sin(rot), math.cos(rot)
    foot.add(p['x'] + fx * (d / 2 + 14), p['z'] + fz * (d / 2 + 14), 30, 22, rot, 0.0, 'plaza')
    style = plan['style']
    wall = pal_plan['wall_color'] or (style['wall_colors'][0] if style['wall_colors'] else MATERIAL_COLORS.get(style['material'], '#8d8a82'))
    roof_color = pal_plan['roof_color'] or (style['roof_colors'][0] if style['roof_colors'] else ROOF_DEFAULTS.get(style['material'], '#4d5560'))
    roof = pal_plan['roof'] or ('hip' if kind == 'classical' else (style['roof'] if style['roof'] != 'flat' else 'dome'))
    return {'x': round(p['x'], 2), 'z': round(p['z'], 2), 'y': round(grid.at(p['x'], p['z']), 2), 'w': w, 'd': d, 'h': h, 'rot': round(rot, 4), 'kind': kind,
            'name': p.get('name', 'הארמון'), 'wall_color': wall, 'roof_color': roof_color, 'roof': roof, 'door': {'wall': 's', 'width': 3.6, 'height': 4.6}, 'rooms': PALACE_ROOMS}


def road_points(grid, pts, width, rivers, sea, bridges_out, style, carve=True):
    dense = densify([p[:2] for p in pts], 5.0)
    out = []
    k = 0
    while k < len(dense):
        x, z = dense[k]
        if not grid.inside(x, z, 2):
            k += 1
            continue
        if water_at(grid, rivers, sea, x, z) and out:
            j = k
            while j < len(dense) and water_at(grid, rivers, sea, *dense[j]):
                j += 1
            if j < len(dense) and j - k < 30:
                a, b = out[-1], dense[j]
                yb = grid.at(*b)
                deck = max(a[2], yb, (water_surface(rivers, x, z) or a[2]) + 6.0)
                bridges_out.append({'id': f'auto{len(bridges_out)}', 'name': 'גשר', 'style': style, 'a': [a[0], a[1], round(deck, 2)], 'b': [round(b[0], 2), round(b[1], 2), round(deck, 2)],
                                    'width': max(6.0, width + 2), 'water': round(water_surface(rivers, x, z) or 0.0, 2), 'bed': round(grid.at(x, z), 2)})
                grid.pull(a[0], a[1], deck, 3.0, 14.0, 1.0)
                grid.pull(b[0], b[1], deck, 3.0, 14.0, 1.0)
                out.append([round(b[0], 2), round(b[1], 2), round(deck, 2), 2])
            k = j + 1
            continue
        if water_at(grid, rivers, sea, x, z):
            k += 1
            continue
        y = grid.at(x, z)
        if carve:
            grid.pull(x, z, y, width / 2, 3.5, 0.9)
            y = grid.at(x, z)
        flag = 1 if out and out[-1][3] != 2 and abs(y - out[-1][2]) / 5.0 > 0.2 else 0
        out.append([round(x, 2), round(z, 2), round(y, 2), flag])
        k += 1
    return out


def walk(grid, rng, start, heading, steps, step, style, blocked, center, goal=None):
    x, z = start
    pts = [(x, z)]
    for n in range(steps):
        offsets = (0, 90, -90) if style == 'grid' else (-50, -30, -15, 0, 15, 30, 50)
        cands = []
        for off in offsets:
            ang = heading + math.radians(off)
            nx, nz = x + step * math.cos(ang), z + step * math.sin(ang)
            if not grid.inside(nx, nz, 12) or blocked(nx, nz):
                continue
            grade = abs(grid.at(nx, nz) - grid.at(x, z)) / step
            cost = 12 * max(0.0, grade - 0.16) ** 2 + 1.5 * grade + 0.01 * abs(off) + rng.random() * 0.25
            cost += 0.02 * math.hypot(goal[0] - nx, goal[1] - nz) if goal else -0.25 * (((nx - center[0]) * math.cos(ang) + (nz - center[1]) * math.sin(ang)) / (math.hypot(nx - center[0], nz - center[1]) + 1))
            cands.append((cost, ang, nx, nz))
        if not cands:
            break
        _, heading, x, z = min(cands)
        pts.append((x, z))
        if goal and math.hypot(goal[0] - x, goal[1] - z) < step * 1.2:
            pts.append(goal)
            break
    return pts


def build_streets(grid, bm, plan, rng, rivers, sea, foot, palace, landmarks, bridges):
    style = plan['city']['street']
    bstyle = 'arched_stone' if plan['style']['material'] in ('stone', 'marble', 'plaster', 'sandstone', 'brick') else 'wood'
    streets = []
    roads = Spatial(10.0)
    blocked = lambda x, z: foot.hit(x, z, 1.5) or (sea is not None and grid.at(x, z) < sea + 1.0)
    add = lambda pts, width, main, name: streets.append({'pts': pts, 'width': width, 'main': main, 'name': name}) or [roads.add(p[0], p[1], width) for p in pts]
    for r in bm['roads']:
        pts = road_points(grid, r['pts'], r['width'], rivers, sea, bridges, bstyle)
        if len(pts) > 1:
            add(pts, r['width'], r['main'], r['name'])
    c = bm['city']
    center = (c['x'], c['z'])
    if not bm['historical']:
        fx, fz = math.sin(palace['rot']), math.cos(palace['rot'])
        door = (palace['x'] + fx * (palace['d'] / 2 + 26), palace['z'] + fz * (palace['d'] / 2 + 26))
        density = plan['city']['density']
        mains = 4 if density > 0.5 else 3
        base = rng.uniform(0, 6.28)
        for k in range(mains):
            heading = base + k * 2 * math.pi / mains
            start_r = next((r for r in range(14, 90, 4) if not foot.hit(c['x'] + r * math.cos(heading), c['z'] + r * math.sin(heading), 2.0)), 90)
            raw = walk(grid, rng, (c['x'] + start_r * math.cos(heading), c['z'] + start_r * math.sin(heading)), heading, int(c['r'] / 7 * 1.2), 7.0, style,
                       lambda x, z: foot.hit(x, z, 1.5), center)
            pts = road_points(grid, raw, 6.0, rivers, sea, bridges, bstyle)
            if len(pts) > 2:
                add(pts, 6.0, True, f'דרך ראשית {k + 1}')
        if math.hypot(door[0] - c['x'], door[1] - c['z']) > 20:
            raw = walk(grid, rng, door, math.atan2(c['z'] - door[1], c['x'] - door[0]), 120, 6.0, 'winding', lambda x, z: foot.hit(x, z, 1.0) and math.hypot(x - door[0], z - door[1]) > 10, center, center)
            add(road_points(grid, raw, 6.0, rivers, sea, bridges, bstyle), 6.0, True, 'דרך הארמון')
        for m in landmarks:
            if m['kind'] in ('garden', 'forum', 'circus', 'aqueduct'):
                continue
            start = (m['x'] + math.sin(m['rot']) * (m['d'] / 2 + 8), m['z'] + math.cos(m['rot']) * (m['d'] / 2 + 8))
            raw = walk(grid, rng, start, math.atan2(c['z'] - start[1], c['x'] - start[0]), 80, 6.0, 'winding', lambda x, z: foot.hit(x, z, 1.0) and math.hypot(x - start[0], z - start[1]) > 8, center, center)
            pts = road_points(grid, raw, 4.5, rivers, sea, bridges, bstyle)
            if len(pts) > 2:
                add(pts, 4.5, False, m['name'])
    branch_blocked = lambda x, z: blocked(x, z) or water_at(grid, rivers, sea, x, z) or not in_district(bm, x, z)
    for street in list(streets):
        pts = street['pts']
        for k in range(3, len(pts) - 2, 6 if bm['historical'] else 4):
            dist = district_of(bm, pts[k][0], pts[k][1])
            if dist is None or rng.random() > dist['density'] + 0.2 or pts[k][3] == 2:
                continue
            p, q = pts[k], pts[k + 1]
            heading = math.atan2(q[1] - p[1], q[0] - p[0]) + rng.choice([-1, 1]) * math.pi / 2
            raw = walk(grid, rng, (p[0], p[1]), heading, int(rng.uniform(6, 10 + dist['density'] * 14)), 6.0, style, branch_blocked, center)
            if len(raw) > 3:
                add(road_points(grid, raw, 4.0, rivers, sea, bridges, bstyle, True), 4.0, False, '')
    return streets, roads


def district_of(bm, x, z):
    best = None
    for d in bm['districts']:
        dist = math.hypot(x - d['x'], z - d['z'])
        key = (bool(d.get('fallback')), dist / d['r'])
        if dist <= d['r'] and (best is None or key < best[0]):
            best = (key, d)
    return best[1] if best else None


def in_district(bm, x, z):
    return district_of(bm, x, z) is not None


def in_keepout(bm, x, z, r):
    return any(math.hypot(x - k['x'], z - k['z']) < k['r'] + r for k in bm['keepout'])


def merged_style(plan, district):
    base = dict(plan['style'])
    base.update({k: v for k, v in (district.get('style') or {}).items() if v not in (None, [], '')})
    return base


def place_houses(grid, bm, plan, rng, streets, roads, foot, rivers, sea):
    cond = plan['condition']
    houses = []
    index = Spatial(14.0)
    cap = 1900 if bm['historical'] else int(150 + plan['city']['density'] * 450 * (bm['size'] / 600) ** 2)
    for street in streets:
        pts = street['pts']
        carry = 0.0
        for k in range(len(pts) - 1):
            p, q = pts[k], pts[k + 1]
            if p[3] == 2 or q[3] == 2:
                continue
            seg = math.hypot(q[0] - p[0], q[1] - p[1])
            if seg < 0.1:
                continue
            tx, tz = (q[0] - p[0]) / seg, (q[1] - p[1]) / seg
            t = carry
            dist = district_of(bm, p[0], p[1])
            spacing = lerp(13.0, 7.0, dist['density']) if dist else 99.0
            while t < seg:
                for side in (-1, 1):
                    if len(houses) >= cap or dist is None:
                        continue
                    style = merged_style(plan, dist)
                    floors_lo, floors_hi = style['floors']
                    tower = rng.random() < style['towers']
                    insula = floors_hi >= 3 and not tower
                    w = rng.uniform(4.2, 5.2) if tower else rng.uniform(8.0, 14.0) if insula else rng.uniform(5.5, 8.5)
                    d = w if tower else rng.uniform(7.0, 11.0) if insula else rng.uniform(5.0, 8.0)
                    off = street['width'] / 2 + 1.4 + d / 2 + rng.uniform(0.0, 0.8)
                    cx = p[0] + tx * t - tz * side * off
                    cz = p[1] + tz * t + tx * side * off
                    reach = math.hypot(w, d) / 2
                    if not grid.inside(cx, cz, 8) or foot.hit(cx, cz, reach * 0.7) or in_keepout(bm, cx, cz, reach):
                        continue
                    if any(math.hypot(ex - cx, ez - cz) < reach + pl['reach'] + 0.6 for (ex, ez, pl) in index.near(cx, cz, reach + 16.0)):
                        continue
                    if any(math.hypot(rx - cx, rz - cz) < min(w, d) / 2 + wd / 2 + 0.8 for (rx, rz, wd) in roads.near(cx, cz, 12.0)):
                        continue
                    ys = [grid.at(cx + sx * w / 2, cz + sz * d / 2) for sx in (-1, 1) for sz in (-1, 1)]
                    if max(ys) - min(ys) > 7.5 or water_at(grid, rivers, sea, cx, cz) or any(water_at(grid, rivers, sea, cx + sx * w / 2, cz + sz * d / 2) for sx in (-1, 1) for sz in (-1, 1)):
                        continue
                    y0 = sum(ys) / 4
                    floors = rng.randint(max(3, floors_hi), floors_hi + 1) if tower else rng.randint(floors_lo, floors_hi)
                    grid.pull(cx, cz, y0, reach * 0.75, 2.5, 1.0)
                    wall = jitter(rng.choice(style['wall_colors']) if style['wall_colors'] else MATERIAL_COLORS.get(style['material'], '#8d8a82'), 0.07, rng)
                    roof_color = jitter(rng.choice(style['roof_colors']) if style['roof_colors'] else ROOF_DEFAULTS.get(style['material'], '#4d5560'), 0.08, rng)
                    roof = 'pointed' if tower and style['roof'] in ('flat', 'hip') and not insula and style['material'] != 'plaster' else style['roof']
                    if rng.random() < 0.15 and roof not in ('dome', 'flat'):
                        roof = rng.choice(['gable', 'hip']) if roof in ('gable', 'hip') else roof
                    ruin = rng.random() < cond['ruins'] * 0.7
                    houses.append({
                        'id': f'h{len(houses)}', 'x': round(cx, 2), 'z': round(cz, 2), 'y': round(y0, 2), 'rot': round(math.atan2(side * tz, -side * tx), 3),
                        'w': round(w, 2), 'd': round(d, 2), 'floors': int(floors), 'type': 'tower' if tower else ('insula' if insula else 'cottage'),
                        'roof': roof, 'pitch': style['roof_pitch'], 'window': style['window'], 'wall_color': wall, 'roof_color': roof_color,
                        'material': style['material'], 'timber': style['timber'], 'balconies': style['balconies'] and floors > 1, 'arcades': style['arcades'],
                        'chimneys': style['chimneys'], 'shutters': style['shutters'], 'foundation': round(max(0.0, y0 - min(ys)) + 0.5, 2), 'reach': round(reach, 2),
                        'district': dist['id'], 'ruin': ruin, 'vines': round(min(1.0, cond['overgrowth'] * rng.uniform(0.3, 1.4)), 2), 'grime': round(cond['decay'] * rng.uniform(0.5, 1.2), 2),
                    })
                    index.add(cx, cz, {'reach': reach})
                t += spacing + rng.uniform(-1.0, 2.0)
            carry = t - seg
    return houses


def infill_houses(grid, bm, plan, rng, houses, roads, foot, rivers, sea):
    cond = plan['condition']
    cap = 2900 if bm['historical'] else int(220 + plan['city']['density'] * 600 * (bm['size'] / 600) ** 2)
    index = Spatial(14.0)
    for h in houses:
        index.add(h['x'], h['z'], {'reach': h['reach']})
    for dist in bm['districts']:
        step = lerp(20.0, 10.5, dist['density'])
        style = merged_style(plan, dist)
        n = int(dist['r'] * 2 / step)
        for gi in range(n):
            for gj in range(n):
                if len(houses) >= cap:
                    return houses
                x = dist['x'] - dist['r'] + (gi + 0.5) * step + rng.uniform(-step * 0.3, step * 0.3)
                z = dist['z'] - dist['r'] + (gj + 0.5) * step + rng.uniform(-step * 0.3, step * 0.3)
                if math.hypot(x - dist['x'], z - dist['z']) > dist['r'] or rng.random() > dist['density'] * 1.05:
                    continue
                if not grid.inside(x, z, 8) or district_of(bm, x, z) is not dist:
                    continue
                near_roads = roads.near(x, z, 42.0)
                if not near_roads:
                    continue
                rx, rz, _ = min(near_roads, key=lambda r: math.hypot(r[0] - x, r[1] - z))
                lo, hi = style['floors']
                insula = hi >= 3
                w = rng.uniform(8.0, 13.0) if insula else rng.uniform(5.5, 8.5)
                d = rng.uniform(7.0, 10.0) if insula else rng.uniform(5.0, 8.0)
                reach = math.hypot(w, d) / 2
                if foot.hit(x, z, reach * 0.7) or in_keepout(bm, x, z, reach) or water_at(grid, rivers, sea, x, z):
                    continue
                if any(math.hypot(ex - x, ez - z) < reach + pl['reach'] + 0.8 for (ex, ez, pl) in index.near(x, z, reach + 16.0)):
                    continue
                if any(math.hypot(qx - x, qz - z) < min(w, d) / 2 + wd / 2 + 1.0 for (qx, qz, wd) in roads.near(x, z, 12.0)):
                    continue
                ys = [grid.at(x + sx * w / 2, z + sz * d / 2) for sx in (-1, 1) for sz in (-1, 1)]
                if max(ys) - min(ys) > 7.5:
                    continue
                y0 = sum(ys) / 4
                grid.pull(x, z, y0, reach * 0.75, 2.5, 1.0)
                houses.append({
                    'id': f'h{len(houses)}', 'x': round(x, 2), 'z': round(z, 2), 'y': round(y0, 2), 'rot': round(math.atan2(rx - x, rz - z), 3),
                    'w': round(w, 2), 'd': round(d, 2), 'floors': rng.randint(lo, hi), 'type': 'insula' if insula else 'cottage',
                    'roof': style['roof'], 'pitch': style['roof_pitch'], 'window': style['window'],
                    'wall_color': jitter(rng.choice(style['wall_colors']) if style['wall_colors'] else MATERIAL_COLORS.get(style['material'], '#8d8a82'), 0.07, rng),
                    'roof_color': jitter(rng.choice(style['roof_colors']) if style['roof_colors'] else ROOF_DEFAULTS.get(style['material'], '#4d5560'), 0.08, rng),
                    'material': style['material'], 'timber': style['timber'], 'balconies': style['balconies'], 'arcades': style['arcades'] and rng.random() < 0.5,
                    'chimneys': style['chimneys'], 'shutters': style['shutters'], 'foundation': round(max(0.0, y0 - min(ys)) + 0.5, 2), 'reach': round(reach, 2),
                    'district': dist['id'], 'ruin': rng.random() < cond['ruins'] * 0.7, 'vines': round(min(1.0, cond['overgrowth'] * rng.uniform(0.3, 1.4)), 2),
                    'grime': round(cond['decay'] * rng.uniform(0.5, 1.2), 2),
                })
                index.add(x, z, {'reach': reach})
    return houses


FILL_SIZES = {'insula': [(26, 20), (22, 16), (17, 13), (13, 10), (9, 8)], 'domus': [(24, 32), (18, 26), (14, 18), (10, 12)]}


def water_mask(grid, rivers, sea):
    mask = Occupancy(grid.size, 2.5)
    for r in rivers:
        for a, b in zip(r['pts'], r['pts'][1:]):
            mask.mark_segment(a, b, max(a[3], b[3]) / 2 + 0.5)
    return lambda x, z: mask.taken(x, z) or (sea is not None and grid.at(x, z) < sea + 0.6)


def mark_steep(occ, grid, limit=0.55):
    h, n, step = grid.h, grid.n, grid.step
    for j in range(1, n - 1):
        for i in range(1, n - 1):
            k = j * n + i
            slope = math.hypot(h[k + 1] - h[k - 1], h[k + n] - h[k - n]) / (2 * step)
            if slope > limit:
                occ.mark_disc(grid.x_of(i), grid.x_of(j), step * 0.75)


def fill_blocks(grid, bm, plan, rng, houses, streets, landmarks, palace, rivers, sea, water, cap=6500):
    occ = occupancy(grid.size, streets, houses, landmarks, palace, bm['keepout'], water, lambda x, z: 0.0, lambda x, z: grid.inside(x, z, 12))
    for r in rivers:
        for a, b in zip(r['pts'], r['pts'][1:]):
            occ.mark_segment(a, b, max(a[3], b[3]) / 2 + 4.0)
    mark_steep(occ, grid)
    segs = street_segments(streets)
    cond = plan['condition']
    half = grid.size / 2 - 12
    cands = [(x + rng.uniform(-2.5, 2.5), z + rng.uniform(-2.5, 2.5)) for x in [-half + 7 * k for k in range(int(2 * half / 7))] for z in [-half + 7 * k for k in range(int(2 * half / 7))]]
    rng.shuffle(cands)
    added = 0
    for x, z in cands:
        if len(houses) >= cap:
            break
        if occ.taken(x, z):
            continue
        dist = district_of(bm, x, z)
        if dist is None or rng.random() > min(1.0, dist['density'] + 0.1):
            continue
        style = merged_style(plan, dist)
        domus = dist['density'] < 0.5 or rng.random() < 0.08
        near = segs.near(x, z, 70.0)
        if near:
            a, b, _, _ = min(near, key=lambda sg: point_seg(x, z, sg[0][0], sg[0][1], sg[1][0], sg[1][1]))
            dx, dz = b[0] - a[0], b[1] - a[1]
            norm = math.hypot(dx, dz) or 1.0
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dz) / (norm * norm)))
            rot = math.atan2(a[0] + dx * t - x, a[1] + dz * t - z)
        else:
            rot = rng.choice([0.0, math.pi / 2, math.pi, -math.pi / 2]) + rng.uniform(-0.1, 0.1)
        for w, d in FILL_SIZES['domus' if domus else 'insula']:
            w, d = w * rng.uniform(0.92, 1.08), d * rng.uniform(0.92, 1.08)
            if not occ.fits(obox(x, z, w, d, rot, 0.4)):
                continue
            ys = [grid.at(cx, cz) for cx, cz in corners(obox(x, z, w, d, rot))]
            if max(ys) - min(ys) > 6.0:
                continue
            y0 = sum(ys) / 4
            lo, hi = style['floors']
            floors = rng.randint(1, 2) if domus else rng.randint(max(lo, 3), max(hi, 3))
            houses.append({
                'id': f'h{len(houses)}', 'x': round(x, 2), 'z': round(z, 2), 'y': round(y0, 2), 'rot': round(rot, 3), 'w': round(w, 2), 'd': round(d, 2),
                'floors': floors, 'type': 'domus' if domus else 'insula', 'roof': style['roof'], 'pitch': style['roof_pitch'], 'window': style['window'],
                'wall_color': jitter(rng.choice(style['wall_colors']) if style['wall_colors'] else MATERIAL_COLORS.get(style['material'], '#8d8a82'), 0.07, rng),
                'roof_color': jitter(rng.choice(style['roof_colors']) if style['roof_colors'] else ROOF_DEFAULTS.get(style['material'], '#4d5560'), 0.08, rng),
                'material': style['material'], 'timber': style['timber'], 'balconies': style['balconies'] and not domus, 'arcades': style['arcades'] and not domus and rng.random() < 0.6,
                'chimneys': style['chimneys'], 'shutters': style['shutters'], 'foundation': round(max(0.0, y0 - min(ys)) + 0.5, 2), 'reach': round(math.hypot(w, d) / 2, 2),
                'district': dist['id'], 'ruin': rng.random() < cond['ruins'] * 0.7, 'vines': round(min(1.0, cond['overgrowth'] * rng.uniform(0.3, 1.4)), 2),
                'grime': round(cond['decay'] * rng.uniform(0.5, 1.2), 2), 'fill': True,
            })
            occ.mark_box(obox(x, z, w, d, rot, 1.3))
            added += 1
            break
    return houses, added


def scatter_trees(grid, bm, plan, rng, houses, roads, foot, rivers, sea):
    species = plan['nature']['species'] or SPECIES_BY_VEG.get(plan['climate']['vegetation'], ['broadleaf'])
    amount = plan['nature']['trees']
    if not species or amount < 0.02:
        return []
    count = int((80 + amount * 900) * (bm['size'] / 600) ** 2 * (0.32 if bm['historical'] else 1.0))
    count = min(count, 3200)
    hindex = Spatial(16.0)
    for h in houses:
        hindex.add(h['x'], h['z'], h['reach'])
    trees = []
    half = bm['size'] / 2 - 6
    gardens = [m for m in bm['landmarks'] if m['kind'] == 'garden']
    tries = 0
    while len(trees) < count and tries < count * 5:
        tries += 1
        if gardens and rng.random() < 0.18:
            g = rng.choice(gardens)
            x, z = g['x'] + rng.uniform(-g['w'] / 2, g['w'] / 2) * 0.8, g['z'] + rng.uniform(-g['d'] / 2, g['d'] / 2) * 0.8
        else:
            x, z = rng.uniform(-half, half), rng.uniform(-half, half)
        if water_at(grid, rivers, sea, x, z) or grid.slope(x, z) > 0.8:
            continue
        if in_district(bm, x, z) and rng.random() < 0.75:
            continue
        if any(math.hypot(rx - x, rz - z) < wd / 2 + 1.8 for (rx, rz, wd) in roads.near(x, z, 8.0)):
            continue
        if any(math.hypot(hx - x, hz - z) < reach + 1.2 for (hx, hz, reach) in hindex.near(x, z, 14.0)):
            continue
        if foot.hit(x, z, 1.0) and not any(abs(x - g['x']) < g['w'] / 2 and abs(z - g['z']) < g['d'] / 2 for g in gardens):
            continue
        kind = rng.choice(species)
        if kind == 'pine' and plan['climate']['vegetation'] == 'temperate' and grid.at(x, z) < 40 and 'broadleaf' in species:
            kind = 'broadleaf'
        trees.append({'x': round(x, 1), 'z': round(z, 1), 'y': round(grid.at(x, z), 2), 'kind': kind, 's': round(rng.uniform(0.75, 1.3), 2)})
    if plan['condition']['overgrowth'] > 0.3:
        for h in houses:
            if rng.random() < plan['condition']['overgrowth'] * 0.25:
                a = rng.uniform(0, 6.28)
                x, z = h['x'] + math.cos(a) * (h['reach'] + 1.5), h['z'] + math.sin(a) * (h['reach'] + 1.5)
                if not water_at(grid, rivers, sea, x, z):
                    trees.append({'x': round(x, 1), 'z': round(z, 1), 'y': round(grid.at(x, z), 2), 'kind': 'shrub', 's': round(rng.uniform(0.8, 1.6), 2)})
    return trees


def build_walls(grid, bm, plan, houses, streets, rivers, sea):
    if not plan['city']['walls'] or not houses:
        return []
    c = bm['city']
    bins = 48
    radius = [c['r'] * 0.5] * bins
    for h in houses:
        a = math.atan2(h['z'] - c['z'], h['x'] - c['x'])
        k = int((a + math.pi) / (2 * math.pi) * bins) % bins
        radius[k] = max(radius[k], math.hypot(h['x'] - c['x'], h['z'] - c['z']) + 14)
    smooth_r = [max(radius[(k + d) % bins] for d in (-1, 0, 1)) for k in range(bins)]
    pts = []
    for k in range(bins + 1):
        a = (k % bins) / bins * 2 * math.pi - math.pi
        x, z = c['x'] + math.cos(a) * smooth_r[k % bins], c['z'] + math.sin(a) * smooth_r[k % bins]
        pts.append([round(x, 1), round(z, 1)])
    dense = densify(pts, 6.0)
    road_pts = [p for s in streets if s['main'] for p in s['pts']]
    segs = []
    current = []
    for x, z in dense:
        gate = any(math.hypot(px - x, pz - z) < 7 for px, pz, *_ in road_pts)
        bad = not grid.inside(x, z, 4) or water_at(grid, rivers, sea, x, z) or gate
        if bad:
            if len(current) > 2:
                segs.append(current)
            current = []
        else:
            current.append([round(x, 1), round(z, 1), round(grid.at(x, z), 2)])
    if len(current) > 2:
        segs.append(current)
    return [{'pts': s, 'height': 8.5, 'thick': 2.4} for s in segs]


def build_aqueducts(grid, bm):
    out = []
    for a in bm['aqueducts']:
        pts = densify(a['pts'], 8.0)
        top = max(grid.at(x, z) for x, z in pts if grid.inside(x, z, 0)) + 3 if pts else 0
        top = max(top, grid.at(*pts[0]) + a['h']) if grid.inside(*pts[0], 0) else top
        out.append({'id': a['id'], 'name': a['name'], 'top': round(top, 2), 'pts': [[round(x, 1), round(z, 1), round(grid.at(x, z), 2)] for x, z in pts if grid.inside(x, z, 2)]})
    return out


def add_plan_extras(bm, plan, rng):
    if not bm['historical']:
        return bm
    for k, m in enumerate(plan['landmarks']):
        w, d, h = LANDMARK_SIZES[m['kind']]
        x, z = resolve(m['at'], bm, rng, 300.0)
        bm['landmarks'].append({'id': f'extra{k}', 'kind': m['kind'], 'name': m['name'] or HE_KINDS.get(m['kind'], m['kind']), 'x': x + rng.uniform(-20, 20), 'z': z + rng.uniform(-20, 20), 'w': w, 'd': d, 'h': h, 'axis': rng.uniform(0, 180)})
    for k, r in enumerate(plan['water']['rivers']):
        half = bm['size'] / 2
        start, end = edge_point(r['from'], half, rng), edge_point(r['to'], half, rng)
        via = resolve(r['via'], bm, rng, 250.0) if r['via'] != 'center' else (0.0, 0.0)
        bm['rivers'].append({'id': f'river_extra{k}', 'name': f'נהר {k + 2}', 'quays': r['quays'], 'pts': [[x, z, r['width']] for x, z in meander(bezier(start, via, end, 8.0), 6.0, rng)]})
    return bm


def build_decor(grid, bm, plan, rng, rivers, bridges, houses, landmarks):
    boats = []
    for r in rivers:
        pts = r['pts']
        for k in range(6, len(pts) - 6, max(8, len(pts) // 9)):
            p, q = pts[k], pts[k + 1]
            if any(math.hypot(p[0] - (b['a'][0] + b['b'][0]) / 2, p[1] - (b['a'][1] + b['b'][1]) / 2) < 35 for b in bridges):
                continue
            nx, nz = -(q[1] - p[1]), q[0] - p[0]
            norm = math.hypot(nx, nz) or 1.0
            off = rng.uniform(-0.3, 0.3) * p[3]
            boats.append({'x': round(p[0] + nx / norm * off, 1), 'z': round(p[1] + nz / norm * off, 1), 'y': p[2], 'rot': round(math.atan2(q[0] - p[0], q[1] - p[1]) + rng.choice([0, math.pi]), 3),
                          'kind': 'sail' if rng.random() < 0.5 else 'barge', 's': round(rng.uniform(0.8, 1.2), 2)})
    mills = []
    for m in bm.get('mills', []):
        spots = [(m['x'] + r * math.cos(a), m['z'] + r * math.sin(a)) for r in range(0, 60, 4) for a in [k * math.pi / 8 for k in range(16)]]
        spot = next(((x, z) for x, z in spots if grid.at(x, z) < (water_surface(rivers, x, z) or -1e9) - 1.5 and all(grid.at(x + dx, z + dz) < (water_surface(rivers, x, z) or -1e9) - 0.5 for dx, dz in ((6, 0), (-6, 0), (0, 6), (0, -6)))), None)
        frame = river_frame(rivers, *(spot or (m['x'], m['z'])))
        if frame and spot:
            _, p, (fx, fz) = frame
            mills.append({'name': m['name'], 'x': round(spot[0], 1), 'z': round(spot[1], 1), 'y': p[2], 'rot': round(math.atan2(fx, fz), 3)})
    animals = []
    for f in bm.get('flocks', []):
        for _ in range(f['count']):
            a, rr = rng.uniform(0, 6.28), f['r'] * math.sqrt(rng.random())
            x, z = f['x'] + math.cos(a) * rr, f['z'] + math.sin(a) * rr
            if not water_at(grid, rivers, None, x, z):
                animals.append({'x': round(x, 1), 'z': round(z, 1), 'y': round(grid.at(x, z), 2), 'rot': round(rng.uniform(0, 6.28), 2), 'kind': 'goat' if 'עזים' in f['name'] else 'sheep'})
    smoke = [{'x': m['x'], 'z': m['z'], 'y': m['y'] + m['h'], 's': 1.6} for m in landmarks if m['kind'] == 'lime_kiln']
    smoke += [{'x': h['x'], 'z': h['z'], 'y': h['y'] + h['floors'] * 3.0 + 1.0, 's': 0.8} for h in houses if not h['ruin'] and rng.random() < 0.025]
    return {'boats': boats, 'mills': mills, 'animals': animals, 'smoke': smoke[:40]}


def survey_map(plan):
    rng = random.Random(plan['seed'])
    bm = add_plan_extras(basemap_for(plan), plan, rng)
    grid, sea = base_terrain(plan, bm, rng)
    rivers = carve_rivers(grid, bm, plan)
    bridges = build_bridges(grid, bm, rivers)
    foot = Footprints()
    landmarks = place_landmarks(grid, bm, plan, rng, foot, rivers)
    palace = place_palace(grid, bm, plan, rng, foot)
    for b in bridges:
        foot.add((b['a'][0] + b['b'][0]) / 2, (b['a'][1] + b['b'][1]) / 2, b['width'] + 2, math.hypot(b['b'][0] - b['a'][0], b['b'][1] - b['a'][1]),
                 math.atan2(b['b'][0] - b['a'][0], b['b'][1] - b['a'][1]), 1.0, 'bridge')
    streets, _ = build_streets(grid, bm, plan, rng, rivers, sea, foot, palace, landmarks, bridges)
    water = water_mask(grid, rivers, sea)
    streets, routing = route_around(streets, landmarks, palace, grid, water)
    roads = Spatial(10.0)
    for st in streets:
        for pt in st['pts']:
            roads.add(pt[0], pt[1], st['width'])
    houses = place_houses(grid, bm, plan, rng, streets, roads, foot, rivers, sea)
    houses = infill_houses(grid, bm, plan, rng, houses, roads, foot, rivers, sea)
    filled = 0
    if bm['historical'] and plan['city']['density'] >= 0.8:
        houses, filled = fill_blocks(grid, bm, plan, rng, houses, streets, landmarks, palace, rivers, sea, water)
    walls = build_walls(grid, bm, plan, houses, streets, rivers, sea)
    aqueducts = build_aqueducts(grid, bm)
    trees = scatter_trees(grid, bm, plan, rng, houses, roads, foot, rivers, sea)
    houses, trees, fixed, remaining = repair(streets, houses, landmarks, palace, trees, water)
    for k, h in enumerate(houses):
        h['id'] = f'h{k}'
    palace['y'] = round(grid.at(palace['x'], palace['z']), 2)
    site = {'plan': plan, 'bm': bm, 'grid': grid, 'sea': sea, 'rivers': rivers, 'bridges': bridges, 'streets': streets, 'houses': houses, 'trees': trees,
            'palace': palace, 'landmarks': landmarks, 'walls': walls, 'aqueducts': aqueducts, 'rng': rng,
            'report': {'version': 1, 'rerouted_streets': routing['rerouted'], 'cut_streets': routing['cut'], 'filled_buildings': filled, **fixed,
                       'remaining_conflicts': remaining, 'clean': not any(remaining.values())}}
    return site


def build_scene(site):
    plan, bm, grid, sea, rng = site['plan'], site['bm'], site['grid'], site['sea'], site['rng']
    rivers, bridges, streets, houses, trees = site['rivers'], site['bridges'], site['streets'], site['houses'], site['trees']
    palace, landmarks, walls, aqueducts = site['palace'], site['landmarks'], site['walls'], site['aqueducts']
    decor = build_decor(grid, bm, plan, rng, rivers, bridges, houses, landmarks)
    flat = [round(h, 2) for h in grid.h]
    labels = ([{'name': h['name'], 'x': round(h['x'], 1), 'z': round(h['z'], 1), 'kind': 'hill'} for h in bm['hills']]
              + [{'name': m['name'], 'x': m['x'], 'z': m['z'], 'kind': m['kind']} for m in landmarks]
              + [{'name': b['name'], 'x': round((b['a'][0] + b['b'][0]) / 2, 1), 'z': round((b['a'][1] + b['b'][1]) / 2, 1), 'kind': 'bridge'} for b in bridges if not b['id'].startswith('auto')]
              + [{'name': r['name'], 'x': r['pts'][len(r['pts']) // 3][0], 'z': r['pts'][len(r['pts']) // 3][1], 'kind': 'river'} for r in rivers]
              + [{'name': i['name'], 'x': round(i['x'], 1), 'z': round(i['z'], 1), 'kind': 'island'} for i in bm['islands']]
              + [{'name': a['name'], 'x': a['pts'][len(a['pts']) // 2][0], 'z': a['pts'][len(a['pts']) // 2][1], 'kind': 'aqueduct'} for a in aqueducts if a['pts']]
              + [{'name': m['name'], 'x': m['x'], 'z': m['z'], 'kind': 'mill'} for m in decor['mills']]
              + [{'name': palace['name'], 'x': palace['x'], 'z': palace['z'], 'kind': 'palace'}])
    return {
        'version': 2, 'size': grid.size, 'n': grid.n, 'heights': flat, 'sea_level': sea, 'lakes': [], 'rivers': rivers, 'bridges': bridges,
        'streets': [{'main': s['main'], 'width': s['width'], 'name': s['name'], 'pts': s['pts']} for s in streets],
        'houses': houses, 'trees': trees, 'palace': palace, 'landmarks': landmarks, 'walls': walls, 'aqueducts': aqueducts, 'decor': decor,
        'districts': [{'id': d['id'], 'name': d['name'], 'x': round(d['x'], 1), 'z': round(d['z'], 1), 'r': d['r'], 'density': d['density']} for d in bm['districts']],
        'styles': {'window': plan['style']['window'], 'material': plan['style']['material'], 'ornament': [], 'snow_roofs': plan['climate']['snow_roofs']},
        'climate': plan['climate'], 'mood': plan['mood'], 'time_of_day': plan['time_of_day'], 'condition': plan['condition'], 'terrain_kind': plan['terrain']['kind'],
        'basemap': {'id': bm['id'], 'name': bm['name'], 'historical': bm['historical'], 'origin': bm['origin'], 'sources': bm['sources'], 'labels': labels},
        'stats': {'houses': len(houses), 'streets': len(streets), 'trees': len(trees), 'landmarks': len(landmarks), 'bridges': len(bridges),
                  'ruins': sum(1 for h in houses if h['ruin']), 'min_h': min(flat), 'max_h': max(flat)},
        'map': site['report'],
    }


def generate(plan):
    return build_scene(survey_map(plan))
