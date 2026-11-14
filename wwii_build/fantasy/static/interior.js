import * as THREE from 'three';

import { buildItem, solidKinds } from './furniture.js';
import { surfaceTexture } from './textures.js';

const THICK = 0.2;
const DOOR_H = 3.4;
const TONES = { warm: '#ffc98a', cool: '#bcd4ff', neutral: '#fff1d6' };
const WALL_SIGN = { n: 1, s: -1, e: 1, w: -1 };
const WINDOW_SIZES = { small: { w: 0.9, h: 1.3, sill: 1.5 }, normal: { w: 1.4, h: 2.2, sill: 1.0 }, large: { w: 2.3, h: 3.5, sill: 0.6 } };

const wallLength = (room, wall) => (wall === 'n' || wall === 's' ? room.w : room.d);

const apseWidth = (room) => Math.min(room.w * 0.45, 12);

const openings = (room) => room.doors.concat(room.apse ? [{ wall: room.apse, pos: 0, width: apseWidth(room), height: Math.min(room.h - 1.2, apseWidth(room) / 2 + room.h * 0.35), apse: true }] : []);

const hasDoor = (room, wall) => room.doors.some((d) => d.wall === wall);

const windowSlots = (room, design) => {
  const count = Number(design.windows.count) || 0;
  const sides = ['e', 'w'].flatMap((wall) => Array.from({ length: count }, (_, k) => ({ wall, along: ((k + 1) / (count + 1)) * room.d - room.d / 2 })));
  const north = hasDoor(room, 'n') || room.apse || !count
    ? []
    : Array.from({ length: Math.max(1, count - 1) }, (_, k) => ({ wall: 'n', along: ((k + 1) / (count + 1)) * room.w - room.w / 2 }));
  return sides.concat(north).filter((s) => !openings(room).some((d) => d.wall === s.wall && Math.abs(d.pos - s.along) < d.width / 2 + 2));
};

const windowDims = (room, design, wall) => {
  const base = WINDOW_SIZES[design.windows.size] || WINDOW_SIZES.normal;
  const count = Math.max(1, Number(design.windows.count) || 1);
  const spacing = wallLength(room, wall) / (count + 1);
  const width = Math.min(base.w, spacing - 0.6);
  const height = Math.min(base.h, room.h - base.sill - 0.6);
  return { w: Math.max(0.5, width), h: Math.max(0.8, height), sill: base.sill };
};

const holePath = (style, u, dims) => {
  const path = new THREE.Path();
  const x0 = u - dims.w / 2;
  const x1 = u + dims.w / 2;
  const y0 = dims.sill;
  const y1 = dims.sill + dims.h;
  return ({
    round: () => {
      const r = Math.min(dims.w, dims.h) / 2;
      path.absarc(u, y0 + dims.h / 2, r, 0, Math.PI * 2, true);
      return path;
    },
    arched: () => {
      const r = dims.w / 2;
      path.moveTo(x0, y0);
      path.lineTo(x1, y0);
      path.lineTo(x1, y1 - r);
      path.absarc(u, y1 - r, r, 0, Math.PI, false);
      path.lineTo(x0, y0);
      return path;
    },
    rect: () => {
      path.moveTo(x0, y0);
      path.lineTo(x1, y0);
      path.lineTo(x1, y1);
      path.lineTo(x0, y1);
      path.lineTo(x0, y0);
      return path;
    },
  }[style] || (() => holePath('rect', u, dims)))();
};

const wallOutline = (room, design, wall) => {
  const length = wallLength(room, wall);
  const doors = openings(room).filter((d) => d.wall === wall).sort((a, b) => a.pos * WALL_SIGN[wall] - b.pos * WALL_SIGN[wall]);
  const vault = design.ceiling.style === 'vaulted' && (wall === 'n' || wall === 's');
  const shape = new THREE.Shape();
  shape.moveTo(-length / 2, 0);
  doors.forEach((d) => {
    const u = d.pos * WALL_SIGN[wall];
    shape.lineTo(u - d.width / 2, 0);
    shape.lineTo(u - d.width / 2, d.height || DOOR_H);
    shape.lineTo(u + d.width / 2, d.height || DOOR_H);
    shape.lineTo(u + d.width / 2, 0);
  });
  shape.lineTo(length / 2, 0);
  shape.lineTo(length / 2, room.h);
  if (vault) {
    shape.absellipse(0, room.h, length / 2, Math.min(2.6, length / 4), 0, Math.PI, false);
  } else {
    shape.lineTo(-length / 2, room.h);
  }
  shape.lineTo(-length / 2, 0);
  return shape;
};

