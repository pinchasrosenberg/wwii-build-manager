import * as THREE from 'three';

import { arcadeWall, archHole, box, cyl, gable, merge, put, rng, shade } from './geom.js';

const TRAVERTINE = '#d6cab0';
const BRICK = '#a86a44';
const MARBLE = '#e4ddcc';
const TILE = '#a4532f';
const DARK = '#2a2420';
const SAND = '#d9c7a0';
const LEAF = '#4f6b35';

const weathered = (hex, ctx) => shade(hex, (1 - 0.2 * ctx.state) * (0.93 + ctx.rand() * 0.1));

const vines = (parts, ctx, spots) =>
  spots.forEach(([x, y, z, ry, size]) => {
    if (ctx.rand() < ctx.overgrowth) {
      const w = size * (0.6 + ctx.rand());
      const h = size * (1.2 + ctx.rand() * 2.2);
      parts.push(box(w, h, 0.25, shade(LEAF, 0.8 + ctx.rand() * 0.4), x, Math.max(h / 2, y), z, ry));
    }
  });

const ringSpots = (a, b, h, n, ctx) =>
  Array.from({ length: n }, (_, k) => {
    const t = (k / n) * Math.PI * 2 + ctx.rand() * 0.2;
    return [Math.cos(t) * (a + 0.4), ctx.rand() * h * 0.5, Math.sin(t) * (b + 0.4), Math.atan2(-Math.cos(t) * b, -Math.sin(t) * a) + Math.PI / 2, 3];
  });

const boxSpots = (w, d, h, n, ctx) =>
  Array.from({ length: n }, () => {
    const side = Math.floor(ctx.rand() * 4);
    const t = ctx.rand() - 0.5;
    const pos = [[t * w, d / 2 + 0.3, 0], [t * w, -d / 2 - 0.3, Math.PI], [w / 2 + 0.3, t * d, Math.PI / 2], [-w / 2 - 0.3, t * d, -Math.PI / 2]][side];
    return [pos[0], ctx.rand() * h * 0.4, pos[1], pos[2], 2.2];
  });

const ellipseRing = (inner, outer, a, b, y, hex) => {
  const geo = new THREE.RingGeometry(inner, outer, 72, 1);
  geo.rotateX(-Math.PI / 2);
  return put(geo, hex, 0, y, 0, 0, a, 1, b);
};

const ellipseWall = (f, a, b, h, y, hex) => put(new THREE.CylinderGeometry(1, 1, 1, 72, 1, true), hex, 0, y + h / 2, 0, 0, a * f, h, b * f);

const arcadeRing = (parts, a, b, h, tiers, ctx, arc = [0, Math.PI * 2], broken = true) => {
  const perim = Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
  const span = (arc[1] - arc[0]) / (Math.PI * 2);
  const bays = Math.max(12, Math.round((perim * span) / (h > 25 ? 7.6 : 6)));
  const tierH = h / tiers;
  Array.from({ length: bays }).forEach((_, k) => {
    const t0 = arc[0] + ((k + 0.5) / bays) * (arc[1] - arc[0]);
    const x = Math.cos(t0) * a;
    const z = Math.sin(t0) * b;
    const tx = -Math.sin(t0) * a;
    const tz = Math.cos(t0) * b;
    const ry = Math.atan2(-tz, tx);
    const seg = (perim * span) / bays;
    const collapsed = broken && ctx.state > 0.35 && t0 > Math.PI * 0.12 && t0 < Math.PI * 0.62;
    Array.from({ length: tiers }).forEach((__, t) => {
      const gone = collapsed && (t >= tiers - 1 || (t === tiers - 2 && Math.sin((t0 - Math.PI * 0.12) * 2) > 0.25));
      if (!gone) {
        const y = t * tierH;
        const attic = t === tiers - 1 && tiers > 2;
        if (attic) {
          parts.push(box(seg + 0.1, tierH, 1.8, weathered(TRAVERTINE, ctx), x, y + tierH / 2, z, ry));
        } else {
          parts.push(box(1.9, tierH * 0.86, 3.2, weathered(TRAVERTINE, ctx), x, y + tierH * 0.43, z, ry));
          parts.push(box(seg + 0.1, tierH * 0.16, 3.4, weathered(TRAVERTINE, ctx), x, y + tierH * 0.92, z, ry));
        }
      }
    });
  });
};

