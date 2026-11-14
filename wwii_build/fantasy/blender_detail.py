import json
import math
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

TRAVERTINE = (0.80, 0.75, 0.64)
MARBLE = (0.88, 0.85, 0.79)
BRICK = (0.62, 0.40, 0.27)
DARK = (0.10, 0.08, 0.07)
TILE = (0.62, 0.30, 0.18)
SAND = (0.82, 0.74, 0.58)
LEAF = (0.27, 0.36, 0.18)
BRONZE = (0.48, 0.38, 0.22)


class Builder:
    def __init__(self, decay, seed):
        self.parts = {}
        self.decay = decay
        self.rand = random.Random(seed)

    def mesh(self, color):
        key = tuple(round(c * (1 - 0.18 * self.decay), 3) for c in color)
        if key not in self.parts:
            self.parts[key] = bmesh.new()
        return self.parts[key]

    def box(self, color, size, loc, rot_z=0.0):
        bm = self.mesh(color)
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot_z, 4, 'Z') @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
        bmesh.ops.create_cube(bm, size=1.0, matrix=mat)

    def cyl(self, color, r1, r2, h, loc, segs=12, rot_z=0.0, tilt=None, scale=(1.0, 1.0, 1.0)):
        bm = self.mesh(color)
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot_z, 4, 'Z')
        if tilt:
            mat = mat @ Matrix.Rotation(tilt[0], 4, tilt[1])
        mat = mat @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r1, radius2=r2, depth=h, matrix=mat)

    def gable(self, color, w, d, z, rh):
        bm = self.mesh(color)
        v = [bm.verts.new(c) for c in ((-w / 2, -d / 2, z), (w / 2, -d / 2, z), (0, -d / 2, z + rh), (-w / 2, d / 2, z), (w / 2, d / 2, z), (0, d / 2, z + rh))]
        for f in ((0, 2, 5, 3), (1, 4, 5, 2), (0, 1, 2), (3, 5, 4)):
            bm.faces.new([v[i] for i in f])

    def sphere(self, color, r, loc, scale=(1, 1, 1)):
        bm = self.mesh(color)
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        bmesh.ops.create_uvsphere(bm, u_segments=14, v_segments=8, radius=r, matrix=mat)

    def arch(self, color, center, radius, thick, depth, rot_z, pieces=9):
        for k in range(pieces):
            a0 = math.pi * k / pieces
            a1 = math.pi * (k + 1) / pieces
            am = (a0 + a1) / 2
            seg = radius * (a1 - a0) * 1.08
            lx = math.cos(am) * radius
            lz = math.sin(am) * radius
            local = Vector((lx, 0.0, lz))
            world = Vector(center) + Matrix.Rotation(rot_z, 3, 'Z') @ local
            bm = self.mesh(color)
            mat = Matrix.Translation(world) @ Matrix.Rotation(rot_z, 4, 'Z') @ Matrix.Rotation(-(am - math.pi / 2), 4, 'Y') @ Matrix.Diagonal((seg, depth, thick, 1.0))
            bmesh.ops.create_cube(bm, size=1.0, matrix=mat)

    def finish(self, path):
        for i, (color, bm) in enumerate(self.parts.items()):
            me = bpy.data.meshes.new(f'part{i}')
            bm.to_mesh(me)
            bm.free()
            mat = bpy.data.materials.new(f'mat{i}')
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get('Principled BSDF')
            bsdf.inputs['Base Color'].default_value = (*color, 1.0)
            bsdf.inputs['Roughness'].default_value = 0.85
            me.materials.append(mat)
            obj = bpy.data.objects.new(f'part{i}', me)
            bpy.context.scene.collection.objects.link(obj)
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_apply=True)


def order_capital(b, order, x, y, z, rot, r):
    if order == 'tuscan':
        b.box(TRAVERTINE, (r * 2.6, r * 2.6, 0.35), (x, y, z), rot)
    elif order == 'ionic':
        b.box(TRAVERTINE, (r * 2.8, r * 1.4, 0.4), (x, y, z), rot)
        for s in (-1, 1):
            dx, dy = math.cos(rot) * s * r * 1.3, math.sin(rot) * s * r * 1.3
            b.cyl(TRAVERTINE, 0.28, 0.28, r * 1.4, (x + dx, y + dy, z - 0.1), 10, rot, (math.pi / 2, 'X'))
    else:
        b.cyl(TRAVERTINE, r * 1.5, r * 0.95, 0.9, (x, y, z - 0.25), 12)
        b.box(TRAVERTINE, (r * 3.0, r * 3.0, 0.25), (x, y, z + 0.3), rot)


