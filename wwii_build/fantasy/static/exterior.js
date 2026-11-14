import * as THREE from 'three';

import { archHole, box, cyl, gable, hip, merge, put, rng, shade, tint, xform } from './geom.js';
import { buildDecor } from './decor.js';
import { buildAqueducts, buildLandmarks } from './landmarks.js';
import { buildAtmosphere } from './atmosphere.js';

const MOODS = {
  realistic: { top: '#6fa6df', bottom: '#dbe8f2', fog: '#c9d6e0', density: 0.0011, sun: '#fff3dc', sunI: 2.6, amb: 0.7, height: 0.8, lit: 0.2 },
  magical: { top: '#3a2a78', bottom: '#e7a6dc', fog: '#8f7ad1', density: 0.0022, sun: '#ffd9fb', sunI: 2.0, amb: 0.95, height: 0.5, lit: 0.8 },
  dark: { top: '#14141c', bottom: '#3d3d4b', fog: '#2b2b34', density: 0.004, sun: '#9aa6c9', sunI: 1.0, amb: 0.45, height: 0.35, lit: 0.9 },
  ancient: { top: '#7f9cc4', bottom: '#f0dfb8', fog: '#d9c9a2', density: 0.0012, sun: '#ffe2a8', sunI: 2.4, amb: 0.75, height: 0.55, lit: 0.3 },
  dramatic: { top: '#2c3e60', bottom: '#f0a15c', fog: '#b98a6a', density: 0.0022, sun: '#ffb66b', sunI: 2.8, amb: 0.55, height: 0.3, lit: 0.5 },
  colorful: { top: '#4fa9ff', bottom: '#ffe0f0', fog: '#f6dff0', density: 0.001, sun: '#fff6d8', sunI: 2.6, amb: 0.9, height: 0.8, lit: 0.25 },
};

const TIMES = {
  day: {},
  golden: { top: '#86a9d4', bottom: '#f2d3a6', fog: '#e6d0a8', sun: '#ffcf92', sunI: 2.6, height: 0.26, amb: 1.05, west: true },
  dawn: { top: '#7d9ccc', bottom: '#f6c9a8', fog: '#e3c7b6', sun: '#ffd0b0', sunI: 2.2, height: 0.16, amb: 0.6 },
  dusk: { top: '#2f3e66', bottom: '#e58a6a', fog: '#9f7a72', sun: '#ff9a6a', sunI: 1.8, height: 0.09, amb: 0.45, lit: 0.7 },
  night: { top: '#101a36', bottom: '#2a3658', fog: '#1d2440', sun: '#b4c6f0', sunI: 0.9, height: 0.6, amb: 0.75, lit: 0.9 },
};

const GRASS = { temperate: '#6a8048', alpine: '#6b7a5a', tropical: '#4f8f46', desert: '#c9a56a', none: '#8a8a80' };
const PITCH = { low: 0.3, normal: 0.5, steep: 0.95 };
const TILE = 150;

const smooth = (a, b, t) => {
  const x = Math.max(0, Math.min(1, (t - a) / (b - a)));
  return x * x * (3 - 2 * x);
};

export const upgradeScene = (data) => {
  if (data.version === 2) return data;
  const styles = data.styles || { window: 'rect', ornament: [], snow_roofs: false };
  const legacyBridges = data.streets.flatMap((s) =>
    s.pts.slice(1).map((q, i) => [s.pts[i], q]).filter(([, q]) => q[3] === 2).map(([p, q], i) => ({ id: `legacy${i}`, name: 'גשר', style: 'wood', a: [p[0], p[1], q[2] + 0.1], b: [q[0], q[1], q[2] + 0.1], width: 3.6, water: q[2] - 6, bed: q[2] - 8 })));
  return {
    ...data,
    version: 2,
    rivers: (data.rivers || []).map((r) => ({ ...r, quays: false, pts: r.pts.map((p) => [p[0], p[1], p[2] + 0.4, r.width || 5]) })),
    bridges: legacyBridges,
    landmarks: [],
    aqueducts: [],
    walls: [],
    districts: [],
    time_of_day: 'day',
    condition: { decay: 0, overgrowth: 0, ruins: 0 },
    palace: { ...data.palace, rot: 0, kind: 'castle' },
    houses: data.houses.map((h) => ({ ...h, pitch: 'normal', window: styles.window, timber: false, balconies: false, arcades: false, chimneys: true, shutters: false, ruin: false, vines: 0, grime: 0 })),
    streets: data.streets.map((s) => ({ ...s, width: s.main ? 3.4 : 2.5 })),
    basemap: { id: 'legacy', name: 'מפת פרויקט (גרסה ישנה)', historical: false, sources: [], labels: [{ name: 'הארמון', x: data.palace.x, z: data.palace.z, kind: 'palace' }] },
  };
};

const makeSampler = (data) => {
  const n = data.n;
  const step = data.size / (n - 1);
  const h = data.heights;
  return (x, z) => {
    const fx = Math.max(0, Math.min(n - 1.0001, (x + data.size / 2) / step));
    const fz = Math.max(0, Math.min(n - 1.0001, (z + data.size / 2) / step));
    const i = Math.floor(fx);
    const j = Math.floor(fz);
    const tx = fx - i;
    const tz = fz - j;
    const a = h[j * n + i];
    const b = h[j * n + i + 1];
    const c = h[(j + 1) * n + i];
    const d = h[(j + 1) * n + i + 1];
    return tx + tz <= 1 ? a + (b - a) * tx + (c - a) * tz : d + (c - d) * (1 - tx) + (b - d) * (1 - tz);
  };
};

const makeWaterIndex = (data) => {
  const cells = new Map();
  const key = (x, z) => `${Math.floor(x / 4)},${Math.floor(z / 4)}`;
  data.rivers.forEach((r) =>
    r.pts.forEach((p, k) => {
      const q = r.pts[Math.min(k + 1, r.pts.length - 1)];
      const steps = Math.max(1, Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / 3));
      const rad = p[3] / 2 - 1;
      for (let s = 0; s < steps; s += 1) {
        const t = s / steps;
        const x = p[0] + (q[0] - p[0]) * t;
        const z = p[1] + (q[1] - p[1]) * t;
        for (let dx = -rad; dx <= rad; dx += 3) {
          for (let dz = -rad; dz <= rad; dz += 3) {
            if (dx * dx + dz * dz <= rad * rad) cells.set(key(x + dx, z + dz), p[2]);
          }
        }
      }
    }));
  return (x, z) => cells.get(key(x, z));
};