const amphitheater = (m, ctx) => {
  const parts = [];
  const a = m.w / 2;
  const b = m.d / 2;
  const tiers = m.h > 25 ? 4 : 2;
  arcadeRing(parts, a, b, m.h, tiers, ctx);
  parts.push(ellipseWall(0.955, a, b, m.h * (tiers > 2 ? 0.7 : 0.9), 0, DARK));
  Array.from({ length: 6 }).forEach((_, k) => {
    const f0 = 0.94 - k * 0.085;
    const y = m.h * 0.72 * (1 - k / 6);
    parts.push(ellipseRing(f0 - 0.085, f0, a, b, y, weathered(shade(TRAVERTINE, 0.85), ctx)));
    parts.push(ellipseWall(f0 - 0.085, a, b, (m.h * 0.72) / 6, y - (m.h * 0.72) / 6, weathered(shade(TRAVERTINE, 0.7), ctx)));
  });
  parts.push(ellipseRing(0, 0.43, a, b, 1.0, SAND));
  vines(parts, ctx, ringSpots(a, b, m.h, 26, ctx));
  return { parts, colliders: [{ x: 0, z: 0, hw: a * 0.93, hd: b * 0.93 }] };
};

const temple = (m, ctx) => {
  const parts = [];
  const ph = Math.max(1.2, m.h * 0.14);
  const ch = m.h * 0.6;
  const stone = m.w > 40 ? MARBLE : TRAVERTINE;
  parts.push(box(m.w + 3, ph, m.d + 3, weathered(TRAVERTINE, ctx), 0, ph / 2, 0));
  parts.push(box(m.w * 0.55, ph, 5, weathered(TRAVERTINE, ctx), 0, ph / 2 - 0.3, m.d / 2 + 4));
  const nx = Math.max(4, Math.round(m.w / 3.8));
  const nz = Math.max(5, Math.round(m.d / 3.8));
  const r = Math.min(1.0, m.w / (nx * 3.4));
  const cols = [
    ...Array.from({ length: nx }, (_, k) => [(-0.5 + k / (nx - 1)) * (m.w - 2), m.d / 2 - 1]),
    ...Array.from({ length: nx }, (_, k) => [(-0.5 + k / (nx - 1)) * (m.w - 2), -m.d / 2 + 1]),
    ...Array.from({ length: nz - 2 }, (_, k) => [m.w / 2 - 1, (-0.5 + (k + 1) / (nz - 1)) * (m.d - 2)]),
    ...Array.from({ length: nz - 2 }, (_, k) => [-m.w / 2 + 1, (-0.5 + (k + 1) / (nz - 1)) * (m.d - 2)]),
  ];
  cols.forEach(([x, z]) => {
    if (ctx.rand() > ctx.state * 0.22) {
      parts.push(cyl(r * 0.85, r, ch, 12, weathered(stone, ctx), x, ph + ch / 2, z));
      parts.push(box(r * 2.4, 0.5, r * 2.4, weathered(stone, ctx), x, ph + ch - 0.25, z));
    }
  });
  parts.push(box(m.w * 0.62, ch * 0.95, m.d * 0.6, weathered(m.w > 40 ? BRICK : TRAVERTINE, ctx), 0, ph + ch * 0.475, -m.d * 0.12));
  const roofless = ctx.state > 0.55 && ctx.rand() < 0.4;
  if (!roofless) {
    parts.push(box(m.w, m.h * 0.08, m.d, weathered(stone, ctx), 0, ph + ch + m.h * 0.04, 0));
    parts.push(put(gable(m.d, m.w, m.h * 0.17, 0.4), weathered(TILE, ctx), 0, ph + ch + m.h * 0.08, 0, Math.PI / 2));
  }
  vines(parts, ctx, boxSpots(m.w, m.d, m.h, 8, ctx));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2 + 1.5, hd: m.d / 2 + 1.5 }] };
};

