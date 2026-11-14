import * as THREE from 'three';

import { api } from './api.js';
import { buildExterior } from './exterior.js';
import { buildInterior, exitDoor, interiorColliders, roomAt } from './interior.js';
import { applyObject, describeParams, pickTarget } from './detail.js';
import { createLife } from './life.js';
import { initPlanner } from './planner.js';
import { renderRoomImage } from './preview.js';

const $ = (id) => document.getElementById(id);
const EYE = 1.7;
const RADIUS = 0.4;

const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
const camera = new THREE.PerspectiveCamera(70, 1, 0.1, 4500);

const state = {
  worldId: null,
  data: null,
  rooms: {},
  versions: {},
  ext: null,
  interior: null,
  interiorScene: null,
  colliders: [],
  mode: 'world',
  roomId: null,
  player: { x: 0, y: 0, z: 0, yaw: 0, pitch: 0 },
  keys: new Set(),
  panelOpen: false,
  proposal: null,
  lastSave: 0,
  time: 0,
  drag: null,
};

const resize = () => {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
};

const palaceRooms = () => (state.place ? state.place.rooms : state.data.palace.rooms);

const roomKey = (rid) => (state.place && state.place.kind === 'house' ? `${state.place.id}__${rid}` : rid);

const pushOut = (pos, c) => {
  if (c.cx === undefined) {
    const nx = Math.max(c.minx, Math.min(pos.x, c.maxx));
    const nz = Math.max(c.minz, Math.min(pos.z, c.maxz));
    const dx = pos.x - nx;
    const dz = pos.z - nz;
    const dist = Math.hypot(dx, dz);
    if (dist < RADIUS && dist > 1e-6) {
      pos.x = nx + (dx / dist) * RADIUS;
      pos.z = nz + (dz / dist) * RADIUS;
    } else if (dist <= 1e-6 && pos.x > c.minx && pos.x < c.maxx && pos.z > c.minz && pos.z < c.maxz) {
      const left = pos.x - c.minx;
      const right = c.maxx - pos.x;
      const top = pos.z - c.minz;
      const bottom = c.maxz - pos.z;
      const m = Math.min(left, right, top, bottom);
      pos.x = m === left ? c.minx - RADIUS : m === right ? c.maxx + RADIUS : pos.x;
      pos.z = m === top ? c.minz - RADIUS : m === bottom ? c.maxz + RADIUS : pos.z;
    }
    return;
  }
  const cos = Math.cos(c.rot);
  const sin = Math.sin(c.rot);
  const dx = pos.x - c.cx;
  const dz = pos.z - c.cz;
  const lx = dx * cos - dz * sin;
  const lz = dx * sin + dz * cos;
  const nx = Math.max(-c.hw, Math.min(lx, c.hw));
  const nz = Math.max(-c.hd, Math.min(lz, c.hd));
  const ddx = lx - nx;
  const ddz = lz - nz;
  const dist = Math.hypot(ddx, ddz);
  if (dist < RADIUS) {
    const inside = dist <= 1e-6;
    const push = inside ? { x: lx > 0 ? c.hw + RADIUS - lx : -c.hw - RADIUS - lx, z: 0 } : { x: (ddx / dist) * (RADIUS - dist), z: (ddz / dist) * (RADIUS - dist) };
    pos.x += push.x * cos + push.z * sin;
    pos.z += -push.x * sin + push.z * cos;
  }
};

const collide = (pos) => {
  const list = state.mode === 'world' ? state.ext.near(pos.x, pos.z) : state.colliders;
  [0, 1, 2].forEach(() => list.forEach((c) => pushOut(pos, c)));
};

const setLocation = (main, sub) => {
  $('loc-main').textContent = main;
  $('loc-sub').textContent = sub;
};

const refreshLocation = () => {
  const room = state.mode === 'interior' ? palaceRooms().find((r) => r.id === state.roomId) : null;
  const where = state.place && state.place.kind === 'house' ? 'בתוך בית' : 'בתוך הארמון';
  setLocation(room ? `${where} · ${room.name}` : 'בעיר', `${state.data ? state.data.name : ''}`);
  $('design-open').style.display = room ? 'block' : 'none';
  $('exit-btn').style.display = room ? 'block' : 'none';
};

