import math
import random

from .lexicon import MATERIAL_COLORS
from .terrain import SIZE, build_heights, carve_lakes, carve_river, choose_center, lerp

ROOF_DEFAULTS = {
    'stone': '#4d5560', 'wood': '#6b4a2f', 'sandstone': '#a85c3a', 'marble': '#3f6fa0',
    'brick': '#7a3b2a', 'ice': '#9fd2e6', 'dark_stone': '#2d2d36', 'plaster': '#b4553a',
}

PALACE_ROOMS = [
    {'id': 'entrance', 'name': 'אולם כניסה', 'cx': 0.0, 'cz': 0.0, 'w': 14.0, 'd': 10.0, 'h': 6.0,
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 3.4, 'exit': True}, {'wall': 'n', 'pos': 0.0, 'width': 3.4}]},
    {'id': 'great_hall', 'name': 'האולם הגדול', 'cx': 0.0, 'cz': -15.4, 'w': 18.0, 'd': 20.0, 'h': 8.0,
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 3.4}, {'wall': 'n', 'pos': 0.0, 'width': 3.4}]},
    {'id': 'chamber', 'name': 'החדר המלכותי', 'cx': 0.0, 'cz': -31.8, 'w': 12.0, 'd': 12.0, 'h': 5.5,
     'doors': [{'wall': 's', 'pos': 0.0, 'width': 3.4}]},
]


def jitter(hex_color, amount, rng):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    f = 1.0 + rng.uniform(-amount, amount)
    mix = lambda c: max(0, min(255, int(c * f)))
    return '#%02x%02x%02x' % (mix(r), mix(g), mix(b))


def default_room_design(room, spec):
    arch = spec['architecture']
    material = arch['material']
    wall_color = arch['wall_color'] or MATERIAL_COLORS.get(material, '#8d8a82')
    wall_material = material if material in ('stone', 'wood', 'marble', 'brick', 'plaster') else 'stone'
    return {
        'id': room['id'], 'name': room['name'], 'w': room['w'], 'd': room['d'], 'h': room['h'],
        'floor': {'material': 'stone', 'color': '#7d7a74'},
        'walls': {'material': wall_material, 'color': wall_color},
        'ceiling': {'style': 'flat', 'color': '#cfc8b8'},
        'windows': {'style': arch['window'], 'size': 'normal', 'count': 2, 'color': '#e8d9a8', 'stained': False},
        'light': {'tone': 'neutral', 'intensity': 1.0},
        'items': [],
    }


class Spatial:
    def __init__(self, cell=12.0):
        self.cell = cell
        self.cells = {}

    def key(self, x, z):
        return (int(math.floor(x / self.cell)), int(math.floor(z / self.cell)))

    def add(self, x, z, payload):
        self.cells.setdefault(self.key(x, z), []).append((x, z, payload))

    def near(self, x, z, r):
        kx, kz = self.key(x, z)
        span = int(math.ceil(r / self.cell))
        return [(px, pz, pl) for dx in range(-span, span + 1) for dz in range(-span, span + 1)
                for (px, pz, pl) in self.cells.get((kx + dx, kz + dz), []) if math.hypot(px - x, pz - z) <= r]


def road_params(spec):
    density = spec['urban']['density']
    return {'step': 7.0, 'main': 4 if density > 0.5 else 2, 'length': int(26 + density * 26)}