const roundTemple = (m, ctx) => {
  const parts = [];
  const r = m.w / 2;
  parts.push(cyl(r + 1, r + 1.2, 1.4, 24, weathered(TRAVERTINE, ctx), 0, 0.7, 0));
  const n = Math.max(10, Math.round(r * 3));
  Array.from({ length: n }).forEach((_, k) => {
    const t = (k / n) * Math.PI * 2;
    parts.push(cyl(0.35, 0.42, m.h * 0.65, 10, weathered(MARBLE, ctx), Math.cos(t) * (r - 0.4), 1.4 + m.h * 0.325, Math.sin(t) * (r - 0.4)));
  });
  parts.push(cyl(r * 0.7, r * 0.7, m.h * 0.62, 20, weathered(MARBLE, ctx), 0, 1.4 + m.h * 0.31, 0));
  parts.push(cyl(r + 0.4, r + 0.4, 0.6, 24, weathered(MARBLE, ctx), 0, 1.4 + m.h * 0.67, 0));
  parts.push(put(new THREE.ConeGeometry(r + 0.6, m.h * 0.3, 24), weathered(TILE, ctx), 0, 1.4 + m.h * 0.82, 0));
  return { parts, colliders: [{ x: 0, z: 0, hw: r + 1, hd: r + 1 }] };
};

const triumphalArch = (m, ctx) => {
  const parts = [];
  const bodyH = m.h * 0.72;
  const outline = new THREE.Shape();
  outline.moveTo(-m.w / 2, 0);
  outline.lineTo(m.w / 2, 0);
  outline.lineTo(m.w / 2, bodyH);
  outline.lineTo(-m.w / 2, bodyH);
  outline.lineTo(-m.w / 2, 0);
  const triple = m.w >= 19;
  const cw = triple ? m.w * 0.27 : m.w * 0.42;
  outline.holes.push(archHole(0, 0, cw, bodyH * 0.55));
  triple && [-1, 1].forEach((s) => outline.holes.push(archHole(s * m.w * 0.33, 0, m.w * 0.12, bodyH * 0.33)));
  const geo = new THREE.ExtrudeGeometry(outline, { depth: m.d, bevelEnabled: false, curveSegments: 10 });
  geo.translate(0, 0, -m.d / 2);
  parts.push(put(geo, weathered(MARBLE, ctx), 0, 0, 0));
  parts.push(box(m.w, m.h - bodyH, m.d, weathered(MARBLE, ctx), 0, bodyH + (m.h - bodyH) / 2, 0));
  [-1, 1].forEach((face) =>
    (triple ? [-0.44, -0.2, 0.2, 0.44] : [-0.38, 0.38]).forEach((f) => parts.push(cyl(0.45, 0.5, bodyH * 0.92, 10, weathered(MARBLE, ctx), f * m.w, bodyH * 0.46, face * (m.d / 2 + 0.5)))));
  vines(parts, ctx, boxSpots(m.w, m.d, m.h, 5, ctx));
  const pier = (m.w - cw) / 4;
  return { parts, colliders: [{ x: -(cw / 2 + pier), z: 0, hw: pier, hd: m.d / 2 }, { x: cw / 2 + pier, z: 0, hw: pier, hd: m.d / 2 }] };
};

const facadeArches = (parts, len, y, z, ry, count, w, h, ctx) =>
  Array.from({ length: count }).forEach((_, k) => {
    const x = (-0.5 + (k + 0.5) / count) * len;
    const shape = new THREE.Shape(archHole(0, 0, w, h - w / 2).getPoints(10));
    const geo = new THREE.ShapeGeometry(shape);
    parts.push(put(geo, DARK, x * Math.cos(ry) + z * Math.sin(ry), y, -x * Math.sin(ry) + z * Math.cos(ry), ry));
    return ctx;
  });

const basilica = (m, ctx) => {
  const parts = [];
  const brick = weathered(m.h > 30 ? BRICK : TRAVERTINE, ctx);
  parts.push(box(m.w, m.h * 0.62, m.d, brick, 0, m.h * 0.31, 0));
  parts.push(box(m.w * 0.97, m.h * 0.38, m.d * 0.5, brick, 0, m.h * 0.81, 0));
  parts.push(put(gable(m.w * 0.97, m.d * 0.5, m.h * 0.13), weathered(TILE, ctx), 0, m.h, 0));
  parts.push(put(gable(m.w, m.d, m.h * 0.05, 0.2), weathered(TILE, ctx), 0, m.h * 0.62, 0));
  const bays = Math.max(3, Math.round(m.w / 9));
  [1, -1].forEach((s) => {
    facadeArches(parts, m.w * 0.9, 1.5, m.d / 2 + 0.05, s > 0 ? 0 : Math.PI, bays, Math.min(6, (m.w / bays) * 0.6), m.h * 0.42, ctx);
    facadeArches(parts, m.w * 0.9, m.h * 0.68, m.d / 4 + 0.05, s > 0 ? 0 : Math.PI, bays, Math.min(4, (m.w / bays) * 0.45), m.h * 0.22, ctx);
  });
  vines(parts, ctx, boxSpots(m.w, m.d, m.h, Math.round(m.w / 8), ctx));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.d / 2 }] };
};