const terrainMesh = (data, sample) => {
  const n = data.n;
  const step = data.size / (n - 1);
  const maxH = data.heights.reduce((m, v) => (v > m ? v : m), -1e9);
  const climate = data.climate;
  const grass = new THREE.Color(GRASS[climate.vegetation] || GRASS.temperate);
  const dry = new THREE.Color('#a89a6c');
  const rock = new THREE.Color('#7c766d');
  const sand = new THREE.Color('#cdbb8f');
  const snow = new THREE.Color('#f2f5f8');
  const pos = new Float32Array(n * n * 3);
  const col = new Float32Array(n * n * 3);
  const cold = climate.vegetation !== 'tropical' && climate.vegetation !== 'desert';
  const mountain = ['sharp_mountains', 'mountains', 'cliff_port'].includes(data.terrain_kind);
  const c = new THREE.Color();
  const earth = new THREE.Color(data.mood === 'ancient' ? '#a8977a' : '#9b927f');
  const districts = data.districts || [];
  data.mood === 'ancient' && grass.lerp(new THREE.Color('#9a9658'), 0.45);
  const urban = (x, z) => districts.reduce((m, d) => Math.max(m, (1 - smooth(d.r * 0.55, d.r * 1.02, Math.hypot(x - d.x, z - d.z))) * Math.min(1, (d.density ?? 0.6) * 1.1)), 0);
  data.heights.forEach((y, k) => {
    const i = k % n;
    const j = Math.floor(k / n);
    const x = -data.size / 2 + i * step;
    const z = -data.size / 2 + j * step;
    pos[k * 3] = x;
    pos[k * 3 + 1] = y;
    pos[k * 3 + 2] = z;
    const r = 3;
    const slope = Math.hypot(sample(x + r, z) - sample(x - r, z), sample(x, z + r) - sample(x, z - r)) / (2 * r);
    const noise = (Math.sin(x * 0.07) * Math.cos(z * 0.09) + Math.sin(x * 0.31 + z * 0.17)) * 0.25 + 0.5;
    c.copy(grass).lerp(dry, noise * 0.45).lerp(earth, urban(x, z) * 0.85).lerp(rock, smooth(0.42, 0.9, slope));
    data.sea_level !== null && data.sea_level !== undefined && c.lerp(sand, 1 - smooth(data.sea_level + 0.4, data.sea_level + 2.6, y));
    const alt = cold && mountain ? smooth(maxH * 0.58, maxH * 0.78, y) : 0;
    const ground = climate.snow_ground ? 0.88 : 0;
    c.lerp(snow, Math.max(ground * (1 - 0.5 * smooth(0.6, 1.1, slope)), alt * (1 - 0.6 * smooth(0.7, 1.3, slope))));
    c.multiplyScalar(0.94 + ((((Math.sin(x * 12.9898 + z * 78.233) * 43758.5453) % 1) + 1) % 1) * 0.1);
    col[k * 3] = c.r;
    col[k * 3 + 1] = c.g;
    col[k * 3 + 2] = c.b;
  });
  const idx = new Uint32Array((n - 1) * (n - 1) * 6);
  let w = 0;
  for (let j = 0; j < n - 1; j += 1) {
    for (let i = 0; i < n - 1; i += 1) {
      const a = j * n + i;
      idx.set([a, a + n, a + 1, a + 1, a + n, a + n + 1], w);
      w += 6;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 }));
  mesh.receiveShadow = true;
  return mesh;
};

const tiltBox = (geo, hex, x, y, z, yaw, pitch) => xform(tint(geo, hex), x, y, z, yaw, 1, 1, 1, -pitch);

const basaltTexture = () => {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const g = c.getContext('2d');
  const img = g.createImageData(size, size);
  const rand = rng(5150);
  const seeds = Array.from({ length: 34 }, () => [rand() * size, rand() * size, 0.82 + rand() * 0.3]);
  const wrap = (d) => Math.min(Math.abs(d), size - Math.abs(d));
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      let a = 1e9;
      let b = 1e9;
      let tone = 1;
      seeds.forEach(([sx, sy, t]) => {
        const d = Math.hypot(wrap(x - sx), wrap(y - sy));
        if (d < a) {
          b = a;
          a = d;
          tone = t;
        } else if (d < b) b = d;
      });
      const joint = b - a < 2.2 ? 0.55 : 1;
      const grain = 0.92 + ((x * 7 + y * 13) % 11) / 110;
      const v = Math.round(255 * tone * joint * grain * 0.62);
      img.data.set([v, v * 0.98, v * 0.95, 255], (y * size + x) * 4);
    }
  }
  g.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
};

const scaleUv = (geo, su, sv) => {
  const uv = geo.attributes.uv;
  for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv);
  return geo;
};