def colosseum(b, m, p):
    a, bb, h = m['w'] / 2, m['d'] / 2, m['h']
    tiers = 4
    tier_h = [10.5, 11.8, 11.6, h - 33.9]
    orders = p.get('orders') or ['tuscan', 'ionic', 'corinthian']
    bays = 80
    collapse = p.get('collapsed_sector', True) and b.decay > 0.3
    perim_seg = math.pi * (3 * (a + bb) - math.sqrt((3 * a + bb) * (a + 3 * bb))) / bays
    base_z = 0.0
    for t in range(tiers):
        th = tier_h[t]
        for k in range(bays):
            ang = 2 * math.pi * (k + 0.5) / bays
            x, y = math.cos(ang) * a, math.sin(ang) * bb
            tx, ty = -math.sin(ang) * a, math.cos(ang) * bb
            rot = math.atan2(ty, tx)
            gone = collapse and 0.22 * math.pi < ang < 0.68 * math.pi and (t >= 2 or (t == 1 and b.rand.random() < 0.4))
            if gone:
                if t == tiers - 1 and b.rand.random() < 0.6:
                    b.box(TRAVERTINE, (perim_seg * 0.8, 2.4, b.rand.uniform(0.8, 3)), (x, y, b.rand.uniform(0.3, 1.2)), rot)
                continue
            if t < 3:
                b.box(TRAVERTINE, (1.6, 2.6, th * 0.92), (x, y, base_z + th * 0.46), rot)
                ox, oy = math.cos(rot - math.pi / 2) * 1.6, math.sin(rot - math.pi / 2) * 1.6
                b.cyl(TRAVERTINE, 0.62, 0.55, th * 0.8, (x + ox, y + oy, base_z + th * 0.42), 12)
                order_capital(b, orders[min(t, len(orders) - 1)], x + ox, y + oy, base_z + th * 0.84, rot, 0.6)
                a1 = 2 * math.pi * (k + 1) / bays
                cx, cy = math.cos(a1) * a, math.sin(a1) * bb
                rot1 = math.atan2(math.cos(a1) * bb, -math.sin(a1) * a)
                b.arch(TRAVERTINE, (cx, cy, base_z + th * 0.6), (perim_seg - 1.6) / 2, 0.75, 2.4, rot1, 9)
                b.box(TRAVERTINE, (perim_seg + 0.2, 3.0, th * 0.12), (x, y, base_z + th * 0.94), rot)
                if p.get('statues_in_arches', True) and t in (1, 2) and b.rand.random() > b.decay * 0.6:
                    b.cyl(MARBLE, 0.35, 0.45, 2.3, (cx, cy, base_z + 1.15 + 0.9), 8)
                    b.sphere(MARBLE, 0.32, (cx, cy, base_z + 3.5))
            else:
                b.box(TRAVERTINE, (perim_seg + 0.15, 2.2, th), (x, y, base_z + th / 2), rot)
                ox, oy = math.cos(rot - math.pi / 2) * 1.2, math.sin(rot - math.pi / 2) * 1.2
                b.box(TRAVERTINE, (0.9, 0.5, th * 0.9), (x + ox, y + oy, base_z + th * 0.45), rot)
                if k % 2 == 0 and p.get('attic_windows', True):
                    b.box(DARK, (1.4, 0.3, 1.8), (x + ox * 1.05, y + oy * 1.05, base_z + th * 0.55), rot)
                if p.get('velarium_masts', True) and k % 2 == 1:
                    b.box(TRAVERTINE, (0.5, 0.5, 0.6), (x + ox * 1.3, y + oy * 1.3, base_z + th * 0.25), rot)
                    b.cyl(BRONZE, 0.18, 0.15, 6.0, (x + ox * 1.35, y + oy * 1.35, base_z + th + 2.0), 6)
        base_z += th
    ratio = (1.0, bb / a, 1.0)
    for k in range(7):
        f = 0.9 - k * 0.075
        z = h * 0.68 * (1 - k / 7)
        b.cyl(TRAVERTINE, a * f, a * f, 1.0, (0, 0, z), 64, scale=ratio)
    b.cyl(DARK, a * 0.94, a * 0.94, h * 0.62, (0, 0, h * 0.31), 64, scale=ratio)
    b.cyl(SAND, a * 0.42, a * 0.42, 0.4, (0, 0, 1.0), 48, scale=ratio)
    if p.get('hypogeum', True):
        for k in range(-6, 7):
            b.box(BRICK, (a * 0.7, 0.6, 1.4), (0, k * 3.2, 0.2), 0.0)