def walk_road(grid, info, spec, rng, roads, start, heading, steps, step, style, bridges, center):
    sea = info['sea_level']
    x, z = start
    pts = [[x, z, grid.at(x, z), 0]]
    for n in range(steps):
        cands = []
        offsets = [0, 90, -90, 180] if style == 'grid' else [-60, -45, -30, -15, 0, 15, 30, 45, 60]
        for off in offsets:
            ang = heading + math.radians(off)
            if style == 'grid':
                ang = round(ang / (math.pi / 2)) * (math.pi / 2)
            nx, nz = x + step * math.cos(ang), z + step * math.sin(ang)
            if not grid.inside(nx, nz, 10):
                continue
            ny = grid.at(nx, nz)
            if sea is not None and ny < sea + 1.0:
                continue
            if any(math.hypot(nx - px, nz - pz) < 4.5 for (px, pz, _) in roads.near(nx, nz, 5.0) if (px, pz) not in [(p[0], p[1]) for p in pts[-8:]]):
                continue
            grade = abs(ny - pts[-1][2]) / step
            cost = 14 * max(0.0, grade - 0.18) ** 2 + 2.0 * grade + 0.015 * abs(off) + rng.random() * 0.3
            outward = ((nx - center[0]) * math.cos(ang) + (nz - center[1]) * math.sin(ang)) / (math.hypot(nx - center[0], nz - center[1]) + 1)
            cost -= 0.35 * outward
            if style == 'winding' and n % 4 < 2:
                cost += 0.05 * abs(off - 25 * math.sin(n * 0.9))
            cands.append((cost, ang, nx, nz, ny))
        if not cands:
            break
        _, ang, nx, nz, ny = min(cands)
        bridge = None
        if bridges and rng.random() < 0.6:
            bridge = find_bridge(grid, info, pts[-1], ang, step)
        if bridge:
            for bx, bz, by in bridge:
                pts.append([bx, bz, by, 2])
                roads.add(bx, bz, 'bridge')
            x, z = bridge[-1][0], bridge[-1][1]
            heading = ang
            continue
        grid.pull(nx, nz, ny, 1.8, 4.2, 0.95)
        ny = grid.at(nx, nz)
        flag = 1 if abs(ny - pts[-1][2]) / step > 0.22 else 0
        pts.append([nx, nz, ny, flag])
        roads.add(nx, nz, 'road')
        x, z, heading = nx, nz, ang
    return pts


def find_bridge(grid, info, last, ang, step):
    sea = info['sea_level']
    y0 = last[2]
    for span in (14.0, 21.0, 28.0):
        tx, tz = last[0] + span * math.cos(ang), last[1] + span * math.sin(ang)
        if not grid.inside(tx, tz, 10):
            return None
        ty = grid.at(tx, tz)
        if sea is not None and ty < sea + 1.0:
            continue
        if abs(ty - y0) > 5.0 or grid.slope(tx, tz) > 0.6:
            continue
        low = min(grid.at(last[0] + t * (tx - last[0]), last[1] + t * (tz - last[1])) for t in (0.25, 0.5, 0.75))
        if y0 - low < 3.5:
            continue
        n = int(span / 3.5)
        return [(lerp(last[0], tx, k / n), lerp(last[1], tz, k / n), lerp(y0, ty, k / n)) for k in range(1, n + 1)]
    return None


def build_roads(grid, info, spec, rng, center):
    params = road_params(spec)
    style = spec['urban']['street']
    bridges = spec['urban']['bridges']
    roads = Spatial(8.0)
    streets = []
    base = rng.uniform(0, math.pi * 2)
    start_r = 17.0
    for k in range(params['main']):
        heading = base + k * (2 * math.pi / params['main'])
        if style == 'grid':
            heading = round(heading / (math.pi / 2)) * (math.pi / 2)
        sx, sz = center[0] + start_r * math.cos(heading), center[1] + start_r * math.sin(heading)
        if not grid.inside(sx, sz, 12):
            continue
        pts = walk_road(grid, info, spec, rng, roads, (sx, sz), heading, params['length'], params['step'], style, bridges, center)
        streets.append({'pts': pts, 'main': True})
    density = spec['urban']['density']
    for street in list(streets):
        for idx in range(4, len(street['pts']) - 3, 4):
            if rng.random() > density + 0.25:
                continue
            p, q = street['pts'][idx], street['pts'][idx + 1]
            heading = math.atan2(q[1] - p[1], q[0] - p[0]) + rng.choice([-1, 1]) * math.pi / 2
            pts = walk_road(grid, info, spec, rng, roads, (p[0], p[1]), heading, int(rng.uniform(7, 8 + density * 12)), params['step'] * 0.85, style, False, center)
            if len(pts) > 2:
                streets.append({'pts': [list(p)] + pts[1:], 'main': False})
    if style == 'radial':
        for radius in (30.0, 52.0):
            ring = []
            for a in range(0, 360, 12):
                x, z = center[0] + radius * math.cos(math.radians(a)), center[1] + radius * math.sin(math.radians(a))
                if grid.inside(x, z, 10) and grid.slope(x, z) < 0.35 and (info['sea_level'] is None or grid.at(x, z) > info['sea_level'] + 1.0):
                    grid.pull(x, z, grid.at(x, z), 1.6, 3.5, 0.9)
                    ring.append([x, z, grid.at(x, z), 0])
                    roads.add(x, z, 'road')
                elif len(ring) > 2:
                    streets.append({'pts': ring, 'main': False})
                    ring = []
                else:
                    ring = []
            if len(ring) > 2:
                streets.append({'pts': ring, 'main': False})
    return streets, roads


