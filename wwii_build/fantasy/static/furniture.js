import * as THREE from 'three';

import { surfaceTexture } from './textures.js';

const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.05, ...extra });

const gold = (color) => mat(color, { metalness: 0.8, roughness: 0.3 });

const fabric = (color) => mat(color, { roughness: 0.95 });

const woodMat = (color) => mat(color, { roughness: 0.55 });

const surface = (item) =>
  ({ gold: gold(item.color), cloth: fabric(item.color), marble: mat(item.color, { roughness: 0.25 }), leaf: mat(item.color, { roughness: 0.9 }) })[item.material] ||
  (item.material === 'stone' ? mat(item.color, { roughness: 0.9 }) : woodMat(item.color));

const box = (w, h, d, material, x, y, z) => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  return mesh;
};

const cyl = (rt, rb, h, seg, material, x, y, z) => {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), material);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  return mesh;
};

const flame = (x, y, z) => {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), new THREE.MeshBasicMaterial({ color: '#ffcf70' }));
  mesh.position.set(x, y, z);
  return mesh;
};

const table = (item) => {
  const g = new THREE.Group();
  const m = surface(item);
  g.add(box(item.w, 0.1, item.d, m, 0, item.h - 0.05, 0));
  [-1, 1].forEach((sx) => [-1, 1].forEach((sz) => g.add(box(0.14, item.h - 0.1, 0.14, m, sx * (item.w / 2 - 0.2), (item.h - 0.1) / 2, sz * (item.d / 2 - 0.2)))));
  g.add(box(item.w - 0.5, 0.08, 0.1, m, 0, 0.25, 0));
  return g;
};

const chair = (item) => {
  const g = new THREE.Group();
  const m = surface(item);
  g.add(box(0.55, 0.07, 0.55, m, 0, 0.5, 0));
  g.add(box(0.55, 0.62, 0.06, m, 0, 0.82, -0.25));
  [-1, 1].forEach((sx) => [-1, 1].forEach((sz) => g.add(box(0.06, 0.5, 0.06, m, sx * 0.24, 0.25, sz * 0.24))));
  g.add(box(0.5, 0.05, 0.5, fabric('#7a1f2b'), 0, 0.56, 0));
  return g;
};

const chandelier = (item) => {
  const g = new THREE.Group();
  const m = gold(item.color);
  g.add(cyl(0.025, 0.025, 1.2, 6, m, 0, item.h / 2 + 0.6, 0));
  const ring = new THREE.Mesh(new THREE.TorusGeometry(item.w / 2, 0.04, 8, 28), m);
  ring.rotation.x = Math.PI / 2;
  ring.position.y = 0.3;
  g.add(ring);
  g.add(cyl(0.1, 0.18, 0.5, 10, m, 0, 0.15, 0));
  Array.from({ length: 8 }).forEach((_, i) => {
    const a = (i / 8) * Math.PI * 2;
    const x = Math.cos(a) * (item.w / 2);
    const z = Math.sin(a) * (item.w / 2);
    g.add(cyl(0.03, 0.03, 0.2, 6, fabric('#f4ecd8'), x, 0.42, z));
    g.add(flame(x, 0.58, z));
  });
  const light = new THREE.PointLight('#ffd9a0', 14, 18, 1.6);
  light.position.y = 0.2;
  light.userData.chandelierLight = true;
  g.add(light);
  return g;
};

const rug = (item) => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(item.w, 0.03, item.d), [
    mat(item.color), mat(item.color), new THREE.MeshStandardMaterial({ map: surfaceTexture('rug', item.color, 1, 1), roughness: 0.95 }), mat(item.color), mat(item.color), mat(item.color),
  ]);
  mesh.position.y = 0.02;
  mesh.receiveShadow = true;
  return mesh;
};

const throne = (item) => {
  const g = new THREE.Group();
  const m = gold(item.color);
  const cushion = fabric('#7a1f2b');
  g.add(box(1.5, 0.5, 1.2, m, 0, 0.25, 0));
  g.add(box(1.1, 0.14, 0.9, cushion, 0, 0.57, 0.05));
  g.add(box(1.4, 2.4, 0.18, m, 0, 1.5, -0.5));
  g.add(box(0.9, 1.6, 0.05, cushion, 0, 1.4, -0.4));
  [-1, 1].forEach((s) => g.add(box(0.16, 0.7, 1.0, m, s * 0.68, 0.85, 0)));
  const crown = new THREE.Mesh(new THREE.ConeGeometry(0.55, 0.7, 4), m);
  crown.position.set(0, 2.9, -0.5);
  crown.rotation.y = Math.PI / 4;
  g.add(crown);
  [0.5, 1.0].forEach((y) => g.add(box(1.7 - y * 0.2, 0.18, 1.5 - y * 0.2, mat('#6c1d28'), 0, -0.1 + (y - 0.5) * 0.4, 0.3)));
  return g;
};

