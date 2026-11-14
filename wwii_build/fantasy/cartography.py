import math
from html import escape

PASSABLE = {'forum', 'garden', 'triumphal_arch', 'vegetable_garden'}
STEP = 5.0


def box(x, z, w, d, rot, margin=0.0):
    return (x, z, w / 2 + margin, d / 2 + margin, rot)


def to_local(o, x, z):
    c, s = math.cos(o[4]), math.sin(o[4])
    dx, dz = x - o[0], z - o[1]
    return dx * c - dz * s, dx * s + dz * c


def to_world(o, lx, lz):
    c, s = math.cos(o[4]), math.sin(o[4])
    return o[0] + lx * c + lz * s, o[1] - lx * s + lz * c


def corners(o):
    return [to_world(o, sx * o[2], sz * o[3]) for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def inside(o, x, z):
    lx, lz = to_local(o, x, z)
    return abs(lx) <= o[2] and abs(lz) <= o[3]


def point_rect(px, pz, hw, hd):
    return math.hypot(max(0.0, abs(px) - hw), max(0.0, abs(pz) - hd))


def point_seg(px, pz, ax, az, bx, bz):
    dx, dz = bx - ax, bz - az
    l2 = dx * dx + dz * dz
    t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / l2))
    return math.hypot(px - ax - t * dx, pz - az - t * dz)


def seg_hits_rect(ax, az, bx, bz, hw, hd):
    t0, t1 = 0.0, 1.0
    dx, dz = bx - ax, bz - az
    for p, q in ((-dx, ax + hw), (dx, hw - ax), (-dz, az + hd), (dz, hd - az)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def seg_box_dist(o, a, b):
    ax, az = to_local(o, a[0], a[1])
    bx, bz = to_local(o, b[0], b[1])
    if seg_hits_rect(ax, az, bx, bz, o[2], o[3]):
        return 0.0
    hw, hd = o[2], o[3]
    return min(point_rect(ax, az, hw, hd), point_rect(bx, bz, hw, hd), *(point_seg(cx, cz, ax, az, bx, bz) for cx, cz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))))


def overlap(o1, o2):
    c1, c2 = corners(o1), corners(o2)
    for o in (o1, o2):
        for ax, az in ((math.cos(o[4]), -math.sin(o[4])), (math.sin(o[4]), math.cos(o[4]))):
            p1 = [x * ax + z * az for x, z in c1]
            p2 = [x * ax + z * az for x, z in c2]
            if max(p1) <= min(p2) or max(p2) <= min(p1):
                return False
    return True


class Index:
    def __init__(self, cell=24.0):
        self.cell = cell
        self.cells = {}

    def keys(self, x, z, r):
        k0, k1 = int(math.floor((x - r) / self.cell)), int(math.floor((x + r) / self.cell))
        j0, j1 = int(math.floor((z - r) / self.cell)), int(math.floor((z + r) / self.cell))
        return [(i, j) for i in range(k0, k1 + 1) for j in range(j0, j1 + 1)]

    def add(self, x, z, r, item):
        for k in self.keys(x, z, r):
            self.cells.setdefault(k, []).append(item)

    def near(self, x, z, r):
        seen = {}
        for k in self.keys(x, z, r):
            for it in self.cells.get(k, []):
                seen[id(it)] = it
        return list(seen.values())


def solid(m):
    return m['kind'] not in PASSABLE and m.get('h', 1) > 0


def obstacles(landmarks, palace, margin=1.0):
    out = [(box(m['x'], m['z'], m['w'], m['d'], m['rot'], margin), m['id']) for m in landmarks if solid(m)]
    return out + [(box(palace['x'], palace['z'], palace['w'], palace['d'], palace['rot'], margin), 'palace')]


def perimeter_point(hw, hd, lx, lz):
    cx, cz = max(-hw, min(hw, lx)), max(-hd, min(hd, lz))
    gaps = [(hw - cx, 0), (cx + hw, 2), (hd - cz, 1), (cz + hd, 3)] if abs(cx) < hw and abs(cz) < hd else []
    if gaps:
        side = min(gaps)[1]
        cx, cz = (hw, cz) if side == 0 else (-hw, cz) if side == 2 else (cx, hd) if side == 1 else (cx, -hd)
    if abs(cz + hd) < 1e-6:
        return cx + hw
    if abs(cx - hw) < 1e-6:
        return 2 * hw + cz + hd
    if abs(cz - hd) < 1e-6:
        return 2 * hw + 2 * hd + hw - cx
    return 4 * hw + 2 * hd + hd - cz


