import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';

import { box, cyl, merge, put, rng } from './geom.js';

const NEAR = 78;
const FAR = 330;
const MAX_SKINNED = 130;
const PER_TYPE = 30;
const VEHICLE_NEAR = 190;
const CARGO_COLORS = { amphorae: '#b5653a', grain: '#cdb88c', stone: '#ebe6dc', timber: '#8a6038', bricks: '#a5532f', barrels: '#7a5230' };

const inHours = ([a, b], h) => (a <= b ? h >= a && h < b : h >= a || h < b);

const makePath = (pts) => {
  const cum = [0];
  for (let i = 1; i < pts.length; i += 1) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return { pts, cum, len: cum[cum.length - 1] };
};

const sampleOn = (path, agent, out) => {
  const { pts, cum } = path;
  let k = Math.min(agent.seg, pts.length - 2);
  while (k < pts.length - 2 && agent.s > cum[k + 1]) k += 1;
  while (k > 0 && agent.s < cum[k]) k -= 1;
  agent.seg = k;
  const a = pts[k];
  const b = pts[k + 1];
  const len = cum[k + 1] - cum[k] || 1;
  const t = Math.max(0, Math.min(1, (agent.s - cum[k]) / len));
  out.dx = (b[0] - a[0]) / len;
  out.dz = (b[1] - a[1]) / len;
  out.x = a[0] + (b[0] - a[0]) * t - out.dz * agent.lat;
  out.z = a[1] + (b[1] - a[1]) * t + out.dx * agent.lat;
  out.y = a[2] + (b[2] - a[2]) * t;
  return out;
};

const toWorld = (m, lx, lz) => ({ x: m.x + lx * Math.cos(m.rot) + lz * Math.sin(m.rot), z: m.z - lx * Math.sin(m.rot) + lz * Math.cos(m.rot) });

const weightedPicker = (items, weightOf, rand) => {
  const total = items.reduce((s, it) => s + weightOf(it), 0);
  return () => {
    let r = rand() * total;
    return items.find((it) => {
      r -= weightOf(it);
      return r <= 0;
    }) || items[items.length - 1];
  };
};

const impostorGeometry = () => merge([cyl(0.2, 0.27, 1.25, 7, '#ffffff', 0, 0.68, 0), put(new THREE.SphereGeometry(0.12, 7, 5), '#e2c2a8', 0, 1.6, 0), box(0.3, 0.12, 0.2, '#ffffff', 0, 1.35, 0)]);

const legGroup = (color, x, z, len, w) => {
  const g = new THREE.Group();
  g.position.set(x, len, z);
  const leg = new THREE.Mesh(new THREE.BoxGeometry(w, len, w), new THREE.MeshStandardMaterial({ color, roughness: 0.9 }));
  leg.position.y = -len / 2;
  leg.castShadow = true;
  g.add(leg);
  return g;
};

const animal = (kind) => {
  const ox = kind === 'ox';
  const color = ox ? '#b9b0a2' : '#5d4432';
  const g = new THREE.Group();
  const body = new THREE.Mesh(merge([
    box(ox ? 0.78 : 0.5, ox ? 0.82 : 0.6, ox ? 1.9 : 1.35, color, 0, ox ? 1.12 : 0.98, 0),
    box(ox ? 0.42 : 0.26, ox ? 0.46 : 0.5, ox ? 0.62 : 0.6, color, 0, ox ? 1.12 : 1.32, ox ? 1.18 : 0.88),
    ...(ox ? [cyl(0.03, 0.05, 0.42, 5, '#e8dcc0', 0.26, 1.4, 1.25).rotateZ(0.9), cyl(0.03, 0.05, 0.42, 5, '#e8dcc0', -0.26, 1.4, 1.25).rotateZ(-0.9)] : [box(0.06, 0.24, 0.06, color, 0.08, 1.62, 0.78), box(0.06, 0.24, 0.06, color, -0.08, 1.62, 0.78)]),
    box(0.06, 0.5, 0.06, color, 0, ox ? 0.95 : 0.8, ox ? -0.98 : -0.7),
  ]), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92 }));
  body.castShadow = true;
  g.add(body);
  const hip = ox ? 0.72 : 0.66;
  const legs = [[-1, 1], [1, 1], [-1, -1], [1, -1]].map(([sx, sz], i) => {
    const l = legGroup(color, sx * (ox ? 0.26 : 0.16), sz * (ox ? 0.72 : 0.5), hip, ox ? 0.15 : 0.1);
    l.userData.phase = i % 3 === 0 ? 0 : Math.PI;
    g.add(l);
    return l;
  });
  g.userData.legs = legs;
  return g;
};

