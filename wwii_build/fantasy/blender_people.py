import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

BONES = [
    ('hips', (0, 0, 0.95), (0, 0, 1.05), None),
    ('spine', (0, 0, 1.05), (0, 0, 1.40), 'hips'),
    ('head', (0, 0, 1.45), (0, 0, 1.75), 'spine'),
    ('upper_arm.L', (0.21, 0, 1.39), (0.23, 0, 1.12), 'spine'),
    ('forearm.L', (0.23, 0, 1.12), (0.24, 0, 0.88), 'upper_arm.L'),
    ('upper_arm.R', (-0.21, 0, 1.39), (-0.23, 0, 1.12), 'spine'),
    ('forearm.R', (-0.23, 0, 1.12), (-0.24, 0, 0.88), 'upper_arm.R'),
    ('thigh.L', (0.09, 0, 0.95), (0.09, 0, 0.52), 'hips'),
    ('shin.L', (0.09, 0, 0.52), (0.09, 0, 0.08), 'thigh.L'),
    ('thigh.R', (-0.09, 0, 0.95), (-0.09, 0, 0.52), 'hips'),
    ('shin.R', (-0.09, 0, 0.52), (-0.09, 0, 0.08), 'thigh.R'),
]

SKINS = [(0.78, 0.58, 0.44), (0.66, 0.47, 0.34), (0.86, 0.68, 0.54), (0.55, 0.38, 0.27)]
HAIR = [(0.10, 0.07, 0.05), (0.20, 0.13, 0.08), (0.30, 0.22, 0.14), (0.45, 0.42, 0.40)]


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


BONE_NAMES = [b[0] for b in BONES]


class Body:
    def __init__(self):
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()
        self.color = self.bm.loops.layers.color.new('Col')

    def add(self, bone, color, fn, matrix):
        verts = fn(self.bm, matrix)['verts']
        group = BONE_NAMES.index(bone)
        for v in verts:
            v[self.deform][group] = 1.0
        for f in {f for v in verts for f in v.link_faces}:
            for loop in f.loops:
                loop[self.color] = (*color, 1.0)

    def box(self, bone, color, size, loc, rot=(0, 0, 0)):
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot[2], 4, 'Z') @ Matrix.Rotation(rot[1], 4, 'Y') @ Matrix.Rotation(rot[0], 4, 'X') @ Matrix.Diagonal((*size, 1))
        self.add(bone, color, lambda bm, m: bmesh.ops.create_cube(bm, size=1.0, matrix=m), mat)

    def cyl(self, bone, color, r1, r2, h, loc, segs=10, rot=(0, 0, 0), scale=(1, 1, 1)):
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot[2], 4, 'Z') @ Matrix.Rotation(rot[1], 4, 'Y') @ Matrix.Rotation(rot[0], 4, 'X') @ Matrix.Diagonal((*scale, 1))
        self.add(bone, color, lambda bm, m: bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r1, radius2=r2, depth=h, matrix=m), mat)

    def sphere(self, bone, color, r, loc, scale=(1, 1, 1)):
        mat = Matrix.Translation(Vector(loc)) @ Matrix.Diagonal((*scale, 1))
        self.add(bone, color, lambda bm, m: bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r, matrix=m), mat)

    def limb(self, bone, color, a, b, r1, r2):
        a, b = Vector(a), Vector(b)
        mid = (a + b) / 2
        d = b - a
        rot = d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        mat = Matrix.Translation(mid) @ rot
        self.add(bone, color, lambda bm, m: bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=r2, radius2=r1, depth=d.length, matrix=m), mat)