const buildInteriorScene = () => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(palaceRooms().some((r) => r.open) ? '#9fb8d0' : '#14100d');
  state.interior = buildInterior(palaceRooms(), state.rooms);
  scene.add(state.interior);
  state.interiorScene = scene;
  state.colliders = interiorColliders(palaceRooms(), state.rooms);
};

const rebuildInterior = () => {
  buildInteriorScene();
  refreshLocation();
};

const enterPalace = () => {
  state.place = { kind: 'palace', rooms: state.data.palace.rooms };
  state.rooms = state.palaceDesigns;
  buildInteriorScene();
  const entrance = palaceRooms()[0];
  state.mode = 'interior';
  state.roomId = entrance.id;
  Object.assign(state.player, { x: entrance.cx, z: entrance.cz + entrance.d / 2 - 1.6, yaw: 0, pitch: 0 });
  refreshLocation();
};

const doorPoint = (h, extra) => ({ x: h.x + Math.sin(h.rot || 0) * (h.d / 2 + extra), z: h.z + Math.cos(h.rot || 0) * (h.d / 2 + extra) });

const enterHouse = async (h) => {
  const payload = await api.house(state.worldId, h.id);
  state.place = { kind: 'house', id: h.id, house: h, rooms: payload.rooms };
  state.rooms = payload.designs;
  buildInteriorScene();
  const entrance = payload.rooms.find((r) => r.doors.some((d) => d.exit)) || payload.rooms[0];
  state.mode = 'interior';
  state.roomId = entrance.id;
  Object.assign(state.player, { x: entrance.cx, z: entrance.cz + entrance.d / 2 - 1.0, y: EYE, yaw: 0, pitch: 0 });
  refreshLocation();
};

const nearDoor = () => {
  if (state.mode !== 'world' || !state.ext) return null;
  const pl = state.player;
  const p = state.data.palace;
  const pd = doorPoint(p, 2.0);
  const house = state.data.houses.reduce((best, h) => {
    if (h.ruin || Math.abs(h.x - pl.x) > 16 || Math.abs(h.z - pl.z) > 16) return best;
    const dp = doorPoint(h, 0.9);
    const dist = Math.hypot(dp.x - pl.x, dp.z - pl.z);
    return dist < 2.2 && (!best || dist < best.dist) ? { h, dist } : best;
  }, null);
  return Math.hypot(pd.x - pl.x, pd.z - pl.z) < 4 ? { kind: 'palace' } : house ? { kind: 'house', h: house.h } : null;
};

const interact = () => {
  const target = nearDoor();
  target && target.kind === 'palace' && enterPalace();
  target && target.kind === 'house' && enterHouse(target.h);
};

const exitPalace = () => {
  const house = state.place && state.place.kind === 'house' ? state.place.house : null;
  const p = house || state.data.palace;
  state.mode = 'world';
  state.roomId = null;
  state.place = null;
  const out = p.d / 2 + (house ? 1.4 : 2.2);
  Object.assign(state.player, { x: p.x + Math.sin(p.rot || 0) * out, z: p.z + Math.cos(p.rot || 0) * out, yaw: (p.rot || 0) + Math.PI, pitch: 0 });
  refreshLocation();
};