def perimeter_xy(hw, hd, t):
    total = 4 * (hw + hd)
    t %= total
    if t < 2 * hw:
        return -hw + t, -hd
    t -= 2 * hw
    if t < 2 * hd:
        return hw, -hd + t
    t -= 2 * hd
    if t < 2 * hw:
        return hw - t, hd
    t -= 2 * hw
    return -hw, hd - t


def walk_around(o, a, b):
    hw, hd = o[2], o[3]
    total = 4 * (hw + hd)
    ta = perimeter_point(hw, hd, *to_local(o, a[0], a[1]))
    tb = perimeter_point(hw, hd, *to_local(o, b[0], b[1]))
    fwd = (tb - ta) % total
    span, sign = (fwd, 1) if fwd <= total - fwd else (total - fwd, -1)
    marks = sorted({0.0, span, *[((c - ta) * sign) % total for c in (0, 2 * hw, 2 * hw + 2 * hd, 4 * hw + 2 * hd)]})
    marks = [m for m in marks if m <= span]
    pts = []
    for m0, m1 in zip(marks, marks[1:]):
        n = max(1, int(math.ceil((m1 - m0) / STEP)))
        pts += [to_world(o, *perimeter_xy(hw, hd, ta + sign * (m0 + (m1 - m0) * k / n))) for k in range(n)]
    pts.append(to_world(o, *perimeter_xy(hw, hd, ta + sign * span)))
    return pts


def route_around(streets, landmarks, palace, grid, water):
    blocks = obstacles(landmarks, palace, 0.0)
    report = {'rerouted': 0, 'cut': 0}
    out = []
    for street in streets:
        pts = [list(p) for p in street['pts']]
        margin = street['width'] / 2 + 1.2
        for o, oid in blocks * 4:
            if not pts:
                break
            big = (o[0], o[1], o[2] + margin, o[3] + margin, o[4])
            reach = math.hypot(big[2], big[3])
            if not any(math.hypot(p[0] - o[0], p[1] - o[1]) < reach + STEP for p in pts):
                continue
            hit = [k for k in range(len(pts)) if inside(big, pts[k][0], pts[k][1]) or (k + 1 < len(pts) and seg_box_dist(big, pts[k], pts[k + 1]) == 0.0 and pts[k][3] != 2 and pts[k + 1][3] != 2)]
            if not hit:
                continue
            i0, i1 = hit[0], min(len(pts) - 1, hit[-1] + 1)
            while i1 < len(pts) - 1 and inside(big, pts[i1][0], pts[i1][1]):
                i1 += 1
            if i0 == 0 or inside(big, pts[i1][0], pts[i1][1]) or any(p[3] == 2 for p in pts[i0:i1 + 1]):
                keep = pts[:i0] if i0 > 0 else pts[i1 + 1:] if i1 < len(pts) - 1 and not inside(big, pts[-1][0], pts[-1][1]) else []
                pts = keep if len(keep) >= 2 else []
                report['cut'] += 1
                if not pts:
                    break
                continue
            a, b = pts[i0 - 1], pts[i1]
            ring = (o[0], o[1], o[2] + margin + 0.5, o[3] + margin + 0.5, o[4])
            path = walk_around(ring, a, b)
            if any(water(x, z) for x, z in path):
                pts = pts[:i0] if i0 >= 2 else []
                report['cut'] += 1
                if not pts:
                    break
                continue
            pts = pts[:i0] + [[round(x, 2), round(z, 2), round(grid.at(x, z), 2), 0] for x, z in path[1:-1]] + pts[i1:]
            report['rerouted'] += 1
        bad = set()
        for o, _ in blocks:
            big = (o[0], o[1], o[2] + street['width'] / 2 + 0.6, o[3] + street['width'] / 2 + 0.6, o[4])
            for k in range(len(pts)):
                if inside(big, pts[k][0], pts[k][1]) or (k + 1 < len(pts) and pts[k][3] != 2 and pts[k + 1][3] != 2 and seg_box_dist(big, pts[k], pts[k + 1]) == 0.0 and not (inside(big, pts[k][0], pts[k][1]))):
                    bad.update({k} if inside(big, pts[k][0], pts[k][1]) else {k, k + 1})
        runs, run = [], []
        for k, p in enumerate(pts):
            if k in bad:
                runs.append(run)
                run = []
            else:
                run.append(p)
        runs.append(run)
        pieces = [r for r in runs if len(r) >= 2]
        report['cut'] += len(pieces) - 1 if bad else 0
        out += [{**street, 'pts': r} for r in pieces]
    return out, report