def base_body(b, skin, hair, tunic, sleeve, long_skirt, female):
    b.sphere('head', skin, 0.105, (0, 0, 1.6), (1, 1.05, 1.12))
    b.sphere('head', hair, 0.11, (0, 0.012, 1.645), (1.02, 1.05, 0.75))
    if female:
        b.sphere('head', hair, 0.06, (0, 0.1, 1.6))
    b.sphere('head', skin, 0.018, (0, -0.105, 1.59))
    b.cyl('spine', skin, 0.045, 0.04, 0.1, (0, 0, 1.47))
    b.cyl('spine', tunic, 0.17, 0.19, 0.42, (0, 0, 1.2), 12, scale=(1, 0.68, 1))
    bottom = 0.1 if long_skirt else 0.55
    b.cyl('hips', tunic, 0.19, 0.27 if long_skirt else 0.24, 1.0 - bottom, (0, 0, (1.0 + bottom) / 2), 14, scale=(1, 0.75, 1))
    for side, s in (('L', 1), ('R', -1)):
        b.limb(f'upper_arm.{side}', sleeve, (0.21 * s, 0, 1.38), (0.23 * s, 0, 1.12), 0.05, 0.045)
        b.limb(f'forearm.{side}', skin, (0.23 * s, 0, 1.12), (0.24 * s, 0, 0.9), 0.04, 0.035)
        b.sphere(f'forearm.{side}', skin, 0.04, (0.24 * s, 0, 0.86))
        b.limb(f'thigh.{side}', skin, (0.09 * s, 0, 0.92), (0.09 * s, 0, 0.52), 0.065, 0.055)
        b.limb(f'shin.{side}', skin, (0.09 * s, 0, 0.52), (0.09 * s, 0, 0.1), 0.05, 0.04)
        b.box(f'shin.{side}', (0.32, 0.20, 0.12), (0.09, 0.22, 0.06), (0.09 * s, -0.04, 0.035))


def dress(b, kind, p):
    skin, hair = p['skin'], p['hair']
    tunic = p.get('tunic', (0.7, 0.62, 0.48))
    if kind == 'senator':
        base_body(b, skin, hair, (0.92, 0.90, 0.84), (0.92, 0.90, 0.84), True, False)
        for x in (-0.06, 0.06):
            b.box('spine', (0.42, 0.08, 0.36), (0.035, 0.01, 0.4), (x, -0.13, 1.22))
        b.cyl('spine', (0.94, 0.93, 0.88), 0.26, 0.24, 0.18, (0, 0, 1.22), 14, rot=(0, 0.42, 0), scale=(1, 0.8, 1))
        b.box('spine', (0.94, 0.93, 0.88), (0.17, 0.08, 0.95), (0.12, -0.02, 0.98))
        b.box('spine', (0.42, 0.08, 0.36), (0.02, 0.085, 0.95), (0.205, -0.02, 0.98))
        b.box('hips', (0.94, 0.93, 0.88), (0.42, 0.06, 0.55), (0.02, -0.17, 0.62), (0.1, 0, 0.2))
    elif kind == 'citizen':
        base_body(b, skin, hair, tunic, tunic, False, False)
        b.cyl('hips', (0.35, 0.22, 0.12), 0.195, 0.195, 0.04, (0, 0, 1.0), 14, scale=(1, 0.72, 1))
        if p.get('clavus'):
            for x in (-0.07, 0.07):
                b.box('spine', (0.42, 0.08, 0.36), (0.018, 0.01, 0.4), (x, -0.13, 1.2))
        if p.get('cloak'):
            b.cyl('spine', p['cloak'], 0.2, 0.3, 0.62, (0, 0.01, 1.12), 14, scale=(1, 0.78, 1))
            b.sphere('head', p['cloak'], 0.08, (0, 0.11, 1.5), (1.2, 0.8, 0.6))
    elif kind == 'vigil':
        base_body(b, skin, hair, (0.42, 0.30, 0.20), (0.42, 0.30, 0.20), False, False)
        b.cyl('spine', (0.30, 0.24, 0.18), 0.2, 0.3, 0.6, (0, 0.01, 1.12), 14, scale=(1, 0.78, 1))
        b.cyl('forearm.R', (0.40, 0.28, 0.16), 0.02, 0.025, 0.55, (-0.24, -0.05, 0.98), 6, rot=(0.5, 0, 0))
        b.sphere('forearm.R', (1.0, 0.62, 0.18), 0.05, (-0.24, -0.17, 1.22))
        b.box('forearm.L', (0.45, 0.42, 0.40), (0.05, 0.05, 0.3), (0.26, 0, 0.75))
    elif kind == 'matron':
        base_body(b, skin, hair, p['stola'], p['stola'], True, True)
        b.box('spine', p['palla'], (0.46, 0.08, 0.7), (0, 0.13, 1.18), (0.12, 0, 0))
        b.cyl('head', p['palla'], 0.13, 0.15, 0.16, (0, 0.03, 1.66), 12, rot=(0.3, 0, 0), scale=(1, 1, 1))
        b.sphere('spine', (0.85, 0.68, 0.25), 0.02, (0, -0.12, 1.36))
    elif kind == 'woman':
        base_body(b, skin, hair, tunic, tunic, True, True)
        b.box('spine', p['palla'], (0.42, 0.07, 0.4), (0, 0.12, 1.3), (0.15, 0, 0))
    elif kind == 'slave':
        base_body(b, skin, hair, (0.45, 0.36, 0.25), skin, False, False)
        b.cyl('upper_arm.L', (0.70, 0.42, 0.25), 0.14, 0.06, 0.55, (0.26, 0.05, 1.55), 10, rot=(0, -0.5, 0))
    elif kind == 'soldier':
        base_body(b, skin, hair, (0.62, 0.12, 0.10), (0.62, 0.12, 0.10), False, False)
        b.cyl('spine', (0.55, 0.56, 0.58), 0.18, 0.2, 0.4, (0, 0, 1.21), 12, scale=(1, 0.72, 1))
        b.sphere('head', (0.60, 0.58, 0.52), 0.125, (0, 0, 1.64), (1, 1.05, 0.85))
        b.box('head', (0.70, 0.10, 0.08), (0.03, 0.22, 0.12), (0, 0, 1.78))
        b.box('spine', (0.58, 0.10, 0.09), (0.46, 0.05, 0.8), (0, 0.15, 1.05))
        b.cyl('forearm.R', (0.45, 0.32, 0.18), 0.015, 0.015, 2.1, (-0.24, -0.02, 1.2), 6)
        b.box('forearm.L', (0.62, 0.12, 0.10), (0.06, 0.55, 0.8), (0.3, -0.05, 0.95))
    elif kind == 'merchant':
        base_body(b, skin, hair, tunic, tunic, False, False)
        b.box('hips', (0.80, 0.74, 0.62), (0.36, 0.04, 0.42), (0, -0.19, 0.78))
        b.cyl('head', (0.55, 0.42, 0.25), 0.13, 0.11, 0.08, (0, 0, 1.72), 12)
    elif kind == 'child':
        base_body(b, skin, hair, tunic, tunic, False, False)
        b.sphere('spine', (0.85, 0.68, 0.25), 0.025, (0, -0.13, 1.3))
    elif kind == 'vestal':
        base_body(b, skin, hair, (0.95, 0.95, 0.92), (0.95, 0.95, 0.92), True, True)
        b.cyl('head', (0.97, 0.97, 0.95), 0.13, 0.16, 0.22, (0, 0.03, 1.62), 12, rot=(0.25, 0, 0))
        b.box('head', (0.70, 0.14, 0.18), (0.24, 0.02, 0.04), (0, -0.11, 1.68))
    elif kind == 'bearer':
        base_body(b, skin, hair, (0.55, 0.12, 0.15), (0.55, 0.12, 0.15), False, False)


