// Car bodies as one instanced mesh -- there may be 50 on screen at once.
// Positions are lerped every frame toward the latest tick's station
// coordinates, so motion reads as continuous between the (periodic) WS
// ticks rather than snapping station to station.

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import type { LineState, StationCoordinate } from "../state/types";
import { PALETTE } from "../styles/tokens";
import { BLOCK_SIZE } from "./Station3D";
import { toonGradientMap } from "./toonGradient";

const LERP_SPEED = 4; // higher = snappier catch-up to the target position
const HIDDEN_POSITION = new THREE.Vector3(0, -1000, 0);
// Reused across every instance within a frame instead of allocating a
// fresh Vector3 per car per frame (up to 80 allocations every frame,
// pure garbage-collector pressure). Safe to share: lerp() below reads
// the target and writes only to `current`.
const SCRATCH_TARGET = new THREE.Vector3();
const CAR_SIZE: [number, number, number] = [1.4, 0.6, 0.8];
const CAR_GAP_ABOVE_STATION = 0.1;
// Sits on top of the station block, not inside it -- BLOCK_SIZE[1] is the
// station's full height (it's centered at half that), so this is the
// station's top surface plus half the car's own height plus a visible gap.
export const CAR_Y = BLOCK_SIZE[1] + CAR_SIZE[1] / 2 + CAR_GAP_ABOVE_STATION;

// Phase 7 "juice": a brief squash-then-recover bounce plays whenever a car
// arrives at a new station -- a cheap, purely visual scale envelope layered
// on top of the existing lerp-based position update. Keyed by car id (not
// instance index): activeCars[i] is a fresh array built from lineState every
// frame, so the same index i can end up holding a different car between
// frames as cars enter/leave the line -- keying by index would occasionally
// fire a false bounce for a car that just inherited a slot, not actually
// arrived anywhere.
const BOUNCE_DURATION_S = 0.35;
const BOUNCE_AMPLITUDE = 0.22;

function bounceEnvelope(elapsedS: number): number {
  if (elapsedS < 0 || elapsedS >= BOUNCE_DURATION_S) return 0;
  const t = elapsedS / BOUNCE_DURATION_S;
  // A single damped half-cycle: peaks early, decays to 0 by t=1 -- reads as
  // a squash-and-recover, not a sustained wobble.
  return BOUNCE_AMPLITUDE * Math.sin(t * Math.PI) * (1 - t);
}

interface Props {
  lineState: LineState | null;
  coordinatesByStation: Map<string, StationCoordinate>;
  selectedCarId: string | null;
  followedCarId: string | null;
  // Instance count for the pooled mesh. Derived from LineSpec by the
  // caller, never a fixed literal: a hardcoded 80 silently dropped
  // every car past that index on a longer line, which is exactly the
  // kind of station-count assumption this project forbids.
  maxCars: number;
  onSelectCar: (carId: string) => void;
}

