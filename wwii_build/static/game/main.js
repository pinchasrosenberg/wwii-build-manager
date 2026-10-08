import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRButton } from 'three/addons/webxr/VRButton.js';

const canvas = document.getElementById('viewport');
const status = document.getElementById('status');
const error = document.getElementById('error');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({canvas, antialias: true, powerPreference: 'high-performance'});
} catch (cause) {
  error.textContent = 'לא ניתן להציג תלת־ממד בדפדפן הזה: ' + cause.message;
  error.style.display = 'block';
  throw cause;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.35;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.xr.enabled = true;

const scene = new THREE.Scene();
scene.background = new THREE.Color('#0b2035');
scene.fog = new THREE.Fog('#0b2035', 18, 42);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
const hemi = new THREE.HemisphereLight(0xbadfff, 0x253026, 2.7);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffdf9c, 3.7);
sun.position.set(-4, 9, 5);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -12; sun.shadow.camera.right = 12;
sun.shadow.camera.top = 12; sun.shadow.camera.bottom = -12;
scene.add(sun);
const rim = new THREE.DirectionalLight(0x8ac5ff, 2.1);
rim.position.set(4, 3, -5);
scene.add(rim);

const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200),
  new THREE.MeshStandardMaterial({color: 0x34483b, roughness: 1}));
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);
const pad = new THREE.Mesh(new THREE.CylinderGeometry(4.2, 4.4, 0.16, 64),
  new THREE.MeshStandardMaterial({color: 0x1e3546, roughness: 0.86, metalness: 0.12}));
pad.position.y = 0.08; pad.receiveShadow = true; scene.add(pad);
const ring = new THREE.Mesh(new THREE.TorusGeometry(4.1, 0.035, 8, 64),
  new THREE.MeshBasicMaterial({color: 0xd0a92f}));
ring.rotation.x = Math.PI / 2; ring.position.y = 0.18; scene.add(ring);

const paint = new THREE.MeshStandardMaterial({color: 0x677d5d, roughness: 0.83, metalness: 0.12});
const darkPaint = new THREE.MeshStandardMaterial({color: 0x435747, roughness: 0.9, metalness: 0.08});
const metal = new THREE.MeshStandardMaterial({color: 0x727f76, roughness: 0.55, metalness: 0.45});
const rubber = new THREE.MeshStandardMaterial({color: 0x1a2427, roughness: 0.98});
const glass = new THREE.MeshStandardMaterial({color: 0xa7c4c9, roughness: 0.22, metalness: 0.4});
const tank = new THREE.Group(); scene.add(tank);
const hull = new THREE.Group(); tank.add(hull);
const leftTrack = new THREE.Group(); tank.add(leftTrack);
const rightTrack = new THREE.Group(); tank.add(rightTrack);
const turret = new THREE.Group(); tank.add(turret);

function box(parent, w, h, d, x, y, z, material, angle = 0) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z); mesh.rotation.x = angle;
  mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
}
box(hull, 2.55, 0.7, 4.85, 0, 0.95, 0, paint);
box(hull, 2.26, 0.48, 3.55, 0, 1.52, -0.18, paint);
box(hull, 2.3, 0.32, 1.1, 0, 1.36, 1.72, darkPaint, -0.27);
box(hull, 2.28, 0.1, 2.0, 0, 1.79, -0.65, darkPaint);
for (const side of [-1, 1]) {
  const group = side < 0 ? leftTrack : rightTrack;
  box(group, 0.57, 0.78, 5.13, side * 1.49, 0.66, 0, rubber);
  box(hull, 0.52, 0.1, 4.98, side * 1.46, 1.22, 0, darkPaint);
  for (const z of [-1.92, -0.96, 0, 0.96, 1.92]) {
    const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.17, 20), darkPaint);
    wheel.rotation.z = Math.PI / 2; wheel.position.set(side * 1.84, 0.58, z);
    wheel.castShadow = true; group.add(wheel);
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.19, 16), metal);
    hub.rotation.z = Math.PI / 2; hub.position.set(side * 1.96, 0.58, z); group.add(hub);
  }
  for (let z = -2.35; z < 2.5; z += 0.34) {
    box(group, 0.65, 0.055, 0.12, side * 1.49, 1.08, z, metal);
    box(group, 0.65, 0.055, 0.12, side * 1.49, 0.23, z, metal);
  }
  box(hull, 0.12, 0.15, 0.42, side * 1.18, 1.42, 2.18, metal);
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 10), glass);
  lamp.position.set(side * 1.0, 1.49, 2.43); hull.add(lamp);
}