const forum = (m, ctx) => {
  const parts = [];
  parts.push(box(m.w, 0.35, m.d, weathered(TRAVERTINE, ctx), 0, 0.12, 0));
  const n = Math.max(6, Math.round(m.w / 5));
  [1, -1].forEach((s) =>
    Array.from({ length: n }).forEach((_, k) => {
      const x = (-0.5 + k / (n - 1)) * (m.w - 4);
      if (ctx.rand() > ctx.state * 0.3) parts.push(cyl(0.45, 0.55, 8, 10, weathered(MARBLE, ctx), x, 4.3, s * (m.d / 2 - 1.5)));
    }));
  [1, -1].forEach((s) => ctx.state < 0.7 && parts.push(box(m.w - 3, 1.0, 1.6, weathered(MARBLE, ctx), 0, 8.8, s * (m.d / 2 - 1.5))));
  Array.from({ length: 4 }).forEach((_, k) => {
    const x = (-0.35 + k * 0.23) * m.w;
    parts.push(box(1.6, 2.4, 1.6, weathered(MARBLE, ctx), x, 1.4, 0));
    parts.push(cyl(0.35, 0.45, 2.6, 8, '#7e6a4c', x, 3.9, 0));
  });
  return { parts, colliders: [] };
};

const circus = (m, ctx) => {
  const parts = [];
  const len = m.w;
  parts.push(box(len * 0.96, 0.25, m.d * 0.66, SAND, 0, 0.12, 0));
  parts.push(box(len * 0.6, 1.8, 7, weathered(MARBLE, ctx), 0, 0.9, 0));
  parts.push(put(new THREE.CylinderGeometry(0.9, 1.6, Math.min(24, m.h * 1.6), 4), '#b9a684', 0, 1.8 + Math.min(24, m.h * 1.6) / 2, 0, Math.PI / 4));
  [-1, 1].forEach((s) => parts.push(put(new THREE.ConeGeometry(1.4, 6, 10), '#9a8a6a', s * len * 0.3, 4.8, 0)));
  const steps = 5;
  [-1, 1].forEach((s) => {
    Array.from({ length: steps }).forEach((_, k) => parts.push(box(len * 0.9, (m.h * (k + 1)) / steps, m.d * 0.035, weathered(shade(TRAVERTINE, 0.85 + k * 0.03), ctx), 0, (m.h * (k + 1)) / steps / 2, s * (m.d * 0.34 + k * m.d * 0.035))));
    parts.push(put(arcadeWall(len * 0.9, m.h * 1.08, 1.5, Math.round(len / 7), 4.2, m.h * 0.45), weathered(TRAVERTINE, ctx), 0, 0, s * (m.d * 0.34 + steps * m.d * 0.035 + 0.8)));
  });
  const bank = m.d * 0.34 + steps * m.d * 0.035;
  return { parts, colliders: [{ x: 0, z: bank - steps * m.d * 0.0175, hw: len * 0.45, hd: steps * m.d * 0.0175 + 1 }, { x: 0, z: -(bank - steps * m.d * 0.0175), hw: len * 0.45, hd: steps * m.d * 0.0175 + 1 }, { x: 0, z: 0, hw: len * 0.3, hd: 3.6 }] };
};

const theater = (m, ctx) => {
  const parts = [];
  const a = m.w / 2;
  const b = m.d / 2;
  arcadeRing(parts, a, b, m.h, 3, ctx, [Math.PI, Math.PI * 2], false);
  Array.from({ length: 5 }).forEach((_, k) => {
    const f0 = 0.95 - k * 0.1;
    const y = m.h * 0.8 * (1 - k / 5);
    const geo = new THREE.RingGeometry(f0 - 0.1, f0, 48, 1, Math.PI, Math.PI);
    geo.rotateX(-Math.PI / 2);
    parts.push(put(geo, weathered(shade(TRAVERTINE, 0.82), ctx), 0, y, 0, 0, a, 1, b));
  });
  parts.push(box(m.w * 0.92, m.h * 0.75, 6, weathered(TRAVERTINE, ctx), 0, m.h * 0.375, 3));
  return { parts, colliders: [{ x: 0, z: -b / 2, hw: a * 0.95, hd: b / 2 }, { x: 0, z: 3, hw: m.w * 0.46, hd: 3 }] };
};