const buildStreets = (data, sample) => {
  const parts = [];
  const steps = [];
  const paved = [];
  const roman = String((data.basemap && data.basemap.id) || '').startsWith('rome_');
  const climate = data.climate;
  const decay = data.condition.decay || 0;
  const pathColor = climate.snow_ground ? '#cfd6da' : climate.vegetation === 'desert' ? '#b79a68' : shade('#9a8f7a', 1 - decay * 0.15);
  const stepColor = climate.snow_ground ? '#dfe5e8' : '#8f877a';
  data.streets.forEach((street) => {
    const width = street.width || (street.main ? 3.4 : 2.5);
    street.pts.slice(0, -1).forEach((p, i) => {
      const q = street.pts[i + 1];
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      if (len < 0.05 || q[3] === 2 || p[3] === 2) return;
      const y0 = sample(p[0], p[1]);
      const y1 = sample(q[0], q[1]);
      const ang = Math.atan2(q[0] - p[0], q[1] - p[1]);
      const mid = [(p[0] + q[0]) / 2, (y0 + y1) / 2, (p[1] + q[1]) / 2];
      const pitch = Math.atan2(y1 - y0, len);
      if (roman && street.main && !climate.snow_ground) {
        paved.push(tiltBox(scaleUv(tint(new THREE.BoxGeometry(width - 1.4, 0.3, len + 0.3), '#ffffff'), (width - 1.4) / 2.6, (len + 0.3) / 2.6), '#ffffff', mid[0], mid[1], mid[2], ang, pitch));
        [-1, 1].forEach((side) => parts.push(tiltBox(new THREE.BoxGeometry(0.7, 0.48, len + 0.3), shade('#b9ad94', 1 - decay * 0.2), mid[0] + Math.cos(ang) * side * (width / 2 - 0.35), mid[1] + 0.08, mid[2] - Math.sin(ang) * side * (width / 2 - 0.35), ang, pitch)));
      } else {
        parts.push(tiltBox(new THREE.BoxGeometry(width, 0.3, len + 0.3), roman ? shade('#8c8270', 1 - decay * 0.1) : pathColor, mid[0], mid[1], mid[2], ang, pitch));
      }
      if (q[3] === 1) {
        const count = Math.ceil(len / 0.5);
        for (let k = 0; k < count; k += 1) {
          const t = (k + 0.5) / count;
          const x = p[0] + (q[0] - p[0]) * t;
          const z = p[1] + (q[1] - p[1]) * t;
          steps.push(box(width, 0.22, 0.5, stepColor, x, Math.round(sample(x, z) / 0.22) * 0.22 + 0.02, z, ang));
        }
      }
    });
  });
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const basalt = new THREE.MeshStandardMaterial({ map: basaltTexture(), color: shade('#ffffff', 1 - decay * 0.25), roughness: 0.82, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const group = new THREE.Group();
  [[parts, mat], [steps, mat], [paved, basalt]].forEach(([list, material]) => {
    const geo = merge(list);
    if (geo) {
      const mesh = new THREE.Mesh(geo, material);
      mesh.receiveShadow = true;
      group.add(mesh);
    }
  });
  return group;
};

const buildBridges = (data) => {
  const parts = [];
  const decks = [];
  data.bridges.forEach((b) => {
    const dx = b.b[0] - b.a[0];
    const dz = b.b[1] - b.a[1];
    const L = Math.hypot(dx, dz);
    const deck = b.a[2];
    const yaw = Math.atan2(-dz, dx);
    const cx = (b.a[0] + b.b[0]) / 2;
    const cz = (b.a[1] + b.b[1]) / 2;
    const side = (s, off) => [cx + Math.sin(yaw) * s * off, cz + Math.cos(yaw) * s * off];
    decks.push({ ax: b.a[0], az: b.a[1], ay: b.a[2], bx: b.b[0], bz: b.b[1], by: b.b[2], half: b.width / 2 });
    if (b.style === 'arched_stone') {
      const bottom = (b.bed ?? deck - 9) - 1;
      const H = deck - bottom;
      const k = Math.max(1, Math.round(L / 24));
      const outline = new THREE.Shape();
      outline.moveTo(-L / 2, 0);
      outline.lineTo(L / 2, 0);
      outline.lineTo(L / 2, H);
      outline.lineTo(-L / 2, H);
      outline.lineTo(-L / 2, 0);
      const pitch = L / k;
      const open = pitch * 0.72;
      const spring = Math.max(0.5, H - open / 2 - 1.4);
      for (let i = 0; i < k; i += 1) outline.holes.push(archHole(-L / 2 + pitch * (i + 0.5), 0, open, spring));
      const geo = new THREE.ExtrudeGeometry(outline, { depth: b.width, bevelEnabled: false, curveSegments: 10 });
      geo.translate(0, 0, -b.width / 2);
      parts.push(put(geo, '#c9bb9a', cx, bottom, cz, yaw));
      [-1, 1].forEach((s) => {
        const [x, z] = side(s, b.width / 2 - 0.25);
        parts.push(put(new THREE.BoxGeometry(L, 1.0, 0.5), '#b9ab8a', x, deck + 0.5, z, yaw));
      });
    } else {
      parts.push(put(new THREE.BoxGeometry(L, 0.45, b.width), '#6a4a2c', cx, deck - 0.22, cz, yaw));
      const posts = Math.max(2, Math.round(L / 8));
      for (let i = 0; i <= posts; i += 1) {
        const t = i / posts - 0.5;
        const h = deck - (b.bed ?? deck - 6);
        parts.push(box(0.7, h, 0.7, '#4a3524', cx + Math.cos(yaw) * t * L, deck - h / 2, cz - Math.sin(yaw) * t * L, yaw));
      }
      [-1, 1].forEach((s) => {
        const [x, z] = side(s, b.width / 2);
        parts.push(put(new THREE.BoxGeometry(L, 0.9, 0.15), '#4a3524', x, deck + 0.45, z, yaw));
      });
    }
  });
  const geo = merge(parts);
  const mesh = geo ? new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 })) : new THREE.Group();
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return { mesh, decks };
};