const turretBase = new THREE.Mesh(new THREE.CylinderGeometry(1.12, 1.19, 0.62, 10), paint);
turretBase.position.y = 2.02; turretBase.castShadow = true; turret.add(turretBase);
box(turret, 1.65, 0.32, 1.38, 0, 2.35, -0.15, darkPaint);
const mantlet = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.36, 0.37, 16), metal);
mantlet.rotation.x = Math.PI / 2; mantlet.position.set(0, 2.07, 1.11); turret.add(mantlet);
const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.105, 0.15, 2.7, 16), metal);
barrel.rotation.x = Math.PI / 2; barrel.position.set(0, 2.07, 2.56); barrel.castShadow = true; turret.add(barrel);
const muzzle = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.16, 0.31, 16), darkPaint);
muzzle.rotation.x = Math.PI / 2; muzzle.position.set(0, 2.07, 4.03); turret.add(muzzle);
const hatch = new THREE.Mesh(new THREE.CylinderGeometry(0.37, 0.37, 0.09, 24), metal);
hatch.position.set(0.38, 2.55, -0.28); hatch.castShadow = true; turret.add(hatch);
const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.018, 1.4, 8), metal);
antenna.position.set(-0.7, 3.08, -0.5); turret.add(antenna);

let yaw = 0.67, pitch = 0.37, radius = 9.3, dragging = false, lastX = 0, lastY = 0, exploded = false;
function positionCamera() {
  camera.position.set(Math.sin(yaw) * Math.cos(pitch) * radius,
    1.1 + Math.sin(pitch) * radius, Math.cos(yaw) * Math.cos(pitch) * radius);
  camera.lookAt(0, 1.18, 0);
}
positionCamera();
canvas.addEventListener('pointerdown', e => {dragging = true; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointerup', () => {dragging = false;});
canvas.addEventListener('pointermove', e => {if (!dragging) return; yaw += (e.clientX - lastX) * 0.008;
  pitch = Math.max(-0.03, Math.min(1.27, pitch + (e.clientY - lastY) * 0.006));
  lastX = e.clientX; lastY = e.clientY; positionCamera();});
canvas.addEventListener('wheel', e => {e.preventDefault(); radius = Math.max(5.5, Math.min(16, radius + e.deltaY * 0.008)); positionCamera();}, {passive:false});
document.getElementById('turret').addEventListener('input', e => {turret.rotation.y = Number(e.target.value) * Math.PI / 180;});
document.getElementById('reset').addEventListener('click', () => {yaw = 0.67; pitch = 0.37; radius = 9.3;
  turret.rotation.y = 0; document.getElementById('turret').value = 0; positionCamera();});
document.getElementById('explode').addEventListener('click', e => {exploded = !exploded;
  leftTrack.position.x = exploded ? -0.75 : 0; rightTrack.position.x = exploded ? 0.75 : 0;
  turret.position.y = exploded ? 0.95 : 0; e.target.textContent = exploded ? 'הרכב את החלקים' : 'הצג חלקים בנפרד';});

const params = new URLSearchParams(location.search);
const artifact = params.get('artifact');
const task = params.get('task');
const path = params.get('path');
const modelUrl = artifact && /^\d+$/.test(artifact) ? '/artifact/' + artifact :
  task && path ? '/wtfile?task=' + encodeURIComponent(task) + '&path=' + encodeURIComponent(path) + '&raw=1' : null;
if (modelUrl) {
  tank.visible = false;
  document.getElementById('basic-controls').hidden = true;
  document.getElementById('title').textContent = 'טוען מודל שנוצר במשימה';
  document.getElementById('description').textContent = 'כאן יוצג קובץ המודל שיצרה המשימה עצמה.';
  document.getElementById('parts').textContent = 'לפי קובץ התוצר';
  document.getElementById('source').textContent = artifact ? 'קובץ תוצר #' + artifact : path;
  status.textContent = 'טוען קובץ תוצר';
  const loader = new GLTFLoader();
  loader.load(modelUrl, gltf => {
    const model = gltf.scene; model.traverse(item => {if (item.isMesh) item.castShadow = true;});
    const bounds = new THREE.Box3().setFromObject(model);
    const size = bounds.getSize(new THREE.Vector3());
    if (Math.max(size.x, size.y, size.z) > 0) model.scale.setScalar(5 / Math.max(size.x, size.y, size.z));
    const centered = new THREE.Box3().setFromObject(model);
    model.position.y -= centered.min.y;
    scene.add(model);
    document.getElementById('title').textContent = 'מודל תלת־ממד שנוצר במשימה';
    document.getElementById('description').textContent = 'זהו קובץ המודל שהעובד יצר, מוצג ישירות בתלת־ממד.';
    status.textContent = 'מודל משימה נטען';
  }, undefined, () => {
    status.textContent = 'טעינת המודל נכשלה';
    error.textContent = 'לא ניתן לטעון את קובץ המודל שיצרה המשימה.';
    error.style.display = 'block';
  });
} else {
  status.textContent = 'רכיב בסיסי זמין';
}

if (navigator.xr && window.top === window) {
  navigator.xr.isSessionSupported('immersive-vr').then(supported => {
    if (supported) document.body.appendChild(VRButton.createButton(renderer));
  }).catch(() => {});
}
function resize() {
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * renderer.getPixelRatio()) || canvas.height !== Math.round(height * renderer.getPixelRatio())) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height; camera.updateProjectionMatrix();
  }
}
renderer.setAnimationLoop(() => {resize(); renderer.render(scene, camera);});