def street_segments(streets):
    idx = Index(24.0)
    for si, s in enumerate(streets):
        for k in range(len(s['pts']) - 1):
            a, b = s['pts'][k], s['pts'][k + 1]
            if a[3] == 2 or b[3] == 2:
                continue
            seg = (a, b, s['width'] / 2, si)
            mx, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            idx.add(mx, mz, math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + s['width'] / 2, seg)
    return idx


def house_box(h, margin=0.0):
    return box(h['x'], h['z'], h['w'], h['d'], h['rot'], margin)


def conflicts(streets, houses, landmarks, palace, trees, water):
    segs = street_segments(streets)
    solids = obstacles(landmarks, palace, 0.0)
    hidx = Index(24.0)
    boxes = {}
    for h in houses:
        o = house_box(h)
        boxes[h['id']] = o
        hidx.add(h['x'], h['z'], math.hypot(o[2], o[3]), (h['id'], o))
    found = {'street_through_building': [], 'building_on_building': [], 'building_in_water': [], 'building_in_monument': [], 'tree_in_building': []}
    for o, oid in solids:
        for a, b, half, si in segs.near(o[0], o[1], math.hypot(o[2], o[3])):
            if seg_box_dist(o, a, b) < half - 0.25:
                found['street_through_building'].append((si, oid))
    for h in houses:
        o = boxes[h['id']]
        r = math.hypot(o[2], o[3])
        for a, b, half, si in segs.near(h['x'], h['z'], r):
            if seg_box_dist(o, a, b) < half + 0.2:
                found['street_through_building'].append((si, h['id']))
                break
        for oid, other in hidx.near(h['x'], h['z'], r):
            if oid > h['id'] and overlap(o, other):
                found['building_on_building'].append((h['id'], oid))
        if any(water(x, z) for x, z in corners(o) + [(h['x'], h['z'])]):
            found['building_in_water'].append(h['id'])
        if any(math.hypot(m[0] - h['x'], m[1] - h['z']) < r + math.hypot(m[2], m[3]) and overlap(o, m) for m, _ in solids):
            found['building_in_monument'].append(h['id'])
    for k, t in enumerate(trees):
        if any(inside(o, t['x'], t['z']) for _, o in hidx.near(t['x'], t['z'], 30.0)) or any(inside(m, t['x'], t['z']) for m, _ in solids) or \
                any(point_seg(t['x'], t['z'], a[0], a[1], b[0], b[1]) < half + 0.6 for a, b, half, _ in segs.near(t['x'], t['z'], 12.0)):
            found['tree_in_building'].append(k)
    return found


def repair(streets, houses, landmarks, palace, trees, water):
    fixed = {'houses_removed': 0, 'trees_removed': 0}
    for _ in range(3):
        found = conflicts(streets, houses, landmarks, palace, trees, water)
        ids = {h['id'] for h in houses}
        bad_houses = {hid for _, hid in found['street_through_building'] if hid in ids}
        bad_houses |= {b for _, b in found['building_on_building']} | set(found['building_in_water']) | set(found['building_in_monument'])
        bad_trees = set(found['tree_in_building'])
        if not bad_houses and not bad_trees:
            break
        houses = [h for h in houses if h['id'] not in bad_houses]
        trees = [t for k, t in enumerate(trees) if k not in bad_trees]
        fixed['houses_removed'] += len(bad_houses)
        fixed['trees_removed'] += len(bad_trees)
    final = conflicts(streets, houses, landmarks, palace, trees, water)
    return houses, trees, fixed, {k: len(v) for k, v in final.items()}