const buildWater = (data, sample) => {
  const group = new THREE.Group();
  const color = data.mood === 'ancient' ? '#4b7f86' : '#2b6f9a';
  const material = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.88, roughness: 0.08, metalness: 0.15, side: THREE.DoubleSide });
  material.userData.noWeather = true;
  if (data.sea_level !== null && data.sea_level !== undefined) {
    const sea = new THREE.Mesh(new THREE.PlaneGeometry(5000, 5000), material);
    sea.rotation.x = -Math.PI / 2;
    sea.position.y = data.sea_level;
    group.add(sea);
  }
  (data.lakes || []).forEach((l) => {
    const lake = new THREE.Mesh(new THREE.CircleGeometry(l.r, 40), material);
    lake.rotation.x = -Math.PI / 2;
    lake.position.set(l.x, l.y, l.z);
    group.add(lake);
  });
  const quays = [];
  data.rivers.forEach((r) => {
    const pts = r.pts;
    const pos = [];
    const edges = pts.map((p, k) => {
      const q = pts[Math.min(k + 1, pts.length - 1)];
      const o = pts[Math.max(k - 1, 0)];
      const dx = q[0] - o[0];
      const dz = q[1] - o[1];
      const len = Math.hypot(dx, dz) || 1;
      const nx = -dz / len;
      const nz = dx / len;
      return [[p[0] + (nx * p[3]) / 2, p[1] + (nz * p[3]) / 2], [p[0] - (nx * p[3]) / 2, p[1] - (nz * p[3]) / 2], nx, nz];
    });
    pts.slice(0, -1).forEach((p, k) => {
      const q = pts[k + 1];
      const [la, ra] = edges[k];
      const [lb, rb] = edges[k + 1];
      pos.push(la[0], p[2], la[1], ra[0], p[2], ra[1], lb[0], q[2], lb[1], ra[0], p[2], ra[1], rb[0], q[2], rb[1], lb[0], q[2], lb[1]);
      if (r.quays) {
        [[la, lb, 1], [ra, rb, -1]].forEach(([a, b, s]) => {
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
          const nx = edges[k][2] * s;
          const nz = edges[k][3] * s;
          const top = p[2] + 5.4;
          const bottom = p[2] - 2.5;
          quays.push(put(new THREE.BoxGeometry(3.6, top - bottom, len + 0.6), '#b6a989', (a[0] + b[0]) / 2 - nx * 1.2, (top + bottom) / 2, (a[1] + b[1]) / 2 - nz * 1.2, Math.atan2(b[0] - a[0], b[1] - a[1])));
        });
      }
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.computeVertexNormals();
    const strip = new THREE.Mesh(geo, material);
    strip.receiveShadow = true;
    group.add(strip);
  });
  const qgeo = merge(quays);
  qgeo && group.add(new THREE.Mesh(qgeo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 })));
  return group;
};

const windowShape = (style, r) => {
  const shape = new THREE.Shape();
  return ({
    round: () => {
      shape.absarc(0, 0, r * 0.5, 0, Math.PI * 2, false);
      return shape;
    },
    arched: () => {
      shape.moveTo(-r * 0.38, -r * 0.65);
      shape.lineTo(r * 0.38, -r * 0.65);
      shape.lineTo(r * 0.38, r * 0.25);
      shape.absarc(0, r * 0.25, r * 0.38, 0, Math.PI, false);
      shape.lineTo(-r * 0.38, -r * 0.65);
      return shape;
    },
  }[style] || (() => null))();
};

const windowGeo = (style, size) => {
  const shape = windowShape(style, size);
  return shape ? new THREE.ShapeGeometry(shape, 4) : new THREE.PlaneGeometry(size * 0.72, size * 1.25);
};

const roofParts = (roof, pitch, w, d, y, color, snow) => {
  const p = PITCH[pitch] || PITCH.normal;
  const geos = {
    gable: () => [gable(w, d, Math.max(1, d * p)), 0],
    hip: () => [hip(w, d, Math.max(0.9, Math.min(w, d) * p)), 0],
    pointed: () => [new THREE.ConeGeometry((Math.hypot(w, d) / 2) * 1.08, Math.max(w, d) * (p + 0.55), 4, 1).rotateY(Math.PI / 4), (Math.max(w, d) * (p + 0.55)) / 2],
    dome: () => [new THREE.SphereGeometry((Math.max(w, d) / 2) * 1.04, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2), 0],
    curved: () => [new THREE.CylinderGeometry(d / 2 + 0.2, d / 2 + 0.2, w + 0.6, 14, 1, false, 0, Math.PI).rotateZ(Math.PI / 2), 0],
    flat: () => [new THREE.BoxGeometry(w + 0.4, 0.35, d + 0.4), 0.17],
  };
  const [geo, lift] = (geos[roof] || geos.gable)();
  const base = put(geo.clone(), color, 0, y + lift, 0);
  return snow ? [base, put(geo.clone(), '#f4f7fa', 0, y + lift + 0.06, 0, 0, 1.04, 1.05, 1.04)] : [base];
};

const ruinParts = (h, wallH, rand) => {
  const parts = [];
  [[0, h.d / 2 - 0.3, h.w, 0.6], [0, -h.d / 2 + 0.3, h.w, 0.6], [h.w / 2 - 0.3, 0, 0.6, h.d], [-h.w / 2 + 0.3, 0, 0.6, h.d]].forEach(([x, z, sw, sd]) => {
    if (rand() > 0.25) {
      const hh = wallH * (0.25 + rand() * 0.6);
      parts.push(box(sw, hh, sd, shade(h.wall_color, 0.85), x, hh / 2, z));
    }
  });
  Array.from({ length: 4 }).forEach(() => parts.push(box(1 + rand() * 1.5, 0.5 + rand() * 0.8, 1 + rand() * 1.5, shade(h.wall_color, 0.7), (rand() - 0.5) * h.w * 0.7, 0.3, (rand() - 0.5) * h.d * 0.7)));
  Array.from({ length: Math.round(h.vines * 4) + 1 }).forEach(() => parts.push(box(1.5 + rand() * 2, 0.8 + rand(), 1.5 + rand() * 2, '#5f7a3a', (rand() - 0.5) * h.w * 0.6, 0.4, (rand() - 0.5) * h.d * 0.6)));
  return parts;
};

