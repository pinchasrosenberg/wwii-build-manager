import * as THREE from 'three';

import { box, cyl, merge, put, rng } from './geom.js';

const boatParts = (b) => {
  const parts = [box(2.2, 0.8, 7.5, '#5a3d24', 0, 0.2, 0), put(new THREE.ConeGeometry(1.1, 2.2, 4).rotateX(Math.PI / 2).rotateZ(Math.PI / 4), '#5a3d24', 0, 0.2, 4.6, 0, 1, 0.55, 1)];
  if (b.kind === 'sail') {
    parts.push(cyl(0.08, 0.1, 6, 6, '#4a3524', 0, 3.4, 0.6));
    parts.push(put(new THREE.PlaneGeometry(2.8, 3.4), '#d9c9a0', 0, 3.6, 0.7, Math.PI / 2));
  } else {
    [-1.6, 0, 1.6].forEach((z) => parts.push(cyl(0.45, 0.45, 0.9, 10, '#7a5230', 0, 1.05, z)));
  }
  return parts;
};

const millParts = () => {
  const parts = [box(2.4, 1.0, 9, '#4a3524', -2.6, 0.2, 0), box(2.4, 1.0, 9, '#4a3524', 2.6, 0.2, 0), box(7.6, 0.3, 6, '#6a4a2c', 0, 0.85, -1), box(4.6, 3.2, 4.2, '#7a5a3a', 0, 2.6, -1.4)];
  parts.push(put(new THREE.ConeGeometry(3.6, 1.6, 4).rotateY(Math.PI / 4), '#5a4030', 0, 4.9, -1.4, 0, 1, 1, 0.85));
  const wheel = put(new THREE.TorusGeometry(1.9, 0.12, 6, 18), '#3a2716', 0, 0.9, 3.0, Math.PI / 2);
  parts.push(wheel);
  Array.from({ length: 8 }).forEach((_, k) => {
    const a = (k / 8) * Math.PI * 2;
    parts.push(put(new THREE.BoxGeometry(0.15, 1.0, 1.0), '#3a2716', 0, 0.9 + Math.sin(a) * 1.7, 3.0 + Math.cos(a) * 1.7, 0, 1, 1, 1, a));
  });
  return parts;
};

const animalGeo = (kind) =>
  merge(kind === 'goat'
    ? [box(1.0, 0.55, 0.42, '#6a4a32', 0, 0.7, 0), box(0.32, 0.32, 0.3, '#4a3424', 0.6, 0.98, 0), ...[[-0.35, -0.13], [0.35, -0.13], [-0.35, 0.13], [0.35, 0.13]].map(([x, z]) => box(0.08, 0.45, 0.08, '#3a2a1c', x, 0.22, z))]
    : [box(1.0, 0.6, 0.6, '#e6dfcf', 0, 0.72, 0), box(0.3, 0.3, 0.3, '#2a2420', 0.6, 0.85, 0), ...[[-0.32, -0.18], [0.32, -0.18], [-0.32, 0.18], [0.32, 0.18]].map(([x, z]) => box(0.09, 0.42, 0.09, '#2a2420', x, 0.21, z))]);

const smokeTexture = () => {
  const c = document.createElement('canvas');
  c.width = 64;
  c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 2, 32, 32, 30);
  grad.addColorStop(0, 'rgba(225,220,210,0.55)');
  grad.addColorStop(1, 'rgba(225,220,210,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
};

export const buildDecor = (decor) => {
  const group = new THREE.Group();
  const d = decor || { boats: [], mills: [], animals: [], smoke: [] };
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const parts = [];
  d.boats.forEach((b) => boatParts(b).forEach((g) => parts.push(g.applyMatrix4(m.compose(new THREE.Vector3(b.x, b.y, b.z), q.setFromAxisAngle(up, b.rot), new THREE.Vector3(b.s, b.s, b.s))))));
  d.mills.forEach((mi) => millParts().forEach((g) => parts.push(g.applyMatrix4(m.compose(new THREE.Vector3(mi.x, mi.y, mi.z), q.setFromAxisAngle(up, mi.rot), new THREE.Vector3(1, 1, 1))))));
  const geo = merge(parts);
  if (geo) {
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, side: THREE.DoubleSide }));
    mesh.castShadow = true;
    group.add(mesh);
  }
  ['sheep', 'goat'].forEach((kind) => {
    const list = d.animals.filter((a) => a.kind === kind);
    if (list.length) {
      const inst = new THREE.InstancedMesh(animalGeo(kind), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 }), list.length);
      list.forEach((a, i) => inst.setMatrixAt(i, m.compose(new THREE.Vector3(a.x, a.y, a.z), q.setFromAxisAngle(up, a.rot), new THREE.Vector3(1, 1, 1))));
      inst.castShadow = true;
      group.add(inst);
    }
  });
  const rand = rng(31);
  const per = 18;
  const pos = new Float32Array(d.smoke.length * per * 3);
  const seeds = Array.from({ length: d.smoke.length * per }, () => rand());
  const smoke = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ size: 4.5, map: smokeTexture(), transparent: true, depthWrite: false, opacity: 0.8 }));
  smoke.geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  smoke.frustumCulled = false;
  d.smoke.length && group.add(smoke);
  const update = (time) => {
    d.smoke.forEach((src, k) => {
      for (let i = 0; i < per; i += 1) {
        const idx = k * per + i;
        const t = (time * 0.12 + seeds[idx]) % 1;
        pos[idx * 3] = src.x + Math.sin(seeds[idx] * 40 + time * 0.3) * t * 3 * src.s + t * 6 * src.s;
        pos[idx * 3 + 1] = src.y + t * 22 * src.s;
        pos[idx * 3 + 2] = src.z + Math.cos(seeds[idx] * 17) * t * 3 * src.s;
      }
    });
    smoke.geometry.attributes.position.needsUpdate = true;
  };
  return { group, update };
};