const wallPlacement = (room) => ({
  n: { pos: [0, 0, -room.d / 2], rot: 0 },
  s: { pos: [0, 0, room.d / 2], rot: Math.PI },
  e: { pos: [room.w / 2, 0, 0], rot: -Math.PI / 2 },
  w: { pos: [-room.w / 2, 0, 0], rot: Math.PI / 2 },
});

const glassMaterial = (design, dims) => {
  const stained = design.windows.stained;
  return stained
    ? new THREE.MeshBasicMaterial({ map: surfaceTexture('stained', '#ffffff', 1 / dims.w, 1 / dims.h), side: THREE.DoubleSide })
    : new THREE.MeshBasicMaterial({ color: design.windows.color || '#e8d9a8', side: THREE.DoubleSide });
};

const buildWall = (room, design, wall) => {
  const group = new THREE.Group();
  const length = wallLength(room, wall);
  const outline = wallOutline(room, design, wall);
  const slots = windowSlots(room, design).filter((s) => s.wall === wall);
  const dims = windowDims(room, design, wall);
  slots.forEach((s) => outline.holes.push(holePath(design.windows.style, s.along * WALL_SIGN[wall], dims)));
  const geo = new THREE.ExtrudeGeometry(outline, { depth: THICK, bevelEnabled: false });
  geo.translate(0, 0, -THICK);
  const map = surfaceTexture(design.walls.material, design.walls.color, 0.25, 0.25);
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map, roughness: 0.9, side: THREE.DoubleSide }));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  slots.forEach((s) => {
    const u = s.along * WALL_SIGN[wall];
    const pane = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(holePath(design.windows.style, u, dims).getPoints(24))), glassMaterial(design, dims));
    pane.position.z = -THICK / 2;
    group.add(pane);
    const sill = new THREE.Mesh(new THREE.BoxGeometry(dims.w + 0.3, 0.1, THICK + 0.25), new THREE.MeshStandardMaterial({ color: '#4a3524', roughness: 0.6 }));
    sill.position.set(u, dims.sill - 0.05, -THICK / 2 + 0.05);
    group.add(sill);
  });
  room.doors.filter((d) => d.wall === wall).forEach((d) => {
    const u = d.pos * WALL_SIGN[wall];
    const frame = new THREE.MeshStandardMaterial({ color: '#3a2716', roughness: 0.5 });
    [-1, 1].forEach((s) => {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.22, DOOR_H, THICK + 0.2), frame);
      post.position.set(u + (s * d.width) / 2, DOOR_H / 2, -THICK / 2);
      group.add(post);
    });
    const lintel = new THREE.Mesh(new THREE.BoxGeometry(d.width + 0.5, 0.26, THICK + 0.2), frame);
    lintel.position.set(u, DOOR_H + 0.1, -THICK / 2);
    group.add(lintel);
  });
  const place = wallPlacement(room)[wall];
  group.position.set(...place.pos);
  group.rotation.y = place.rot;
  group.userData.length = length;
  return group;
};