def armature():
    arm = bpy.data.armatures.new('rig')
    ob = bpy.data.objects.new('rig', arm)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    for name, head, tail, parent in BONES:
        e = arm.edit_bones.new(name)
        e.head, e.tail = head, tail
        if parent:
            e.parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


def key(ob, bone, frame, rx=0.0, rz=0.0, z=None):
    pb = ob.pose.bones[bone]
    pb.rotation_mode = 'XYZ'
    pb.rotation_euler = (rx, 0, rz)
    pb.keyframe_insert('rotation_euler', frame=frame)
    if z is not None:
        pb.location = (0, z, 0)
        pb.keyframe_insert('location', frame=frame)


def action(ob, name, frames, fn):
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ob.animation_data.action = act
    for f in frames:
        fn(f)
    track = ob.animation_data.nla_tracks.new()
    track.name = name
    track.strips.new(name, 1, act)
    ob.animation_data.action = None


def animate(ob, kind):
    ob.animation_data_create()
    stiff = 0.42 if kind in ('senator', 'matron', 'woman', 'vestal') else 1.0
    carry = kind == 'slave'

    def walk(f):
        t = (f - 1) / 24 * 2 * math.pi
        s = math.sin(t)
        key(ob, 'thigh.L', f, 0.45 * s * stiff)
        key(ob, 'thigh.R', f, -0.45 * s * stiff)
        key(ob, 'shin.L', f, -max(0.0, -math.sin(t + 0.6)) * 0.7 * stiff)
        key(ob, 'shin.R', f, -max(0.0, math.sin(t + 0.6)) * 0.7 * stiff)
        key(ob, 'upper_arm.L', f, -0.35 * s * stiff if not carry else -2.6, 0.0)
        key(ob, 'upper_arm.R', f, 0.35 * s * stiff)
        key(ob, 'forearm.L', f, -0.25 if not carry else -0.3)
        key(ob, 'forearm.R', f, -0.25)
        key(ob, 'hips', f, 0.0, 0.0, 0.025 * abs(math.cos(t)))
        key(ob, 'spine', f, 0.04, 0.06 * s)
        key(ob, 'head', f, -0.03, -0.03 * s)

    def idle(f):
        t = (f - 1) / 48 * 2 * math.pi
        key(ob, 'spine', f, 0.02 * math.sin(t), 0.03 * math.sin(t * 0.5))
        key(ob, 'head', f, 0.03 * math.sin(t * 1.3), 0.12 * math.sin(t * 0.5))
        key(ob, 'upper_arm.L', f, -0.05 + 0.03 * math.sin(t) if not carry else -2.6)
        key(ob, 'upper_arm.R', f, 0.05 - 0.03 * math.sin(t))
        key(ob, 'forearm.L', f, -0.15 if not carry else -0.3)
        key(ob, 'forearm.R', f, -0.15)
        for side in ('L', 'R'):
            key(ob, f'thigh.{side}', f, 0.0)
            key(ob, f'shin.{side}', f, 0.0)
        key(ob, 'hips', f, 0.0, 0.0, 0.0)

    def talk(f):
        t = (f - 1) / 48 * 2 * math.pi
        key(ob, 'upper_arm.R', f, -0.45 - 0.18 * math.sin(t * 2), -0.15)
        key(ob, 'forearm.R', f, -0.75 - 0.3 * math.sin(t * 2 + 1))
        key(ob, 'upper_arm.L', f, -0.1 if not carry else -2.6)
        key(ob, 'forearm.L', f, -0.2)
        key(ob, 'head', f, 0.08 * math.sin(t * 3), 0.15 * math.sin(t))
        key(ob, 'spine', f, 0.03, 0.05 * math.sin(t))
        for side in ('L', 'R'):
            key(ob, f'thigh.{side}', f, 0.0)
            key(ob, f'shin.{side}', f, 0.0)
        key(ob, 'hips', f, 0.0, 0.0, 0.0)

    def sit(f):
        t = (f - 1) / 48 * 2 * math.pi
        for side in ('L', 'R'):
            key(ob, f'thigh.{side}', f, 1.45)
            key(ob, f'shin.{side}', f, -1.45)
        key(ob, 'upper_arm.L', f, 0.45)
        key(ob, 'upper_arm.R', f, 0.45 + 0.08 * math.sin(t))
        key(ob, 'forearm.L', f, 0.9)
        key(ob, 'forearm.R', f, 0.9)
        key(ob, 'head', f, 0.03 * math.sin(t), 0.2 * math.sin(t * 0.5))
        key(ob, 'spine', f, -0.05)
        key(ob, 'hips', f, 0.0, 0.0, 0.0)

    action(ob, 'walk', range(1, 26, 2), walk)
    action(ob, 'idle', range(1, 50, 4), idle)
    action(ob, 'talk', range(1, 50, 3), talk)
    action(ob, 'sit', range(1, 50, 6), sit)


