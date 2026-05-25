import * as THREE from "three";
import { STLLoader } from "/static/vendor/STLLoader.js";

const JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"];
const INITIAL_ORBIT_X_OFFSET_RAD = THREE.MathUtils.degToRad(-60);
const views = new Map();
let robotAsset = null;
let lastRobotState = null;
let lastStatePoll = 0;
const X_AXIS = new THREE.Vector3(1, 0, 0);

function parseVector(raw) {
  const values = String(raw ?? "0 0 0").trim().split(/\s+/).map(Number);
  return new THREE.Vector3(values[0] || 0, values[1] || 0, values[2] || 0);
}

function parseRpy(raw) {
  const values = String(raw ?? "0 0 0").trim().split(/\s+/).map(Number);
  const roll = values[0] || 0;
  const pitch = values[1] || 0;
  const yaw = values[2] || 0;
  const matrix = new THREE.Matrix4()
    .makeRotationZ(yaw)
    .multiply(new THREE.Matrix4().makeRotationY(pitch))
    .multiply(new THREE.Matrix4().makeRotationX(roll));
  return new THREE.Quaternion().setFromRotationMatrix(matrix);
}

function parseUrdf(text) {
  const xml = new DOMParser().parseFromString(text, "application/xml");
  const materials = {};
  for (const material of xml.querySelectorAll("robot > material")) {
    const name = material.getAttribute("name") ?? "";
    const rgba = material.querySelector("color")?.getAttribute("rgba");
    if (!name || !rgba) continue;
    const v = rgba.split(/\s+/).map(Number);
    materials[name] = { color: new THREE.Color(v[0], v[1], v[2]) };
  }

  const links = {};
  for (const link of xml.querySelectorAll("link")) {
    const name = link.getAttribute("name") ?? "";
    links[name] = {
      name,
      visuals: Array.from(link.querySelectorAll(":scope > visual")).map((visual) => ({
        xyz: parseVector(visual.querySelector("origin")?.getAttribute("xyz")),
        rpy: parseRpy(visual.querySelector("origin")?.getAttribute("rpy")),
        mesh: visual.querySelector("mesh")?.getAttribute("filename") ?? "",
        material: visual.querySelector("material")?.getAttribute("name") ?? "3d_printed"
      }))
    };
  }

  const joints = Array.from(xml.querySelectorAll("joint")).map((joint) => ({
    name: joint.getAttribute("name") ?? "",
    type: joint.getAttribute("type") ?? "",
    parent: joint.querySelector("parent")?.getAttribute("link") ?? "",
    child: joint.querySelector("child")?.getAttribute("link") ?? "",
    xyz: parseVector(joint.querySelector("origin")?.getAttribute("xyz")),
    rpy: parseRpy(joint.querySelector("origin")?.getAttribute("rpy")),
    axis: parseVector(joint.querySelector("axis")?.getAttribute("xyz") ?? "0 0 1").normalize()
  }));
  return { links, joints, materials };
}

function materialFor(name, materials) {
  const source = materials[name] ?? materials["3d_printed"];
  return new THREE.MeshStandardMaterial({
    color: source?.color ?? new THREE.Color(0xffd21f),
    roughness: 0.72,
    metalness: 0.05
  });
}

async function loadStl(loader, url) {
  return new Promise((resolve, reject) => loader.load(url, resolve, undefined, reject));
}

async function loadRobotAsset() {
  if (robotAsset) return robotAsset;
  const response = await fetch("/static/robot-assets/so101/so101_new_calib.urdf");
  if (!response.ok) throw new Error(`SO-101 URDF load failed: ${response.status}`);
  const urdf = parseUrdf(await response.text());
  const loader = new STLLoader();
  const geometryCache = new Map();
  for (const link of Object.values(urdf.links)) {
    for (const visual of link.visuals) {
      if (!visual.mesh.endsWith(".stl")) continue;
      const url = `/static/robot-assets/so101/${visual.mesh}`;
      if (geometryCache.has(url)) continue;
      const geometry = await loadStl(loader, url);
      geometry.computeVertexNormals();
      geometryCache.set(url, geometry);
    }
  }
  robotAsset = { urdf, geometryCache };
  return robotAsset;
}