def temple(b, m, p):
    w, d, h = m['w'], m['d'], m['h']
    ph = max(1.4, h * 0.14)
    ch = h * 0.62
    b.box(TRAVERTINE, (w + 3, d + 3, ph), (0, 0, ph / 2))
    for i in range(max(4, int(ph / 0.35))):
        b.box(TRAVERTINE, (w * 0.6, 0.45, 0.35), (0, -(d / 2 + 1.5 + i * 0.45), ph - 0.18 - i * 0.35))
    front = p.get('columns_front', max(6, int(w / 3.6)))
    side = max(6, int(front * d / w))
    r = min(0.95, w / (front * 3.3))
    spots = [((-0.5 + i / (front - 1)) * (w - 2), -d / 2 + 1) for i in range(front)]
    spots += [((-0.5 + i / (front - 1)) * (w - 2), d / 2 - 1) for i in range(front)]
    spots += [(s * (w / 2 - 1), (-0.5 + (i + 1) / (side - 1)) * (d - 2)) for s in (-1, 1) for i in range(side - 2)]
    for x, y in spots:
        if b.rand.random() < b.decay * 0.18:
            b.cyl(MARBLE, r, r, b.rand.uniform(1, ch * 0.4), (x, y, ph + 0.5), 14)
            continue
        b.box(MARBLE, (r * 2.6, r * 2.6, 0.5), (x, y, ph + 0.25))
        flutes = p.get('fluting', True)
        b.cyl(MARBLE, r * 0.86, r, ch, (x, y, ph + 0.5 + ch / 2), 20 if flutes else 12)
        order_capital(b, p.get('order', 'corinthian'), x, y, ph + 0.5 + ch, 0.0, r)
    b.box(BRICK, (w * 0.62, d * 0.62, ch * 0.95), (0, d * 0.1, ph + ch * 0.475))
    b.box(DARK, (w * 0.16, 0.3, ch * 0.5), (0, d * 0.1 - d * 0.31 - 0.1, ph + ch * 0.25))
    ent = ph + 0.5 + ch + 0.6
    b.box(MARBLE, (w + 0.6, d + 0.6, 1.0), (0, 0, ent + 0.5))
    b.box(MARBLE, (w + 0.9, d + 0.9, 0.5), (0, 0, ent + 1.25))
    if b.decay < 0.6 or b.rand.random() > 0.5:
        rh = h * 0.16
        b.gable(TILE, w + 0.8, d + 0.8, ent + 1.5, rh)
        if p.get('pediment_relief', True):
            for i in range(5):
                b.box(MARBLE, (0.7, 0.4, 0.9 + (2 - abs(i - 2)) * 0.6), ((i - 2) * w * 0.12, -d / 2 - 0.2, ent + 1.9 + (2 - abs(i - 2)) * 0.3))
        if p.get('acroteria', True):
            for x in (-w / 2, 0, w / 2):
                b.sphere(BRONZE, 0.6, (x, -d / 2, ent + 1.5 + (rh if x == 0 else 0.3) + 0.5))