const buildFloor = (room, design) => {
  const tile = design.floor.material === 'wood' ? 4 : 3;
  const map = surfaceTexture(design.floor.material, design.floor.color, room.w / tile, room.d / tile);
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(room.w, room.d),
    new THREE.MeshStandardMaterial({ map, roughness: design.floor.material === 'marble' ? 0.18 : 0.8, metalness: design.floor.material === 'marble' ? 0.1 : 0 }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.receiveShadow = true;
  return mesh;
};

const buildCeiling = (room, design) => {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color: design.ceiling.color || '#cfc8b8', roughness: 0.95, side: THREE.DoubleSide });
  const flat = new THREE.Mesh(new THREE.PlaneGeometry(room.w, room.d), material);
  flat.rotation.x = Math.PI / 2;
  flat.position.y = room.h;
  const rise = Math.min(2.6, room.w / 4);
  const vault = new THREE.Mesh(new THREE.CylinderGeometry(room.w / 2, room.w / 2, room.d, 32, 1, true, -Math.PI / 2, Math.PI), material);
  vault.rotation.x = -Math.PI / 2;
  vault.scale.set(1, 1, rise / (room.w / 2));
  vault.position.y = room.h;
  const beams = Array.from({ length: Math.max(3, Math.round(room.d / 3)) }, (_, k) => {
    const beam = new THREE.Mesh(new THREE.BoxGeometry(room.w, 0.28, 0.3), new THREE.MeshStandardMaterial({ color: '#3a2716', roughness: 0.6 }));
    beam.position.set(0, room.h - 0.14, ((k + 0.5) / Math.max(3, Math.round(room.d / 3)) - 0.5) * room.d);
    return beam;
  });
  const coffers = Array.from({ length: Math.round(room.w / 3) + 1 }, (_, k) => {
    const beam = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.45, room.d), new THREE.MeshStandardMaterial({ color: '#b8ab8e', roughness: 0.7 }));
    beam.position.set(-room.w / 2 + (k * room.w) / Math.round(room.w / 3), room.h - 0.22, 0);
    return beam;
  }).concat(Array.from({ length: Math.round(room.d / 3) + 1 }, (_, k) => {
    const beam = new THREE.Mesh(new THREE.BoxGeometry(room.w, 0.45, 0.35), new THREE.MeshStandardMaterial({ color: '#b8ab8e', roughness: 0.7 }));
    beam.position.set(0, room.h - 0.22, -room.d / 2 + (k * room.d) / Math.round(room.d / 3));
    return beam;
  }));
  const parts = { vaulted: [vault], beams: [flat, ...beams], flat: [flat], coffered: [flat, ...coffers], open: [] }[design.ceiling.style] || [flat];
  parts.forEach((p) => group.add(p));
  return group;
};

const itemTransform = (room, item) =>
  item.kind === 'curtains'
    ? {
        n: { x: item.along, z: -room.d / 2 + 0.05, rot: 0 },
        s: { x: item.along, z: room.d / 2 - 0.05, rot: Math.PI },
        e: { x: room.w / 2 - 0.05, z: item.along, rot: -Math.PI / 2 },
        w: { x: -room.w / 2 + 0.05, z: item.along, rot: Math.PI / 2 },
      }[item.wall]
    : { x: item.x, z: item.z, rot: item.rot };

const mountItems = (room, design) => {
  const group = new THREE.Group();
  design.items.forEach((item) => {
    const mesh = buildItem(item);
    const t = itemTransform(room, item);
    mesh.position.set(t.x, item.y || 0, t.z);
    mesh.rotation.y = t.rot;
    group.add(mesh);
  });
  return group;
};

const roomLight = (room, design) => {
  const light = new THREE.PointLight(TONES[design.light.tone] || TONES.neutral, 38 * design.light.intensity, Math.max(room.w, room.d) * 1.6, 1.4);
  light.position.set(0, Math.max(2, room.h - 1.2), 0);
  return light;
};

