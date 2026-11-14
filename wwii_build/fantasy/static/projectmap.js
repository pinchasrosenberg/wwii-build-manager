const terrainCache = new WeakMap();

const hypso = (t) => {
  const stops = [[0, [196, 186, 150]], [0.25, [176, 172, 122]], [0.5, [158, 150, 104]], [0.75, [150, 126, 92]], [1, [170, 140, 110]]];
  const i = Math.max(0, stops.findIndex((s) => s[0] >= t) - 1);
  const [t0, c0] = stops[i];
  const [t1, c1] = stops[Math.min(i + 1, stops.length - 1)];
  const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
  return c0.map((v, k) => v + (c1[k] - v) * f);
};

const terrainImage = (data) => {
  const cached = terrainCache.get(data);
  if (cached) return cached;
  const n = data.n;
  const canvas = document.createElement('canvas');
  canvas.width = n;
  canvas.height = n;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(n, n);
  const h = data.heights;
  const lo = h.reduce((m, v) => Math.min(m, v), 1e9);
  const hi = h.reduce((m, v) => Math.max(m, v), -1e9);
  const step = data.size / (n - 1);
  const sea = data.sea_level;
  for (let j = 0; j < n; j += 1) {
    for (let i = 0; i < n; i += 1) {
      const k = j * n + i;
      const dx = (h[j * n + Math.min(n - 1, i + 1)] - h[j * n + Math.max(0, i - 1)]) / (2 * step);
      const dz = (h[Math.min(n - 1, j + 1) * n + i] - h[Math.max(0, j - 1) * n + i]) / (2 * step);
      const shadeV = Math.max(0.45, Math.min(1.25, 1 + (dx + dz) * -0.9));
      const base = sea !== null && sea !== undefined && h[k] < sea ? [86, 140, 170] : hypso((h[k] - lo) / Math.max(1, hi - lo));
      img.data.set([base[0] * shadeV, base[1] * shadeV, base[2] * shadeV, 255], k * 4);
    }
  }
  ctx.putImageData(img, 0, 0);
  terrainCache.set(data, canvas);
  return canvas;
};

const rotRect = (ctx, x, y, w, d, rot) => {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-rot);
  ctx.beginPath();
  ctx.rect(-w / 2, -d / 2, w, d);
  ctx.restore();
};

const rotEllipse = (ctx, x, y, w, d, rot, half) => {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-rot);
  ctx.beginPath();
  half ? ctx.ellipse(0, 0, w / 2, d / 2, 0, Math.PI, Math.PI * 2) : ctx.ellipse(0, 0, w / 2, d / 2, 0, 0, Math.PI * 2);
  half && ctx.closePath();
  ctx.restore();
};

const polyline = (ctx, pts, tx) => {
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(...tx(p[0], p[1])) : ctx.moveTo(...tx(p[0], p[1]))));
};

const label = (ctx, text, x, y, size, color) => {
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(255,250,235,0.85)';
  ctx.strokeText(text, x, y);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
};

export const fitView = (canvas, data) => ({ cx: 0, cz: 0, scale: Math.min(canvas.width, canvas.height) / data.size });

export const toWorld = (canvas, view, px, py) => [(px - canvas.width / 2) / view.scale + view.cx, (py - canvas.height / 2) / view.scale + view.cz];

