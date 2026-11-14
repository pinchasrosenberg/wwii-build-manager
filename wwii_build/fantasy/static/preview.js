import * as THREE from 'three';

import { buildRoomGroup } from './interior.js';

const holder = {};

const getRenderer = () => {
  holder.renderer = holder.renderer || new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  holder.renderer.setSize(400, 250, false);
  holder.renderer.outputColorSpace = THREE.SRGBColorSpace;
  return holder.renderer;
};

export const renderRoomImage = (target, room, design) => {
  const renderer = getRenderer();
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#1b1713');
  scene.add(buildRoomGroup(room, design, true));
  scene.add(new THREE.AmbientLight('#ffffff', 0.6));
  const camera = new THREE.PerspectiveCamera(72, 400 / 250, 0.1, 120);
  camera.position.set(room.w * 0.28, 2.2, room.d / 2 - 0.7);
  camera.lookAt(-room.w * 0.08, 1.4, -room.d * 0.25);
  renderer.render(scene, camera);
  const ctx = target.getContext('2d');
  ctx.drawImage(renderer.domElement, 0, 0, target.width, target.height);
  scene.traverse((o) => o.geometry && o.geometry.dispose());
  return target.toDataURL('image/png');
};