const cargoParts = (kind, rand) => {
  const c = CARGO_COLORS[kind];
  const parts = [];
  if (kind === 'amphorae') Array.from({ length: 9 }).forEach((_, i) => parts.push(put(new THREE.CylinderGeometry(0.09, 0.2, 0.75, 8), c, -0.45 + (i % 3) * 0.45, 1.45, -0.9 + Math.floor(i / 3) * 0.6, 0, 1, 1, 1, 0.25)));
  if (kind === 'grain') Array.from({ length: 8 }).forEach((_, i) => parts.push(put(new THREE.SphereGeometry(0.32, 8, 6), c, -0.35 + (i % 2) * 0.7, 1.3 + (i > 5 ? 0.35 : 0), -0.9 + (i % 4) * 0.55, rand(), 1, 0.7, 1.2)));
  if (kind === 'stone') parts.push(box(1.1, 0.6, 1.2, c, 0, 1.4, -0.4), box(0.9, 0.5, 0.9, c, 0.05, 1.35, 0.75));
  if (kind === 'timber') Array.from({ length: 6 }).forEach((_, i) => parts.push(put(new THREE.CylinderGeometry(0.12, 0.12, 3.8, 7).rotateX(Math.PI / 2), c, -0.42 + (i % 3) * 0.42, 1.25 + Math.floor(i / 3) * 0.24, 0.1)));
  if (kind === 'bricks') Array.from({ length: 6 }).forEach((_, i) => parts.push(box(0.5, 0.3, 0.8, c, -0.3 + (i % 2) * 0.6, 1.25 + Math.floor(i / 4) * 0.3, -0.8 + (i % 3) * 0.8)));
  if (kind === 'barrels') Array.from({ length: 3 }).forEach((_, i) => parts.push(put(new THREE.CylinderGeometry(0.34, 0.34, 0.9, 10).rotateZ(Math.PI / 2), c, 0, 1.45, -0.9 + i * 0.9)));
  return parts;
};

const cartMesh = (cargo, rand) => {
  const g = new THREE.Group();
  const bed = new THREE.Mesh(merge([
    box(1.4, 0.14, 2.9, '#7a5634', 0, 1.0, 0), box(0.08, 0.35, 2.9, '#6a4a2c', 0.7, 1.22, 0), box(0.08, 0.35, 2.9, '#6a4a2c', -0.7, 1.22, 0),
    box(0.1, 0.1, 3.0, '#5a3d24', 0, 0.86, 2.6), box(1.5, 0.1, 0.1, '#5a3d24', 0, 1.25, 4.0), cyl(0.05, 0.05, 1.7, 6, '#5a3d24', 0, 0.55, 0).rotateZ(Math.PI / 2),
    box(0.05, 1.1, 0.05, '#4a3020', 0.6, 1.6, 1.4), ...cargoParts(cargo.kind, rand),
  ]), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }));
  bed.castShadow = true;
  g.add(bed);
  const wheels = [-0.82, 0.82].map((x) => {
    const w = new THREE.Mesh(merge([cyl(0.55, 0.55, 0.14, 14, '#5a3d24', 0, 0, 0), box(0.16, 1.0, 0.1, '#3f2a18', 0, 0, 0), box(0.16, 0.1, 1.0, '#3f2a18', 0, 0, 0)]).rotateZ(Math.PI / 2),
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }));
    w.position.set(x, 0.55, 0);
    w.castShadow = true;
    g.add(w);
    return w;
  });
  const beasts = (cargo.animal === 'ox' ? [-0.48, 0.48] : [0]).map((x) => {
    const a = animal(cargo.animal);
    a.position.set(x, 0, 3.3);
    g.add(a);
    return a;
  });
  const lantern = new THREE.Mesh(new THREE.SphereGeometry(0.11, 8, 6), new THREE.MeshStandardMaterial({ color: '#ffb050', emissive: '#ff9a30', emissiveIntensity: 0 }));
  lantern.position.set(0.6, 2.2, 1.4);
  g.add(lantern);
  g.userData = { wheels, beasts, lantern };
  return g;
};

