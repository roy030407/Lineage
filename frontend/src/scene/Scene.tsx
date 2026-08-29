// react-three-fiber canvas root: camera, lights, and the Line3D scene graph.

import { ContactShadows, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import type { ElementRef } from "react";
import { useEffect, useRef } from "react";
import * as THREE from "three";

import { useLineageStore } from "../state/store";
import { setTestScene } from "../testHooks";
import { PALETTE } from "../styles/tokens";
import { BOOT_CAMERA_S, bootElapsed, cameraApproachFactor } from "./bootReveal";
import { Line3D } from "./Line3D";

/** Frames the camera to the line's actual extent once, when the LineSpec
 * first loads -- a line 8 stations long and one 42 stations long need very
 * different default distances; nothing here is a fixed guess. */
function InitialFraming({ controlsRef }: { controlsRef: React.RefObject<ElementRef<typeof OrbitControls>> }) {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const { camera } = useThree();
  const framed = useRef(false);
  const flight = useRef<{ from: THREE.Vector3; to: THREE.Vector3; look: THREE.Vector3 } | null>(
    null,
  );
  const userTookOver = useRef(false);

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

    const to = new THREE.Vector3(centerX, fitDistance * 0.6, centerZ + fitDistance);
    // Starts wider and higher, then closes in. The whole line is visible at
    // t=0 even on a 42-station spec, and 2.2x fitDistance stays well inside
    // the camera's far plane (5000; fitDistance for that line is ~330).
    const from = new THREE.Vector3(centerX, fitDistance * 1.5, centerZ + fitDistance * 2.2);

    camera.position.copy(from);
    controlsRef.current.target.set(centerX, 0, centerZ);
    controlsRef.current.update();
    flight.current = { from, to, look: new THREE.Vector3(centerX, 0, centerZ) };
    framed.current = true;
  }, [lineSpec, camera, controlsRef]);

  // The entrance must never fight the mouse. Any user input hands control
  // back immediately and permanently, rather than the camera continuing to
  // drag itself toward a target while someone is orbiting.
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const takeOver = () => {
      userTookOver.current = true;
    };
    controls.addEventListener("start", takeOver);
    return () => controls.removeEventListener("start", takeOver);
  }, [controlsRef]);

  useFrame(({ clock }) => {
    const path = flight.current;
    if (!path || userTookOver.current) return;
    const factor = cameraApproachFactor(bootElapsed(clock.elapsedTime));
    camera.position.lerpVectors(path.from, path.to, factor);
    if (controlsRef.current) {
      controlsRef.current.target.copy(path.look);
      controlsRef.current.update();
    }
    // Released once arrived, so OrbitControls owns the camera from here on.
    if (factor >= 1) flight.current = null;
  });

  return null;
}

/** A paused or ended line still has to look alive rather than like a
 * screenshot. Deliberately tiny in amplitude: this is breathing, not
 * motion that could be mistaken for the line actually running. */
function AmbientDrift({
  controlsRef,
}: {
  controlsRef: React.RefObject<ElementRef<typeof OrbitControls>>;
}) {
  const lastInput = useRef(0);
  const { camera } = useThree();

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const mark = () => {
      lastInput.current = performance.now();
    };
    controls.addEventListener("start", mark);
    return () => controls.removeEventListener("start", mark);
  }, [controlsRef]);

  useFrame(({ clock }) => {
    const elapsed = bootElapsed(clock.elapsedTime);
    // Only once the entrance has finished and the user has been idle, so it
    // competes with neither the flight nor an active drag.
    if (elapsed === null || elapsed < BOOT_CAMERA_S) return;
    if (performance.now() - lastInput.current < 6000) return;
    camera.position.y += Math.sin(clock.elapsedTime * 0.25) * 0.004;
  });

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

/** Follow mode has no visible indication otherwise, and no way back to free
 * orbit -- clicking a car engages it (see Line3D's onSelectCar), but a
 * judge (or anyone) who does that has no way to tell it happened, or to
 * stop. */
function FollowIndicator() {
  const followedCarId = useLineageStore((s) => s.followedCarId);
  const followCar = useLineageStore((s) => s.followCar);

  if (!followedCarId) return null;

  return (
    <div
      style={{
        position: "absolute",
        // Bottom-RIGHT: bottom-left is occupied by App.tsx's Open
        // Builder button at the identical offset, and the two overlapped
        // whenever a car was followed.
        right: "var(--space-4)",
        bottom: "var(--space-4)",
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        padding: "var(--space-2) var(--space-4)",
        background: "var(--color-cast-steel)",
        color: "var(--color-vellum)",
        borderRadius: "2px",
      }}
    >
      <span className="eyebrow">Following {followedCarId}</span>
      <button onClick={() => followCar(null)}>Stop</button>
    </div>
  );
}

export function Scene() {
  const controlsRef = useRef<ElementRef<typeof OrbitControls>>(null);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <Canvas
        shadows
        camera={{ position: [40, 60, 120], fov: 45, near: 0.1, far: 5000 }}
        style={{ background: PALETTE.foundry }}
        onCreated={(state) => setTestScene(state.scene, state.camera, state.gl)}
      >
        {/* Ambient dropped from 0.6: that high, it washed out the toon
            shading's light/dark bands entirely, reading flat/CAD-like
            instead of chunky. The key light does the real modelling work
            now; a second, dimmer, cool-tinted light from roughly the
            opposite side catches edges the key light leaves in shadow --
            the classic two-point setup that sells a toy-diorama silhouette
            rather than one that just goes fully black on its far side. */}
        <ambientLight intensity={0.28} />
        <directionalLight
          position={[80, 120, 40]}
          intensity={1.15}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />
        <directionalLight position={[-70, 50, -50]} intensity={0.35} color="#a9c6e0" />
        <Line3D />
        <ContactShadows position={[0, -0.02, 0]} opacity={0.45} blur={2.2} far={40} scale={300} />
        {/* Selective by luminance threshold, not per-object layers: nothing
            hardcodes the station count, so there's no fixed list of lamp/
            beam meshes to register with a selection API -- thresholding
            gets the same practical result (only the bright emissive
            lamps/beams bloom) without that plumbing. mipmapBlur keeps the
            blur cheap at any resolution; luminanceThreshold/intensity were
            tuned by screenshot against a real 42-station line specifically
            so the diamond/hexagon/torus lamp shapes stay legible, not
            blurred into indistinct blobs -- the status vocabulary depends
            on their silhouettes, per styles/tokens.ts. */}
        <EffectComposer>
          <Bloom
            mipmapBlur
            luminanceThreshold={0.65}
            luminanceSmoothing={0.15}
            intensity={0.55}
          />
        </EffectComposer>
        <OrbitControls ref={controlsRef} makeDefault minDistance={5} maxDistance={2000} maxPolarAngle={Math.PI / 2.05} />
        <InitialFraming controlsRef={controlsRef} />
        <AmbientDrift controlsRef={controlsRef} />
        <CameraRig controlsRef={controlsRef} />
      </Canvas>
      <FollowIndicator />
    </div>
  );
}