const stepPlayer = (dt, input) => {
  const pl = state.player;
  const speed = state.mode === 'interior' ? (input.run ? 5.5 : 3.2) : input.run ? 11 : 5;
  pl.yaw += input.turn * dt * 1.9;
  const fx = -Math.sin(pl.yaw);
  const fz = -Math.cos(pl.yaw);
  const rx = Math.cos(pl.yaw);
  const rz = -Math.sin(pl.yaw);
  const mx = fx * input.fwd + rx * input.strafe;
  const mz = fz * input.fwd + rz * input.strafe;
  const len = Math.hypot(mx, mz) || 1;
  const step = Math.min(speed * dt, 1.0);
  const target = { x: pl.x + (mx / len) * step * Math.min(1, Math.hypot(mx, mz)), z: pl.z + (mz / len) * step * Math.min(1, Math.hypot(mx, mz)) };
  if (state.mode === 'world') {
    const here = state.ext.groundAt(pl.x, pl.z, pl.y - EYE);
    const there = state.ext.groundAt(target.x, target.z, pl.y - EYE);
    const dist = Math.hypot(target.x - pl.x, target.z - pl.z);
    const blocked = there - here > dist * 1.15 + 0.25 || state.ext.isWater(target.x, target.z, pl.y - EYE);
    if (!blocked) Object.assign(pl, target);
    collide(pl);
    const ground = state.ext.groundAt(pl.x, pl.z, pl.y - EYE) + EYE;
    pl.y += (ground - pl.y) * Math.min(1, dt * 14);
    const t = state.ext.trigger;
    const dx = pl.x - t.x;
    const dz = pl.z - t.z;
    const lx = dx * Math.cos(t.rot) - dz * Math.sin(t.rot);
    const lz = dx * Math.sin(t.rot) + dz * Math.cos(t.rot);
    if (Math.abs(lx) < t.half && lz - t.zBack < 0.95 && lz - t.zBack > -0.3 && pl.y - EYE > state.data.palace.y - 1.5) enterPalace();
  } else {
    Object.assign(pl, target);
    collide(pl);
    pl.y = EYE;
    const room = roomAt(palaceRooms(), pl.x, pl.z);
    if (room && room.id !== state.roomId) {
      state.roomId = room.id;
      refreshLocation();
    }
    const door = exitDoor(palaceRooms());
    if (pl.z > door.z - 0.25 && Math.abs(pl.x - door.x) < door.width / 2) exitPalace();
  }
};

const inputFromKeys = (keys) => ({
  fwd: (keys.has('ArrowUp') || keys.has('KeyW') ? 1 : 0) - (keys.has('ArrowDown') || keys.has('KeyS') ? 1 : 0),
  strafe: (keys.has('KeyD') ? 1 : 0) - (keys.has('KeyA') ? 1 : 0),
  turn: (keys.has('ArrowLeft') ? 1 : 0) - (keys.has('ArrowRight') ? 1 : 0),
  run: keys.has('ShiftLeft') || keys.has('ShiftRight'),
});

const typing = () => ['TEXTAREA', 'INPUT'].includes(document.activeElement && document.activeElement.tagName);

const savePlayer = (force) => {
  const now = performance.now();
  if (state.worldId && (force || now - state.lastSave > 4000)) {
    state.lastSave = now;
    const pl = state.player;
    const place = state.place && state.place.kind === 'house' ? { kind: 'house', id: state.place.id } : { kind: 'palace' };
    api.savePlayer(state.worldId, { mode: state.mode, room: state.roomId, place, x: pl.x, y: pl.y, z: pl.z, yaw: pl.yaw, pitch: pl.pitch }).catch(() => null);
  }
};

const tick = (dt, t) => {
  if (state.data) {
    if (!state.panelOpen && !typing()) stepPlayer(dt, inputFromKeys(state.keys));
    const pl = state.player;
    camera.position.set(pl.x, pl.y, pl.z);
    camera.rotation.set(pl.pitch, pl.yaw, 0, 'YXZ');
    state.mode === 'world' && state.ext.update(dt, camera.position, t / 1000);
    const atmo = state.ext.atmo;
    state.mode === 'world' && state.life && atmo && state.life.update(dt, camera.position, atmo.clock());
    renderer.toneMappingExposure = state.mode === 'world' && atmo ? atmo.exposure : 1;
    state.frameNo = (state.frameNo || 0) + 1;
    if (state.frameNo % 12 === 0) {
      const target = nearDoor();
      $('interact').textContent = target ? (target.kind === 'palace' ? 'E — כניסה לארמון' : 'E — כניסה לבית') : '';
      $('interact').style.display = target ? 'block' : 'none';
    }
    if (state.frameNo % 30 === 0 && state.mode === 'world' && atmo) $('loc-sub').textContent = `${state.data.name} · ${atmo.label()}`;
    renderer.render(state.mode === 'world' ? state.ext.scene : state.interiorScene, camera);
    savePlayer(false);
  }
};

const frame = (t) => {
  const dt = Math.min(0.1, (t - (state.time || t)) / 1000);
  state.time = t;
  tick(dt, t);
  requestAnimationFrame(frame);
};

