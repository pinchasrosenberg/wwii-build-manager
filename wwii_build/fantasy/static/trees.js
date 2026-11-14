import * as THREE from 'three';

import { merge, put, rng, shade, tint, xform } from './geom.js';

const limb = (from, to, r0, r1, hex) => {
  const dir = new THREE.Vector3().subVectors(to, from);
  const len = dir.length();
  const geo = new THREE.CylinderGeometry(r1, r0, len, 7, 1);
  geo.translate(0, len / 2, 0);
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  return tint(geo, hex).applyMatrix4(new THREE.Matrix4().compose(from, q, new THREE.Vector3(1, 1, 1)));
};

const blob = (pos, size, squash, hex) => xform(tint(new THREE.IcosahedronGeometry(1, 1), hex), pos.x, pos.y, pos.z, 0, size, size * squash, size);

const CROWN = {
  umbrella: { up: [0.55, 0.85], spread: 1.0, squash: 0.32, tip: 0.55 },
  column: { up: [1.25, 1.45], spread: 0.18, squash: 1.6, tip: 0.35 },
  round: { up: [0.45, 1.0], spread: 0.75, squash: 0.85, tip: 0.6 },
  spreading: { up: [0.3, 0.7], spread: 1.0, squash: 0.6, tip: 0.6 },
  cone: { up: [0.1, 0.35], spread: 0.7, squash: 0.5, tip: 0.45 },
  fan: { up: [0.2, 0.6], spread: 0.6, squash: 0.25, tip: 0.5 },
};

export const buildDetailedTree = (p, seed) => {
  const rand = rng(seed);
  const parts = [];
  const shape = CROWN[p.crown_shape] || CROWN.round;
  const bark = p.bark_color || '#6a4a32';
  const leaf = p.leaf_color || '#3d5a33';
  const trunkTop = p.height * (p.crown_shape === 'column' ? 0.92 : p.trunk_ratio);
  const leanA = rand() * Math.PI * 2;
  const lean = THREE.MathUtils.degToRad(p.lean || 0);
  const r0 = Math.max(0.18, p.height * 0.028);
  const segs = 6;
  const trunk = Array.from({ length: segs + 1 }, (_, k) => {
    const t = k / segs;
    const bend = Math.sin(t * Math.PI * 0.9) * lean * trunkTop * 0.5 + t * lean * trunkTop * 0.4;
    return new THREE.Vector3(Math.cos(leanA) * bend + (rand() - 0.5) * 0.15 * t, t * trunkTop, Math.sin(leanA) * bend + (rand() - 0.5) * 0.15 * t);
  });
  trunk.slice(0, -1).forEach((a, k) => parts.push(limb(a, trunk[k + 1], r0 * (1 - (k / segs) * 0.45), r0 * (1 - ((k + 1) / segs) * 0.45), bark)));
  const top = trunk[segs];
  const grow = (from, dir, len, radius, level) => {
    const to = from.clone().addScaledVector(dir, len);
    parts.push(limb(from, to, radius, radius * 0.6, bark));
    if (level <= 1) {
      const clusters = Math.round(3 + p.foliage * 5);
      Array.from({ length: clusters }).forEach(() => {
        const off = new THREE.Vector3((rand() - 0.5) * len * 0.8, (rand() - 0.2) * len * 0.35, (rand() - 0.5) * len * 0.8);
        parts.push(blob(to.clone().add(off), (p.crown_width / 6) * (0.5 + rand() * 0.6) * shape.tip, shape.squash, shade(leaf, 0.85 + rand() * 0.3)));
      });
      return;
    }
    const kids = 2 + Math.round(rand() * 2);
    Array.from({ length: kids }).forEach(() => {
      const d = dir.clone().add(new THREE.Vector3((rand() - 0.5) * 0.9, (rand() - 0.2) * 0.5, (rand() - 0.5) * 0.9)).normalize();
      grow(to, d, len * 0.62, radius * 0.6, level - 1);
    });
  };
  if (p.crown_shape === 'column') {
    Array.from({ length: 14 }).forEach((_, k) => {
      const t = k / 13;
      const y = p.height * (0.08 + t * 0.9);
      const r = (p.crown_width / 2) * Math.sin(Math.PI * Math.min(1, 0.15 + t * 0.9)) * (0.85 + rand() * 0.3);
      parts.push(blob(new THREE.Vector3(Math.cos(leanA) * lean * y * 0.4, y, Math.sin(leanA) * lean * y * 0.4), Math.max(0.35, r), 1.4, shade(leaf, 0.85 + rand() * 0.25)));
    });
  } else if (p.crown_shape === 'fan') {
    Array.from({ length: 12 }).forEach((_, k) => {
      const a = (k / 12) * Math.PI * 2;
      const frond = put(new THREE.ConeGeometry(0.5, p.crown_width / 2, 4).rotateZ(Math.PI / 2 + 0.5).translate(p.crown_width / 4, 0, 0), shade(leaf, 0.9 + rand() * 0.2), top.x, top.y, top.z, a, 1, 0.3, 1);
      parts.push(frond);
    });
  } else {
    Array.from({ length: p.branches }).forEach((_, k) => {
      const a = (k / p.branches) * Math.PI * 2 + rand() * 0.5;
      const up = shape.up[0] + rand() * (shape.up[1] - shape.up[0]);
      const start = p.crown_shape === 'cone' ? trunk[Math.max(2, Math.round(segs * (0.4 + (k / p.branches) * 0.55)))] : top;
      const dir = new THREE.Vector3(Math.cos(a) * shape.spread, up, Math.sin(a) * shape.spread).normalize();
      const len = (p.crown_width / 2) * (p.crown_shape === 'cone' ? 1 - k / (p.branches + 1) : 0.75) * (0.8 + rand() * 0.4);
      grow(start, dir, len, r0 * 0.55, p.levels + 1);
    });
    p.crown_shape === 'cone' && parts.push(blob(new THREE.Vector3(top.x, p.height * 0.97, top.z), p.crown_width * 0.12, 1.6, leaf));
  }
  const mesh = new THREE.Mesh(merge(parts), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
};
