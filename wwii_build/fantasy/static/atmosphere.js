import * as THREE from 'three';

import { rng } from './geom.js';

const KEYS = [
  { alt: -18, top: '#05081a', bottom: '#121a32', fog: '#0b1020', sun: '#8fa4d8', sunI: 0.34, amb: 0.2, exposure: 1.55, window: 1 },
  { alt: -8, top: '#0e1838', bottom: '#33355a', fog: '#22263f', sun: '#9fb0e0', sunI: 0.3, amb: 0.24, exposure: 1.4, window: 1 },
  { alt: -2, top: '#22325c', bottom: '#b96c58', fog: '#5e4c58', sun: '#ff7a45', sunI: 0.3, amb: 0.32, exposure: 1.18, window: 0.85 },
  { alt: 3, top: '#46608f', bottom: '#ee9460', fog: '#c39680', sun: '#ff9a5c', sunI: 1.3, amb: 0.48, exposure: 1.02, window: 0.35 },
  { alt: 10, top: '#6c90c4', bottom: '#f0cd9e', fog: '#dcc6a4', sun: '#ffd29a', sunI: 2.2, amb: 0.66, exposure: 1, window: 0 },
  { alt: 25, top: '#5d91cf', bottom: '#d5e2ea', fog: '#cbd6dc', sun: '#fff1da', sunI: 2.6, amb: 0.74, exposure: 1, window: 0 },
  { alt: 70, top: '#4d85c8', bottom: '#cfdfec', fog: '#c5d3dc', sun: '#fff7ea', sunI: 2.8, amb: 0.8, exposure: 1, window: 0 },
];

const DECL = [-21, -13, -2, 10, 19, 23, 21, 14, 3, -9, -18, -23];

const TARGETS = {
  clear: { cloud: 0.08, rain: 0, snow: 0, fog: 0, storm: 0 },
  cloudy: { cloud: 0.62, rain: 0, snow: 0, fog: 0.1, storm: 0 },
  rain: { cloud: 0.86, rain: 0.75, snow: 0, fog: 0.25, storm: 0 },
  storm: { cloud: 1, rain: 1, snow: 0, fog: 0.3, storm: 1 },
  fog: { cloud: 0.5, rain: 0, snow: 0, fog: 1, storm: 0 },
  snow: { cloud: 0.82, rain: 0, snow: 1, fog: 0.35, storm: 0 },
};

const smooth = (a, b, t) => {
  const x = Math.max(0, Math.min(1, (t - a) / (b - a)));
  return x * x * (3 - 2 * x);
};

const lerpKey = (alt) => {
  const k = Math.max(0, KEYS.findIndex((key) => key.alt > alt) - 1);
  const a = KEYS[Math.min(k, KEYS.length - 1)];
  const b = KEYS[Math.min(k + 1, KEYS.length - 1)];
  const t = a === b ? 0 : Math.max(0, Math.min(1, (alt - a.alt) / (b.alt - a.alt)));
  const col = (key) => new THREE.Color(a[key]).lerp(new THREE.Color(b[key]), t);
  const num = (key) => a[key] + (b[key] - a[key]) * t;
  return { top: col('top'), bottom: col('bottom'), fog: col('fog'), sun: col('sun'), sunI: num('sunI'), amb: num('amb'), exposure: num('exposure'), window: num('window') };
};

const glowTexture = (inner, outer) => {
  const c = document.createElement('canvas');
  c.width = 64;
  c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 1, 32, 32, 31);
  grad.addColorStop(0, inner);
  grad.addColorStop(0.35, outer);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
};

const SKY_VERT = 'varying vec3 vDir; void main(){ vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }';
const SKY_FRAG = `
uniform vec3 top; uniform vec3 bottom; uniform vec3 sunDir; uniform vec3 sunColor; uniform vec3 cloudLit; uniform vec3 cloudDark;
uniform float cover; uniform float night; uniform float time; uniform float sunVis; uniform float flash;
varying vec3 vDir;
float h1(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n2(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h1(i), h1(i + vec2(1.0, 0.0)), f.x), mix(h1(i + vec2(0.0, 1.0)), h1(i + vec2(1.0, 1.0)), f.x), f.y); }
float fbm(vec2 p){ float v = 0.0; float a = 0.5; for (int i = 0; i < 5; i++) { v += a * n2(p); p *= 2.03; a *= 0.5; } return v; }
void main(){
  vec3 d = normalize(vDir);
  float h = d.y;
  vec3 col = mix(bottom, top, smoothstep(-0.02, 0.45, h));
  float s = max(dot(d, sunDir), 0.0);
  col += sunColor * (pow(s, 900.0) * 4.0 + pow(s, 9.0) * 0.22) * sunVis * (1.0 - cover * 0.85);
  if (h > 0.0) {
    vec3 q = floor(d * 380.0);
    float star = step(0.9978, h1(q.xy + q.z * 7.13));
    col += vec3(star) * night * (1.0 - smoothstep(0.25, 0.6, cover)) * smoothstep(0.02, 0.2, h);
    vec2 uv = d.xz / (h + 0.09) * 0.8 + vec2(time * 0.006, time * 0.0035);
    float n = fbm(uv);
    float th = mix(0.74, 0.22, cover);
    float c = smoothstep(th, th + 0.2, n) * smoothstep(0.0, 0.1, h);
    vec3 cc = mix(cloudDark, cloudLit, smoothstep(0.35, 0.95, n));
    col = mix(col, cc, c * 0.94);
  }
  col += vec3(0.75, 0.8, 1.0) * flash;
  gl_FragColor = vec4(col, 1.0);
  #include <colorspace_fragment>
}`;