const loadWorld = async (id) => {
  const payload = await api.world(id);
  state.rooms = payload.rooms;
  state.palaceDesigns = payload.rooms;
  state.place = null;
  state.versions = payload.versions;
  state.ext = buildExterior(payload.world.scene);
  state.data = { ...state.ext.data, name: payload.world.name };
  const life = payload.world.scene.life;
  state.life = life && !life.off && state.ext.atmo ? createLife({ ext: state.ext, scene: state.ext.scene, life, base: life.population.base }) : null;
  $('clock-open').style.display = state.ext.atmo ? 'block' : 'none';
  state.payload = payload;
  state.worldId = id;
  (payload.objects || []).forEach((o) => applyObject(state.ext, o));
  buildInteriorScene();
  const saved = payload.player;
  const spawn = state.ext.spawn();
  Object.assign(state.player, { x: spawn.x, z: spawn.z, yaw: spawn.yaw, pitch: 0, y: state.ext.sample(spawn.x, spawn.z) + EYE });
  state.mode = 'world';
  state.roomId = null;
  if (saved && Number.isFinite(saved.x) && Math.abs(saved.x) < state.data.size / 2 && Math.abs(saved.z) < state.data.size / 2) {
    Object.assign(state.player, { x: saved.x, y: saved.y, z: saved.z, yaw: saved.yaw, pitch: saved.pitch || 0 });
    state.mode = saved.mode;
    state.roomId = saved.room;
  }
  if (saved && saved.mode === 'interior') {
    const house = saved.place && saved.place.kind === 'house' ? state.data.houses.find((h) => h.id === saved.place.id) : null;
    house ? await enterHouse(house) : enterPalace();
    Object.assign(state.player, { x: saved.x, z: saved.z, yaw: saved.yaw, y: EYE });
    state.roomId = saved.room;
  }
  $('start').classList.remove('on');
  refreshLocation();
  canvas.focus();
};

const renderWorldList = async () => {
  const { worlds } = await api.worlds();
  $('worlds').innerHTML = worlds.length ? '<h2>עולמות קיימים</h2>' : '';
  worlds.forEach((w) => {
    const row = document.createElement('div');
    row.className = 'world';
    row.innerHTML = `<div><b></b><span></span></div><button class="primary">המשך</button>`;
    row.querySelector('b').textContent = w.name;
    row.querySelector('span').textContent = w.description.slice(0, 90);
    row.querySelector('button').onclick = () => loadWorld(w.id);
    $('worlds').appendChild(row);
  });
};

const createWorld = async () => {
  $('create').disabled = true;
  $('status').textContent = $('wllm').checked ? 'מפרש את התיאור עם המודל המקומי ובונה את העולם… (עד דקה)' : 'בונה את העולם…';
  try {
    const { id } = await api.createWorld($('wname').value, $('wdesc').value, $('wllm').checked, planner.createExtras());
    await loadWorld(id);
  } catch (err) {
    $('status').textContent = `שגיאה: ${err.message}`;
  }
  $('create').disabled = false;
};

const currentRoom = () => palaceRooms().find((r) => r.id === state.roomId);

const openClock = () => {
  const atmo = state.ext && state.ext.atmo;
  if (!atmo) return;
  const c = atmo.clock();
  const months = state.data.life.climate.months_he;
  $('clock-month').innerHTML = '';
  months.forEach((m, k) => {
    const opt = document.createElement('option');
    opt.value = String(k);
    opt.textContent = m;
    $('clock-month').appendChild(opt);
  });
  $('clock-month').value = String(c.month);
  $('clock-day').value = String(c.dom);
  $('clock-time').value = `${String(Math.floor(c.hour)).padStart(2, '0')}:${String(Math.floor((c.hour % 1) * 60)).padStart(2, '0')}`;
  $('clock-year').textContent = c.year ? `השנה לפי מפת הפרויקט: ${c.year} לספירה. התאריך קובע את השמש, אורך היום והסיכוי לגשם או שלג (שלג רק בדצמבר–פברואר).` : '';
  $('clock-status').textContent = '';
  $('clock-panel').style.display = 'block';
  state.panelOpen = true;
};