export const drawProjectMap = (canvas, data, view, player) => {
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const s = view.scale;
  const tx = (x, z) => [(x - view.cx) * s + W / 2, (z - view.cz) * s + H / 2];
  ctx.fillStyle = '#efe6cf';
  ctx.fillRect(0, 0, W, H);
  const [ox, oy] = tx(-data.size / 2, -data.size / 2);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(terrainImage(data), ox, oy, data.size * s, data.size * s);
  (data.districts || []).forEach((d) => {
    const [x, y] = tx(d.x, d.z);
    ctx.setLineDash([6, 5]);
    ctx.strokeStyle = 'rgba(120,70,40,0.45)';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(x, y, d.r * s, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  });
  data.rivers.forEach((r) => {
    ctx.strokeStyle = '#5b93b4';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    r.pts.slice(0, -1).forEach((p, k) => {
      const q = r.pts[k + 1];
      ctx.lineWidth = Math.max(2, p[3] * s);
      polyline(ctx, [p, q], tx);
      ctx.stroke();
    });
  });
  data.streets.forEach((st) => {
    ctx.strokeStyle = st.main ? '#7a5a3a' : 'rgba(122,90,58,0.75)';
    ctx.lineWidth = Math.max(st.main ? 1.6 : 0.8, (st.width || 3) * s);
    polyline(ctx, st.pts, tx);
    ctx.stroke();
  });
  (data.bridges || []).forEach((b) => {
    ctx.strokeStyle = b.style === 'wood' ? '#6a4a2c' : '#c9b48a';
    ctx.lineWidth = Math.max(3, b.width * s);
    polyline(ctx, [b.a, b.b], tx);
    ctx.stroke();
  });
  (data.aqueducts || []).forEach((a) => {
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = '#8a4b2b';
    ctx.lineWidth = Math.max(2, 3 * s);
    polyline(ctx, a.pts, tx);
    ctx.stroke();
    ctx.setLineDash([]);
  });
  (data.walls || []).forEach((w) => {
    ctx.strokeStyle = '#5a554c';
    ctx.lineWidth = Math.max(2, w.thick * s);
    polyline(ctx, w.pts, tx);
    ctx.stroke();
  });
  data.houses.forEach((h) => {
    const [x, y] = tx(h.x, h.z);
    if (x < -20 || y < -20 || x > W + 20 || y > H + 20) return;
    ctx.fillStyle = h.ruin ? '#9a9080' : h.roof_color || h.wall_color;
    rotRect(ctx, x, y, Math.max(1.5, h.w * s), Math.max(1.5, h.d * s), h.rot);
    ctx.fill();
  });
  (data.landmarks || []).forEach((m) => {
    const [x, y] = tx(m.x, m.z);
    const round = ['amphitheater', 'round_temple', 'fountain', 'column', 'obelisk', 'statue'].includes(m.kind);
    ctx.fillStyle = ['garden'].includes(m.kind) ? 'rgba(90,130,70,0.6)' : ['forum', 'circus'].includes(m.kind) ? 'rgba(230,220,195,0.85)' : 'rgba(238,230,210,0.95)';
    ctx.strokeStyle = '#5b4632';
    ctx.lineWidth = 1.2;
    m.kind === 'theater' ? rotEllipse(ctx, x, y, m.w * s, m.d * s, m.rot, true) : round ? rotEllipse(ctx, x, y, Math.max(4, m.w * s), Math.max(4, m.d * s), m.rot, false) : rotRect(ctx, x, y, Math.max(3, m.w * s), Math.max(3, m.d * s), m.rot);
    ctx.fill();
    ctx.stroke();
  });
  const p = data.palace;
  const [px, py] = tx(p.x, p.z);
  ctx.fillStyle = '#d4a93a';
  ctx.strokeStyle = '#5b3b10';
  rotRect(ctx, px, py, Math.max(6, p.w * s), Math.max(6, p.d * s), p.rot || 0);
  ctx.fill();
  ctx.stroke();
  const labels = (data.basemap && data.basemap.labels) || [];
  const big = s > 0.9;
  labels.forEach((l) => {
    const [x, y] = tx(l.x, l.z);
    if (x < 0 || y < 0 || x > W || y > H) return;
    const important = ['hill', 'river', 'palace', 'amphitheater', 'circus', 'island'].includes(l.kind);
    if (!important && !big && s < 0.45) return;
    label(ctx, l.name, x, y + (l.kind === 'hill' ? 0 : -6), l.kind === 'hill' ? 14 : important ? 12 : 10, l.kind === 'hill' ? '#6b3f1f' : l.kind === 'river' ? '#1f4f74' : '#2b2118');
  });
  if (player) {
    const [x, y] = tx(player.x, player.z);
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-player.yaw);
    ctx.fillStyle = '#d0321e';
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, -11);
    ctx.lineTo(7, 8);
    ctx.lineTo(0, 4);
    ctx.lineTo(-7, 8);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }
  const meters = [50, 100, 200, 500][[50, 100, 200, 500].findIndex((m) => m * s > 70)] || 500;
  ctx.fillStyle = '#2b2118';
  ctx.fillRect(16, H - 22, meters * s, 4);
  label(ctx, `${meters} מ׳`, 16 + (meters * s) / 2, H - 28, 11, '#2b2118');
  label(ctx, 'צ ▲', W - 26, 24, 13, '#2b2118');
};