const bookshelf = (item) => {
  const g = new THREE.Group();
  const m = surface(item);
  g.add(box(item.w, item.h, 0.06, m, 0, item.h / 2, -item.d / 2 + 0.03));
  [-1, 1].forEach((s) => g.add(box(0.06, item.h, item.d, m, s * (item.w / 2 - 0.03), item.h / 2, 0)));
  const colors = ['#7a1f2b', '#2f5d9e', '#3f7a4a', '#c9a227', '#5a3a1f', '#6a4a9c'];
  Array.from({ length: 6 }).forEach((_, r) => {
    g.add(box(item.w, 0.05, item.d, m, 0, 0.05 + (r * (item.h - 0.1)) / 5, 0));
    if (r < 5) {
      Array.from({ length: 12 }).forEach((__, b) => {
        const bh = 0.3 + ((b * 7 + r * 3) % 5) * 0.04;
        g.add(box(0.1, bh, 0.28, fabric(colors[(b + r) % colors.length]), -item.w / 2 + 0.2 + b * ((item.w - 0.4) / 11), 0.1 + (r * (item.h - 0.1)) / 5 + bh / 2, 0));
      });
    }
  });
  return g;
};

const bed = (item) => {
  const g = new THREE.Group();
  const m = surface({ ...item, material: 'wood', color: '#5a3a1f' });
  g.add(box(item.w, 0.4, item.d, m, 0, 0.35, 0));
  g.add(box(item.w - 0.1, 0.25, item.d - 0.1, fabric(item.color), 0, 0.65, 0.05));
  g.add(box(item.w, 1.3, 0.12, m, 0, 0.9, -item.d / 2));
  g.add(box(0.8, 0.14, 0.4, fabric('#f4ecd8'), -0.45, 0.82, -item.d / 2 + 0.4));
  g.add(box(0.8, 0.14, 0.4, fabric('#f4ecd8'), 0.45, 0.82, -item.d / 2 + 0.4));
  return g;
};

const column = (item) => {
  const g = new THREE.Group();
  const m = mat(item.color, { roughness: 0.35 });
  g.add(box(1.0, 0.3, 1.0, m, 0, 0.15, 0));
  g.add(cyl(0.32, 0.38, item.h - 0.7, 20, m, 0, item.h / 2, 0));
  g.add(box(1.0, 0.4, 1.0, m, 0, item.h - 0.2, 0));
  return g;
};

const fireplace = (item) => {
  const g = new THREE.Group();
  const m = surface(item);
  g.add(box(item.w, item.h, item.d, m, 0, item.h / 2, 0));
  g.add(box(item.w * 0.55, item.h * 0.5, 0.2, mat('#0c0a09'), 0, item.h * 0.3, item.d / 2 - 0.05));
  g.add(box(item.w + 0.3, 0.14, item.d + 0.2, m, 0, item.h, 0));
  const fire = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 7), new THREE.MeshBasicMaterial({ color: '#ff8a2a' }));
  fire.position.set(0, 0.4, item.d / 2 - 0.2);
  g.add(fire);
  const light = new THREE.PointLight('#ff9a4a', 8, 12, 1.6);
  light.position.set(0, 0.6, item.d / 2 + 0.3);
  g.add(light);
  return g;
};

const banner = (item) => {
  const g = new THREE.Group();
  g.add(box(item.w + 0.2, 0.06, 0.08, gold('#d4a93a'), 0, item.h, 0));
  g.add(box(item.w, item.h, 0.04, fabric(item.color), 0, item.h / 2, 0));
  g.add(box(item.w * 0.5, item.h * 0.3, 0.05, gold('#d4a93a'), 0, item.h * 0.55, 0.02));
  return g;
};

const candelabra = (item) => {
  const g = new THREE.Group();
  const m = gold(item.color);
  g.add(cyl(0.18, 0.22, 0.1, 12, m, 0, 0.05, 0));
  g.add(cyl(0.03, 0.03, item.h, 8, m, 0, item.h / 2, 0));
  [-0.18, 0, 0.18].forEach((x) => {
    g.add(cyl(0.025, 0.025, 0.14, 6, fabric('#f4ecd8'), x, item.h + 0.07, 0));
    g.add(flame(x, item.h + 0.19, 0));
  });
  const light = new THREE.PointLight('#ffcf8a', 3, 7, 1.8);
  light.position.y = item.h + 0.3;
  g.add(light);
  return g;
};