const applyClock = async () => {
  const atmo = state.ext && state.ext.atmo;
  if (!atmo) return;
  const month = Number($('clock-month').value);
  const day = Number($('clock-day').value) || 1;
  const [hh, mm] = ($('clock-time').value || '09:00').split(':').map(Number);
  const hour = hh + (mm || 0) / 60;
  atmo.setDate(month, day);
  atmo.set(hour);
  state.life && state.life.resync();
  $('clock-status').textContent = atmo.label();
  api.setClock(state.worldId, { month, day, hour }).catch(() => null);
};

const fillLibrary = async () => {
  const { assets } = await api.assets();
  $('d-library').textContent = assets.length ? assets.map((a) => `${a.name}`).join(' · ') : 'הספרייה ריקה. סמנו "לשמור בספרייה" בעת אישור שינוי.';
};

const fillHistory = async () => {
  const { history } = await api.history(state.worldId, roomKey(state.roomId));
  $('d-history').innerHTML = '';
  history.slice(0, 8).forEach((h) => {
    const row = document.createElement('div');
    row.className = 'hist';
    row.innerHTML = '<span></span><button>חזור לגרסה</button>';
    row.querySelector('span').textContent = `גרסה ${h.version}: ${h.summary}`;
    row.querySelector('button').onclick = async () => {
      const { design } = await api.revert(state.worldId, roomKey(state.roomId), h.version);
      state.rooms[state.roomId] = design;
      rebuildInterior();
      fillHistory();
    };
    $('d-history').appendChild(row);
  });
};

const openObjectPanel = (picked) => {
  const target = picked || pickTarget(state.ext, camera);
  state.objTarget = target;
  state.panelOpen = true;
  $('objpanel').classList.add('on');
  $('o-proposal').style.display = 'none';
  $('o-target').textContent = target ? `${target.name} · במרחק ${Math.round(target.distance)} מ׳` : 'לא נבחר אובייקט. לחצו בעכבר על בית, אנדרטה, ארמון או עץ.';
  $('o-propose').disabled = !target;
  document.exitPointerLock && document.exitPointerLock();
};

const closeObjectPanel = () => {
  state.panelOpen = false;
  $('objpanel').classList.remove('on');
  canvas.focus();
};

const proposeObject = async () => {
  $('o-propose').disabled = true;
  $('o-status').textContent = 'בודק במודל המקומי איך זה נראה באמת…';
  try {
    const prop = await api.proposeObject(state.worldId, { type: state.objTarget.type, id: state.objTarget.id }, $('o-text').value.trim(), $('o-llm').checked);
    state.objProposal = prop;
    $('o-proposal').style.display = 'block';
    $('o-notes').textContent = prop.params.notes || '';
    $('o-params').innerHTML = '';
    describeParams(prop.params).forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      $('o-params').appendChild(li);
    });
    $('o-status').textContent = `פורש באמצעות: ${prop.source} · ייבנה ב: ${prop.engine}`;
    $('o-apply').disabled = !prop.supported;
  } catch (err) {
    $('o-status').textContent = `שגיאה: ${err.message}`;
  }
  $('o-propose').disabled = false;
};

const resolveObject = async (action) => {
  $('o-apply').disabled = true;
  $('o-status').textContent = action === 'apply' ? (state.objProposal.engine === 'Blender' ? 'בונה דגם מפורט ב־Blender… (עד דקה)' : 'בונה את העץ…') : 'ההצעה נדחתה.';
  try {
    const result = await api.resolveObject(state.objProposal.id, action);
    if (action === 'apply') {
      await applyObject(state.ext, { object_id: result.object_id, kind: result.kind, params: result.params, model: result.model });
      $('o-status').textContent = `נבנה ונשמר (גרסה ${result.version}).`;
    }
  } catch (err) {
    $('o-status').textContent = `שגיאה: ${err.message}`;
  }
  $('o-proposal').style.display = 'none';
  $('o-apply').disabled = false;
};

const LIB_GROUPS = [['model', 'מבנים ואנדרטאות מפורטים (Blender)'], ['tree', 'עצים מפורטים'], ['room', 'חדרים מעוצבים'], ['interior_set', 'פנים מבנים שלמים'], ['world_plan', 'אבני דרך — תוכניות עולם'], ['item', 'רהיטים ורכיבים']];