class Occupancy:
    def __init__(self, size, cell=2.5, ox=0.0, oz=0.0):
        self.size = size
        self.cell = cell
        self.ox = ox
        self.oz = oz
        self.n = int(math.ceil(size / cell))
        self.bits = bytearray(self.n * self.n)

    def ij(self, x, z):
        return int(math.floor((x - self.ox + self.size / 2) / self.cell)), int(math.floor((z - self.oz + self.size / 2) / self.cell))

    def taken(self, x, z):
        i, j = self.ij(x, z)
        return not (0 <= i < self.n and 0 <= j < self.n) or self.bits[j * self.n + i] == 1

    def mark_box(self, o):
        xs = [c[0] for c in corners(o)]
        zs = [c[1] for c in corners(o)]
        i0, j0 = self.ij(min(xs), min(zs))
        i1, j1 = self.ij(max(xs), max(zs))
        for j in range(max(0, j0), min(self.n, j1 + 1)):
            z = self.oz - self.size / 2 + (j + 0.5) * self.cell
            for i in range(max(0, i0), min(self.n, i1 + 1)):
                if inside(o, self.ox - self.size / 2 + (i + 0.5) * self.cell, z):
                    self.bits[j * self.n + i] = 1

    def mark_disc(self, x, z, r):
        i0, j0 = self.ij(x - r, z - r)
        i1, j1 = self.ij(x + r, z + r)
        for j in range(max(0, j0), min(self.n, j1 + 1)):
            cz = self.oz - self.size / 2 + (j + 0.5) * self.cell
            for i in range(max(0, i0), min(self.n, i1 + 1)):
                if math.hypot(self.ox - self.size / 2 + (i + 0.5) * self.cell - x, cz - z) <= r:
                    self.bits[j * self.n + i] = 1

    def mark_segment(self, a, b, half):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(length / (self.cell * 0.8)))
        for k in range(n + 1):
            t = k / n
            self.mark_disc(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, half)

    def fits(self, o):
        for fx in (-1.0, -0.5, 0.0, 0.5, 1.0):
            for fz in (-1.0, -0.5, 0.0, 0.5, 1.0):
                if self.taken(*to_world(o, fx * o[2], fz * o[3])):
                    return False
        return True


def occupancy(size, streets, houses, landmarks, palace, keepout, water, slope, inside_city):
    occ = Occupancy(size)
    for s in streets:
        for a, b in zip(s['pts'], s['pts'][1:]):
            occ.mark_segment(a, b, s['width'] / 2 + 1.0)
    for h in houses:
        occ.mark_box(house_box(h, 1.2))
    for m in landmarks:
        occ.mark_box(box(m['x'], m['z'], m['w'], m['d'], m['rot'], 3.0))
    occ.mark_box(box(palace['x'], palace['z'], palace['w'], palace['d'] + 30, palace['rot'], 4.0))
    for k in keepout:
        occ.mark_disc(k['x'], k['z'], k['r'])
    for j in range(occ.n):
        z = -size / 2 + (j + 0.5) * occ.cell
        row = j * occ.n
        for i in range(occ.n):
            if occ.bits[row + i]:
                continue
            x = -size / 2 + (i + 0.5) * occ.cell
            if not inside_city(x, z) or water(x, z) or slope(x, z) > 0.55:
                occ.bits[row + i] = 1
    return occ


def local_occupancy(scene, x, z, radius=120.0, placed=()):
    occ = Occupancy(radius * 2, 1.5, x, z)
    near = lambda px, pz, r: abs(px - x) < radius + r and abs(pz - z) < radius + r
    for s in scene['streets']:
        for a, b in zip(s['pts'], s['pts'][1:]):
            if near(a[0], a[1], 20) or near(b[0], b[1], 20):
                occ.mark_segment(a, b, s['width'] / 2 + 0.8)
    for r in scene['rivers']:
        for a, b in zip(r['pts'], r['pts'][1:]):
            if near(a[0], a[1], 60):
                occ.mark_segment(a, b, max(a[3], b[3]) / 2 + 1.0)
    for h in scene['houses']:
        if near(h['x'], h['z'], h.get('reach', 15)):
            occ.mark_box(house_box(h, 0.6))
    for m in scene['landmarks']:
        if near(m['x'], m['z'], max(m['w'], m['d'])) and m['kind'] not in ('forum', 'garden'):
            occ.mark_box(box(m['x'], m['z'], m['w'], m['d'], m['rot'], 1.0))
    p = scene['palace']
    occ.mark_box(box(p['x'], p['z'], p['w'], p['d'], p['rot'], 2.0))
    for o in placed:
        occ.mark_box(box(o['x'], o['z'], o.get('w', 4), o.get('d', 4), o.get('rot', 0), 0.5))
    return occ


