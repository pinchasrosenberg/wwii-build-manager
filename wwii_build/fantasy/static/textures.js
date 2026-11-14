import * as THREE from 'three';

const cache = new Map();

const makeCanvas = (size, draw) => {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  draw(canvas.getContext('2d'), size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
};

const noise = (ctx, size, amount) =>
  Array.from({ length: size * 6 }).forEach(() => {
    ctx.fillStyle = `rgba(${Math.random() < 0.5 ? '0,0,0' : '255,255,255'},${Math.random() * amount})`;
    ctx.fillRect(Math.random() * size, Math.random() * size, 2 + Math.random() * 6, 2 + Math.random() * 6);
  });

const painters = {
  marble: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    Array.from({ length: 14 }).forEach(() => {
      ctx.strokeStyle = `rgba(90,90,100,${0.08 + Math.random() * 0.14})`;
      ctx.lineWidth = 1 + Math.random() * 2;
      ctx.beginPath();
      ctx.moveTo(Math.random() * s, 0);
      ctx.bezierCurveTo(Math.random() * s, s * 0.3, Math.random() * s, s * 0.6, Math.random() * s, s);
      ctx.stroke();
    });
    ctx.strokeStyle = 'rgba(60,60,70,0.28)';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, s, s);
  },
  wood: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    Array.from({ length: 8 }).forEach((_, i) => {
      ctx.fillStyle = `rgba(0,0,0,${0.05 + (i % 3) * 0.05})`;
      ctx.fillRect(0, (i * s) / 8, s, s / 8);
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.fillRect(0, (i * s) / 8, s, 2);
    });
    noise(ctx, s, 0.12);
  },
  stone: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    noise(ctx, s, 0.22);
    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.lineWidth = 3;
    [0, s / 2].forEach((y) => {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(s, y);
      ctx.stroke();
    });
    [s / 4, (s * 3) / 4].forEach((x) => {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, s / 2);
      ctx.stroke();
    });
    [0, s / 2].forEach((x) => {
      ctx.beginPath();
      ctx.moveTo(x, s / 2);
      ctx.lineTo(x, s);
      ctx.stroke();
    });
  },
  tile: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = 'rgba(40,30,20,0.5)';
    ctx.lineWidth = 3;
    [0, 1, 2, 3].forEach((i) => {
      ctx.strokeRect((i % 2) * (s / 2), Math.floor(i / 2) * (s / 2), s / 2, s / 2);
    });
    noise(ctx, s, 0.1);
  },
  checker: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    ctx.fillStyle = 'rgba(20,20,25,0.85)';
    ctx.fillRect(0, 0, s / 2, s / 2);
    ctx.fillRect(s / 2, s / 2, s / 2, s / 2);
  },
  plaster: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    noise(ctx, s, 0.08);
  },
  brick: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = 'rgba(30,20,15,0.55)';
    ctx.lineWidth = 3;
    Array.from({ length: 8 }).forEach((_, r) => {
      ctx.beginPath();
      ctx.moveTo(0, (r * s) / 8);
      ctx.lineTo(s, (r * s) / 8);
      ctx.stroke();
      Array.from({ length: 4 }).forEach((__, c) => {
        const x = c * (s / 4) + (r % 2 ? s / 8 : 0);
        ctx.beginPath();
        ctx.moveTo(x, (r * s) / 8);
        ctx.lineTo(x, ((r + 1) * s) / 8);
        ctx.stroke();
      });
    });
    noise(ctx, s, 0.14);
  },
  rug: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = '#d4a93a';
    ctx.lineWidth = s / 24;
    ctx.strokeRect(s * 0.06, s * 0.06, s * 0.88, s * 0.88);
    ctx.lineWidth = s / 60;
    ctx.strokeRect(s * 0.16, s * 0.16, s * 0.68, s * 0.68);
    ctx.fillStyle = 'rgba(212,169,58,0.8)';
    ctx.beginPath();
    ctx.moveTo(s / 2, s * 0.28);
    ctx.lineTo(s * 0.72, s / 2);
    ctx.lineTo(s / 2, s * 0.72);
    ctx.lineTo(s * 0.28, s / 2);
    ctx.closePath();
    ctx.fill();
  },
  opus_sectile: (ctx, s, color) => {
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, s, s);
    const colors = ['#6e2433', '#3f5f3f', '#c9a24a', '#6e2433'];
    [0, 1].forEach((i) => [0, 1].forEach((j) => {
      const x = (i * s) / 2;
      const y = (j * s) / 2;
      ctx.fillStyle = colors[(i + j * 2) % 4];
      ctx.fillRect(x + s * 0.03, y + s * 0.03, s * 0.44, s * 0.44);
      ctx.fillStyle = '#ece6d8';
      ctx.beginPath();
      ctx.arc(x + s / 4, y + s / 4, s * 0.17, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = colors[(i + j * 2 + 1) % 4];
      ctx.beginPath();
      ctx.arc(x + s / 4, y + s / 4, s * 0.12, 0, Math.PI * 2);
      ctx.fill();
    }));
    ctx.strokeStyle = 'rgba(40,30,25,0.35)';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, s, s);
  },
  marble_revetment: (ctx, s, color) => {
    ctx.fillStyle = '#e8e2d4';
    ctx.fillRect(0, 0, s, s);
    ctx.fillStyle = color;
    ctx.fillRect(s * 0.06, s * 0.06, s * 0.88, s * 0.58);
    ctx.fillStyle = '#6e2433';
    ctx.fillRect(0, s * 0.7, s, s * 0.06);
    ctx.fillStyle = '#3f5f3f';
    ctx.fillRect(s * 0.06, s * 0.78, s * 0.88, s * 0.18);
    Array.from({ length: 10 }).forEach(() => {
      ctx.strokeStyle = `rgba(80,60,70,${0.1 + Math.random() * 0.15})`;
      ctx.lineWidth = 1 + Math.random() * 2;
      ctx.beginPath();
      ctx.moveTo(Math.random() * s, s * 0.06);
      ctx.bezierCurveTo(Math.random() * s, s * 0.25, Math.random() * s, s * 0.45, Math.random() * s, s * 0.64);
      ctx.stroke();
    });
    ctx.strokeStyle = 'rgba(40,30,25,0.4)';
    ctx.strokeRect(s * 0.06, s * 0.06, s * 0.88, s * 0.58);
  },
  stained: (ctx, s, color) => {
    const hues = ['#c0392b', '#2e86c1', '#d4ac0d', '#27ae60', '#8e44ad', '#e67e22'];
    Array.from({ length: 36 }).forEach((_, i) => {
      ctx.fillStyle = hues[(i * 5 + Math.floor(i / 6)) % hues.length];
      ctx.fillRect((i % 6) * (s / 6), Math.floor(i / 6) * (s / 6), s / 6, s / 6);
    });
    ctx.strokeStyle = '#1b1b1b';
    ctx.lineWidth = 4;
    Array.from({ length: 7 }).forEach((_, i) => {
      ctx.beginPath();
      ctx.moveTo((i * s) / 6, 0);
      ctx.lineTo((i * s) / 6, s);
      ctx.moveTo(0, (i * s) / 6);
      ctx.lineTo(s, (i * s) / 6);
      ctx.stroke();
    });
  },
};

export const surfaceTexture = (kind, color, repeatX, repeatY) => {
  const key = `${kind}|${color}`;
  const base = cache.get(key) || makeCanvas(256, (ctx, s) => (painters[kind] || painters.plaster)(ctx, s, color));
  cache.set(key, base);
  const tex = base.clone();
  tex.needsUpdate = true;
  tex.repeat.set(repeatX, repeatY);
  return tex;
};