const libraryGroup = (a) => (LIB_GROUPS.some(([k]) => k === a.kind) ? a.kind : 'item');

const useAsset = async (asset, mode) => {
  const ahead = { x: state.player.x - Math.sin(state.player.yaw) * 18, z: state.player.z - Math.cos(state.player.yaw) * 18 };
  const body = { asset_id: asset.id };
  mode === 'target' && Object.assign(body, { target: state.objTarget });
  mode === 'place' && Object.assign(body, { place: { ...ahead, y: state.ext.groundAt(ahead.x, ahead.z, 1e9), rot: state.player.yaw + Math.PI } });
  mode === 'room' && Object.assign(body, { room_key: roomKey(state.roomId) });
  $('lib-status').textContent = 'מחיל…';
  const result = await api.useLibrary(state.worldId, body).catch((err) => ({ error: err.message }));
  if (result.kind === 'room') {
    state.rooms[state.roomId] = result.design;
    rebuildInterior();
  } else if (result.object_id) {
    await applyObject(state.ext, { object_id: result.object_id, kind: result.kind, params: result.params, model: result.model });
  }
  $('lib-status').textContent = result.error || `הוחל ונשמר (גרסה ${result.version}).`;
};

const openLibrary = async () => {
  state.panelOpen = true;
  $('library').classList.add('on');
  $('lib-target').textContent = state.mode === 'interior' ? `חדר נוכחי: ${currentRoom() ? currentRoom().name : ''}` : state.objTarget ? `אובייקט נבחר: ${state.objTarget.name}` : 'אין אובייקט נבחר (לחצו על אובייקט בעולם כדי לבחור).';
  const { assets } = await api.assets();
  $('lib-list').innerHTML = '';
  LIB_GROUPS.forEach(([key, title]) => {
    const items = assets.filter((a) => libraryGroup(a) === key);
    if (!items.length) return;
    const h = document.createElement('h2');
    h.textContent = `${title} (${items.length})`;
    $('lib-list').appendChild(h);
    items.slice(0, 40).forEach((a) => {
      const row = document.createElement('div');
      row.className = 'hist';
      const label = document.createElement('span');
      label.textContent = `${a.name} · ${new Date(a.created_at * 1000).toLocaleDateString('he-IL')}`;
      row.appendChild(label);
      const actions = [];
      ['model', 'tree'].includes(a.kind) && state.mode === 'world' && state.objTarget && actions.push(['החל על הנבחר', 'target']);
      ['model', 'tree'].includes(a.kind) && state.mode === 'world' && actions.push(['הצב לפניי', 'place']);
      a.kind === 'room' && state.mode === 'interior' && actions.push(['החל על החדר', 'room']);
      actions.forEach(([text, mode]) => {
        const b = document.createElement('button');
        b.textContent = text;
        b.onclick = () => useAsset(a, mode);
        row.appendChild(b);
      });
      $('lib-list').appendChild(row);
    });
  });
};

const closeLibrary = () => {
  state.panelOpen = false;
  $('library').classList.remove('on');
  canvas.focus();
};

const openDesigner = () => {
  if (state.mode === 'world' && state.data) {
    openObjectPanel();
    return;
  }
  if (state.mode === 'interior') {
    state.panelOpen = true;
    $('designer').classList.add('on');
    $('d-room').textContent = `החדר: ${currentRoom().name}`;
    document.exitPointerLock && document.exitPointerLock();
    fillHistory();
    fillLibrary();
  }
};

const closeDesigner = () => {
  state.panelOpen = false;
  $('designer').classList.remove('on');
  canvas.focus();
};

const selectedKeys = () => [...document.querySelectorAll('#d-comps input:checked')].map((i) => i.dataset.key);

const refreshPreviewAfter = async () => {
  const { preview } = await api.preview(state.proposal.id, selectedKeys());
  state.proposal.preview = preview;
  renderRoomImage($('pv-after'), currentRoom(), preview);
};