const houseParts = (h, styles, mood, rand) => {
  const floorH = h.type === 'insula' ? 3.1 : 2.8;
  const wallH = floorH * h.floors;
  const wall = h.wall_color;
  const parts = [box(h.w + 0.3, h.foundation + 0.3, h.d + 0.3, '#6e6b64', 0, -h.foundation / 2 + 0.15, 0)];
  if (h.ruin) return parts.concat(ruinParts(h, wallH, rand));
  parts.push(box(h.w, wallH, h.d, wall, 0, wallH / 2, 0));
  h.grime > 0.15 && parts.push(box(h.w + 0.05, 0.8 + h.grime * 1.6, h.d + 0.05, shade(wall, 1 - h.grime * 0.35), 0, (0.8 + h.grime * 1.6) / 2, 0));
  Array.from({ length: h.floors - 1 }).forEach((_, i) => parts.push(box(h.w + 0.12, 0.16, h.d + 0.12, h.timber ? '#3a2716' : shade(wall, 0.8), 0, floorH * (i + 1), 0)));
  parts.push(...roofParts(h.roof, h.pitch, h.w, h.d, wallH, h.roof_color, styles.snow_roofs));
  const faces = [
    { n: Math.max(1, Math.floor(h.w / 2.6)), len: h.w, pos: (o) => [o, h.d / 2 + 0.03], ry: 0, front: true },
    { n: Math.max(1, Math.floor(h.w / 2.6)), len: h.w, pos: (o) => [-o, -h.d / 2 - 0.03], ry: Math.PI },
    { n: Math.max(1, Math.floor(h.d / 3.2)), len: h.d, pos: (o) => [h.w / 2 + 0.03, -o], ry: Math.PI / 2 },
    { n: Math.max(1, Math.floor(h.d / 3.2)), len: h.d, pos: (o) => [-h.w / 2 - 0.03, o], ry: -Math.PI / 2 },
  ];
  const style = h.window || styles.window;
  faces.forEach((f) =>
    Array.from({ length: h.floors }).forEach((_, fl) =>
      Array.from({ length: f.n }).forEach((__, k) => {
        const off = ((k + 0.5) / f.n - 0.5) * f.len;
        const [x, z] = f.pos(off);
        const ground = fl === 0 && f.front;
        if (ground && (h.arcades || Math.abs(off) < 1.3)) return;
        const y = 1.55 + fl * floorH;
        parts.push(put(windowGeo(style, 0.95), rand() < mood.lit ? '#f4c870' : '#26344d', x, y, z, f.ry));
        h.shutters && [-1, 1].forEach((s) => parts.push(box(0.36, 1.15, 0.05, '#3f6a4a', x + Math.cos(f.ry) * s * 0.62, y, z - Math.sin(f.ry) * s * 0.62, f.ry)));
      })));
  if (h.arcades) {
    const bays = Math.max(1, Math.floor(h.w / 3.2));
    Array.from({ length: bays }).forEach((_, k) => parts.push(put(new THREE.ShapeGeometry(new THREE.Shape(archHole(0, 0, 2.2, 1.6).getPoints(6))), '#1f1b18', ((k + 0.5) / bays - 0.5) * h.w, 0.05, h.d / 2 + 0.04)));
  } else {
    parts.push(put(windowGeo(style === 'arched' ? 'arched' : 'rect', 2.2), '#3a2716', 0, 1.05, h.d / 2 + 0.04));
  }
  h.balconies && Array.from({ length: Math.min(2, h.floors - 1) }).forEach((_, i) => {
    const y = floorH * (i + 1);
    parts.push(box(h.w * 0.7, 0.14, 1.0, '#5a3d24', 0, y, h.d / 2 + 0.5));
    parts.push(box(h.w * 0.7, 0.75, 0.08, '#4a3524', 0, y + 0.42, h.d / 2 + 1.0));
  });
  if (h.timber) {
    [[-1, 1], [1, 1], [-1, -1], [1, -1]].forEach(([sx, sz]) => parts.push(box(0.26, wallH, 0.26, '#3a2716', sx * (h.w / 2 - 0.05), wallH / 2, sz * (h.d / 2 - 0.05))));
    [1, -1].forEach((sz) => Array.from({ length: h.floors }).forEach((_, fl) => [-1, 1].forEach((s) => parts.push(put(new THREE.BoxGeometry(0.2, floorH * 1.1, 0.06).rotateZ(s * 0.65), '#3a2716', s * h.w * 0.3, floorH * (fl + 0.5), sz * (h.d / 2 + 0.05))))));
  }
  h.chimneys && h.roof !== 'flat' && rand() < 0.45 && parts.push(box(0.8, 1.8, 0.8, '#6e6b64', h.w * 0.25, wallH + 1.2, h.d * 0.12));
  Array.from({ length: Math.round(h.vines * 5) }).forEach(() => {
    const side = Math.floor(rand() * 4);
    const t = rand() - 0.5;
    const vh = 1.5 + rand() * wallH * 0.8;
    const vw = 0.8 + rand() * 2;
    const spot = [[t * h.w, h.d / 2 + 0.12, 0], [t * h.w, -h.d / 2 - 0.12, 0], [h.w / 2 + 0.12, t * h.d, Math.PI / 2], [-h.w / 2 - 0.12, t * h.d, Math.PI / 2]][side];
    parts.push(box(vw, vh, 0.2, shade('#4f6b35', 0.8 + rand() * 0.4), spot[0], vh / 2, spot[1], spot[2]));
  });
  return parts;
};

const tileKey = (h) => `${Math.floor(h.x / TILE)},${Math.floor(h.z / TILE)}`;

const tileMesh = (houses, styles, mood, mat) => {
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const one = new THREE.Vector3(1, 1, 1);
  const list = houses.flatMap((h) => {
    m.compose(new THREE.Vector3(h.x, h.y, h.z), q.setFromAxisAngle(up, h.rot), one);
    return houseParts(h, styles, mood, rng(Number(h.id.slice(1)) * 7 + 23)).map((g) => g.applyMatrix4(m));
  });
  const geo = merge(list);
  const mesh = geo ? new THREE.Mesh(geo, mat) : new THREE.Group();
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
};

const buildHouses = (data, styles, mood, hidden = new Set()) => {
  const tiles = new Map();
  data.houses.forEach((h) => {
    const key = tileKey(h);
    tiles.has(key) || tiles.set(key, []);
    hidden.has(h.id) || tiles.get(key).push(h);
  });
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 });
  const group = new THREE.Group();
  tiles.forEach((houses, key) => {
    const mesh = tileMesh(houses, styles, mood, mat);
    mesh.userData.houseTile = key;
    group.add(mesh);
  });
  group.userData.mat = mat;
  return group;
};

