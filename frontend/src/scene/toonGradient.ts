// A tiny, hard-edged gradient map for THREE.MeshToonMaterial -- generated
// procedurally (no image asset), NearestFilter so the light/dark bands stay
// crisp bands, not a blurred low-res copy of the smooth PBR shading this
// replaces (which would defeat the point of switching to toon shading at
// all). One shared singleton texture: every toon-shaded mesh in the scene
// reads from the same instance, same as sharing any other texture/material
// resource in three.js.

import * as THREE from "three";

const STEPS = 4;

let cached: THREE.DataTexture | null = null;

export function toonGradientMap(): THREE.DataTexture {
  if (cached) return cached;

  const data = new Uint8Array(STEPS * 4);
  for (let i = 0; i < STEPS; i++) {
    const value = Math.round((255 * (i + 1)) / STEPS);
    data[i * 4] = value;
    data[i * 4 + 1] = value;
    data[i * 4 + 2] = value;
    data[i * 4 + 3] = 255;
  }

  const texture = new THREE.DataTexture(data, STEPS, 1, THREE.RGBAFormat);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.needsUpdate = true;
  cached = texture;
  return texture;
}