const showProposal = (proposal) => {
  state.proposal = proposal;
  $('d-proposal').style.display = 'block';
  renderRoomImage($('pv-before'), currentRoom(), proposal.current);
  renderRoomImage($('pv-after'), proposal.preview_room || currentRoom(), proposal.preview);
  $('d-comps').innerHTML = '';
  proposal.components.forEach((c) => {
    const row = document.createElement('label');
    row.className = 'comp';
    row.innerHTML = '<input type="checkbox" checked><span></span>';
    row.querySelector('input').dataset.key = c.key;
    row.querySelector('input').onchange = refreshPreviewAfter;
    const small = document.createElement('small');
    small.textContent = c.action === 'remove' ? 'הסרה' : c.type === 'item' ? 'הוספה' : c.type === 'info' ? 'מה היה כאן' : 'שינוי';
    row.querySelector('span').textContent = c.label;
    row.querySelector('span').appendChild(small);
    $('d-comps').appendChild(row);
  });
  const note = proposal.notes.length ? ` · ${proposal.notes.join(' · ')}` : '';
  $('d-status').textContent = proposal.components.length ? `פורש באמצעות: ${proposal.source}${note}` : 'לא זוהו שינויים בבקשה. נסו לנסח אחרת, למשל "הוסף שולחן" או "רצפת שיש".';
};

const propose = async () => {
  const text = $('d-text').value.trim();
  if (text) {
    $('d-propose').disabled = true;
    $('d-status').textContent = 'מכין הצעה…';
    try {
      showProposal(await api.propose(state.worldId, roomKey(state.roomId), text, $('d-llm').checked));
    } catch (err) {
      $('d-status').textContent = `שגיאה: ${err.message}`;
    }
    $('d-propose').disabled = false;
  }
};

const resolveProposal = async (action) => {
  const scopes = ['room', ...['building', 'houses', 'library'].filter((s) => $(`sc-${s}`).checked)];
  const result = await api.resolve(state.proposal.id, action, selectedKeys(), scopes);
  if (action === 'apply' && result.reconstructed) {
    const keepRoom = 'aula_regia';
    await loadWorld(state.worldId);
    enterPalace();
    state.roomId = keepRoom;
    $('d-status').textContent = 'הארמון שוחזר כפי שהיה — דומוס פלאוויה. כל החדרים נשמרו כגרסה חדשה.';
    fillHistory();
  } else if (action === 'apply') {
    const payload = await api.world(state.worldId);
    state.palaceDesigns = payload.rooms;
    state.rooms = state.place && state.place.kind === 'house' ? (await api.house(state.worldId, state.place.id)).designs : payload.rooms;
    state.versions = payload.versions;
    if (scopes.includes('houses')) {
      state.data.styles = payload.world.scene.styles;
      state.ext.rebuildHouses(state.data.styles);
    }
    rebuildInterior();
    $('d-status').textContent = `השינוי נבנה ונשמר (${Object.entries(result.versions).map(([r, v]) => `${r}: גרסה ${v}`).join(', ')})`;
    fillHistory();
    fillLibrary();
  } else {
    $('d-status').textContent = 'ההצעה נדחתה.';
  }
  $('d-proposal').style.display = 'none';
  state.proposal = null;
};