def triumphal_arch(b, m, p):
    w, d, h = m['w'], m['d'], m['h']
    body = h * 0.72
    triple = w >= 19
    cw = w * 0.27 if triple else w * 0.42
    lw = w * 0.12
    piers = [(-w / 2, -cw / 2)] if not triple else [(-w / 2, -w / 2 + w * 0.09), (-w * 0.33 + lw / 2, -cw / 2)]
    piers += [(-b_, -a_) for a_, b_ in piers]
    for x0, x1 in piers:
        b.box(MARBLE, (x1 - x0, d, body), ((x0 + x1) / 2, 0, body / 2))
    b.arch(MARBLE, (0, 0, body * 0.55), cw / 2, 1.2, d, 0.0, 11)
    b.box(MARBLE, (cw, d, body - body * 0.55 - cw / 2 + 0.6), (0, 0, body - (body - body * 0.55 - cw / 2 + 0.6) / 2))
    if triple:
        for s in (-1, 1):
            b.arch(MARBLE, (s * w * 0.33, 0, body * 0.33), lw / 2, 0.8, d, 0.0, 9)
            b.box(MARBLE, (lw, d, body - body * 0.33 - lw / 2), (s * w * 0.33, 0, body - (body - body * 0.33 - lw / 2) / 2))
            b.box(MARBLE, (lw * 0.9, 0.3, 2.0), (s * w * 0.33, -d / 2 - 0.1, body * 0.75))
    for face in (-1, 1):
        for f in ([-0.44, -0.2, 0.2, 0.44] if triple else [-0.38, 0.38]):
            b.box(MARBLE, (1.4, 1.4, 1.6), (f * w, face * (d / 2 + 0.7), 0.8))
            b.cyl(p.get('column_color') and tuple(p['column_color']) or (0.86, 0.78, 0.55), 0.45, 0.5, body * 0.78, (f * w, face * (d / 2 + 0.7), 1.6 + body * 0.39), 16)
            order_capital(b, 'corinthian', f * w, face * (d / 2 + 0.7), 1.6 + body * 0.78, 0.0, 0.5)
            if p.get('statues_on_attic', True):
                b.cyl(MARBLE, 0.4, 0.5, 2.6, (f * w, face * (d / 2 + 0.7), body + 1.3 + 0.6), 8)
                b.sphere(MARBLE, 0.35, (f * w, face * (d / 2 + 0.7), body + 3.0))
        if p.get('reliefs', True):
            for s in (-1, 1):
                b.box((0.78, 0.74, 0.66), (w * 0.14, 0.3, body * 0.18), (s * w * 0.22, face * (d / 2 + 0.05), body * 0.82))
    b.box(MARBLE, (w + 0.6, d + 0.6, 1.0), (0, 0, body + 0.5))
    b.box(MARBLE, (w, d, h - body - 1.0), (0, 0, body + 1.0 + (h - body - 1.0) / 2))
    if p.get('attic_inscription', True):
        for face in (-1, 1):
            b.box(BRONZE, (w * 0.5, 0.15, (h - body) * 0.45), (0, face * (d / 2 + 0.05), body + 1.0 + (h - body - 1.0) / 2))