const pantheon = (m, ctx) => {
  const parts = [];
  const r = m.w / 2;
  const cz = -m.d / 2 + r;
  parts.push(cyl(r, r, r * 0.75, 40, weathered(BRICK, ctx), 0, (r * 0.75) / 2, cz));
  parts.push(put(new THREE.SphereGeometry(r * 0.94, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), weathered('#9fa3a2', ctx), 0, r * 0.75, cz));
  parts.push(box(r * 1.15, r * 0.75, 8, weathered(BRICK, ctx), 0, (r * 0.75) / 2, cz + r - 1));
  const pz = cz + r + 9;
  parts.push(box(r * 1.15, 1.4, 16, weathered(MARBLE, ctx), 0, 0.7, pz));
  Array.from({ length: 8 }).forEach((_, k) => parts.push(cyl(0.7, 0.8, 13, 12, weathered('#c9c2b3', ctx), (-0.5 + k / 7) * (r * 1.05), 7.9, pz + 6.5)));
  parts.push(box(r * 1.15, 1.6, 16, weathered(MARBLE, ctx), 0, 15.2, pz));
  parts.push(put(gable(16, r * 1.15, 5, 0.3), weathered('#8f8a80', ctx), 0, 16, pz, Math.PI / 2));
  return { parts, colliders: [{ x: 0, z: cz, hw: r, hd: r }, { x: 0, z: pz, hw: r * 0.58, hd: 1 }] };
};

const column = (m, ctx) => ({
  parts: [box(5, 4.5, 5, weathered(MARBLE, ctx), 0, 2.25, 0), cyl(1.8, 1.9, m.h - 7, 16, weathered(MARBLE, ctx), 0, 4.5 + (m.h - 7) / 2, 0),
    box(4.2, 1.2, 4.2, weathered(MARBLE, ctx), 0, m.h - 2.5, 0), cyl(0.5, 0.6, 2, 8, '#7e6a4c', 0, m.h - 0.9, 0)],
  colliders: [{ x: 0, z: 0, hw: 2.6, hd: 2.6 }],
});

const statue = (m, ctx) => {
  const ped = Math.max(1.8, m.h * 0.2);
  const fig = m.h - ped;
  return {
    parts: [box(m.w, ped, m.w, weathered(MARBLE, ctx), 0, ped / 2, 0), cyl(fig * 0.09, fig * 0.12, fig * 0.75, 12, '#8a7a5a', 0, ped + fig * 0.375, 0),
      put(new THREE.SphereGeometry(fig * 0.09, 14, 10), '#8a7a5a', 0, ped + fig * 0.86, 0)],
    colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }],
  };
};

const obelisk = (m, ctx) => ({
  parts: [box(3.4, 2.2, 3.4, weathered(MARBLE, ctx), 0, 1.1, 0), put(new THREE.CylinderGeometry(0.8, 1.3, m.h - 3, 4), '#c4ab86', 0, 2.2 + (m.h - 3) / 2, 0, Math.PI / 4),
    put(new THREE.ConeGeometry(1.1, 1.6, 4), '#c4ab86', 0, m.h - 0.2, 0, Math.PI / 4)],
  colliders: [{ x: 0, z: 0, hw: 1.8, hd: 1.8 }],
});

const fountain = (m, ctx) => ({
  parts: [cyl(m.w / 2, m.w / 2, 1.0, 28, weathered(MARBLE, ctx), 0, 0.5, 0), cyl(m.w / 2 - 0.6, m.w / 2 - 0.6, 0.2, 28, '#4b8fb5', 0, 0.95, 0),
    cyl(1.0, Math.min(3.4, m.w / 4), m.h, 14, weathered(BRICK, ctx), 0, m.h / 2, 0)],
  colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }],
});

const garden = (m, ctx) => {
  const parts = [box(m.w, 0.25, m.d, '#5d7a3e', 0, 0.1, 0), box(m.w * 0.9, 0.3, 3, '#b8a888', 0, 0.15, 0)];
  [1, -1].forEach((s) => parts.push(box(m.w, 1.1, 1.2, '#3f5f2f', 0, 0.55, s * (m.d / 2 - 0.6))));
  ctx.state > 0.4 && Array.from({ length: 12 }).forEach(() => parts.push(box(2 + ctx.rand() * 3, 0.9, 2 + ctx.rand() * 3, '#6a7f3a', (ctx.rand() - 0.5) * m.w, 0.45, (ctx.rand() - 0.5) * m.d)));
  return { parts, colliders: [] };
};