const wire = () => {
  window.addEventListener('resize', resize);
  window.addEventListener('keydown', (e) => {
    if (typing()) return;
    state.keys.add(e.code);
    e.code === 'KeyT' && openDesigner();
    e.code === 'KeyM' && planner.toggleMap();
    e.code === 'KeyL' && !state.panelOpen && openLibrary();
    e.code === 'KeyE' && !state.panelOpen && interact();
    e.code === 'KeyX' && !state.panelOpen && state.mode === 'interior' && exitPalace();
    e.code === 'Escape' && closeDesigner();
    e.code === 'Escape' && closeObjectPanel();
    e.code === 'Escape' && closeLibrary();
    e.code.startsWith('Arrow') && e.preventDefault();
  });
  window.addEventListener('keyup', (e) => state.keys.delete(e.code));
  window.addEventListener('blur', () => state.keys.clear());
  window.addEventListener('beforeunload', () => savePlayer(true));
  canvas.addEventListener('mousedown', (e) => {
    state.drag = { x: e.clientX, y: e.clientY };
    state.click = { x: e.clientX, y: e.clientY, t: performance.now() };
    canvas.focus();
  });
  window.addEventListener('mouseup', (e) => {
    state.drag = null;
    const c = state.click;
    state.click = null;
    if (c && state.data && state.mode === 'world' && Math.hypot(e.clientX - c.x, e.clientY - c.y) < 5 && performance.now() - c.t < 450) {
      const r = canvas.getBoundingClientRect();
      const picked = pickTarget(state.ext, camera, { x: ((e.clientX - r.left) / r.width) * 2 - 1, y: -((e.clientY - r.top) / r.height) * 2 + 1 });
      picked && openObjectPanel(picked);
    }
  });
  window.addEventListener('mousemove', (e) => {
    if (state.drag && state.data) {
      state.player.yaw -= (e.clientX - state.drag.x) * 0.0042;
      state.player.pitch = Math.max(-1.3, Math.min(1.3, state.player.pitch - (e.clientY - state.drag.y) * 0.0042));
      state.drag = { x: e.clientX, y: e.clientY };
    }
  });
  $('create').onclick = createWorld;
  $('design-open').onclick = openDesigner;
  $('d-close').onclick = closeDesigner;
  $('d-propose').onclick = propose;
  $('d-apply').onclick = () => resolveProposal('apply');
  $('d-reject').onclick = () => resolveProposal('reject');
  $('o-close').onclick = closeObjectPanel;
  $('exit-btn').onclick = () => {
    exitPalace();
    canvas.focus();
  };
  $('lib-close').onclick = closeLibrary;
  $('lib-open').onclick = openLibrary;
  $('o-library').onclick = () => {
    closeObjectPanel();
    openLibrary();
  };
  $('clock-open').onclick = openClock;
  $('clock-close').onclick = () => {
    $('clock-panel').style.display = 'none';
    state.panelOpen = false;
    canvas.focus();
  };
  $('clock-apply').onclick = applyClock;
  $('o-propose').onclick = proposeObject;
  $('o-apply').onclick = () => resolveObject('apply');
  $('o-reject').onclick = () => resolveObject('reject');
};

window.__fw = {
  state,
  renderer,
  camera,
  api,
  loadWorld,
  enterPalace,
  exitPalace,
  enterHouse,
  nearDoor,
  openObjectPanel,
  openLibrary,
  useAsset,
  pick: (ndc) => pickTarget(state.ext, camera, ndc),
  openDesigner,
  closeDesigner,
  teleport: (x, z, yaw = 0, pitch = 0) => {
    Object.assign(state.player, { x, z, yaw, pitch });
    state.mode === 'world' && (state.player.y = state.ext.groundAt(x, z, 1e9) + EYE);
  },
  simulate: (seconds, input) => Array.from({ length: Math.round(seconds * 60) }).forEach(() => stepPlayer(1 / 60, { fwd: 0, strafe: 0, turn: 0, run: false, ...input })),
  savePlayer: () => savePlayer(true),
  planner: () => planner,
  tick: (dt = 0.016) => tick(dt, performance.now()),
  setDate: (month, day) => state.ext.atmo && state.ext.atmo.setDate(month, day),
  openClock,
  applyClock,
  setHour: (h) => {
    state.ext.atmo && state.ext.atmo.set(h);
    state.life && state.life.resync();
  },
  setWeather: (kind, instant = true) => state.ext.atmo && state.ext.atmo.setWeather(kind, instant),
  setCover: (snow, wet) => state.ext.atmo && state.ext.atmo.setCover(snow, wet),
  freezeClock: (v = true) => state.ext.atmo && state.ext.atmo.freeze(v),
  clock: () => state.ext.atmo && state.ext.atmo.clock(),
  lifeStats: () => state.life && state.life.stats(),
  life: () => state.life,
};

const teleport = (x, z) => {
  state.mode = 'world';
  state.roomId = null;
  Object.assign(state.player, { x, z, y: state.ext.groundAt(x, z, 1e9) + EYE });
  refreshLocation();
};

const planner = initPlanner({ state, api, loadWorld, teleport, $ });

resize();
wire();
renderWorldList();
const wantedWorld = new URLSearchParams(location.search).get('world');
wantedWorld && /^[\w]+$/.test(wantedWorld) && loadWorld(wantedWorld).catch(() => null);
requestAnimationFrame(frame);
