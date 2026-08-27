// react-three-fiber canvas root: camera, lights, and the Line3D scene graph.

import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import type { ElementRef } from "react";
import { useEffect, useRef } from "react";
import * as THREE from "three";

import { useLineageStore } from "../state/store";
import { setTestScene } from "../testHooks";
import { Line3D } from "./Line3D";

const FOUNDRY = "#22231f";

/** Frames the camera to the line's actual extent once, when the LineSpec
 * first loads -- a line 8 stations long and one 42 stations long need very
 * different default distances; nothing here is a fixed guess. */
function InitialFraming({ controlsRef }: { controlsRef: React.RefObject<ElementRef<typeof OrbitControls>> }) {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const { camera } = useThree();
  const framed = useRef(false);

  useEffect(() => {
    if (!lineSpec || framed.current || !controlsRef.current) return;
    const coords = lineSpec.layout.coordinates;
    if (coords.length === 0) return;

    const xs = coords.map((c) => c.x_m);
    const zs = coords.map((c) => c.y_m);
    const minX = Math.min(...xs);
    const fullExtent = Math.max(Math.max(...xs) - minX, Math.max(...zs) - Math.min(...zs), 10);

    // Fitting the whole extent of a very long line (dozens of stations,
    // hundreds of meters) would shrink individual stations to sub-pixel
    // dots -- defeats "read instantly". Cap the default framing to a
    // legible portion near the start of the line instead; OrbitControls
    // reaches the rest.
    const extent = Math.min(fullExtent, 120);
    const centerX = minX + extent / 2;
    const centerZ = (Math.min(...zs) + Math.max(...zs)) / 2;

    // The line's extent runs mostly along the horizontal screen axis, so fit
    // against the *horizontal* FOV, not the vertical one Three.js reports --
    // an aspect ratio wider than 1 (the common case) makes horizontal FOV
    // larger than vertical, and using vertical FOV directly overshoots the
    // distance needed, which is exactly the bug that made the camera frame
    // the whole 328m line instead of the intended 120m cap.
    const perspective = camera as THREE.PerspectiveCamera;
    const verticalFovRad = (perspective.fov * Math.PI) / 180;
    const horizontalFovRad = 2 * Math.atan(Math.tan(verticalFovRad / 2) * perspective.aspect);
    const fitDistance = (extent / (2 * Math.tan(horizontalFovRad / 2))) * 1.4;

    camera.position.set(centerX, fitDistance * 0.6, centerZ + fitDistance);
    controlsRef.current.target.set(centerX, 0, centerZ);
    controlsRef.current.update();
    framed.current = true;
  }, [lineSpec, camera, controlsRef]);

  return null;
}

function CameraRig({ controlsRef }: { controlsRef: React.RefObject<ElementRef<typeof OrbitControls>> }) {
  const followedCarId = useLineageStore((s) => s.followedCarId);
  const lineState = useLineageStore((s) => s.lineState);
  const lineSpec = useLineageStore((s) => s.lineSpec);

  useFrame((_state, delta) => {
    if (!followedCarId || !lineState || !lineSpec || !controlsRef.current) return;
    const station = lineState.stations.find((s) => s.car_id === followedCarId);
    if (!station) return;
    const coord = lineSpec.layout.coordinates.find((c) => c.station_id === station.station_id);
    if (!coord) return;

    const target = new THREE.Vector3(coord.x_m, 0, coord.y_m);
    const controls = controlsRef.current;
    controls.target.lerp(target, Math.min(1, delta * 3));
    controls.update();
  });

  return null;
}

export function Scene() {
  const controlsRef = useRef<ElementRef<typeof OrbitControls>>(null);

  return (
    <Canvas
      shadows
      camera={{ position: [40, 60, 120], fov: 45, near: 0.1, far: 5000 }}
      style={{ background: FOUNDRY }}
      onCreated={(state) => setTestScene(state.scene)}
    >
      <ambientLight intensity={0.6} />
      <directionalLight
        position={[80, 120, 40]}
        intensity={1.1}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <Line3D />
      <OrbitControls ref={controlsRef} makeDefault minDistance={5} maxDistance={2000} maxPolarAngle={Math.PI / 2.05} />
      <InitialFraming controlsRef={controlsRef} />
      <CameraRig controlsRef={controlsRef} />
    </Canvas>
  );
}