const market = (m, ctx) => {
  const parts = [];
  const n = 14;
  Array.from({ length: n }).forEach((_, k) => {
    const t = Math.PI + (k / (n - 1)) * Math.PI;
    const x = Math.cos(t) * (m.w / 2);
    const z = Math.sin(t) * (m.d / 2) + m.d / 2;
    const ry = Math.atan2(-Math.cos(t) * (m.d / 2), -Math.sin(t) * (m.w / 2)) + Math.PI / 2;
    [0, 1, 2].forEach((f) => parts.push(box((Math.PI * m.w) / 2 / n + 0.4, m.h / 3 - 0.4, 9, weathered(BRICK, ctx), x, f * (m.h / 3) + m.h / 6, z, ry)));
  });
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.d / 2 }] };
};

const bath = (m, ctx) => {
  const parts = [box(m.w * 0.82, m.h * 0.7, m.d * 0.62, weathered(BRICK, ctx), 0, m.h * 0.35, 0), box(m.w, m.h * 0.45, m.d * 0.3, weathered(BRICK, ctx), 0, m.h * 0.225, m.d * 0.33)];
  parts.push(put(new THREE.SphereGeometry(m.d * 0.2, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2), weathered('#9b9f9c', ctx), 0, m.h * 0.7, 0));
  parts.push(put(gable(m.w * 0.82, m.d * 0.62, m.h * 0.12), weathered(TILE, ctx), 0, m.h * 0.7, 0));
  vines(parts, ctx, boxSpots(m.w * 0.82, m.d * 0.62, m.h, 10, ctx));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.d / 2 }] };
};

const tower = (m, ctx) => ({
  parts: [cyl(m.w / 2, m.w / 2 + 0.4, m.h, 16, weathered('#9a958a', ctx), 0, m.h / 2, 0), cyl(m.w / 2 + 0.6, m.w / 2 + 0.6, 1.6, 16, weathered('#9a958a', ctx), 0, m.h + 0.8, 0),
    put(new THREE.ConeGeometry(m.w / 2 + 0.8, m.w, 16), weathered(TILE, ctx), 0, m.h + 1.6 + m.w / 2, 0)],
  colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }],
});

const lighthouse = (m, ctx) => ({
  parts: [cyl(m.w / 2 - 1.5, m.w / 2, m.h, 14, weathered('#e8e2d4', ctx), 0, m.h / 2, 0), cyl(2.2, 2.2, 3, 12, '#ffd77a', 0, m.h + 1.5, 0),
    put(new THREE.ConeGeometry(3, 3, 12), '#4a4a52', 0, m.h + 4.5, 0)],
  colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }],
});

const windmill = (m, ctx) => ({
  parts: [cyl(m.w / 2 - 1, m.w / 2, m.h, 12, weathered('#d8d0bf', ctx), 0, m.h / 2, 0), put(new THREE.ConeGeometry(m.w / 2 + 0.4, 4, 12), TILE, 0, m.h + 2, 0),
    ...[0, 1].map((k) => put(new THREE.BoxGeometry(0.6, m.h * 1.1, 0.3).rotateZ((k * Math.PI) / 2 + Math.PI / 4), '#6b4a2f', 0, m.h * 0.85, m.w / 2 + 0.5))],
  colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }],
});

const castle = (m, ctx) => {
  const parts = [box(m.w * 0.7, m.h, m.d * 0.7, weathered('#8d8a82', ctx), 0, m.h / 2, 0)];
  [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sz]) => parts.push(cyl(3.2, 3.6, m.h * 1.3, 14, weathered('#8d8a82', ctx), sx * m.w * 0.4, m.h * 0.65, sz * m.d * 0.4)));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.d / 2 }] };
};

const AWNINGS = ['#b5523a', '#c9a35a', '#7a5a8a', '#5a7a9a', '#d6c9a8', '#a8442f'];