const litterMesh = (curtain) => {
  const g = new THREE.Group();
  const mesh = new THREE.Mesh(merge([
    cyl(0.05, 0.05, 4.8, 6, '#5a3d24', 0.55, 1.36, 0).rotateX(Math.PI / 2), cyl(0.05, 0.05, 4.8, 6, '#5a3d24', -0.55, 1.36, 0).rotateX(Math.PI / 2),
    box(1.0, 0.12, 2.0, '#6a4a2c', 0, 1.42, 0), box(1.06, 0.08, 2.1, '#d8c39a', 0, 2.42, 0), box(1.0, 0.95, 0.06, curtain, 0, 1.93, 0.98), box(1.0, 0.95, 0.06, curtain, 0, 1.93, -0.98),
    box(0.04, 0.5, 2.0, curtain, 0.5, 2.15, 0), box(0.04, 0.5, 2.0, curtain, -0.5, 2.15, 0),
    ...[[-0.5, -0.98], [0.5, -0.98], [-0.5, 0.98], [0.5, 0.98]].map(([x, z]) => box(0.06, 1.0, 0.06, '#c9a24a', x, 1.92, z)),
    box(0.9, 0.2, 1.6, '#8a2a2a', 0, 1.55, 0),
  ]), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 }));
  mesh.castShadow = true;
  g.add(mesh);
  return g;
};

const boatMesh = (kind, rand) => {
  const g = new THREE.Group();
  const big = kind === 'caudicaria';
  const L = big ? 13 : kind === 'ferry' ? 7 : kind === 'sail' ? 8 : 5.5;
  const W = big ? 3.4 : kind === 'ferry' ? 3.6 : kind === 'sail' ? 2.2 : 1.5;
  const wood = '#5d4026';
  const parts = [box(W, 0.7, L, wood, 0, 0.15, 0), put(new THREE.ConeGeometry(W / 2, 1.6, 4).rotateX(Math.PI / 2).rotateZ(Math.PI / 4), wood, 0, 0.15, L / 2 + 0.7, 0, 1, 0.5, 1),
    box(W * 0.9, 0.06, L * 0.9, '#7a5a3a', 0, 0.52, 0)];
  if (big) {
    Array.from({ length: 14 }).forEach((_, i) => parts.push(put(new THREE.CylinderGeometry(0.1, 0.22, 0.8, 8), '#b5653a', -1 + (i % 3), 0.95, -4 + Math.floor(i / 3) * 1.6, 0, 1, 1, 1, 0.2)));
    parts.push(cyl(0.1, 0.12, 7, 6, '#4a3524', 0, 3.6, 3.5));
  }
  if (kind === 'sail') {
    parts.push(cyl(0.08, 0.1, 6, 6, '#4a3524', 0, 3.3, 0.8));
    parts.push(put(new THREE.PlaneGeometry(3.0, 3.2), '#e2d3b0', 0, 3.8, 0.85, Math.PI / 2));
  }
  if (kind === 'ferry') parts.push(box(0.06, 0.9, L, '#4a3524', W / 2, 0.9, 0), box(0.06, 0.9, L, '#4a3524', -W / 2, 0.9, 0));
  const crewColors = ['#cbb895', '#9c3b2e', '#6e5238', '#4b6283'];
  const crew = big ? 3 : kind === 'ferry' ? 5 : 2;
  Array.from({ length: crew }).forEach((_, i) => {
    const x = (rand() - 0.5) * W * 0.6;
    const z = (i / Math.max(1, crew - 1) - 0.5) * L * 0.6;
    parts.push(cyl(0.18, 0.24, 1.1, 7, crewColors[i % 4], x, 1.1, z), put(new THREE.SphereGeometry(0.12, 7, 5), '#b98a66', x, 1.78, z));
  });
  const hull = new THREE.Mesh(merge(parts), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, side: THREE.DoubleSide }));
  hull.castShadow = true;
  g.add(hull);
  const oars = kind === 'linter' || big ? [-1, 1].map((s) => {
    const p = new THREE.Group();
    p.position.set(s * W / 2, 0.8, big ? -2 : 0);
    const oar = new THREE.Mesh(merge([box(0.07, 0.07, 3.2, '#6a4a2c', 0, 0, 0), box(0.06, 0.3, 0.7, '#6a4a2c', 0, 0, 1.6)]), new THREE.MeshStandardMaterial({ vertexColors: true }));
    oar.rotation.set(0, s * 1.2, 0);
    oar.position.set(s * 1.3, -0.25, 0);
    p.add(oar);
    g.add(p);
    return p;
  }) : [];
  g.userData = { oars, length: L };
  return g;
};

