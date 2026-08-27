// Exposes read-only internal state for the Playwright E2E smoke suite to
// query directly -- mesh counts and positions in the Three.js scene aren't
// otherwise observable from outside the React tree without fragile
// pixel-based inspection (the slow, error-prone way this got verified by
// hand earlier in this project). Never mutates app state; test-only reads.

import type * as THREE from "three";

export interface LineageTestHooks {
  scene: THREE.Scene | null;
  wsTickCount: number;
}

declare global {
  interface Window {
    __lineageTest?: LineageTestHooks;
  }
}

export function initTestHooks(): void {
  window.__lineageTest ??= { scene: null, wsTickCount: 0 };
}

export function setTestScene(scene: THREE.Scene): void {
  if (window.__lineageTest) window.__lineageTest.scene = scene;
}

export function recordTick(): void {
  if (window.__lineageTest) window.__lineageTest.wsTickCount += 1;
}