function buildRobotModel(asset) {
  const root = new THREE.Group();
  root.scale.setScalar(3.2);
  root.rotation.x = 0;
  root.rotation.z = Math.PI;
  const linkGroups = {};
  const jointMotion = {};

  for (const linkName of Object.keys(asset.urdf.links)) {
    const group = new THREE.Group();
    group.name = linkName;
    linkGroups[linkName] = group;
  }

  for (const link of Object.values(asset.urdf.links)) {
    const group = linkGroups[link.name];
    for (const visual of link.visuals) {
      if (!visual.mesh.endsWith(".stl")) continue;
      const geometry = asset.geometryCache.get(`/static/robot-assets/so101/${visual.mesh}`);
      if (!geometry) continue;
      const mesh = new THREE.Mesh(geometry, materialFor(visual.material, asset.urdf.materials));
      mesh.position.copy(visual.xyz);
      mesh.quaternion.copy(visual.rpy);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
  }

  const childLinks = new Set(asset.urdf.joints.map((joint) => joint.child));
  const rootLink = Object.keys(asset.urdf.links).find((name) => !childLinks.has(name)) ?? "base_link";
  root.add(linkGroups[rootLink]);

  for (const joint of asset.urdf.joints) {
    const parent = linkGroups[joint.parent];
    const child = linkGroups[joint.child];
    if (!parent || !child) continue;
    const origin = new THREE.Group();
    origin.position.copy(joint.xyz);
    origin.quaternion.copy(joint.rpy);
    const motion = new THREE.Group();
    origin.add(motion);
    motion.add(child);
    parent.add(origin);
    jointMotion[joint.name] = { motion, axis: joint.axis, type: joint.type };
  }

  root.userData.jointMotion = jointMotion;
  return root;
}

function currentJointMap() {
  const pose = lastRobotState?.believed_joint_pose;
  const joints = Array.isArray(pose?.joints) ? pose.joints : [0, -25, 35, -10, 0, 0];
  const names = Array.isArray(pose?.joint_names) ? pose.joint_names : JOINT_NAMES;
  return Object.fromEntries(names.map((name, index) => [name, Number(joints[index]) || 0]));
}

function setRobotPose(robot) {
  const positions = currentJointMap();
  const motions = robot.userData.jointMotion ?? {};
  for (const [name, entry] of Object.entries(motions)) {
    entry.motion.quaternion.identity();
    if (entry.type === "fixed") continue;
    const degrees = positions[name] ?? 0;
    const radians = THREE.MathUtils.degToRad(degrees);
    entry.motion.quaternion.setFromAxisAngle(entry.axis, radians);
  }
}

function makeInitialOrbit() {
  const target = new THREE.Vector3(0.0, 0.0, 0.18);
  const offset = new THREE.Vector3(0.9, -1.35, 0.85).sub(target);
  offset.applyAxisAngle(X_AXIS, INITIAL_ORBIT_X_OFFSET_RAD);
  const radius = offset.length();
  const orientation = new THREE.Quaternion();
  new THREE.Matrix4().lookAt(offset, new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 1, 0)).invert().decompose(
    new THREE.Vector3(),
    orientation,
    new THREE.Vector3()
  );
  return {
    target,
    radius,
    orientation,
    dragging: false,
    lastX: 0,
    lastY: 0
  };
}

function updateOrbitCamera(camera, orbit) {
  const offset = new THREE.Vector3(0, 0, orbit.radius).applyQuaternion(orbit.orientation);
  camera.position.copy(orbit.target).add(offset);
  camera.quaternion.copy(orbit.orientation);
}

function installOrbitControls(element, state, update) {
  element.addEventListener("pointerdown", (event) => {
    state.dragging = true;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    element.setPointerCapture(event.pointerId);
  });
  element.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    const dx = event.clientX - state.lastX;
    const dy = event.clientY - state.lastY;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    const screenUp = new THREE.Vector3(0, 1, 0).applyQuaternion(state.orientation);
    const screenRight = new THREE.Vector3(1, 0, 0).applyQuaternion(state.orientation);
    const yaw = new THREE.Quaternion().setFromAxisAngle(screenUp, -dx * 0.008);
    const pitch = new THREE.Quaternion().setFromAxisAngle(screenRight, -dy * 0.008);
    state.orientation.premultiply(yaw).premultiply(pitch).normalize();
    update();
  });
  element.addEventListener("pointerup", (event) => {
    state.dragging = false;
    element.releasePointerCapture(event.pointerId);
  });
  element.addEventListener("pointercancel", () => {
    state.dragging = false;
  });
}