def roof_for(spec, rng):
    base = spec['architecture']['roof']
    return base if rng.random() < 0.8 else ('gable' if base != 'gable' else 'pointed')


def place_houses(grid, info, spec, rng, streets, roads, center):
    arch = spec['architecture']
    density = spec['urban']['density']
    sea = info['sea_level']
    wall_base = arch['wall_color'] or MATERIAL_COLORS.get(arch['material'], '#8d8a82')
    roof_base = arch['roof_color'] or ROOF_DEFAULTS.get(arch['material'], '#4d5560')
    houses = []
    index = Spatial(14.0)
    spacing = lerp(11.0, 6.5, density)
    max_houses = int(60 + density * 230)
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
            while t < seg:
                for side in (-1, 1):
                    if len(houses) >= max_houses:
                        return houses
                    type_roll = rng.random()
                    tower = density > 0.5 and type_roll < 0.12
                    w = rng.uniform(4.0, 5.0) if tower else rng.uniform(5.0, 8.2)
                    d = w if tower else rng.uniform(5.0, 8.0)
                    off = 3.6 + d / 2 + rng.uniform(0.0, 1.2)
                    cx = p[0] + tx * t - tz * side * off
                    cz = p[1] + tz * t + tx * side * off
                    reach = math.hypot(w, d) / 2
                    dist_center = math.hypot(cx - center[0], cz - center[1])
                    if dist_center < 22 or not grid.inside(cx, cz, 8):
                        continue
                    if any(math.hypot(ex - cx, ez - cz) < reach + pl['reach'] + 0.8 for (ex, ez, pl) in index.near(cx, cz, reach + 12.0)):
                        continue
                    if any(math.hypot(rx - cx, rz - cz) < min(w, d) / 2 + 2.4 for (rx, rz, _) in roads.near(cx, cz, 9.0)):
                        continue
                    ys = [grid.at(cx + sx * w / 2, cz + sz * d / 2) for sx in (-1, 1) for sz in (-1, 1)]
                    y0 = sum(ys) / 4
                    if max(ys) - min(ys) > 8.0 or min(ys) < (sea if sea is not None else -1e9) + 0.5:
                        continue
                    floors = 3 + (1 if rng.random() < 0.4 else 0) if tower else 1 + (rng.random() < 0.35) + (rng.random() < 0.15 and density > 0.5 and dist_center < 70)
                    grid.pull(cx, cz, y0, reach * 0.8, 3.0, 1.0)
                    house = {
                        'id': f'h{len(houses)}', 'x': round(cx, 2), 'z': round(cz, 2), 'y': round(y0, 2),
                        'rot': round(math.atan2(side * tz, -side * tx), 3),
                        'w': round(w, 2), 'd': round(d, 2), 'floors': int(floors), 'type': 'tower' if tower else 'cottage',
                        'roof': 'pointed' if tower and arch['roof'] == 'flat' else roof_for(spec, rng),
                        'wall_color': jitter(wall_base, 0.08, rng), 'roof_color': jitter(roof_base, 0.1, rng),
                        'foundation': round(max(0.0, y0 - min(ys)) + 0.6, 2), 'reach': round(reach, 2),
                    }
                    houses.append(house)
                    index.add(cx, cz, {'reach': reach})
                t += spacing + rng.uniform(-1.5, 2.5)
            carry = t - seg
    return houses