def paint(me, bm):
    bm.to_mesh(me)
    mat = bpy.data.materials.new('cloth')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get('Principled BSDF')
    attr = nodes.new('ShaderNodeVertexColor')
    attr.layer_name = 'Col'
    mat.node_tree.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.85
    me.materials.append(mat)


def build(spec, out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig = armature()
    body = Body()
    dress(body, spec['kind'], spec)
    me = bpy.data.meshes.new(spec['name'])
    paint(me, body.bm)
    body.bm.free()
    mo = bpy.data.objects.new(spec['name'], me)
    bpy.context.scene.collection.objects.link(mo)
    for bone in BONE_NAMES:
        mo.vertex_groups.new(name=bone)
    mo.parent = rig
    mo.modifiers.new('rig', 'ARMATURE').object = rig
    scale = spec.get('scale', 1.0)
    rig.scale = (scale, scale, scale)
    animate(rig, spec['kind'])
    bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animation_mode='NLA_TRACKS', export_apply=False)


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    specs = json.loads(Path(args[0]).read_text())
    out_dir = Path(args[1])
    for spec in specs:
        for k in ('skin', 'hair', 'tunic', 'stola', 'palla', 'cloak'):
            if isinstance(spec.get(k), str):
                spec[k] = rgb(spec[k])
        build(spec, str(out_dir / f"{spec['name']}.glb"))


main()
