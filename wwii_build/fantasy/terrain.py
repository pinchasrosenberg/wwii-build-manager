import math
import random

SIZE = 400.0
N = 129


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def hash2(ix, iz, seed):
    n = (ix * 374761393 + iz * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 4294967295.0


def vnoise(x, z, seed):
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = smooth(x - ix), smooth(z - iz)
    a, b = hash2(ix, iz, seed), hash2(ix + 1, iz, seed)
    c, d = hash2(ix, iz + 1, seed), hash2(ix + 1, iz + 1, seed)
    return lerp(lerp(a, b, fx), lerp(c, d, fx), fz)


def fbm(x, z, seed, octaves=5):
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        total += vnoise(x * freq, z * freq, seed + o * 17) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def ridged(x, z, seed, octaves=5, sharp=1.6):
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        n = 1.0 - abs(2.0 * vnoise(x * freq, z * freq, seed + o * 31) - 1.0)
        total += (n ** sharp) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


class Grid:
    def __init__(self, size=SIZE, n=N):
        self.size = size
        self.n = n
        self.step = size / (n - 1)
        self.h = [0.0] * (n * n)

    def x_of(self, i):
        return -self.size / 2 + i * self.step

    def idx(self, i, j):
        return j * self.n + i

    def at(self, x, z):
        fx = (x + self.size / 2) / self.step
        fz = (z + self.size / 2) / self.step
        i0 = max(0, min(self.n - 2, int(math.floor(fx))))
        j0 = max(0, min(self.n - 2, int(math.floor(fz))))
        tx, tz = max(0.0, min(1.0, fx - i0)), max(0.0, min(1.0, fz - j0))
        a, b = self.h[self.idx(i0, j0)], self.h[self.idx(i0 + 1, j0)]
        c, d = self.h[self.idx(i0, j0 + 1)], self.h[self.idx(i0 + 1, j0 + 1)]
        return lerp(lerp(a, b, tx), lerp(c, d, tx), tz)

    def slope(self, x, z, r=2.5):
        dx = self.at(x + r, z) - self.at(x - r, z)
        dz = self.at(x, z + r) - self.at(x, z - r)
        return math.hypot(dx, dz) / (2 * r)

    def inside(self, x, z, margin=8.0):
        half = self.size / 2 - margin
        return -half <= x <= half and -half <= z <= half

    def pull(self, x, z, y, core, blend, strength=1.0):
        reach = core + blend
        i_lo = max(0, int((x - reach + self.size / 2) / self.step))
        i_hi = min(self.n - 1, int((x + reach + self.size / 2) / self.step) + 1)
        j_lo = max(0, int((z - reach + self.size / 2) / self.step))
        j_hi = min(self.n - 1, int((z + reach + self.size / 2) / self.step) + 1)
        for j in range(j_lo, j_hi + 1):
            for i in range(i_lo, i_hi + 1):
                d = math.hypot(self.x_of(i) - x, self.x_of(j) - z)
                w = 1.0 if d <= core else (1.0 - smooth((d - core) / blend) if d < reach else 0.0)
                if w > 0:
                    k = self.idx(i, j)
                    self.h[k] = lerp(self.h[k], y, min(1.0, w * strength))


def plateau_shape(x, z, angle, along, across):
    ca, sa = math.cos(angle), math.sin(angle)
    a = x * ca + z * sa
    b = -x * sa + z * ca
    return math.exp(-((a / along) ** 2) - ((b / across) ** 2))


def build_heights(spec, rng, grid=None, center=(0.0, 0.0)):
    kind = spec['terrain']['kind']
    relief = spec['terrain']['relief']
    sharp = spec['terrain']['sharpness']
    seed = spec['seed'] % 100000
    grid = grid or Grid()
    n_ = grid.n
    half = grid.size / 2
    ox, oz = center
    angle = rng.uniform(0, math.pi)
    info = {'kind': kind, 'sea_level': None, 'center': (0.0, 0.0), 'lakes': [], 'angle': angle}
    for j in range(n_):
        z = grid.x_of(j)
        for i in range(n_):
            x = grid.x_of(i)
            u, v = x / half, z / half
            r = math.hypot(u, v)
            if kind == 'sharp_mountains':
                amp = 55 + relief * 120
                base = ridged(x / 95, z / 95, seed, 6, 1.0 + sharp * 1.4)
                h = amp * (0.12 + 0.88 * base) * (0.65 + 0.5 * fbm(x / 170, z / 170, seed + 5, 3))
                shape = plateau_shape(x - ox, z - oz, angle, 105, 24)
                h = lerp(h, amp * 0.5 + 5 * fbm(x / 30, z / 30, seed + 9, 3), shape * 0.92)
            elif kind == 'mountains':
                amp = 25 + relief * 85
                base = 0.55 * ridged(x / 120, z / 120, seed, 5, 1.2) + 0.45 * fbm(x / 110, z / 110, seed + 3, 5)
                h = amp * base
                shape = plateau_shape(x - ox, z - oz, angle, 120, 70)
                h = lerp(h, amp * 0.35 + 4 * fbm(x / 40, z / 40, seed + 9, 3), shape * 0.9)
            elif kind == 'hills':
                h = 8 + (4 + relief * 8) * fbm(x / 140, z / 140, seed, 4)
            elif kind == 'plains':
                h = 4 + (5 + relief * 12) * fbm(x / 120, z / 120, seed, 4)
            elif kind == 'valley':
                rim = smooth((r - 0.28) / 0.6)
                h = 6 + (rim ** 1.3) * (45 + relief * 80) * (0.6 + 0.8 * ridged(x / 100, z / 100, seed, 4, 1.2)) + 3 * fbm(x / 40, z / 40, seed + 2, 3)
            elif kind == 'islands':
                mask = 1.0 - (r / 0.95) ** 2 + 0.55 * (fbm(x / 80, z / 80, seed, 4) - 0.5) + 0.7 * math.exp(-r * r / 0.12)
                h = (mask - 0.28) * (38 + relief * 40)
                info['sea_level'] = 0.0
            elif kind == 'coast':
                h = (0.32 - u) * (30 + relief * 40) + 10 * (fbm(x / 80, z / 80, seed, 5) - 0.4) * smooth(0.55 - u)
                info['sea_level'] = 0.0
            elif kind == 'cliff_port':
                cliff = smooth((u + 0.04) / 0.22) * (60 + relief * 90) * (0.7 + 0.5 * ridged(x / 90, z / 90, seed, 4, 1.4))
                shelf = 3.2 + 1.2 * fbm(x / 25, z / 25, seed + 1, 3)
                h = lerp(shelf, shelf + cliff, smooth((u + 0.04) / 0.3))
                h = lerp(-7.0, h, smooth((u + 0.45) / 0.2))
                info['sea_level'] = 0.0
            elif kind == 'canyon':
                d = abs(z - 70 * math.sin(x / 85) - 20 * fbm(x / 60, 0, seed, 2))
                cut = smooth(d / 38)
                h = (48 + relief * 40) * (0.9 + 0.3 * fbm(x / 70, z / 70, seed, 4)) * cut + 1.5
            else:
                dune = 0.5 + 0.5 * math.sin((x * 0.045 + 6 * fbm(x / 90, z / 90, seed, 3)) + z * 0.012)
                h = 5 + (4 + relief * 12) * dune * (0.5 + fbm(x / 130, z / 130, seed + 1, 3))
            grid.h[grid.idx(i, j)] = h
    return grid, info


def choose_center(grid, info, spec, rng):
    kind = info['kind']
    sea = info['sea_level']
    candidates = {
        'cliff_port': (-grid.size * 0.18, 0.0),
        'coast': (-grid.size * 0.1, rng.uniform(-30, 30)),
    }
    cx, cz = candidates.get(kind, (rng.uniform(-18, 18), rng.uniform(-18, 18)))
    best = (cx, cz)
    best_score = -1e9
    for k in range(60):
        ang = k * 2.399963
        rad = 6.0 * math.sqrt(k) * 4
        px, pz = cx + rad * math.cos(ang), cz + rad * math.sin(ang)
        if not grid.inside(px, pz, 70):
            continue
        y = grid.at(px, pz)
        if sea is not None and y < sea + 2.5:
            continue
        score = -grid.slope(px, pz, 14) * 40 - rad * 0.05
        if score > best_score:
            best, best_score = (px, pz), score
    return best


def carve_lakes(grid, info, spec, rng):
    if not spec['water']['lake'] or info['sea_level'] is not None:
        return
    cx, cz = info['center']
    for _ in range(40):
        px, pz = rng.uniform(-150, 150), rng.uniform(-150, 150)
        if math.hypot(px - cx, pz - cz) < 110:
            continue
        if not grid.inside(px, pz, 40):
            continue
        base = grid.at(px, pz)
        radius = rng.uniform(26, 40)
        level = base - 1.2
        grid.pull(px, pz, level - 6, radius * 0.55, radius * 0.7, 1.0)
        info['lakes'].append({'x': px, 'z': pz, 'r': radius * 0.9, 'y': level})
        return


def carve_river(grid, info, spec, rng):
    if not spec['water']['river']:
        return []
    cx, cz = info['center']
    best = None
    for _ in range(60):
        px, pz = rng.uniform(-170, 170), rng.uniform(-170, 170)
        if math.hypot(px - cx, pz - cz) < 90:
            continue
        y = grid.at(px, pz)
        if best is None or y > best[2]:
            best = (px, pz, y)
    if best is None:
        return []
    x, z, _ = best
    pts = []
    heading = None
    for _ in range(120):
        if not grid.inside(x, z, 2):
            break
        y = grid.at(x, z)
        pts.append([x, z, y])
        sea = info['sea_level']
        if sea is not None and y < sea + 0.5:
            break
        options = []
        for k in range(16):
            ang = k * math.pi / 8
            nx, nz = x + 6 * math.cos(ang), z + 6 * math.sin(ang)
            if not grid.inside(nx, nz, 1):
                continue
            turn = 0.0 if heading is None else abs((ang - heading + math.pi) % (2 * math.pi) - math.pi)
            options.append((grid.at(nx, nz) + turn * 1.2, ang, nx, nz))
        if not options:
            break
        _, heading, x, z = min(options)
    smoothed = []
    for k, p in enumerate(pts):
        ys = [q[2] for q in pts[max(0, k - 3):k + 1]]
        smoothed.append([p[0], p[1], min(ys) - 1.0 if k else p[2] - 1.0])
    for k in range(1, len(smoothed)):
        smoothed[k][2] = min(smoothed[k][2], smoothed[k - 1][2])
    for p in smoothed:
        grid.pull(p[0], p[1], p[2] - 1.5, 2.6, 5.5, 0.9)
    return [{'pts': [[round(p[0], 1), round(p[1], 1), round(p[2], 2)] for p in smoothed], 'width': 5.0}]