const palaceParts = (p, styles, mood) => {
  const parts = [];
  const rand = rng(11);
  const hw = p.w / 2;
  const hd = p.d / 2;
  const dw = p.door.width;
  const pocket = 2.0;
  const wall = p.wall_color;
  const win = styles.window;
  parts.push(box(p.w, p.h, p.d - pocket, wall, 0, p.h / 2, -pocket / 2));
  parts.push(box(hw - dw / 2, p.h, pocket, wall, -(hw + dw / 2) / 2, p.h / 2, hd - pocket / 2));
  parts.push(box(hw - dw / 2, p.h, pocket, wall, (hw + dw / 2) / 2, p.h / 2, hd - pocket / 2));
  parts.push(box(dw, p.h - p.door.height, pocket, wall, 0, p.door.height + (p.h - p.door.height) / 2, hd - pocket / 2));
  parts.push(box(dw - 0.2, p.door.height - 0.2, 0.2, '#3a2716', 0, p.door.height / 2, hd - pocket + 0.1));
  [0.9, -0.9].forEach((x) => parts.push(box(0.25, 0.7, 0.12, '#d4a93a', x, 2.2, hd - pocket + 0.25)));
  parts.push(box(dw + 1.2, 0.2, pocket + 0.6, '#8a8478', 0, 0.1, hd - pocket / 2 + 0.3));
  if (p.kind === 'classical') {
    const cols = 8;
    const depth = 7;
    parts.push(box(p.w, 0.3, depth, '#d7cdb8', 0, 0.15, hd + depth / 2));
    Array.from({ length: cols }).forEach((_, k) => {
      const x = (-0.5 + k / (cols - 1)) * (p.w - 2);
      Math.abs(x) > dw / 2 + 0.6 && parts.push(cyl(0.6, 0.7, p.h - 1.7, 12, '#e4ddcc', x, 0.3 + (p.h - 1.7) / 2, hd + depth - 1));
    });
    parts.push(box(p.w, 1.4, depth, '#e4ddcc', 0, p.h - 0.7, hd + depth / 2));
    parts.push(put(gable(depth, p.w, 4.2, 0.2), p.roof_color, 0, p.h, hd + depth / 2, Math.PI / 2));
    parts.push(put(hip(p.w, p.d, Math.min(p.w, p.d) * 0.28), p.roof_color, 0, p.h, 0));
  } else {
    [[-hw, -hd], [hw, -hd], [-hw, hd], [hw, hd]].forEach(([x, z]) => {
      parts.push(cyl(3.1, 3.4, p.h + 6, 16, wall, x, (p.h + 6) / 2, z));
      roofParts('pointed', 'normal', 6.4, 6.4, p.h + 6, p.roof_color, styles.snow_roofs).forEach((r) => parts.push(r.translate(x, 0, z)));
    });
    const keep = p.roof === 'dome'
      ? [cyl(6, 6.4, 3, 20, wall, 0, p.h + 1.5, -1), put(new THREE.SphereGeometry(7, 24, 14, 0, Math.PI * 2, 0, Math.PI / 2), p.roof_color, 0, p.h + 3, -1)]
      : p.roof === 'pointed' ? [cyl(5, 5.4, 6, 8, wall, 0, p.h + 3, -1), put(new THREE.ConeGeometry(6.2, 14, 8), p.roof_color, 0, p.h + 13, -1)] : roofParts(p.roof, 'normal', p.w, p.d, p.h, p.roof_color, styles.snow_roofs);
    parts.push(...keep);
  }
  [-1, 0, 1].forEach((row) => [-2, -1, 0, 1, 2].forEach((col) => {
    const x = col * (p.w / 6.2);
    const y = p.h * 0.45 + row * (p.h * 0.22);
    (Math.abs(x) > dw / 2 + 0.5 || row === 1) && parts.push(put(windowGeo(win, 1.9), rand() < mood.lit ? '#f4c870' : '#26344d', x, y, hd + 0.04));
    parts.push(put(windowGeo(win, 1.9), '#26344d', x, y, -hd - 0.04, Math.PI));
  }));
  return parts;
};

const buildPalace = (data, mood) => {
  const p = data.palace;
  const g = new THREE.Group();
  const mesh = new THREE.Mesh(merge(palaceParts(p, data.styles, mood)), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 }));
  mesh.userData.palace = true;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  g.add(mesh);
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(16, 40), new THREE.MeshStandardMaterial({ color: data.climate.snow_ground ? '#dfe5e8' : '#b3a990', roughness: 1, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 }));
  plaza.rotation.x = -Math.PI / 2;
  plaza.position.set(0, 0.08, p.d / 2 + 14);
  g.add(plaza);
  g.position.set(p.x, p.y - 0.15, p.z);
  g.rotation.y = p.rot;
  const hw = p.w / 2;
  const hd = p.d / 2;
  const dw = p.door.width;
  const pocket = 2.0;
  const c = Math.cos(p.rot);
  const s = Math.sin(p.rot);
  const local = [
    { x: 0, z: -pocket / 2, hw, hd: hd - pocket / 2 },
    { x: -(hw + dw / 2) / 2, z: hd - pocket / 2, hw: (hw - dw / 2) / 2, hd: pocket / 2 },
    { x: (hw + dw / 2) / 2, z: hd - pocket / 2, hw: (hw - dw / 2) / 2, hd: pocket / 2 },
  ];
  const colliders = local.map((l) => ({ cx: p.x + l.x * c + l.z * s, cz: p.z - l.x * s + l.z * c, hw: l.hw, hd: l.hd, rot: p.rot }));
  return { group: g, colliders, trigger: { x: p.x, z: p.z, rot: p.rot, zBack: hd - pocket, half: dw / 2 - 0.2 } };
};

const buildWalls = (data) => {
  const parts = [];
  const colliders = [];
  data.walls.forEach((w) =>
    w.pts.slice(0, -1).forEach((p, k) => {
      const q = w.pts[k + 1];
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      const ang = Math.atan2(q[0] - p[0], q[1] - p[1]);
      const base = Math.min(p[2], q[2]) - 1;
      const top = Math.max(p[2], q[2]) + w.height;
      parts.push(box(w.thick, top - base, len + 0.3, '#8f877a', (p[0] + q[0]) / 2, (top + base) / 2, (p[1] + q[1]) / 2, ang));
      k % 7 === 0 && parts.push(box(6, top - base + 3, 6, '#857e72', p[0], (top + base + 3) / 2, p[1], ang));
      colliders.push({ cx: (p[0] + q[0]) / 2, cz: (p[1] + q[1]) / 2, hw: w.thick / 2 + 0.2, hd: len / 2 + 0.2, rot: ang });
    }));
  const geo = merge(parts);
  const mesh = geo ? new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95 })) : new THREE.Group();
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return { mesh, colliders };
};