def palace(b, m, p):
    w, d, h = m['w'], m['d'], m['h']
    pocket = 2.0
    dw = 3.6
    b.box(m.get('wall', MARBLE), (w, d - pocket, h), (0, pocket / 2, h / 2))
    for s in (-1, 1):
        b.box(m.get('wall', MARBLE), ((w / 2 - dw / 2), pocket, h), (s * (w / 2 + dw / 2) / 2, -(d / 2 - pocket / 2), h / 2))
    b.box(m.get('wall', MARBLE), (dw, pocket, h - 4.6), (0, -(d / 2 - pocket / 2), 4.6 + (h - 4.6) / 2))
    b.box((0.23, 0.15, 0.09), (dw - 0.2, 0.25, 4.4), (0, -(d / 2 - pocket) - 0.15, 2.2))
    for s in (-1, 1):
        b.box(BRONZE, (0.25, 0.1, 0.7), (s * 0.9, -(d / 2 - pocket) - 0.3, 2.2))
    depth = 7
    cols = p.get('portico_columns', 10)
    b.box(MARBLE, (w + 2, depth + 1, 0.35), (0, -(d / 2 + depth / 2), 0.17))
    for i in range(cols):
        x = (-0.5 + i / (cols - 1)) * (w - 2)
        if abs(x) < dw / 2 + 0.6:
            continue
        b.box(MARBLE, (1.5, 1.5, 0.5), (x, -(d / 2 + depth - 1), 0.6))
        b.cyl((0.86, 0.78, 0.55), 0.55, 0.65, h - 2.6, (x, -(d / 2 + depth - 1), 0.85 + (h - 2.6) / 2), 18)
        order_capital(b, 'corinthian', x, -(d / 2 + depth - 1), h - 1.6, 0.0, 0.6)
    b.box(MARBLE, (w + 0.8, depth + 0.8, 1.4), (0, -(d / 2 + depth / 2), h - 0.7))
    for row in range(2 if p.get('upper_story', True) else 1):
        for i in range(9):
            x = (-0.5 + (i + 0.5) / 9) * (w - 4)
            if abs(x) < dw / 2 + 0.8 and row == 0:
                continue
            b.box(DARK, (1.6, 0.3, 2.8), (x, -(d / 2) - 0.05, h * (0.35 + row * 0.33)))
            b.box(MARBLE, (2.1, 0.4, 0.3), (x, -(d / 2) - 0.1, h * (0.35 + row * 0.33) + 1.6))
    b.box(MARBLE, (w + 0.8, d + 0.8, 1.0), (0, 0, h + 0.5))
    rh = min(w, d) * 0.22
    bm = b.mesh(TILE)
    v = [bm.verts.new(c) for c in ((-w / 2 - 0.4, -d / 2 - 0.4, h + 1), (w / 2 + 0.4, -d / 2 - 0.4, h + 1), (w / 2 + 0.4, d / 2 + 0.4, h + 1), (-w / 2 - 0.4, d / 2 + 0.4, h + 1),
                                   (-w / 2 + d / 2, 0, h + 1 + rh), (w / 2 - d / 2, 0, h + 1 + rh))]
    for f in ((0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4)):
        bm.faces.new([v[i] for i in f])
    for s in (-1, 1):
        b.sphere(BRONZE, 0.5, (s * w / 2, -(d / 2 + depth), h + 1.6))
        b.cyl(MARBLE, 0.5, 0.6, 2.6, (s * w * 0.25, -(d / 2 + depth), h + 2.4), 10)


def hex_rgb(value, fallback):
    ok = isinstance(value, str) and len(value) == 7 and value.startswith('#')
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)) if ok else fallback


def hip_roof(b, color, w, d, z, rh):
    bm = b.mesh(color)
    r = max(0.0, (w - d) / 2)
    v = [bm.verts.new(c) for c in ((-w / 2, -d / 2, z), (w / 2, -d / 2, z), (w / 2, d / 2, z), (-w / 2, d / 2, z), (-r, 0, z + rh), (r, 0, z + rh))]
    for f in ((0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4)):
        bm.faces.new([v[i] for i in f])