const marketStalls = (m, ctx) => {
  const parts = [box(m.w, 0.12, m.d, weathered('#b8a888', ctx), 0, 0.06, 0)];
  const per = Math.max(2, Math.floor(m.w / 4.6));
  const rows = Math.max(1, Math.floor(m.d / 8));
  Array.from({ length: rows }).forEach((_, r) =>
    Array.from({ length: per }).forEach((__, k) => {
      if (ctx.rand() < 0.12) return;
      const x = (-0.5 + (k + 0.5) / per) * m.w;
      const z = rows === 1 ? 0 : (-0.5 + (r + 0.5) / rows) * m.d;
      const face = r % 2 ? Math.PI : 0;
      [[-1.5, -1], [1.5, -1], [-1.5, 1], [1.5, 1]].forEach(([px, pz]) => parts.push(box(0.12, 2.5, 0.12, '#5a3d24', x + px, 1.25, z + pz)));
      parts.push(put(new THREE.BoxGeometry(3.6, 0.06, 2.8), AWNINGS[Math.floor(ctx.rand() * AWNINGS.length)], x, 2.55, z, face, 1, 1, 1, 0.18));
      parts.push(box(3.0, 0.9, 1.0, '#7a5a3a', x, 0.45, z + (face ? -0.6 : 0.6)));
      Array.from({ length: 4 }).forEach((___, g) => {
        const kind = ctx.rand();
        const gx = x - 1.1 + g * 0.75;
        const gz = z + (face ? -0.6 : 0.6);
        parts.push(kind < 0.35 ? cyl(0.18, 0.12, 0.6, 8, '#b06a3a', gx, 1.2, gz) : kind < 0.7 ? put(new THREE.SphereGeometry(0.28, 8, 6), ['#6a8a3a', '#c9a035', '#9a3a2a'][g % 3], gx, 1.12, gz) : box(0.5, 0.3, 0.4, '#8a6a42', gx, 1.05, gz));
      });
    }));
  return { parts, colliders: [] };
};

const church = (m, ctx) => {
  const parts = [];
  const brick = weathered(BRICK, ctx);
  const nave = m.d * 0.5;
  parts.push(box(m.w, m.h * 0.55, m.d, brick, 0, m.h * 0.275, 0));
  parts.push(box(m.w, m.h * 0.45, nave, brick, 0, m.h * 0.55 + m.h * 0.225, 0));
  parts.push(put(new THREE.CylinderGeometry(nave / 2, nave / 2, m.h * 0.7, 20, 1, false, 0, Math.PI), brick, m.w / 2, m.h * 0.35, 0, 0));
  parts.push(put(new THREE.SphereGeometry(nave / 2, 20, 8, 0, Math.PI, 0, Math.PI / 2), weathered(TILE, ctx), m.w / 2, m.h * 0.7, 0, Math.PI / 2));
  parts.push(put(gable(m.w, nave, m.h * 0.14), weathered(TILE, ctx), 0, m.h, 0));
  parts.push(put(gable(m.w, m.d, m.h * 0.06, 0.2), weathered(TILE, ctx), 0, m.h * 0.55, 0));
  parts.push(box(m.d * 0.35, m.h * 0.35, m.d, weathered(TRAVERTINE, ctx), -m.w / 2 - m.d * 0.17, m.h * 0.175, 0));
  const bays = Math.max(4, Math.round(m.w / 6));
  [1, -1].forEach((s) => facadeArches(parts, m.w * 0.85, m.h * 0.66, nave / 2 + 0.05, s > 0 ? 0 : Math.PI, bays, 1.6, m.h * 0.2, ctx));
  vines(parts, ctx, boxSpots(m.w, m.d, m.h * 0.5, 4, ctx));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.d / 2 }, { x: m.w / 2 + nave / 4, z: 0, hw: nave / 4, hd: nave / 2 }] };
};

const limeKiln = (m, ctx) => {
  const parts = [cyl(m.w * 0.36, m.w / 2, m.h, 14, weathered('#8d877a', ctx), 0, m.h / 2, 0), box(1.4, 1.5, 1.0, '#120d0a', 0, 0.75, m.w / 2 - 0.3), cyl(1.2, 1.3, 0.3, 12, '#ff8a3a', 0, m.h + 0.05, 0)];
  Array.from({ length: 14 }).forEach(() => parts.push(box(0.5 + ctx.rand() * 1.4, 0.3 + ctx.rand() * 0.6, 0.4 + ctx.rand() * 0.9, shade(MARBLE, 0.85 + ctx.rand() * 0.15), m.w / 2 + 1 + ctx.rand() * 4, 0.3, (ctx.rand() - 0.5) * 6)));
  parts.push(cyl(0.45, 0.5, 2.6, 10, '#c9c2b3', m.w / 2 + 2.5, 0.25, 2.5).rotateZ(Math.PI / 2));
  return { parts, colliders: [{ x: 0, z: 0, hw: m.w / 2, hd: m.w / 2 }] };
};