def height_at(scene, x, z):
    n, size, h = scene['n'], scene['size'], scene['heights']
    step = size / (n - 1)
    fx = max(0.0, min(n - 1.0001, (x + size / 2) / step))
    fz = max(0.0, min(n - 1.0001, (z + size / 2) / step))
    i, j = int(fx), int(fz)
    tx, tz = fx - i, fz - j
    top = h[j * n + i] * (1 - tx) + h[j * n + i + 1] * tx
    bottom = h[(j + 1) * n + i] * (1 - tx) + h[(j + 1) * n + i + 1] * tx
    return round(top * (1 - tz) + bottom * tz, 2)


def free_spot(scene, x, z, w, d, rot=0.0, placed=()):
    occ = local_occupancy(scene, x, z, 120.0, placed)
    found = place_free(occ, x, z, w, d, rot, 110.0)
    return None if found is None else {'x': found[0], 'z': found[1], 'moved': round(math.hypot(found[0] - x, found[1] - z), 1)}


def place_free(occ, x, z, w, d, rot, reach=80.0):
    for r in [0.0] + [k * 2.5 for k in range(1, int(reach / 2.5) + 1)]:
        for a in [k * math.pi / 8 for k in range(16)] if r else [0.0]:
            cx, cz = x + math.cos(a) * r, z + math.sin(a) * r
            if occ.fits(box(cx, cz, w, d, rot, 0.5)):
                return round(cx, 2), round(cz, 2)
    return None


def map_svg(scene, scale=0.5):
    size = scene['size']
    px = lambda v: round((v + size / 2) * scale, 1)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size * scale:.0f} {size * scale:.0f}" font-family="sans-serif">',
           f'<rect width="{size * scale:.0f}" height="{size * scale:.0f}" fill="#d9cfb4"/>']
    for r in scene['rivers']:
        pts = ' '.join(f'{px(p[0])},{px(p[1])}' for p in r['pts'])
        width = max(p[3] for p in r['pts']) * scale
        out.append(f'<polyline points="{pts}" fill="none" stroke="#5b8fa8" stroke-width="{width:.1f}" stroke-linejoin="round"/>')
    for s in scene['streets']:
        pts = ' '.join(f'{px(p[0])},{px(p[1])}' for p in s['pts'])
        out.append(f'<polyline points="{pts}" fill="none" stroke="{"#5f5b55" if s["main"] else "#8c8270"}" stroke-width="{s["width"] * scale:.1f}" stroke-linecap="round" stroke-linejoin="round"/>')
    for h in scene['houses']:
        pts = ' '.join(f'{px(x)},{px(z)}' for x, z in corners(house_box(h)))
        out.append(f'<polygon points="{pts}" fill="{"#9c8f7a" if h.get("ruin") else "#b8693f" if h.get("type") == "insula" else "#c99a6a"}"/>')
    colors = {'market_stalls': '#e0b040', 'market': '#e0b040', 'garden': '#7a9a55', 'vegetable_garden': '#7a9a55', 'forum': '#e8e2d2', 'circus': '#d6c8a0'}
    for m in scene['landmarks']:
        pts = ' '.join(f'{px(x)},{px(z)}' for x, z in corners(box(m['x'], m['z'], m['w'], m['d'], m['rot'])))
        out.append(f'<polygon points="{pts}" fill="{colors.get(m["kind"], "#f4f1ea")}" stroke="#4a4038" stroke-width="0.6"/>')
    p = scene['palace']
    out.append(f'<polygon points="{" ".join(f"{px(x)},{px(z)}" for x, z in corners(box(p["x"], p["z"], p["w"], p["d"], p["rot"])))}" fill="#e8c860" stroke="#4a4038" stroke-width="0.8"/>')
    for t in scene['trees'][::2]:
        out.append(f'<circle cx="{px(t["x"])}" cy="{px(t["z"])}" r="1.2" fill="#4f6b3a"/>')
    for m in scene['landmarks']:
        if m['w'] * m['d'] > 900:
            out.append(f'<text x="{px(m["x"])}" y="{px(m["z"])}" font-size="7" text-anchor="middle" fill="#2a2420">{escape(m["name"][:28])}</text>')
    out.append('</svg>')
    return '\n'.join(out)