def house(b, m, p):
    w, d = m['w'], m['d']
    floors = int(p.get('floors') or m.get('floors') or 3)
    fh = 3.1
    h = floors * fh
    wall = hex_rgb(m.get('wall_color'), (0.79, 0.64, 0.42))
    roof = hex_rgb(m.get('roof_color'), TILE)
    b.box((0.45, 0.43, 0.40), (w + 0.4, d + 0.4, 0.6), (0, 0, 0.3))
    b.box(wall, (w, d, h), (0, 0, h / 2))
    for f in range(1, floors):
        b.box(tuple(c * 0.8 for c in wall), (w + 0.15, d + 0.15, 0.18), (0, 0, f * fh))
    shops = p.get('shop_front', True)
    bays = max(1, int(w / 3.2))
    for k in range(bays):
        x = (-0.5 + (k + 0.5) / bays) * w
        if shops:
            b.box(DARK, (2.0, 0.3, 2.3), (x, -d / 2 - 0.05, 1.15))
            b.arch(tuple(c * 0.85 for c in wall), (x, -d / 2 - 0.1, 2.3), 1.0, 0.25, 0.4, 0.0, 7)
            b.box((0.42, 0.28, 0.16), (1.8, 0.6, 0.9), (x, -d / 2 - 0.45, 0.45))
        for f in range(1, floors):
            for face, y in ((-1, -d / 2 - 0.06), (1, d / 2 + 0.06)):
                b.box(DARK, (0.85, 0.15, 1.2), (x, y, f * fh + 1.5))
                b.box(MARBLE, (1.15, 0.25, 0.12), (x, y, f * fh + 0.85))
                if p.get('shutters', False):
                    for s in (-1, 1):
                        b.box((0.25, 0.4, 0.28), (0.4, 0.1, 1.2), (x + s * 0.65, y, f * fh + 1.5))
    if not shops:
        b.box((0.23, 0.15, 0.09), (1.2, 0.2, 2.2), (0, -d / 2 - 0.05, 1.1))
    if p.get('balcony', True) and floors > 1:
        b.box((0.36, 0.25, 0.15), (w * 0.8, 1.1, 0.15), (0, -d / 2 - 0.55, fh))
        for k in range(int(w * 0.8 / 0.6)):
            b.box((0.30, 0.20, 0.12), (0.08, 0.08, 0.9), (-w * 0.4 + k * 0.6, -d / 2 - 1.05, fh + 0.5))
        b.box((0.30, 0.20, 0.12), (w * 0.8, 0.1, 0.1), (0, -d / 2 - 1.05, fh + 0.95))
    b.box(tuple(c * 0.9 for c in wall), (w + 0.5, d + 0.5, 0.3), (0, 0, h + 0.15))
    hip_roof(b, roof, w + 0.9, d + 0.9, h + 0.3, min(w, d) * (0.32 if p.get('roof', 'hip') == 'hip' else 0.5))
    m['h'] = h


def generic(b, m, p):
    w, d, h = m['w'], m['d'], max(6.0, m.get('h') or 12.0)
    wall = hex_rgb(m.get('wall_color'), TRAVERTINE if m.get('kind') not in ('church', 'bath', 'basilica') else BRICK)
    b.box(TRAVERTINE, (w + 1.2, d + 1.2, 1.0), (0, 0, 0.5))
    b.box(wall, (w, d, h), (0, 0, 1 + h / 2))
    b.box(MARBLE, (w + 0.8, d + 0.8, 0.9), (0, 0, 1 + h + 0.45))
    rows = max(1, int(h / 6))
    for face, (span, pos, rot) in {'front': (w, -d / 2 - 0.05, 0.0), 'back': (w, d / 2 + 0.05, 0.0), 'left': (d, -w / 2 - 0.05, math.pi / 2), 'right': (d, w / 2 + 0.05, math.pi / 2)}.items():
        n = max(1, int(span / 5))
        for r in range(rows):
            for k in range(n):
                off = (-0.5 + (k + 0.5) / n) * span
                x, y = (off, pos) if rot == 0 else (pos, off)
                b.box(DARK, (1.4, 0.2, 2.4), (x, y, 1 + h * (r + 0.55) / rows), rot)
    b.box((0.23, 0.15, 0.09), (2.6, 0.3, 3.6), (0, -d / 2 - 0.1, 2.8))
    hip_roof(b, TILE, w + 1.0, d + 1.0, 1 + h + 0.9, min(w, d) * 0.25)
    m['h'] = h + 1


SIZE = {'small': 0.6, 'medium': 1.0, 'large': 1.5}


def anchor(m, position):
    w, d, h = m['w'], m['d'], m['h']
    spots = {'front': [(0, -d / 2 - 2, 0)], 'back': [(0, d / 2 + 2, 0)], 'left': [(-w / 2 - 2, 0, 0)], 'right': [(w / 2 + 2, 0, 0)], 'top': [(0, 0, h)],
             'corners': [(sx * w / 2, sy * d / 2, 0) for sx in (-1, 1) for sy in (-1, 1)], 'around': [(math.cos(a) * (w / 2 + 3), math.sin(a) * (d / 2 + 3), 0) for a in [k * math.pi / 4 for k in range(8)]]}
    return spots.get(position, spots['front'])