export const createLife = ({ ext, scene, life, base, onReady }) => {
  const rand = rng(20260);
  const data = ext.data;
  const types = life.population.types;
  const typeIndex = Object.fromEntries(types.map((t, i) => [t.name, i]));
  const routes = life.routes.map((r) => ({ ...r, path: makePath(data.streets[r.street].pts.map((p) => [p[0], p[1], p[2]])), width: data.streets[r.street].width || 4 }));
  const routeByStreet = Object.fromEntries(routes.map((r) => [r.street, r]));
  const mainRoutes = life.carts.routes.map((sid) => routeByStreet[sid]).filter((r) => r && r.path.len > 40);
  const pickRoute = weightedPicker(routes, (r) => r.weight, rand);
  const walkerTypes = types.filter((t) => t.weight > 0 && !['bearer', 'vigil'].includes(t.name));
  const pickWalker = weightedPicker(walkerTypes, (t) => t.weight, rand);
  const shopperTypes = types.filter((t) => ['shopper', 'walker', 'porter'].includes(t.role) && !['senator', 'equestrian', 'soldier'].includes(t.name));
  const pickShopper = weightedPicker(shopperTypes, (t) => (t.role === 'shopper' ? 3 * t.weight : t.weight), rand);
  const gossipTypes = types.filter((t) => ['gossip', 'walker'].includes(t.role) && t.name !== 'child' && t.name !== 'porter');
  const pickGossip = weightedPicker(gossipTypes, (t) => (t.role === 'gossip' ? 3 * t.weight : t.weight), rand);
  const agents = [];
  const add = (a) => agents.push({ id: agents.length, seg: 0, lat: 0, on: false, slot: null, anim: 'walk', x: 0, y: 0, z: 0, yaw: 0, wake: rand(), timer: rand() * 8, ...a });

  Array.from({ length: life.agents }).forEach(() => {
    const t = pickWalker();
    const route = pickRoute();
    const speed = (t.name.startsWith('senator') ? 1.0 : t.name === 'child' ? 1.5 : t.role === 'porter' ? 1.05 : 1.25) * (0.85 + rand() * 0.3);
    add({ kind: 'walk', type: typeIndex[t.name], route, s: rand() * route.path.len, dir: rand() < 0.5 ? 1 : -1, speed, lat: (rand() - 0.5) * route.width * 0.7, hours: t.hours });
  });
  Array.from({ length: life.night.patrols }).forEach(() => {
    const route = mainRoutes[Math.floor(rand() * mainRoutes.length)] || pickRoute();
    add({ kind: 'walk', type: typeIndex.vigil, route, s: rand() * route.path.len, dir: rand() < 0.5 ? 1 : -1, speed: 1.0, lat: (rand() - 0.5) * 2, hours: types[typeIndex.vigil].hours, torch: true, wake: 0 });
  });
  life.markets.forEach((m) => {
    m.stalls.forEach(([lx, lz, face]) => {
      const t = rand() < 0.6 ? types[typeIndex[rand() < 0.5 ? 'merchant' : 'merchant_brown']] : pickShopper();
      const local = { x: lx, z: m.kind === 'market' ? lz : lz + (face ? 0.25 : -0.25) };
      const w = toWorld(m, local.x, local.z);
      const yaw = m.rot + (m.kind === 'market' ? Math.atan2(lx, lz - 3) : face ? Math.PI : 0);
      add({ kind: 'still', type: typeIndex[t.name], x: w.x, z: w.z, y: ext.groundAt(w.x, w.z, m.y + 1), yaw, hours: m.open, wake: 0, anim: 'idle', talky: 0.5 });
    });
    const shoppers = Math.min(36, Math.round(m.stalls.length * 1.6));
    Array.from({ length: shoppers }).forEach(() => {
      const t = pickShopper();
      add({ kind: 'shop', type: typeIndex[t.name], market: m, x: m.x, z: m.z, y: m.y, tx: m.x, tz: m.z, hours: m.open, wake: 0, speed: 0.8 + rand() * 0.3, timer: 0 });
    });
  });
  life.gatherings.forEach((g) => {
    Array.from({ length: g.groups }).forEach(() => {
      const a = rand() * Math.PI * 2;
      const r = g.r * Math.sqrt(rand());
      const cx = g.x + Math.cos(a) * r;
      const cz = g.z + Math.sin(a) * r;
      const n = 3 + Math.floor(rand() * 2);
      const cy = ext.groundAt(cx, cz, 1e9);
      Array.from({ length: n }).forEach((_, k) => {
        const ang = (k / n) * Math.PI * 2 + rand() * 0.4;
        const x = cx + Math.cos(ang) * 0.95;
        const z = cz + Math.sin(ang) * 0.95;
        const t = g.id === 'temple_vesta' && k === 0 && typeIndex.vestal !== undefined ? types[typeIndex.vestal] : pickGossip();
        add({ kind: 'still', type: typeIndex[t.name], x, z, y: cy, yaw: Math.atan2(cx - x, cz - z), hours: g.hours, wake: rand() * 0.9, anim: 'idle', talky: 0.35 });
      });
    });
  });

  const carts = Array.from({ length: Math.max(life.carts.day, life.carts.night) }).map((_, i) => {
    const route = mainRoutes[Math.floor(rand() * mainRoutes.length)];
    const cargo = life.carts.cargo[i < life.carts.day ? 2 + (i % 3) : Math.floor(rand() * life.carts.cargo.length)];
    const cart = { i, route, cargo, s: rand() * (route ? route.path.len : 1), dir: rand() < 0.5 ? 1 : -1, seg: 0, lat: 0, speed: cargo.animal === 'ox' ? 0.95 : 1.35, mesh: null, x: 0, y: 0, z: 0, yaw: 0, on: false, dist: 0 };
    add({ kind: 'driver', type: typeIndex[i % 2 ? 'porter_light' : 'citizen_undyed'], cart, hours: [0, 24], wake: 0 });
    return cart;
  }).filter((c) => c.route);
  const litters = Array.from({ length: life.litters.count }).map((_, i) => {
    const route = mainRoutes[Math.floor(rand() * mainRoutes.length)];
    const litter = { i, route, s: rand() * (route ? route.path.len : 1), dir: rand() < 0.5 ? 1 : -1, seg: 0, lat: 0, speed: 1.1, mesh: null, x: 0, y: 0, z: 0, yaw: 0, on: false,
                     curtain: ['#7d2a3a', '#8a2a2a', '#5b2a4a', '#2f4a6a'][i % 4] };
    [[-0.55, 2.05], [0.55, 2.05], [-0.55, -2.05], [0.55, -2.05]].forEach(([ox, oz]) => add({ kind: 'bearer', type: typeIndex.bearer, litter, ox, oz, hours: life.litters.hours, wake: 0 }));
    const rider = life.litters.riders[i % life.litters.riders.length];
    add({ kind: 'rider', type: typeIndex[rider], litter, hours: life.litters.hours, wake: 0, anim: 'sit' });
    return litter;
  }).filter((l) => l.route);
  const boats = [];
  life.boats.rivers.forEach((rv) => {
    const path = makePath(data.rivers[rv.river].pts.map((p) => [p[0], p[1], p[2], p[3]]));
    const n = Math.round(life.boats.count * (rv.length / life.boats.rivers.reduce((s, r) => s + r.length, 0)));
    const pickBoat = weightedPicker(life.boats.kinds, (k) => k.weight, rand);
    Array.from({ length: n }).forEach(() => {
      const kind = pickBoat().kind;
      const dir = rand() < 0.5 ? 1 : -1;
      const boat = { path, kind, s: rand() * path.len, dir, seg: 0, lat: 0, speed: kind === 'caudicaria' ? 0.9 : kind === 'linter' ? 1.6 : 1.3, mesh: boatMesh(kind, rand), side: (rand() - 0.5) * 0.4 };
      scene.add(boat.mesh);
      boats.push(boat);
    });
  });

  const pos0 = { x: 0, y: 0, z: 0, dx: 0, dz: 0 };
  agents.filter((a) => a.kind === 'walk').forEach((a) => {
    sampleOn(a.route.path, a, pos0);
    Object.assign(a, { x: pos0.x, y: pos0.y, z: pos0.z });
  });
  [...carts, ...litters].forEach((o) => {
    sampleOn(o.route.path, o, pos0);
    Object.assign(o, { x: pos0.x, y: pos0.y, z: pos0.z });
  });

  const impostor = new THREE.InstancedMesh(impostorGeometry(), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }), agents.length);
  impostor.count = 0;
  impostor.frustumCulled = false;
  scene.add(impostor);
  const typeColor = types.map((t) => new THREE.Color(t.color || '#c9b48f'));
  const glowPos = new Float32Array(256 * 3);
  const glowGeo = new THREE.BufferGeometry();
  glowGeo.setAttribute('position', new THREE.BufferAttribute(glowPos, 3));
  const glowTex = (() => {
    const c = document.createElement('canvas');
    c.width = 64;
    c.height = 64;
    const g2 = c.getContext('2d');
    const grad = g2.createRadialGradient(32, 32, 1, 32, 32, 31);
    grad.addColorStop(0, 'rgba(255,240,200,1)');
    grad.addColorStop(0.3, 'rgba(255,140,40,0.7)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    g2.fillStyle = grad;
    g2.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  })();
  const glows = new THREE.Points(glowGeo, new THREE.PointsMaterial({ size: 1.8, map: glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }));
  glows.frustumCulled = false;
  scene.add(glows);

  const loaded = [];
  const pools = types.map(() => ({ free: [], all: 0 }));
  const loader = new GLTFLoader();
  const dye = (g, tint) => g.scene.traverse((o) => o.isMesh && [o.material].flat().forEach((m) => tint[m.name] && m.color.set(tint[m.name])));
  Promise.all(types.map((t, i) => loader.loadAsync(`${base}${t.file}`).then((g) => {
    t.tint && dye(g, t.tint);
    loaded[i] = g;
  }))).then(() => onReady && onReady()).catch((err) => console.warn('life models', err));

  const acquire = (ti) => {
    const pool = pools[ti];
    if (pool.free.length) return pool.free.pop();
    if (!loaded[ti] || pool.all >= PER_TYPE) return null;
    pool.all += 1;
    const root = SkeletonUtils.clone(loaded[ti].scene);
    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.frustumCulled = false;
      }
    });
    const mixer = new THREE.AnimationMixer(root);
    const actions = Object.fromEntries(loaded[ti].animations.map((clip) => [clip.name, mixer.clipAction(clip)]));
    scene.add(root);
    return { root, mixer, actions, current: null, ti };
  };

  const release = (a) => {
    a.slot.root.visible = false;
    a.slot.current && a.slot.current.stop();
    a.slot.current = null;
    pools[a.slot.ti].free.push(a.slot);
    a.slot = null;
  };

  const play = (slot, name, speed) => {
    const act = slot.actions[name] || slot.actions.idle;
    if (slot.current !== act) {
      act.reset();
      act.time = Math.random() * act.getClip().duration;
      act.play();
      slot.current && slot.current.crossFadeTo(act, 0.25, false);
      slot.current = act;
    }
    act.timeScale = speed;
  };

  const pos = { x: 0, y: 0, z: 0, dx: 0, dz: 0 };
  const placeOnPath = (o, rate) => {
    o.s += o.dir * o.speed * rate;
    if (o.s < 0 || o.s > o.path.len) {
      o.dir *= -1;
      o.s = Math.max(0, Math.min(o.path.len, o.s));
    }
    sampleOn(o.path, o, pos);
    o.x = pos.x;
    o.z = pos.z;
    o.y = pos.y;
    o.yaw = Math.atan2(pos.dx * o.dir, pos.dz * o.dir);
  };

  const crowdFactor = (clock) => {
    const h = clock.hour;
    const k = Math.floor(h) % 24;
    const t = h - Math.floor(h);
    const f = life.crowd_by_hour[k] * (1 - t) + life.crowd_by_hour[(k + 1) % 24] * t;
    return f * (1 - 0.55 * clock.mix.rain - 0.25 * clock.mix.storm) * (1 - 0.6 * clock.mix.snow);
  };

  const state = { lastAssign: 0, stats: {}, sync: true };
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  const v = new THREE.Vector3();
  const vehiclePool = { carts: [], litters: [] };

  const updateVehicle = (o, dt, cam, kind, clock) => {
    o.path = o.route.path;
    placeOnPath(o, dt);
    o.y = ext.groundAt(o.x, o.z, o.y + 0.5);
    const d2 = (o.x - cam.x) ** 2 + (o.z - cam.z) ** 2;
    o.near = d2 < VEHICLE_NEAR * VEHICLE_NEAR;
    if (o.near && !o.mesh) {
      o.mesh = vehiclePool[kind].pop() || (kind === 'carts' ? cartMesh(o.cargo, rand) : litterMesh(o.curtain));
      o.mesh.userData.cargo !== o.cargo && kind === 'carts' && (o.mesh.userData.cargo = o.cargo);
      scene.add(o.mesh);
    }
    if (!o.near && o.mesh) {
      scene.remove(o.mesh);
      vehiclePool[kind].push(o.mesh);
      o.mesh = null;
    }
    if (o.mesh) {
      o.mesh.position.set(o.x, o.y, o.z);
      o.mesh.rotation.y = o.yaw;
      o.dist = (o.dist || 0) + o.speed * dt;
      if (kind === 'carts') {
        o.mesh.userData.wheels.forEach((w) => { w.rotation.x = o.dist / 0.55; });
        o.mesh.userData.beasts.forEach((b) => b.userData.legs.forEach((l) => { l.rotation.x = Math.sin(o.dist * 2.4 + l.userData.phase) * 0.38; }));
        o.mesh.userData.lantern.material.emissiveIntensity = clock.night > 0.3 ? 3 : 0;
      }
    }
  };

  const update = (dt, camPos, clock) => {
    const cam = camPos;
    const factor = crowdFactor(clock);
    const h = clock.hour;
    const cartCount = clock.daylightCarts ? life.carts.day : life.carts.night;
    carts.forEach((c) => {
      const want = c.i < cartCount;
      const d2 = (c.x - cam.x) ** 2 + (c.z - cam.z) ** 2;
      c.on = state.sync || want === c.on || d2 > 150 * 150 ? want : c.on;
      if (c.on) updateVehicle(c, dt, cam, 'carts', clock);
      else if (c.mesh) {
        scene.remove(c.mesh);
        vehiclePool.carts.push(c.mesh);
        c.mesh = null;
      }
    });
    litters.forEach((l) => {
      const want = inHours(life.litters.hours, h) && factor > 0.2;
      const d2 = (l.x - cam.x) ** 2 + (l.z - cam.z) ** 2;
      l.on = state.sync || want === l.on || d2 > 120 * 120 ? want : l.on;
      if (l.on) updateVehicle(l, dt, cam, 'litters', clock);
      else if (l.mesh) {
        scene.remove(l.mesh);
        vehiclePool.litters.push(l.mesh);
        l.mesh = null;
      }
    });
    const t = performance.now() / 1000;
    boats.forEach((b) => {
      b.lat = b.path.pts[Math.min(b.seg + 1, b.path.pts.length - 1)][3] * (0.18 * b.dir + b.side * 0.3);
      placeOnPath(b, dt);
      b.mesh.position.set(b.x, b.y + 0.05 + Math.sin(t * 1.3 + b.s) * 0.06, b.z);
      b.mesh.rotation.set(0, b.yaw, Math.sin(t * 0.9 + b.s) * 0.025);
      b.mesh.userData.oars.forEach((o, k) => { o.rotation.y = Math.sin(t * 2.2) * 0.45 * (k ? 1 : -1); o.rotation.z = Math.cos(t * 2.2) * 0.12; });
    });

    let near = [];
    let shown = 0;
    let glowN = 0;
    const lights = [];
    agents.forEach((a) => {
      const wanted = inHours(a.hours, h) && (a.kind === 'walk' ? a.wake < (a.torch ? 1 : factor) : a.kind === 'still' || a.kind === 'shop' ? a.wake < Math.max(0.35, factor) : true);
      const attached = a.kind === 'driver' ? a.cart.on : a.kind === 'bearer' || a.kind === 'rider' ? a.litter.on : true;
      const d2 = (a.x - cam.x) ** 2 + (a.z - cam.z) ** 2;
      const want = wanted && attached;
      const linked = a.kind === 'driver' || a.kind === 'bearer' || a.kind === 'rider';
      a.on = linked || state.sync ? want : want === a.on || d2 < (NEAR + 12) ** 2 ? a.on : want;
      if (!a.on) {
        a.slot && release(a);
        return;
      }
      if (a.kind === 'walk') {
        a.path = a.route.path;
        if (a.pause > 0) {
          a.pause -= dt;
          a.anim = 'talk';
        } else {
          placeOnPath(a, dt);
          a.anim = 'walk';
          rand() < dt * 0.004 && !a.torch && (a.pause = 3 + rand() * 6);
        }
      } else if (a.kind === 'shop') {
        const m = a.market;
        if (a.timer > 0) {
          a.timer -= dt;
          a.anim = a.timer % 6 < 3 ? 'talk' : 'idle';
        } else {
          const dx = a.tx - a.x;
          const dz = a.tz - a.z;
          const dist = Math.hypot(dx, dz);
          if (dist < 0.4) {
            a.timer = 3 + rand() * 7;
            const w = toWorld(m, (rand() - 0.5) * (m.w - 2), (rand() - 0.5) * (m.d + 4));
            a.tx = w.x;
            a.tz = w.z;
          } else {
            a.x += (dx / dist) * a.speed * dt;
            a.z += (dz / dist) * a.speed * dt;
            a.yaw = Math.atan2(dx, dz);
            a.anim = 'walk';
          }
        }
        a.y = m.y;
      } else if (a.kind === 'still') {
        a.timer -= dt;
        if (a.timer < 0) {
          a.anim = rand() < a.talky ? 'talk' : 'idle';
          a.timer = 3 + rand() * 6;
        }
      } else if (a.kind === 'driver') {
        const c = a.cart;
        const fx = Math.sin(c.yaw);
        const fz = Math.cos(c.yaw);
        a.x = c.x + fx * 3.3 + fz * 1.15;
        a.z = c.z + fz * 3.3 - fx * 1.15;
        a.y = c.y;
        a.yaw = c.yaw;
        a.anim = 'walk';
        a.speedAnim = c.speed;
        clock.night > 0.3 && lights.push([c.x + fx * 1.4, c.y + 2.2, c.z + fz * 1.4]);
      } else if (a.kind === 'bearer' || a.kind === 'rider') {
        const l = a.litter;
        const fx = Math.sin(l.yaw);
        const fz = Math.cos(l.yaw);
        const ox = a.kind === 'rider' ? 0 : a.ox;
        const oz = a.kind === 'rider' ? -0.3 : a.oz;
        a.x = l.x + fx * oz + fz * ox;
        a.z = l.z + fz * oz - fx * ox;
        a.y = a.kind === 'rider' ? l.y + 0.78 : l.y;
        a.yaw = l.yaw;
        a.anim = a.kind === 'rider' ? 'sit' : 'walk';
        a.speedAnim = l.speed;
      }
      a.torch && clock.night > 0.3 && lights.push([a.x + Math.sin(a.yaw) * 0.2, a.y + 1.95, a.z + Math.cos(a.yaw) * 0.2]);
      const dd = (a.x - cam.x) ** 2 + (a.z - cam.z) ** 2;
      a.d2 = dd;
      dd < NEAR * NEAR && near.push(a);
    });

    state.lastAssign -= dt;
    if (state.lastAssign <= 0) {
      state.lastAssign = 0.25;
      near.sort((p, r) => p.d2 - r.d2);
      const keep = new Set(near.slice(0, MAX_SKINNED));
      agents.forEach((a) => a.slot && !keep.has(a) && release(a));
      keep.forEach((a) => {
        if (!a.slot) {
          a.slot = acquire(a.type);
          a.slot && (a.slot.root.visible = true);
        }
      });
    }
    agents.forEach((a) => {
      if (!a.on) return;
      if (a.slot) {
        const ground = a.kind === 'rider' ? a.y : ext.groundAt(a.x, a.z, a.y + 0.6);
        a.y = ground;
        a.slot.root.position.set(a.x, ground, a.z);
        a.slot.root.rotation.y = a.yaw;
        play(a.slot, a.anim, a.anim === 'walk' ? (a.speedAnim || a.speed || 1.2) / 1.25 : 1);
        a.slot.mixer.update(dt);
        return;
      }
      if (a.d2 < FAR * FAR && shown < impostor.instanceMatrix.count) {
        m4.compose(v.set(a.x, a.y, a.z), q.setFromAxisAngle(up, a.yaw), one);
        impostor.setMatrixAt(shown, m4);
        impostor.setColorAt(shown, typeColor[a.type]);
        shown += 1;
      }
    });
    impostor.count = shown;
    impostor.instanceMatrix.needsUpdate = true;
    impostor.instanceColor && (impostor.instanceColor.needsUpdate = true);
    lights.sort((p, r) => ((p[0] - cam.x) ** 2 + (p[2] - cam.z) ** 2) - ((r[0] - cam.x) ** 2 + (r[2] - cam.z) ** 2));
    lights.slice(0, 256).forEach((p) => {
      if ((p[0] - cam.x) ** 2 + (p[2] - cam.z) ** 2 < FAR * FAR) {
        glowPos.set(p, glowN * 3);
        glowN += 1;
      }
    });
    glowGeo.setDrawRange(0, glowN);
    glowGeo.attributes.position.needsUpdate = true;
    glows.visible = glowN > 0;
    (ext.atmo ? ext.atmo.torches : []).forEach((light, k) => {
      const p = lights[k];
      light.intensity = p && clock.night > 0.3 ? 9 + Math.sin(t * 13 + k) * 1.5 : 0;
      p && light.position.set(p[0], p[1], p[2]);
    });
    state.stats = {
      active: agents.filter((a) => a.on).length, skinned: agents.filter((a) => a.slot).length, impostors: shown, carts: carts.filter((c) => c.on).length,
      cartsNear: carts.filter((c) => c.mesh).length, litters: litters.filter((l) => l.on).length, boats: boats.length, torches: lights.length,
      standing: agents.filter((a) => a.on && a.kind === 'still').length, shoppers: agents.filter((a) => a.on && a.kind === 'shop').length,
    };
    state.sync = false;
  };

  const nearest = (kind) => {
    const list = kind === 'cart' ? carts.filter((c) => c.on) : kind === 'litter' ? litters.filter((l) => l.on) : kind === 'boat' ? boats : agents.filter((a) => a.on && a.kind === kind);
    return list.map((o) => ({ x: o.x, z: o.z, yaw: o.yaw, y: o.y }));
  };

  return { update, stats: () => state.stats, nearest, agents, carts, litters, boats, loaded: () => loaded.filter(Boolean).length, resync: () => { state.sync = true; } };
};