export function Car3D({
  lineState,
  coordinatesByStation,
  selectedCarId,
  followedCarId,
  maxCars,
  onSelectCar,
}: Props) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const currentPositions = useRef<Map<number, THREE.Vector3>>(new Map());
  const carIdByInstance = useRef<Map<number, string>>(new Map());
  const arrivalTrackingByCarId = useRef<Map<string, { stationId: string; arrivalTime: number }>>(
    new Map(),
  );
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const color = useMemo(() => new THREE.Color(), []);

  useFrame((state, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const elapsedTime = state.clock.elapsedTime;

    const activeCars = lineState
      ? lineState.stations
          .filter((s): s is typeof s & { car_id: string } => s.car_id !== null)
          .map((s) => ({ carId: s.car_id, stationId: s.station_id }))
      : [];

    carIdByInstance.current.clear();

    const seenCarIds = new Set<string>();
    for (let i = 0; i < maxCars; i++) {
      const entry = activeCars[i];
      const current =
        currentPositions.current.get(i) ?? HIDDEN_POSITION.clone();

      let target: THREE.Vector3 = HIDDEN_POSITION;
      let bounce = 0;
      if (entry) {
        const coord = coordinatesByStation.get(entry.stationId);
        if (coord) {
          target = SCRATCH_TARGET.set(coord.x_m, CAR_Y, coord.y_m);
        }
        carIdByInstance.current.set(i, entry.carId);
        seenCarIds.add(entry.carId);

        const tracked = arrivalTrackingByCarId.current.get(entry.carId);
        if (tracked && tracked.stationId !== entry.stationId) {
          // bounce stays 0 on this exact frame -- bounceEnvelope(0) is 0 by
          // construction (the envelope starts at 0 and ramps up), so the
          // squash actually appears starting next frame once elapsedTime
          // has moved past this new arrivalTime.
          arrivalTrackingByCarId.current.set(entry.carId, {
            stationId: entry.stationId,
            arrivalTime: elapsedTime,
          });
        } else if (!tracked) {
          // First time this car is seen at all -- record it, but don't
          // bounce: that would read as "arriving" on the very tick a car
          // spawns onto the line, not a real station-to-station transition.
          arrivalTrackingByCarId.current.set(entry.carId, {
            stationId: entry.stationId,
            arrivalTime: -Infinity,
          });
        } else {
          bounce = bounceEnvelope(elapsedTime - tracked.arrivalTime);
        }
      }

      current.lerp(target, Math.min(1, delta * LERP_SPEED));
      currentPositions.current.set(i, current);

      dummy.position.copy(current);
      const isSelected = entry?.carId === selectedCarId;
      const isFollowed = entry?.carId === followedCarId;
      const baseScale = entry ? (isSelected || isFollowed ? 1.15 : 1) : 0.001;
      if (bounce > 0) {
        // Squash on Y, bulge slightly on X/Z to compensate -- the classic
        // "just landed" cue, decaying back to a uniform baseScale.
        dummy.scale.set(baseScale * (1 + bounce * 0.5), baseScale * (1 - bounce), baseScale * (1 + bounce * 0.5));
      } else {
        dummy.scale.setScalar(baseScale);
      }
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);

      color.set(isFollowed ? PALETTE.beaconAmber : PALETTE.vellum);
      mesh.setColorAt(i, color);
    }

    // Prune cars that left the line entirely -- otherwise this map would
    // grow for the life of the session, one entry per car that ever
    // appeared (hundreds, over a full run).
    for (const carId of arrivalTrackingByCarId.current.keys()) {
      if (!seenCarIds.has(carId)) arrivalTrackingByCarId.current.delete(carId);
    }

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    // InstancedMesh.raycast() broad-phase-rejects against `this.boundingSphere`
    // -- a bounding volume cached on the mesh itself, computed once, lazily,
    // on the FIRST raycast call, from whatever instance transforms existed at
    // that moment. Every instance's transform changes every frame here, but
    // nothing recomputed that cached sphere, so it went permanently stale and
    // silently ate every click/hover on every car: a real, shipped bug, not a
    // hypothetical (see DESIGN.md's raycasting diagnosis). This is a distinct
    // failure mode from frustumCulled above -- that's Object3D's own
    // bounding-sphere check for render-time culling; this is
    // InstancedMesh.raycast()'s separate cached sphere for hit-testing. Both
    // are the same underlying three.js gotcha (a per-object cached bounding
    // volume that ignores per-instance updates), so both need their own fix.
    mesh.computeBoundingSphere();
  });

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, maxCars]}
      userData={{ lineageKind: "car" }}
      // Three.js culls an InstancedMesh using a bounding sphere around the
      // *object's own* local origin, ignoring per-instance transforms --
      // with cars scattered across a 300m+ line via setMatrixAt, that check
      // has nothing to do with where they actually are, so it can (and did)
      // cull every car regardless of camera position.
      frustumCulled={false}
      castShadow
      onClick={(event) => {
        event.stopPropagation();
        const carId = carIdByInstance.current.get(event.instanceId ?? -1);
        if (carId) onSelectCar(carId);
      }}
    >
      <boxGeometry args={CAR_SIZE} />
      <meshToonMaterial gradientMap={toonGradientMap()} />
    </instancedMesh>
  );
}
