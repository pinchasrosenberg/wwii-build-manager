import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

import { buildDetailedTree } from './trees.js';

const loader = new GLTFLoader();

const PARAM_LABELS = {
  species: 'מין', height: 'גובה (מ׳)', trunk_ratio: 'גובה הגזע (יחס)', lean: 'נטייה (מעלות)', crown_shape: 'צורת הצמרת', crown_width: 'רוחב הצמרת (מ׳)',
  branches: 'ענפים ראשיים', levels: 'רמות הסתעפות', foliage: 'צפיפות עלווה', leaf_color: 'צבע העלים', bark_color: 'צבע הקליפה',
  orders: 'סדרי העמודים בקומות', statues_in_arches: 'פסלים בקשתות', velarium_masts: 'תרני הוולריום (הסוכך)', attic_windows: 'חלונות בקומה העליונה', hypogeum: 'מרתפי הזירה',
  collapsed_sector: 'צד שקרס', order: 'סדר העמודים', columns_front: 'עמודים בחזית', fluting: 'חריצים בעמודים', pediment_relief: 'תבליט בגמלון', acroteria: 'פסלי גג',
  reliefs: 'תבליטים', statues_on_attic: 'פסלים על העליה', attic_inscription: 'כתובת הקדשה', portico_columns: 'עמודי האכסדרה', upper_story: 'קומה עליונה',
  floors: 'קומות', roof: 'גג', balcony: 'מרפסת', shop_front: 'חנויות בקומת הקרקע', shutters: 'תריסים', additions: 'תוספות',
};

const ADD_HE = { tower: 'מגדל', bell_tower: 'מגדל פעמונים', dome: 'כיפה', statues: 'פסלים', colonnade: 'שורת עמודים', portico: 'אכסדרה', balcony: 'מרפסת', arcade: 'קשתות',
  stairs: 'מדרגות', banner: 'דגלים', fountain: 'מזרקה', obelisk: 'אובליסק', crenellation: 'צריחי חומה', roof_garden: 'גינה על הגג', vines: 'צמחייה מטפסת', windows: 'חלונות', buttress: 'תמוכות', apse: 'אפסיס' };
const POS_HE = { front: 'בחזית', back: 'מאחור', left: 'משמאל', right: 'מימין', top: 'למעלה', corners: 'בפינות', around: 'מסביב' };
const SIZE_HE = { small: 'קטן', medium: 'בינוני', large: 'גדול' };

const valueText = (k, v) =>
  k === 'additions' ? (v.length ? v.map((a) => `${ADD_HE[a.kind] || a.kind} ${POS_HE[a.position] || ''} (${SIZE_HE[a.size] || ''}${a.count > 1 ? `, ×${a.count}` : ''})`).join(' · ') : 'אין')
    : Array.isArray(v) ? v.join(', ') : v === true ? 'כן' : v === false ? 'לא' : v;

export const describeParams = (params) =>
  Object.entries(params).filter(([k]) => !['notes', '_target'].includes(k)).map(([k, v]) => `${PARAM_LABELS[k] || k}: ${valueText(k, v)}`);

const hideTree = (ext, index) => {
  const mesh = ext.trees.children.find((m) => m.userData.treeIndices && m.userData.treeIndices.includes(index));
  if (mesh) {
    const slot = mesh.userData.treeIndices.indexOf(index);
    const m = new THREE.Matrix4();
    mesh.getMatrixAt(slot, m);
    const pos = new THREE.Vector3().setFromMatrixPosition(m);
    mesh.setMatrixAt(slot, new THREE.Matrix4().compose(pos, new THREE.Quaternion(), new THREE.Vector3(0.0001, 0.0001, 0.0001)));
    mesh.instanceMatrix.needsUpdate = true;
  }
};

const clearPrevious = (ext, objectId) => ext.scene.children.filter((c) => c.userData.detailFor === objectId).forEach((c) => ext.scene.remove(c));