def add_tower(b, m, x, y, z, k, color, bell=False):
    r = 2.5 * k
    th = m['h'] * (0.7 if z else 1.25) * k + (6 if bell else 0)
    b.box(color, (r * 2, r * 2, th), (x, y, z + th / 2))
    if bell:
        for s in (-1, 1):
            b.box(DARK, (r * 0.7, 0.3, r * 1.2), (x, y + s * r, z + th - r * 1.1))
            b.box(DARK, (0.3, r * 0.7, r * 1.2), (x + s * r, y, z + th - r * 1.1))
    b.cyl(TILE, r * 1.5, 0.1, r * 2.2, (x, y, z + th + r * 1.1), 4, math.pi / 4)


def apply_additions(b, m, additions):
    for add in additions or []:
        kind = add.get('kind')
        k = SIZE.get(add.get('size'), 1.0)
        color = hex_rgb(add.get('color'), MARBLE)
        count = max(1, min(16, int(add.get('count') or 1)))
        spots = anchor(m, add.get('position', 'front'))
        w, d, h = m['w'], m['d'], m['h']
        if kind in ('tower', 'bell_tower'):
            for x, y, z in spots[:count]:
                add_tower(b, m, x, y, z, k, color if add.get('color') else TRAVERTINE, kind == 'bell_tower')
        elif kind == 'dome':
            r = min(w, d) * 0.28 * k
            b.cyl(color if add.get('color') else TRAVERTINE, r * 1.05, r * 1.05, r * 0.5, (0, 0, h + r * 0.25), 32)
            b.sphere(color if add.get('color') else (0.62, 0.66, 0.66), r, (0, 0, h + r * 0.5), (1, 1, 0.9))
        elif kind == 'statues':
            for i in range(count):
                x = (-0.5 + (i + 0.5) / count) * w
                b.box(MARBLE, (1.0, 1.0, 0.8), (x, -d / 2 + 0.6, h + 0.4))
                b.cyl(color, 0.35 * k, 0.45 * k, 2.2 * k, (x, -d / 2 + 0.6, h + 0.8 + 1.1 * k), 10)
                b.sphere(color, 0.3 * k, (x, -d / 2 + 0.6, h + 0.8 + 2.4 * k))
        elif kind in ('colonnade', 'portico'):
            n = max(4, count if count > 1 else int(w / 3.5))
            depth = 4 * k
            b.box(MARBLE, (w + 1, depth + 1, 0.4), (0, -d / 2 - depth / 2, 0.2))
            for i in range(n):
                x = (-0.5 + i / (n - 1)) * (w - 1)
                b.cyl(color, 0.45 * k, 0.55 * k, min(h, 9 * k), (x, -d / 2 - depth + 0.6, 0.4 + min(h, 9 * k) / 2), 14)
            b.box(MARBLE, (w + 1, depth + 1, 0.8), (0, -d / 2 - depth / 2, 0.4 + min(h, 9 * k) + 0.4))
            if kind == 'portico':
                b.gable(TILE, w + 1, depth + 1, 0.4 + min(h, 9 * k) + 0.8, 2.5 * k)
        elif kind == 'balcony':
            for i in range(count):
                z = h * (0.4 + 0.3 * i / max(1, count))
                b.box((0.36, 0.25, 0.15), (w * 0.7, 1.4 * k, 0.2), (0, -d / 2 - 0.7 * k, z))
                b.box((0.30, 0.20, 0.12), (w * 0.7, 0.12, 1.0), (0, -d / 2 - 1.4 * k, z + 0.5))
        elif kind == 'arcade':
            n = max(3, count if count > 1 else int(w / 4))
            pitch = w / n
            for i in range(n + 1):
                b.box(color, (0.9, 1.2, 4.2 * k), (-w / 2 + i * pitch, -d / 2 - 0.6, 2.1 * k))
            for i in range(n):
                b.arch(color, (-w / 2 + (i + 0.5) * pitch, -d / 2 - 0.6, 4.2 * k), (pitch - 0.9) / 2, 0.6, 1.2, 0.0, 9)
        elif kind == 'stairs':
            for i in range(int(6 * k)):
                b.box(TRAVERTINE, (w * 0.5, 0.5, 0.25), (0, -d / 2 - 0.25 - i * 0.5, 0.125 + (int(6 * k) - i - 1) * 0.25))
        elif kind == 'banner':
            for i in range(count):
                x = (-0.5 + (i + 0.5) / count) * w
                b.box(color if add.get('color') else (0.55, 0.12, 0.15), (1.4 * k, 0.08, 4 * k), (x, -d / 2 - 0.1, h * 0.7))
        elif kind == 'fountain':
            x, y, _ = anchor(m, add.get('position', 'front'))[0]
            b.cyl(MARBLE, 3 * k, 3.2 * k, 0.8, (x, y - 3 * k, 0.4), 24)
            b.cyl((0.30, 0.56, 0.71), 2.8 * k, 2.8 * k, 0.1, (x, y - 3 * k, 0.78), 24)
            b.cyl(MARBLE, 0.4, 0.6, 2.2 * k, (x, y - 3 * k, 1.1 * k + 0.4), 12)
        elif kind == 'obelisk':
            x, y, _ = anchor(m, add.get('position', 'front'))[0]
            b.box(MARBLE, (2.4, 2.4, 1.6), (x, y - 4, 0.8))
            b.cyl((0.77, 0.67, 0.53), 0.8 * k, 1.3 * k, 18 * k, (x, y - 4, 1.6 + 9 * k), 4, math.pi / 4)
        elif kind == 'crenellation':
            for i in range(int((w + d) * 2 / 2.2)):
                t = i * 2.2
                x, y = ((-w / 2 + t, -d / 2) if t < w else (w / 2, -d / 2 + t - w) if t < w + d else (w / 2 - (t - w - d), d / 2) if t < 2 * w + d else (-w / 2, d / 2 - (t - 2 * w - d)))
                b.box(color if add.get('color') else TRAVERTINE, (1.1, 1.1, 1.3), (x, y, h + 0.65))
        elif kind == 'roof_garden':
            b.box((0.36, 0.50, 0.24), (w * 0.8, d * 0.8, 0.4), (0, 0, h + 0.2))
            for i in range(count * 3):
                b.sphere(LEAF, 1.0 * k, ((b.rand.random() - 0.5) * w * 0.7, (b.rand.random() - 0.5) * d * 0.7, h + 1.2), (1, 1, 0.8))
        elif kind == 'vines':
            for i in range(count * 6):
                face = b.rand.choice([(-d / 2 - 0.15, 0.0), (d / 2 + 0.15, 0.0)])
                b.box(LEAF, (1.0 + b.rand.random() * 2, 0.2, 2 + b.rand.random() * h * 0.6), ((b.rand.random() - 0.5) * w, face[0], 1 + b.rand.random() * h * 0.3))
        elif kind == 'windows':
            for r in range(count):
                for i in range(max(2, int(w / 3))):
                    x = (-0.5 + (i + 0.5) / max(2, int(w / 3))) * w
                    b.box(DARK, (1.0, 0.2, 1.8), (x, -d / 2 - 0.08, h * (0.3 + 0.5 * r / max(1, count))))
                    b.arch(MARBLE, (x, -d / 2 - 0.12, h * (0.3 + 0.5 * r / max(1, count)) + 0.9), 0.55, 0.2, 0.25, 0.0, 6)
        elif kind == 'buttress':
            for i in range(max(3, count)):
                y = (-0.5 + (i + 0.5) / max(3, count)) * d
                for s in (-1, 1):
                    b.box(color if add.get('color') else TRAVERTINE, (2.0 * k, 1.2, h * 0.7), (s * (w / 2 + 1.0 * k), y, h * 0.35))
        elif kind == 'apse':
            r = min(w, d) * 0.3 * k
            b.cyl(color if add.get('color') else BRICK, r, r, h * 0.7, (0, d / 2 + r * 0.2, h * 0.35), 24)
            b.sphere(TILE, r, (0, d / 2 + r * 0.2, h * 0.7), (1, 1, 0.6))


BUILDERS = {'amphitheater': colosseum, 'temple': temple, 'triumphal_arch': triumphal_arch, 'palace': palace, 'house': house}


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    spec = json.loads(open(args[0]).read())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    b = Builder(spec.get('state', 0.0), spec.get('seed', 1))
    BUILDERS.get(spec['kind'], generic)(b, spec, spec.get('params', {}))
    apply_additions(b, spec, spec.get('params', {}).get('additions', []))
    b.finish(args[1])


main()