const plant = (item) => {
  const g = new THREE.Group();
  g.add(cyl(0.25, 0.18, 0.4, 12, mat('#8a5a32'), 0, 0.2, 0));
  const leaves = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 1), mat(item.color, { roughness: 0.9 }));
  leaves.position.y = 0.85;
  leaves.castShadow = true;
  g.add(leaves);
  return g;
};

const statue = (item) => {
  const g = new THREE.Group();
  const m = mat(item.color, { roughness: 0.3 });
  g.add(box(0.8, 0.7, 0.8, mat('#8d8a82'), 0, 0.35, 0));
  g.add(cyl(0.2, 0.3, 1.0, 12, m, 0, 1.2, 0));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 14, 14), m);
  head.position.y = 1.9;
  g.add(head);
  return g;
};

const curtains = (item, win) => {
  const g = new THREE.Group();
  const cloth = fabric(item.color);
  const half = item.w / 2;
  g.add(cyl(0.04, 0.04, item.w + 0.6, 8, gold('#d4a93a'), 0, item.h, 0.12)).rotation.z = Math.PI / 2;
  [-1, 1].forEach((s) => {
    const panel = box(0.55, item.h - 0.25, 0.1, cloth, s * (half - 0.1), (item.h - 0.25) / 2 + 0.1, 0.1);
    g.add(panel);
  });
  return g;
};

const couch = (item) => {
  const g = new THREE.Group();
  const wood = woodMat('#5a3a1f');
  g.add(box(item.w, 0.45, item.d, wood, 0, 0.3, 0));
  g.add(box(item.w - 0.1, 0.22, item.d - 0.1, fabric(item.color), 0, 0.62, 0));
  g.add(box(0.5, 0.35, item.d - 0.2, fabric('#d9c9a0'), -item.w / 2 + 0.35, 0.85, 0));
  g.add(box(0.12, 0.7, item.d, gold('#c9a227'), -item.w / 2 + 0.06, 0.65, 0));
  return g;
};

const octFountain = (item) => {
  const g = new THREE.Group();
  const stone = mat(item.color, { roughness: 0.3 });
  const water = new THREE.MeshStandardMaterial({ color: '#4b8fb5', roughness: 0.05, metalness: 0.2, transparent: true, opacity: 0.85 });
  [1, 0.72, 0.46, 0.22].forEach((f, i) => {
    const ring = new THREE.Mesh(new THREE.CylinderGeometry((item.w / 2) * f, (item.w / 2) * f, 0.9 - i * 0.05, 8, 1, true), stone);
    ring.position.y = 0.45;
    ring.material.side = THREE.DoubleSide;
    g.add(ring);
  });
  const pool = new THREE.Mesh(new THREE.CylinderGeometry(item.w / 2 - 0.1, item.w / 2 - 0.1, 0.1, 8), water);
  pool.position.y = 0.55;
  g.add(pool);
  g.add(cyl(0.5, 0.7, 1.6, 12, stone, 0, 0.8, 0));
  g.add(cyl(0.05, 0.25, 1.2, 8, new THREE.MeshStandardMaterial({ color: '#cfe8f5', transparent: true, opacity: 0.7 }), 0, 2.2, 0));
  return g;
};

const fountain = (item) => {
  const g = new THREE.Group();
  g.add(cyl(item.w / 2, item.w / 2 + 0.1, 0.6, 20, mat(item.color, { roughness: 0.3 }), 0, 0.3, 0));
  g.add(cyl(item.w / 2 - 0.15, item.w / 2 - 0.15, 0.08, 20, new THREE.MeshStandardMaterial({ color: '#4b8fb5', roughness: 0.05 }), 0, 0.58, 0));
  g.add(cyl(0.2, 0.3, 1.2, 10, mat(item.color), 0, 1.0, 0));
  return g;
};

const builders = { couch, fountain_oct: octFountain, fountain, long_table: table, table, chair, chandelier, rug, throne, bookshelf, bed, column, fireplace, banner, candelabra, plant, statue, curtains };

export const buildItem = (item) => {
  const group = (builders[item.kind] || (() => new THREE.Group()))(item);
  group.userData.itemId = item.id;
  group.userData.kind = item.kind;
  group.traverse((o) => {
    o.receiveShadow = true;
  });
  return group;
};

export const solidKinds = new Set(['long_table', 'table', 'chair', 'throne', 'bookshelf', 'bed', 'column', 'fireplace', 'candelabra', 'plant', 'statue', 'couch', 'fountain_oct', 'fountain']);