const patchMaterial = (mat, uniforms) => {
  if (!mat || !mat.isMeshStandardMaterial || mat.userData.weatherPatched || mat.userData.noWeather) return;
  mat.userData.weatherPatched = true;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uSnow = uniforms.uSnow;
    shader.uniforms.uWet = uniforms.uWet;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWorldN;\nvarying vec3 vWorldP;')
      .replace('#include <defaultnormal_vertex>', '#include <defaultnormal_vertex>\nvWorldN = normalize((vec4(transformedNormal, 0.0) * viewMatrix).xyz);')
      .replace('#include <project_vertex>', '#include <project_vertex>\n#ifdef USE_INSTANCING\nvWorldP = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;\n#else\nvWorldP = (modelMatrix * vec4(transformed, 1.0)).xyz;\n#endif');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uSnow;\nuniform float uWet;\nvarying vec3 vWorldN;\nvarying vec3 vWorldP;\nfloat wxHash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }')
      .replace('#include <color_fragment>', '#include <color_fragment>\nfloat wxUp = smoothstep(0.45, 0.85, vWorldN.y);\nfloat wxSnow = clamp(uSnow * 1.3 - wxHash(floor(vWorldP.xz * 0.8)) * 0.35, 0.0, 1.0) * wxUp;\ndiffuseColor.rgb = mix(diffuseColor.rgb * (1.0 - 0.4 * uWet * smoothstep(0.2, 0.9, vWorldN.y)), vec3(0.92, 0.94, 0.97), wxSnow);')
      .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = mix(roughnessFactor, 0.16, uWet * wxUp * (1.0 - wxSnow));\nroughnessFactor = mix(roughnessFactor, 0.92, wxSnow);');
  };
  mat.customProgramCacheKey = () => 'weather-v1';
  mat.needsUpdate = true;
};

const windowPoints = (data) => {
  const rand = rng(911);
  const pts = [];
  (data.houses || []).forEach((h) => {
    if (h.ruin || rand() > 0.42) return;
    const n = 1 + Math.floor(rand() * 2.4);
    for (let k = 0; k < n; k += 1) {
      const side = rand() < 0.7 ? 0 : Math.PI;
      const fx = Math.sin(h.rot + side);
      const fz = Math.cos(h.rot + side);
      const lat = (rand() - 0.5) * h.w * 0.7;
      const floor = Math.floor(rand() * (h.floors || 2));
      pts.push(h.x + fx * (h.d / 2 + 0.12) + Math.cos(h.rot) * lat, (h.y || 0) + 1.4 + floor * 3.0, h.z + fz * (h.d / 2 + 0.12) - Math.sin(h.rot) * lat);
    }
  });
  (data.landmarks || []).filter((m) => ['temple', 'basilica', 'round_temple', 'bath', 'market', 'forum'].includes(m.kind)).forEach((m) => {
    const fx = Math.sin(m.rot);
    const fz = Math.cos(m.rot);
    [-1, 1].forEach((s) => pts.push(m.x + fx * (m.d / 2 + 1.5) + Math.cos(m.rot) * s * m.w * 0.3, (m.y || 0) + 2.2, m.z + fz * (m.d / 2 + 1.5) - Math.sin(m.rot) * s * m.w * 0.3));
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  const points = new THREE.Points(geo, new THREE.PointsMaterial({ size: 2.2, map: glowTexture('rgba(255,236,190,1)', 'rgba(255,150,60,0.55)'), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false }));
  points.frustumCulled = false;
  return points;
};

const rainLines = (count) => {
  const pos = new Float32Array(count * 6);
  const seeds = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) seeds.set([(Math.random() - 0.5) * 90, Math.random() * 40, (Math.random() - 0.5) * 90], i * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: '#b8c6d6', transparent: true, opacity: 0, depthWrite: false, fog: true }));
  lines.frustumCulled = false;
  lines.userData = { seeds, count };
  return lines;
};