const treeGeometries = (snowGround) => ({
  pine: merge([box(0.4, 2.0, 0.4, '#5a3a1f', 0, 1.0, 0), put(new THREE.ConeGeometry(2.0, 3.2, 8), '#2f5a3a', 0, 3.2, 0), put(new THREE.ConeGeometry(1.6, 2.8, 8), '#2f6240', 0, 4.8, 0),
    put(new THREE.ConeGeometry(1.1, 2.4, 8), snowGround ? '#e9f0f2' : '#376d47', 0, 6.3, 0)]),
  broadleaf: merge([box(0.5, 2.4, 0.5, '#5a3a1f', 0, 1.2, 0), put(new THREE.IcosahedronGeometry(2.0, 1), '#4f7f3e', 0, 4.0, 0, 0, 1, 0.9, 1), put(new THREE.IcosahedronGeometry(1.3, 1), '#5c8d46', 0.9, 4.9, 0.3)]),
  palm: merge([...Array.from({ length: 5 }, (_, i) => put(new THREE.CylinderGeometry(0.22 - i * 0.02, 0.26 - i * 0.02, 1.7, 7), '#8a6a42', i * 0.16, 0.85 + i * 1.6, 0)),
    ...Array.from({ length: 7 }, (_, i) => put(new THREE.ConeGeometry(0.55, 3.6, 4).rotateZ(Math.PI / 2 + 0.5).translate(1.7, 0, 0), '#3c8f3c', 0.65, 8.2, 0, (i / 7) * Math.PI * 2, 1, 0.35, 1))]),
  shrub: merge([put(new THREE.IcosahedronGeometry(0.8, 1), '#6f7f45', 0, 0.55, 0, 0, 1, 0.7, 1)]),
  cypress: merge([box(0.35, 1.2, 0.35, '#4a3524', 0, 0.6, 0), put(new THREE.SphereGeometry(1, 10, 10), '#2c4a2b', 0, 5.2, 0, 0, 1.1, 4.6, 1.1)]),
  umbrella_pine: merge([put(new THREE.CylinderGeometry(0.28, 0.42, 8.5, 7), '#6a4a32', 0.3, 4.2, 0, 0, 1, 1, 1, 0.06), put(new THREE.SphereGeometry(1, 14, 8), '#3d5a33', 0.8, 9.2, 0, 0, 4.6, 1.3, 4.2),
    put(new THREE.SphereGeometry(1, 12, 6), '#45653a', -0.6, 9.8, 0.4, 0, 3.2, 1.0, 3.0)]),
});

const buildTrees = (data) => {
  const geos = treeGeometries(data.climate.snow_ground);
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9 });
  const group = new THREE.Group();
  const rand = rng(7);
  const m = new THREE.Matrix4();
  Object.entries(geos).forEach(([kind, geo]) => {
    const indices = data.trees.map((t, i) => (t.kind === kind ? i : -1)).filter((i) => i >= 0);
    const list = indices.map((i) => data.trees[i]);
    if (list.length) {
      const mesh = new THREE.InstancedMesh(geo, mat, list.length);
      mesh.userData.treeIndices = indices;
      list.forEach((t, i) => mesh.setMatrixAt(i, m.compose(new THREE.Vector3(t.x, t.y - 0.1, t.z), new THREE.Quaternion().setFromEuler(new THREE.Euler(0, rand() * 6.28, 0)), new THREE.Vector3(t.s, t.s * (0.9 + rand() * 0.3), t.s))));
      mesh.castShadow = true;
      group.add(mesh);
    }
  });
  return group;
};

const skyDome = (look) =>
  new THREE.Mesh(
    new THREE.SphereGeometry(2600, 24, 16),
    new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: { top: { value: new THREE.Color(look.top) }, bottom: { value: new THREE.Color(look.bottom) } },
      vertexShader: 'varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: 'uniform vec3 top; uniform vec3 bottom; varying float h; void main(){ float t = smoothstep(-0.02, 0.42, h); gl_FragColor = vec4(mix(bottom, top, t), 1.0); }',
    }),
  );

const buildWeather = (kind) => {
  const count = kind === 'snow' ? 7000 : 5000;
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) pos.set([(Math.random() - 0.5) * 120, Math.random() * 60, (Math.random() - 0.5) * 120], i * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const points = new THREE.Points(geo, new THREE.PointsMaterial({ color: kind === 'snow' ? '#ffffff' : '#a9c4d8', size: kind === 'snow' ? 0.22 : 0.12, transparent: true, opacity: 0.85, depthWrite: false }));
  points.frustumCulled = false;
  points.userData.kind = kind;
  return points;
};

const colliderIndex = (list) => {
  const cells = new Map();
  const key = (i, j) => `${i},${j}`;
  list.forEach((c) => {
    const box3 = c.cx === undefined;
    const reach = box3 ? Math.max(c.maxx - c.minx, c.maxz - c.minz) / 2 : Math.hypot(c.hw, c.hd);
    const x = box3 ? (c.minx + c.maxx) / 2 : c.cx;
    const z = box3 ? (c.minz + c.maxz) / 2 : c.cz;
    for (let i = Math.floor((x - reach) / 30); i <= Math.floor((x + reach) / 30); i += 1) {
      for (let j = Math.floor((z - reach) / 30); j <= Math.floor((z + reach) / 30); j += 1) {
        const k = key(i, j);
        cells.has(k) || cells.set(k, []);
        cells.get(k).push(c);
      }
    }
  });
  return (x, z) => [...new Set([-1, 0, 1].flatMap((di) => [-1, 0, 1].flatMap((dj) => cells.get(key(Math.floor(x / 30) + di, Math.floor(z / 30) + dj)) || [])))];
};