export const applyObject = (ext, obj) => {
  const data = ext.data;
  clearPrevious(ext, obj.object_id);
  if (obj.kind === 'tree') {
    const index = Number(obj.object_id.slice(4));
    const t = data.trees[index];
    if (!t) return Promise.resolve(false);
    hideTree(ext, index);
    const mesh = buildDetailedTree(obj.params, index + 7);
    mesh.position.set(t.x, t.y - 0.1, t.z);
    mesh.userData.detailFor = obj.object_id;
    mesh.userData.treeIndex = index;
    ext.scene.add(mesh);
    return Promise.resolve(true);
  }
  if (obj.kind === 'placed' && !obj.model) {
    const p = obj.params;
    const mesh = buildDetailedTree(p, 99);
    mesh.position.set(p.x, (p.y ?? ext.groundAt(p.x, p.z, 1e9)) - 0.1, p.z);
    mesh.userData.detailFor = obj.object_id;
    mesh.userData.placed = true;
    ext.scene.add(mesh);
    return Promise.resolve(true);
  }
  if (!obj.model) return Promise.resolve(false);
  const isPalace = obj.object_id === 'palace';
  const house = obj.kind === 'house' ? data.houses.find((h) => h.id === obj.object_id) : null;
  const placed = obj.kind === 'placed' ? { ...obj.params, y: obj.params.y ?? ext.groundAt(obj.params.x, obj.params.z, 1e9) } : null;
  const m = placed || house || (isPalace ? data.palace : (data.landmarks || []).find((l) => l.id === obj.object_id));
  if (!m) return Promise.resolve(false);
  house && ext.hideHouse(house.id);
  return loader.loadAsync(obj.model).then((gltf) => {
    const root = gltf.scene;
    root.traverse((o) => {
      o.castShadow = true;
      o.receiveShadow = true;
    });
    root.position.set(m.x, m.y - (isPalace ? 0.15 : 0.2), m.z);
    root.rotation.y = m.rot || 0;
    root.userData.detailFor = obj.object_id;
    root.userData.landmark = isPalace || house || placed ? undefined : m.id;
    root.userData.palace = isPalace || undefined;
    root.userData.house = house ? house.id : undefined;
    root.userData.placed = placed ? true : undefined;
    isPalace && (ext.palaceGroup.children[0].visible = false);
    !isPalace && !house && !placed && ext.landmarks.children.filter((c) => c.userData.landmark === m.id).forEach((c) => (c.visible = false));
    ext.scene.add(root);
    return true;
  });
};

export const pickTarget = (ext, camera, ndc) => {
  const ray = new THREE.Raycaster(camera.position.clone(), camera.getWorldDirection(new THREE.Vector3()), 0.5, 600);
  ndc && ray.setFromCamera(new THREE.Vector2(ndc.x, ndc.y), camera);
  ray.far = 600;
  const hits = ray.intersectObjects(ext.pickables(), true);
  const hit = hits.find((h) => h.object.visible !== false);
  if (!hit) return null;
  const chain = [];
  for (let o = hit.object; o; o = o.parent) chain.push(o);
  const owner = chain.find((o) => o.userData.detailFor || o.userData.landmark || o.userData.palace || o.userData.treeIndices || o.userData.houseTile);
  if (!owner) return null;
  if (owner.userData.houseTile || owner.userData.house) {
    const p = hit.point;
    const h = owner.userData.house ? ext.data.houses.find((x) => x.id === owner.userData.house) : ext.data.houses.reduce((best, x) => (!best || Math.hypot(x.x - p.x, x.z - p.z) < Math.hypot(best.x - p.x, best.z - p.z) ? x : best), null);
    return h ? { type: 'house', id: h.id, name: `בית (${h.floors} קומות)`, distance: hit.distance } : null;
  }
  if (owner.userData.placed) return { type: 'placed', id: owner.userData.detailFor, name: 'אובייקט מהספרייה', distance: hit.distance };
  if (owner.userData.treeIndices) return { type: 'tree', id: String(owner.userData.treeIndices[hit.instanceId]), name: 'עץ', distance: hit.distance };
  if (owner.userData.detailFor && owner.userData.treeIndex !== undefined) return { type: 'tree', id: String(owner.userData.treeIndex), name: 'עץ (מפורט)', distance: hit.distance };
  if (owner.userData.palace) return { type: 'palace', id: 'palace', name: ext.data.palace.name || 'הארמון', distance: hit.distance };
  const id = owner.userData.landmark || owner.userData.detailFor;
  const m = (ext.data.landmarks || []).find((l) => l.id === id);
  return m ? { type: 'landmark', id: m.id, name: m.name, kind: m.kind, distance: hit.distance } : null;
};