def scatter_trees(grid, info, spec, rng, houses, roads, center):
    veg = spec['climate']['vegetation']
    amount = spec['nature']['trees']
    sea = info['sea_level']
    if veg == 'none' or amount <= 0.02:
        return []
    count = int(60 + amount * 520)
    hindex = Spatial(14.0)
    for h in houses:
        hindex.add(h['x'], h['z'], h['reach'])
    trees = []
    for _ in range(count * 3):
        if len(trees) >= count:
            break
        x, z = rng.uniform(-SIZE / 2 + 6, SIZE / 2 - 6), rng.uniform(-SIZE / 2 + 6, SIZE / 2 - 6)
        y = grid.at(x, z)
        if math.hypot(x - center[0], z - center[1]) < 24 or grid.slope(x, z) > 0.75:
            continue
        if sea is not None and y < sea + 0.8:
            continue
        if any(math.hypot(rx - x, rz - z) < 3.5 for (rx, rz, _) in roads.near(x, z, 4.0)):
            continue
        if any(math.hypot(hx - x, hz - z) < reach + 2.0 for (hx, hz, reach) in hindex.near(x, z, 12.0)):
            continue
        kind = {'tropical': 'palm', 'alpine': 'pine', 'desert': 'shrub', 'temperate': 'broadleaf' if y < 60 else 'pine'}[veg]
        if veg == 'tropical' and sea is None and rng.random() < 0.3:
            kind = 'broadleaf'
        if veg in ('alpine', 'temperate') and y > 105:
            continue
        trees.append({'x': round(x, 1), 'z': round(z, 1), 'y': round(y, 2), 'kind': kind, 's': round(rng.uniform(0.75, 1.35), 2)})
    return trees


def generate_scene(spec):
    rng = random.Random(spec['seed'])
    grid, info = build_heights(spec, rng)
    center = choose_center(grid, info, spec, rng)
    info['center'] = center
    palace_y = grid.at(center[0], center[1])
    grid.pull(center[0], center[1], palace_y, 26.0, 34.0, 1.0)
    palace_y = grid.at(center[0], center[1])
    carve_lakes(grid, info, spec, rng)
    rivers = carve_river(grid, info, spec, rng)
    streets, roads = build_roads(grid, info, spec, rng, center)
    houses = place_houses(grid, info, spec, rng, streets, roads, center)
    trees = scatter_trees(grid, info, spec, rng, houses, roads, center)
    arch = spec['architecture']
    palace_wall = arch['wall_color'] or MATERIAL_COLORS.get(arch['material'], '#8d8a82')
    palace = {
        'x': round(center[0], 2), 'z': round(center[1], 2), 'y': round(palace_y, 2), 'w': 26.0, 'd': 20.0, 'h': 13.0,
        'wall_color': palace_wall, 'roof_color': arch['roof_color'] or ROOF_DEFAULTS.get(arch['material'], '#4d5560'),
        'roof': arch['roof'] if arch['roof'] != 'flat' else 'dome', 'door': {'wall': 's', 'width': 3.6, 'height': 4.6},
        'rooms': PALACE_ROOMS,
    }
    flat = [round(h, 2) for h in grid.h]
    streets_out = [{'main': s['main'], 'pts': [[round(p[0], 1), round(p[1], 1), round(p[2], 2), p[3]] for p in s['pts']]} for s in streets if len(s['pts']) > 1]
    return {
        'size': SIZE, 'n': grid.n, 'heights': flat, 'sea_level': info['sea_level'], 'lakes': info['lakes'], 'rivers': rivers,
        'streets': streets_out, 'houses': houses, 'trees': trees, 'palace': palace,
        'styles': {'window': arch['window'], 'material': arch['material'], 'ornament': arch['ornament'], 'snow_roofs': spec['climate']['snow_roofs']},
        'climate': spec['climate'], 'mood': spec['mood'], 'terrain_kind': info['kind'],
        'stats': {'houses': len(houses), 'street_points': sum(len(s['pts']) for s in streets_out), 'trees': len(trees),
                  'stairs': sum(1 for s in streets_out for p in s['pts'] if p[3] == 1), 'bridge_points': sum(1 for s in streets_out for p in s['pts'] if p[3] == 2),
                  'min_h': min(flat), 'max_h': max(flat)},
    }