const snowPoints = (count) => {
  const seeds = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) seeds.set([(Math.random() - 0.5) * 80, Math.random() * 30, (Math.random() - 0.5) * 80], i * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.16, map: glowTexture('rgba(255,255,255,1)', 'rgba(255,255,255,0.6)'), transparent: true, depthWrite: false, opacity: 0 }));
  pts.frustumCulled = false;
  pts.userData = { seeds, count };
  return pts;
};

const pick = (probs, r) => {
  let acc = 0;
  return probs.findIndex((p) => {
    acc += p;
    return r < acc;
  });
};

const pad = (n) => String(Math.floor(n)).padStart(2, '0');

export const buildAtmosphere = ({ scene, data, sun, hemi, sky, fogBase }) => {
  const climate = data.life.climate;
  const uniforms = { uSnow: { value: 0 }, uWet: { value: 0 } };
  const startWeather = TARGETS[climate.start_weather] ? climate.start_weather : data.climate && data.climate.precip === 'snow' ? 'snow' : data.climate && data.climate.precip === 'rain' ? 'rain' : data.climate && data.climate.fog ? 'fog' : 'clear';
  const daysIn = climate.days_in_month || [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const year = { rome_315: 315, rome_476: 476 }[data.life.era] || null;
  const state = {
    hours: climate.start_hour, day: 0, month: climate.start_month, dom: Math.min(daysIn[climate.start_month], climate.start_day || 15), weather: startWeather, nextChange: climate.start_hour + climate.change_every_hours,
    mix: { ...TARGETS[startWeather] }, flash: 0, nextFlash: 3, speed: 1 / (60 * climate.minutes_per_hour), frozen: false,
  };
  const random = rng(4242);
  sky.material = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    fog: false,
    uniforms: {
      top: { value: new THREE.Color() }, bottom: { value: new THREE.Color() }, sunDir: { value: new THREE.Vector3(0, 1, 0) }, sunColor: { value: new THREE.Color() },
      cloudLit: { value: new THREE.Color() }, cloudDark: { value: new THREE.Color() }, cover: { value: 0 }, night: { value: 0 }, time: { value: 0 }, sunVis: { value: 1 }, flash: { value: 0 },
    },
    vertexShader: SKY_VERT,
    fragmentShader: SKY_FRAG,
  });
  const windows = windowPoints(data);
  const rain = rainLines(7000);
  const snow = snowPoints(6000);
  scene.add(windows, rain, snow);
  const torches = Array.from({ length: 4 }, () => {
    const l = new THREE.PointLight('#ffa64a', 0, 26, 1.6);
    scene.add(l);
    return l;
  });
  const lightDir = new THREE.Vector3(0.5, 0.8, 0.3);
  const out = { exposure: 1, lightDir, night: 0, torches };

  const sunState = () => {
    const f0 = (state.dom - 15) / 30;
    const other = (state.month + (f0 >= 0 ? 1 : 11)) % 12;
    const w = Math.abs(f0);
    const rise = climate.sun[state.month][0] * (1 - w) + climate.sun[other][0] * w;
    const set = climate.sun[state.month][1] * (1 - w) + climate.sun[other][1] * w;
    const noonAlt = 48.1 + DECL[state.month] * (1 - w) + DECL[other] * w;
    const h = state.hours;
    const f = (h - rise) / (set - rise);
    const nightLen = 24 - (set - rise);
    const g = ((h - set + 24) % 24) / nightLen;
    const alt = f >= 0 && f <= 1 ? noonAlt * Math.sin(Math.PI * f) : -Math.min(40, 90 - noonAlt) * Math.sin(Math.PI * Math.min(1, g));
    const az = f >= 0 && f <= 1 ? Math.PI * f : Math.PI + Math.PI * Math.min(1, g);
    const r = THREE.MathUtils.degToRad(alt);
    return { alt, dir: new THREE.Vector3(Math.cos(az) * Math.cos(r), Math.sin(r), Math.sin(az) * Math.cos(r) * 0.8 + 0.25).normalize(), rise, set };
  };

  const rollWeather = () => {
    const probs = climate.by_month[state.month];
    const stay = random() < 0.45;
    state.weather = stay ? state.weather : climate.kinds[Math.max(0, pick(probs, random()))];
    state.nextChange = state.hours + climate.change_every_hours * (0.6 + random() * 0.8);
  };

  const advance = (gameHours) => {
    state.hours += gameHours;
    state.nextChange -= state.hours >= 24 ? 24 : 0;
    while (state.hours >= 24) {
      state.hours -= 24;
      state.day += 1;
      if (climate.calendar === 'real') {
        state.dom += 1;
        if (state.dom > daysIn[state.month]) {
          state.dom = 1;
          state.month = (state.month + 1) % 12;
        }
      } else state.month = (state.month + 1) % 12;
    }
    if (state.hours >= state.nextChange && !state.frozen) rollWeather();
  };

  const updateSprites = (camPos, dt) => {
    const rd = rain.userData;
    const rp = rain.geometry.attributes.position.array;
    const rainN = Math.floor(rd.count * Math.min(1, state.mix.rain));
    for (let i = 0; i < rainN; i += 1) {
      rd.seeds[i * 3 + 1] -= dt * (16 + state.mix.storm * 8);
      rd.seeds[i * 3] -= dt * (1.5 + state.mix.storm * 5);
      if (rd.seeds[i * 3 + 1] < 0) {
        rd.seeds[i * 3 + 1] += 40;
        rd.seeds[i * 3] = (Math.random() - 0.5) * 90;
      }
      const x = camPos.x + rd.seeds[i * 3];
      const y = camPos.y - 12 + rd.seeds[i * 3 + 1];
      const z = camPos.z + rd.seeds[i * 3 + 2];
      rp.set([x, y, z, x + 0.06 + state.mix.storm * 0.25, y + 0.75, z], i * 6);
    }
    rain.geometry.setDrawRange(0, rainN * 2);
    rain.geometry.attributes.position.needsUpdate = true;
    rain.material.opacity = 0.18 + 0.32 * Math.min(1, state.mix.rain) * (0.4 + 0.6 * (1 - out.night * 0.6));
    rain.visible = rainN > 0;
    const sd = snow.userData;
    const sp = snow.geometry.attributes.position.array;
    const snowN = Math.floor(sd.count * Math.min(1, state.mix.snow));
    const t = performance.now() / 1000;
    for (let i = 0; i < snowN; i += 1) {
      sd.seeds[i * 3 + 1] -= dt * (0.9 + (i % 7) * 0.08);
      if (sd.seeds[i * 3 + 1] < 0) sd.seeds[i * 3 + 1] += 30;
      sp.set([camPos.x + sd.seeds[i * 3] + Math.sin(t * 0.7 + i) * 0.6, camPos.y - 8 + sd.seeds[i * 3 + 1], camPos.z + sd.seeds[i * 3 + 2] + Math.cos(t * 0.5 + i * 1.3) * 0.6], i * 3);
    }
    snow.geometry.setDrawRange(0, snowN);
    snow.geometry.attributes.position.needsUpdate = true;
    snow.material.opacity = 0.9 * Math.min(1, state.mix.snow * 1.5);
    snow.visible = snowN > 0;
  };

  const update = (dt, camPos, time) => {
    const gameHours = state.frozen ? 0 : dt * state.speed;
    advance(gameHours);
    const target = TARGETS[state.weather];
    const blend = Math.min(1, dt * 0.25);
    Object.keys(target).forEach((k) => {
      state.mix[k] += (target[k] - state.mix[k]) * blend;
    });
    const hoursPassed = Math.max(gameHours, dt / 600);
    uniforms.uSnow.value = Math.max(0, Math.min(1, uniforms.uSnow.value + (state.mix.snow > 0.3 ? state.mix.snow * 0.5 : -0.25) * hoursPassed));
    uniforms.uWet.value = Math.max(0, Math.min(1, uniforms.uWet.value + (state.mix.rain > 0.2 ? state.mix.rain * 0.9 : -0.3) * hoursPassed));
    const s = sunState();
    const key = lerpKey(s.alt);
    const cover = state.mix.cloud;
    const daylight = smooth(-8, 12, s.alt);
    const grey = new THREE.Color('#141820').lerp(new THREE.Color('#9aa2ab'), daylight);
    const night = 1 - smooth(-10, -1, s.alt);
    out.night = night;
    state.mix.storm > 0.5 && (state.nextFlash -= dt);
    if (state.mix.storm > 0.5 && state.nextFlash < 0) {
      state.flash = 1;
      state.nextFlash = 4 + random() * 9;
    }
    state.flash = Math.max(0, state.flash - dt * 5);
    const u = sky.material.uniforms;
    u.top.value.copy(key.top).lerp(grey, cover * 0.8);
    u.bottom.value.copy(key.bottom).lerp(grey, cover * 0.75);
    u.sunDir.value.copy(s.dir);
    u.sunColor.value.copy(key.sun);
    u.sunVis.value = smooth(-3, 2, s.alt);
    u.cover.value = cover;
    u.night.value = night;
    u.time.value = time;
    u.flash.value = state.flash * 0.6;
    const lit = new THREE.Color('#2a3040').lerp(new THREE.Color('#f3efe6').lerp(key.sun, 0.35), daylight);
    u.cloudLit.value.copy(lit).lerp(grey, cover * 0.5);
    u.cloudDark.value.copy(lit).multiplyScalar(0.72 - cover * 0.25);
    const moon = new THREE.Vector3(-0.35, 0.82, -0.45).normalize();
    lightDir.copy(s.alt > -3 ? s.dir : moon);
    lightDir.y = Math.max(lightDir.y, 0.08);
    lightDir.normalize();
    sun.color.copy(key.sun);
    sun.intensity = key.sunI * (1 - 0.82 * cover) * (s.alt > -3 ? smooth(-3, 4, s.alt) : 1) + state.flash * 2.5;
    hemi.color.copy(key.top).lerp(grey, cover * 0.6);
    hemi.intensity = key.amb * (1 + 0.3 * cover) + state.flash * 1.5;
    scene.fog.color.copy(key.fog).lerp(grey.clone().multiplyScalar(0.95 + 0.1 * daylight), Math.min(1, cover * 0.7 + state.mix.fog * 0.6));
    scene.fog.density = fogBase * (1 + 1.4 * cover + 5.5 * state.mix.fog + 1.6 * state.mix.snow + 1.1 * state.mix.rain) * (1 + night * 0.6);
    out.exposure = key.exposure;
    windows.material.opacity = Math.max(key.window, cover > 0.7 && daylight < 0.6 ? 0.5 : 0) * 0.95;
    windows.visible = windows.material.opacity > 0.02;
    updateSprites(camPos, dt);
  };

  const partOfDay = () => {
    const s = sunState();
    const h = state.hours;
    return s.alt < -8 ? 'לילה' : s.alt < 2 ? (h < 12 ? 'שחר' : 'דמדומים') : h < 11 ? 'בוקר' : h < 14 ? 'צהריים' : h < s.set - 1.5 ? 'אחר הצהריים' : 'ערב';
  };

  const romanHour = () => {
    const s = sunState();
    const h = state.hours;
    if (h >= s.rise && h <= s.set) return `השעה ה־${Math.min(12, Math.floor(((h - s.rise) / (s.set - s.rise)) * 12) + 1)} של היום הרומי`;
    const into = (h - s.set + 24) % 24;
    return `משמר הלילה ה־${Math.min(4, Math.floor((into / (24 - (s.set - s.rise))) * 4) + 1)}`;
  };

  const clock = () => {
    const s = sunState();
    return { hour: state.hours, day: state.day, dom: state.dom, year, daysIn, month: state.month, weather: state.weather, mix: { ...state.mix }, night: out.night, alt: s.alt, rise: s.rise, set: s.set,
             snow: uniforms.uSnow.value, wet: uniforms.uWet.value, daylightCarts: state.hours >= s.rise && state.hours < s.rise + 10 };
  };

  const label = () => `${state.dom} ב${climate.months_he[state.month]}${year ? ` ${year} לספירה` : ''} · ${pad(state.hours)}:${pad((state.hours % 1) * 60)} · ${partOfDay()} (${romanHour()}) · ${climate.weather_he[state.weather]}`;

  const patch = (root) => root.traverse((o) => (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => patchMaterial(m, uniforms)));

  const set = (hour) => {
    state.hours = ((hour % 24) + 24) % 24;
    state.nextChange = state.hours + climate.change_every_hours;
  };

  const setDate = (month, dom) => {
    state.month = ((Math.floor(month) % 12) + 12) % 12;
    state.dom = Math.max(1, Math.min(daysIn[state.month], Math.floor(dom)));
    rollWeather();
  };

  const setWeather = (kind, instant = false) => {
    if (!TARGETS[kind]) return;
    state.weather = kind;
    state.nextChange = state.hours + climate.change_every_hours * 2;
    instant && Object.assign(state.mix, TARGETS[kind]);
  };

  const setCover = (snowCover, wet) => {
    uniforms.uSnow.value = snowCover;
    uniforms.uWet.value = wet;
  };

  return Object.assign(out, { update, clock, label, patch, set, setDate, setWeather, setCover, freeze: (v) => { state.frozen = v; }, setSpeed: (minutesPerHour) => { state.speed = 1 / (60 * minutesPerHour); } });
};
