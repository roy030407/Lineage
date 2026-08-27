// Exposes read-only internal state for the Playwright E2E smoke suite to
// query directly -- mesh counts and positions in the Three.js scene aren't
// otherwise observable from outside the React tree without fragile
// pixel-based inspection (the slow, error-prone way this got verified by
// hand earlier in this project). Never mutates app state; test-only reads.
//
// camera/renderer are exposed (not just scene) so a test can compute the
// exact screen-space projection of a moving instance and click it precisely
// -- this is what the car-click raycasting regression test needs: it must
// click a real, currently-moving car while replay plays, and eyeballing a
// pixel position (as earlier manual verification did) isn't reproducible
// or precise enough to pin down a bug that depends on exact ray geometry.

import type * as THREE from "three";

export interface LineageTestHooks {
  scene: THREE.Scene | null;
  wsTickCount: number;
  camera?: THREE.Camera;
  renderer?: THREE.WebGLRenderer;
}

declare global {
  interface Window {
    __lineageTest?: LineageTestHooks;
  }
}

export function initTestHooks(): void {
  window.__lineageTest ??= { scene: null, wsTickCount: 0 };
}

export function setTestScene(scene: THREE.Scene, camera: THREE.Camera, renderer: THREE.WebGLRenderer): void {
  if (window.__lineageTest) {
    window.__lineageTest.scene = scene;
    window.__lineageTest.camera = camera;
    window.__lineageTest.renderer = renderer;
  }
}

export function recordTick(): void {
  if (window.__lineageTest) window.__lineageTest.wsTickCount += 1;
}
