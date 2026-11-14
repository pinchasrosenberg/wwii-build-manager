import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export const merge = (list) => (list.length ? mergeGeometries(list) : null);

export const rng = (seed) => {
  const state = { s: seed >>> 0 };
  return () => {
    state.s = (state.s * 1664525 + 1013904223) >>> 0;
    return state.s / 4294967296;
  };
};

export const shade = (hex, f) => `#${new THREE.Color(hex).multiplyScalar(f).getHexString()}`;

export const tint = (geo, hex) => {
  const g = geo.index ? geo.toNonIndexed() : geo;
  const count = g.attributes.position.count;
  const c = new THREE.Color(hex);
  const arr = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) arr.set([c.r, c.g, c.b], i * 3);
  g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  g.attributes.uv || g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(count * 2), 2));
  g.attributes.normal || g.computeVertexNormals();
  Object.keys(g.attributes).filter((k) => !['position', 'normal', 'uv', 'color'].includes(k)).forEach((k) => g.deleteAttribute(k));
  return g;
};

export const xform = (geo, x, y, z, ry = 0, sx = 1, sy = 1, sz = 1, rx = 0) =>
  geo.applyMatrix4(new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, 0, 'YXZ')), new THREE.Vector3(sx, sy, sz)));

export const put = (geo, hex, x, y, z, ry = 0, sx = 1, sy = 1, sz = 1, rx = 0) => xform(tint(geo, hex), x, y, z, ry, sx, sy, sz, rx);

export const box = (w, h, d, hex, x, y, z, ry = 0) => put(new THREE.BoxGeometry(w, h, d), hex, x, y, z, ry);

export const cyl = (rt, rb, h, seg, hex, x, y, z) => put(new THREE.CylinderGeometry(rt, rb, h, seg), hex, x, y, z);

export const gable = (w, d, h, over = 0.35) => {
  const hw = w / 2 + over;
  const hd = d / 2 + over;
  const v = [[-hw, 0, hd], [hw, 0, hd], [hw, h, 0], [-hw, h, 0], [hw, 0, -hd], [-hw, 0, -hd]];
  const tri = [[0, 1, 2], [0, 2, 3], [4, 5, 3], [4, 3, 2], [1, 4, 2], [5, 0, 3]];
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(tri.flatMap((t) => t.flatMap((i) => v[i]))), 3));
  geo.computeVertexNormals();
  return geo;
};

export const hip = (w, d, h, over = 0.35) => {
  const long = w >= d;
  const L = (long ? w : d) / 2 + over;
  const S = (long ? d : w) / 2 + over;
  const r = Math.max(0, L - S);
  const v = long
    ? [[-L, 0, S], [L, 0, S], [L, 0, -S], [-L, 0, -S], [r, h, 0], [-r, h, 0]]
    : [[-S, 0, L], [S, 0, L], [S, 0, -L], [-S, 0, -L], [0, h, -r], [0, h, r]];
  const tri = long ? [[0, 1, 4], [0, 4, 5], [2, 3, 5], [2, 5, 4], [1, 2, 4], [3, 0, 5]] : [[0, 1, 5], [1, 2, 4], [1, 4, 5], [2, 3, 4], [3, 0, 5], [3, 5, 4]];
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(tri.flatMap((t) => t.flatMap((i) => v[i]))), 3));
  geo.computeVertexNormals();
  return geo;
};

export const archHole = (cx, bottom, width, spring) => {
  const p = new THREE.Path();
  const r = width / 2;
  p.moveTo(cx - r, bottom);
  p.lineTo(cx + r, bottom);
  p.lineTo(cx + r, bottom + spring);
  p.absarc(cx, bottom + spring, r, 0, Math.PI, false);
  p.lineTo(cx - r, bottom);
  return p;
};

export const arcadeWall = (length, height, thick, bays, opening, spring, bottom = 0) => {
  const outline = new THREE.Shape();
  outline.moveTo(-length / 2, 0);
  outline.lineTo(length / 2, 0);
  outline.lineTo(length / 2, height);
  outline.lineTo(-length / 2, height);
  outline.lineTo(-length / 2, 0);
  const pitch = length / bays;
  Array.from({ length: bays }).forEach((_, k) => outline.holes.push(archHole(-length / 2 + pitch * (k + 0.5), bottom, Math.min(opening, pitch * 0.72), spring)));
  const geo = new THREE.ExtrudeGeometry(outline, { depth: thick, bevelEnabled: false, curveSegments: 6 });
  geo.translate(0, 0, -thick / 2);
  return geo;
};