export const buildExterior = (raw) => {
  const data = upgradeScene(raw);
  const scene = new THREE.Scene();
  const look = { ...(MOODS[data.mood] || MOODS.realistic), ...(TIMES[data.time_of_day] || {}) };
  const climate = data.climate;
  const sample = makeSampler(data);
  const waterAt = makeWaterIndex(data);
  const sky = skyDome(look);
  scene.add(sky);
  scene.fog = new THREE.FogExp2(climate.fog ? '#c9ccd2' : look.fog, look.density * (climate.fog ? 4 : 1) * (climate.precip === 'snow' ? 1.8 : 1) * (data.size > 1200 ? 0.7 : 1));
  const hemi = new THREE.HemisphereLight(look.top, '#6d6a5e', look.amb);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(look.sun, look.sunI);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -110, right: 110, top: 110, bottom: -110, near: 1, far: 700 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.6;
  scene.add(sun, sun.target);
  scene.add(terrainMesh(data, sample));
  scene.add(buildWater(data, sample));
  scene.add(buildStreets(data, sample));
  const bridges = buildBridges(data);
  scene.add(bridges.mesh);
  const palace = buildPalace(data, look);
  scene.add(palace.group);
  const housesRef = { group: buildHouses(data, data.styles, look) };
  scene.add(housesRef.group);
  const marks = buildLandmarks(data.landmarks, data.condition);
  scene.add(marks.group);
  const aq = buildAqueducts(data.aqueducts, data.condition);
  scene.add(aq.mesh);
  const walls = buildWalls(data);
  scene.add(walls.mesh);
  const trees = buildTrees(data);
  scene.add(trees);
  const decor = buildDecor(data.decor);
  scene.add(decor.group);
  const atmo = data.life && !data.life.off && data.life.climate ? buildAtmosphere({ scene, data, sun, hemi, sky, fogBase: 0.00075 }) : null;
  const weather = atmo || climate.precip === 'none' ? null : buildWeather(climate.precip);
  weather && scene.add(weather);
  atmo && atmo.patch(scene);
  const lightDir = new THREE.Vector3(look.west ? -0.8 : 0.5, Math.max(0.12, look.height) * 1.6, look.west ? 0.35 : 0.6).normalize();
  const houseColliders = data.houses.map((h) => ({ cx: h.x, cz: h.z, hw: h.w / 2 + 0.15, hd: h.d / 2 + 0.15, rot: h.rot }));
  const colliders = palace.colliders.concat(houseColliders, marks.colliders, aq.colliders, walls.colliders);
  const near = colliderIndex(colliders);

  const hiddenHouses = new Set();
  const rebuildHouses = (styles) => {
    scene.remove(housesRef.group);
    housesRef.group.children.forEach((mesh) => mesh.geometry && mesh.geometry.dispose());
    housesRef.group = buildHouses(data, styles, look, hiddenHouses);
    atmo && atmo.patch(housesRef.group);
    scene.add(housesRef.group);
  };

  const hideHouse = (id) => {
    const h = data.houses.find((x) => x.id === id);
    if (!h || hiddenHouses.has(id)) return;
    hiddenHouses.add(id);
    const key = tileKey(h);
    const old = housesRef.group.children.find((c) => c.userData.houseTile === key);
    old && housesRef.group.remove(old);
    old && old.geometry && old.geometry.dispose();
    const mesh = tileMesh(data.houses.filter((x) => tileKey(x) === key && !hiddenHouses.has(x.id)), data.styles, look, housesRef.group.userData.mat);
    mesh.userData.houseTile = key;
    atmo && atmo.patch(mesh);
    housesRef.group.add(mesh);
  };

  const groundAt = (x, z, refY) => {
    const terrain = sample(x, z);
    const onDeck = bridges.decks
      .map((d) => {
        const dx = d.bx - d.ax;
        const dz = d.bz - d.az;
        const len2 = dx * dx + dz * dz;
        const t = ((x - d.ax) * dx + (z - d.az) * dz) / len2;
        const lat = Math.abs((x - d.ax) * dz - (z - d.az) * dx) / Math.sqrt(len2);
        return t >= -0.03 && t <= 1.03 && lat <= d.half ? d.ay + (d.by - d.ay) * Math.max(0, Math.min(1, t)) + 0.05 : null;
      })
      .filter((y) => y !== null && Math.abs(y - refY) < 3.0);
    return onDeck.length ? Math.max(terrain, ...onDeck) : terrain;
  };

  const isWater = (x, z, refY) => {
    const surf = waterAt(x, z);
    const sea = data.sea_level;
    const ground = groundAt(x, z, refY);
    return (surf !== undefined && ground < surf + 0.4) || (sea !== null && sea !== undefined && ground < sea - 0.7);
  };

  const update = (dt, camPos, time) => {
    sky.position.copy(camPos);
    decor.update(time);
    atmo && atmo.update(dt, camPos, time);
    const dir = atmo ? atmo.lightDir : lightDir;
    const sx = Math.round(camPos.x / 8) * 8;
    const sz = Math.round(camPos.z / 8) * 8;
    sun.target.position.set(sx, camPos.y, sz);
    sun.position.set(sx + dir.x * 300, camPos.y + dir.y * 300, sz + dir.z * 300);
    if (weather) {
      weather.position.set(camPos.x, camPos.y - 25, camPos.z);
      const arr = weather.geometry.attributes.position.array;
      const fall = weather.userData.kind === 'snow' ? 2.6 : 22;
      for (let i = 0; i < arr.length; i += 3) {
        arr[i + 1] -= fall * dt;
        arr[i] += weather.userData.kind === 'snow' ? Math.sin(time * 0.8 + i) * dt * 0.8 : -dt * 2;
        if (arr[i + 1] < 0) arr[i + 1] += 60;
      }
      weather.geometry.attributes.position.needsUpdate = true;
    }
  };

  const spawn = () => {
    const p = data.palace;
    const dist = p.d / 2 + 16;
    return { x: p.x + Math.sin(p.rot) * dist, z: p.z + Math.cos(p.rot) * dist, yaw: p.rot };
  };

  const pickables = () => [palace.group.children[0], ...marks.group.children, ...trees.children, ...housesRef.group.children, ...scene.children.filter((c) => c.userData.detailFor)];

  return { scene, sample, groundAt, isWater, colliders, near, trigger: palace.trigger, update, spawn, mood: look, data, rebuildHouses, trees, landmarks: marks.group, palaceGroup: palace.group, pickables, hideHouse, atmo, sun, hemi };
};