const vegetableGarden = (m, ctx) => {
  const parts = [box(m.w, 0.18, m.d, '#6e5434', 0, 0.06, 0)];
  const rows = Math.max(4, Math.floor(m.d / 2.2));
  Array.from({ length: rows }).forEach((_, r) => {
    const z = (-0.5 + (r + 0.5) / rows) * (m.d - 2);
    parts.push(box(m.w - 3, 0.45, 0.9, ['#5f8a3a', '#7a9a3a', '#4f7a35', '#8aa04a'][r % 4], 0, 0.3, z));
  });
  [[0, m.d / 2, m.w, 0.12], [0, -m.d / 2, m.w, 0.12], [m.w / 2, 0, 0.12, m.d], [-m.w / 2, 0, 0.12, m.d]].forEach(([x, z, w, d]) => parts.push(box(w, 0.9, d, '#6a4a2c', x, 0.45, z)));
  parts.push(box(3.2, 2.4, 2.6, '#8a7a5a', m.w / 2 - 3, 1.2, m.d / 2 - 2.5));
  parts.push(put(gable(3.2, 2.6, 1.2), '#7a6a3a', m.w / 2 - 3, 2.4, m.d / 2 - 2.5));
  return { parts, colliders: [] };
};

const BUILDERS = { market_stalls: marketStalls, church, lime_kiln: limeKiln, vegetable_garden: vegetableGarden, amphitheater, temple, round_temple: roundTemple, triumphal_arch: triumphalArch, basilica, forum, circus, theater, pantheon, column, statue, obelisk, fountain, garden, market, bath, tower, lighthouse, windmill, castle };

export const buildLandmarks = (list, condition) => {
  const group = new THREE.Group();
  const colliders = [];
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.88 });
  list.forEach((m, i) => {
    const builder = BUILDERS[m.kind] || basilica;
    const ctx = { rand: rng(1000 + i * 97), state: m.state ?? condition.decay ?? 0, overgrowth: condition.overgrowth ?? 0 };
    const { parts, colliders: local } = builder(m, ctx);
    const geo = merge(parts);
    if (geo) {
      const mesh = new THREE.Mesh(geo, material);
      mesh.position.set(m.x, m.y - 0.2, m.z);
      mesh.rotation.y = m.rot;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.landmark = m.id;
      group.add(mesh);
    }
    const c = Math.cos(m.rot);
    const s = Math.sin(m.rot);
    local.forEach((l) => colliders.push({ cx: m.x + l.x * c + l.z * s, cz: m.z - l.x * s + l.z * c, hw: l.hw, hd: l.hd, rot: m.rot }));
  });
  return { group, colliders };
};

export const buildAqueducts = (list, condition) => {
  const parts = [];
  const colliders = [];
  const ctx = { rand: rng(77), state: condition.decay ?? 0, overgrowth: condition.overgrowth ?? 0 };
  list.forEach((a) =>
    a.pts.slice(0, -1).forEach((p, k) => {
      const q = a.pts[k + 1];
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      const ang = Math.atan2(q[0] - p[0], q[1] - p[1]);
      const ground = Math.min(p[2], q[2]);
      const height = a.top - ground;
      if (height < 2) return;
      const wall = arcadeWall(len, height, 2.6, 1, len * 0.62, Math.max(1, height - len * 0.62 / 2 - 1.5));
      parts.push(put(wall, weathered(BRICK, ctx), (p[0] + q[0]) / 2, ground, (p[1] + q[1]) / 2, ang + Math.PI / 2));
      parts.push(box(3.2, 1.6, len + 0.2, weathered(TRAVERTINE, ctx), (p[0] + q[0]) / 2, a.top + 0.8, (p[1] + q[1]) / 2, ang));
      colliders.push({ cx: p[0], cz: p[1], hw: 1.8, hd: 1.8, rot: ang });
    }));
  const geo = merge(parts);
  const mesh = geo ? new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, side: THREE.DoubleSide })) : new THREE.Group();
  mesh.castShadow = true;
  return { mesh, colliders };
};