const buildApse = (room, design) => {
  const group = new THREE.Group();
  const r = apseWidth(room) / 2;
  const H = Math.min(room.h - 1.2, r + room.h * 0.35);
  const map = surfaceTexture(design.walls.material, design.walls.color, 0.25, 0.25);
  const wallMat = new THREE.MeshStandardMaterial({ map, roughness: 0.85, side: THREE.DoubleSide });
  const shell = new THREE.Mesh(new THREE.CylinderGeometry(r, r, H, 24, 1, true, Math.PI / 2, Math.PI), wallMat);
  shell.position.set(0, H / 2, 0);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 10, Math.PI, Math.PI, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: '#c9a24a', roughness: 0.4, metalness: 0.3, side: THREE.DoubleSide }));
  dome.position.set(0, H, 0);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(r, 24, 0, Math.PI), new THREE.MeshStandardMaterial({ map: surfaceTexture(design.floor.material, design.floor.color, 1, 1), roughness: 0.4 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0.01;
  group.add(shell, dome, floor);
  const place = { n: [0, -room.d / 2, 0], s: [0, room.d / 2, Math.PI], e: [room.w / 2, 0, -Math.PI / 2], w: [-room.w / 2, 0, Math.PI / 2] }[room.apse];
  group.position.set(place[0], 0, place[1]);
  group.rotation.y = place[2];
  return group;
};

export const buildRoomGroup = (room, design, local) => {
  const group = new THREE.Group();
  room.apse && group.add(buildApse(room, design));
  group.add(buildFloor(room, design));
  group.add(buildCeiling(room, design));
  ['n', 's', 'e', 'w'].forEach((wall) => group.add(buildWall(room, design, wall)));
  group.add(mountItems(room, design));
  group.add(roomLight(room, design));
  group.position.set(local ? 0 : room.cx, 0, local ? 0 : room.cz);
  group.userData.roomId = room.id;
  return group;
};

const wallColliders = (room) => {
  const pad = 0.5;
  const cx = room.cx;
  const cz = room.cz;
  const split = (wall, lo, hi) => {
    const gaps = openings(room).filter((d) => d.wall === wall).map((d) => [d.pos - d.width / 2 + 0.25, d.pos + d.width / 2 - 0.25]).sort((a, b) => a[0] - b[0]);
    const edges = [lo, ...gaps.flat(), hi];
    return Array.from({ length: edges.length / 2 }, (_, i) => [edges[i * 2], edges[i * 2 + 1]]).filter(([a, b]) => b - a > 0.05);
  };
  const ns = ['n', 's'].flatMap((wall) =>
    split(wall, -room.w / 2 - THICK, room.w / 2 + THICK).map(([a, b]) => ({
      minx: cx + a, maxx: cx + b,
      minz: wall === 'n' ? cz - room.d / 2 - THICK - pad : cz + room.d / 2,
      maxz: wall === 'n' ? cz - room.d / 2 : cz + room.d / 2 + THICK + pad,
    })),
  );
  const ew = ['e', 'w'].flatMap((wall) =>
    split(wall, -room.d / 2 - THICK, room.d / 2 + THICK).map(([a, b]) => ({
      minx: wall === 'e' ? cx + room.w / 2 : cx - room.w / 2 - THICK - pad,
      maxx: wall === 'e' ? cx + room.w / 2 + THICK + pad : cx - room.w / 2,
      minz: cz + a, maxz: cz + b,
    })),
  );
  return ns.concat(ew);
};

const itemColliders = (room, design) =>
  design.items
    .filter((it) => solidKinds.has(it.kind) && it.kind !== 'chair')
    .map((it) => {
      const c = Math.abs(Math.cos(it.rot));
      const s = Math.abs(Math.sin(it.rot));
      const hx = (c * it.w + s * it.d) / 2;
      const hz = (s * it.w + c * it.d) / 2;
      return { minx: room.cx + it.x - hx, maxx: room.cx + it.x + hx, minz: room.cz + it.z - hz, maxz: room.cz + it.z + hz };
    });

const apseColliders = (room) => {
  if (!room.apse) return [];
  const r = apseWidth(room) / 2;
  const base = { n: [0, -1], s: [0, 1], e: [1, 0], w: [-1, 0] }[room.apse];
  const cx = room.cx + (base[0] * room.w) / 2;
  const cz = room.cz + (base[1] * room.d) / 2;
  return Array.from({ length: 9 }, (_, k) => {
    const a = (k / 8) * Math.PI - Math.PI / 2;
    const ox = Math.sin(a) * (r + 0.3);
    const oz = Math.cos(a) * (r + 0.3);
    const x = cx + (base[1] !== 0 ? ox : base[0] * oz);
    const z = cz + (base[1] !== 0 ? base[1] * oz : ox);
    return { minx: x - 0.6, maxx: x + 0.6, minz: z - 0.6, maxz: z + 0.6 };
  });
};

export const interiorColliders = (rooms, designs) => rooms.flatMap((room) => wallColliders(room).concat(apseColliders(room), itemColliders(room, designs[room.id] || { items: [] })));

export const buildInterior = (rooms, designs) => {
  const root = new THREE.Group();
  rooms.forEach((room) => designs[room.id] && root.add(buildRoomGroup(room, designs[room.id], false)));
  root.add(new THREE.AmbientLight('#ffffff', 0.55));
  rooms.some((r) => r.open) && root.add(new THREE.HemisphereLight('#cfe0f0', '#8a7a5a', 1.1));
  return root;
};

export const roomAt = (rooms, x, z) => rooms.find((r) => Math.abs(x - r.cx) <= r.w / 2 + 0.2 && Math.abs(z - r.cz) <= r.d / 2 + 0.2) || null;

export const exitDoor = (rooms) => {
  const room = rooms.find((r) => r.doors.some((d) => d.exit));
  const door = room.doors.find((d) => d.exit);
  return { x: room.cx + door.pos, z: room.cz + room.d / 2, width: door.width };
};