function createScene(container) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x030405);
  scene.fog = new THREE.Fog(0x030405, 4.47, 14.5);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
  const orbit = makeInitialOrbit();
  updateOrbitCamera(camera, orbit);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  container.append(renderer.domElement);
  installOrbitControls(renderer.domElement, orbit, () => updateOrbitCamera(camera, orbit));

  scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x1c2430, 1.8));
  const key = new THREE.DirectionalLight(0xffffff, 1.75);
  key.position.set(1.25, -1.1, 1.7);
  key.castShadow = true;
  scene.add(key);

  const fill = new THREE.DirectionalLight(0x79c7ff, 0.65);
  fill.position.set(-1.2, 1.0, 0.8);
  scene.add(fill);

  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(1.4, 1.0, 0.018),
    new THREE.MeshStandardMaterial({ color: 0x171b22, roughness: 0.9, metalness: 0.05 })
  );
  floor.position.set(0, 0, -0.018);
  floor.receiveShadow = true;
  scene.add(floor);

  const grid = new THREE.GridHelper(1.4, 14, 0x3b4658, 0x242a34);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -0.006;
  scene.add(grid);

  const target = new THREE.Mesh(
    new THREE.SphereGeometry(0.018, 24, 12),
    new THREE.MeshStandardMaterial({ color: 0x6ee7b7, emissive: 0x123c2f, roughness: 0.35 })
  );
  scene.add(target);

  const targetStem = new THREE.Mesh(
    new THREE.CylinderGeometry(0.003, 0.003, 0.18, 10),
    new THREE.MeshBasicMaterial({ color: 0x6ee7b7, transparent: true, opacity: 0.55 })
  );
  targetStem.rotation.x = Math.PI / 2;
  scene.add(targetStem);

  return { scene, camera, orbit, renderer, target, targetStem };
}

function resizeView(view) {
  const rect = view.container.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  const size = view.renderer.getSize(new THREE.Vector2());
  if (size.x === width && size.y === height) return;
  view.renderer.setSize(width, height, false);
  view.camera.aspect = width / height;
  view.camera.updateProjectionMatrix();
}

function updateWorldPoseMarker(view) {
  const world = lastRobotState?.current_world_pose;
  if (!world) return;
  const x = Number(world.x) || 0;
  const y = Number(world.y) || 0;
  const z = Number(world.z) || 0;
  view.target.position.set(x, y, z);
  view.targetStem.position.set(x, y, Math.max(0.02, z / 2));
  view.targetStem.scale.y = Math.max(0.05, z);
}

async function createView(container) {
  if (views.has(container)) return;
  const asset = await loadRobotAsset();
  const { scene, camera, orbit, renderer, target, targetStem } = createScene(container);
  const model = buildRobotModel(asset);
  scene.add(model);
  const view = { container, scene, camera, orbit, renderer, model, target, targetStem };
  views.set(container, view);
  resizeView(view);
  setRobotPose(model);
}

async function syncHosts() {
  const hosts = new Set(document.querySelectorAll("[data-virtual-camera='so101']"));
  for (const [host, view] of views) {
    if (hosts.has(host)) continue;
    view.renderer.dispose();
    host.replaceChildren();
    views.delete(host);
  }
  for (const host of hosts) {
    try {
      await createView(host);
    } catch (error) {
      host.textContent = error instanceof Error ? error.message : String(error);
    }
  }
}

async function pollRobotState(now) {
  if (now - lastStatePoll < 350) return;
  lastStatePoll = now;
  try {
    const response = await fetch("/api/robot/state", { cache: "no-store" });
    if (response.ok) lastRobotState = await response.json();
  } catch {
    // Keep rendering the last believed pose if the state endpoint is briefly unavailable.
  }
}

async function animate(now) {
  await pollRobotState(now || performance.now());
  await syncHosts();
  for (const view of views.values()) {
    resizeView(view);
    setRobotPose(view.model);
    updateWorldPoseMarker(view);
    updateOrbitCamera(view.camera, view.orbit);
    view.renderer.render(view.scene, view.camera);
  }
  requestAnimationFrame(animate);
}

requestAnimationFrame(animate);
