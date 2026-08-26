// Car bodies as one instanced mesh -- there may be 50 on screen at once.
// Positions are lerped every frame toward the latest tick's station
// coordinates, so motion reads as continuous between the (periodic) WS
// ticks rather than snapping station to station.

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import type { LineState, StationCoordinate } from "../state/types";
import { COLORS } from "../styles/colors";
import { BLOCK_SIZE } from "./Station3D";

const MAX_CARS = 80;
const LERP_SPEED = 4; // higher = snappier catch-up to the target position
const HIDDEN_POSITION = new THREE.Vector3(0, -1000, 0);
const CAR_SIZE: [number, number, number] = [1.4, 0.6, 0.8];
const CAR_GAP_ABOVE_STATION = 0.1;
// Sits on top of the station block, not inside it -- BLOCK_SIZE[1] is the
// station's full height (it's centered at half that), so this is the
// station's top surface plus half the car's own height plus a visible gap.
export const CAR_Y = BLOCK_SIZE[1] + CAR_SIZE[1] / 2 + CAR_GAP_ABOVE_STATION;

interface Props {
  lineState: LineState | null;
  coordinatesByStation: Map<string, StationCoordinate>;
  selectedCarId: string | null;
  followedCarId: string | null;
  onSelectCar: (carId: string) => void;
}

export function Car3D({
  lineState,
  coordinatesByStation,
  selectedCarId,
  followedCarId,
  onSelectCar,
}: Props) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const currentPositions = useRef<Map<number, THREE.Vector3>>(new Map());
  const carIdByInstance = useRef<Map<number, string>>(new Map());
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const color = useMemo(() => new THREE.Color(), []);

  useFrame((_state, delta) => {
    const mesh = meshRef.current;
    if (!mesh) return;

    const activeCars = lineState
      ? lineState.stations
          .filter((s): s is typeof s & { car_id: string } => s.car_id !== null)
          .map((s) => ({ carId: s.car_id, stationId: s.station_id }))
      : [];

    carIdByInstance.current.clear();

    for (let i = 0; i < MAX_CARS; i++) {
      const entry = activeCars[i];
      const current =
        currentPositions.current.get(i) ?? HIDDEN_POSITION.clone();

      let target = HIDDEN_POSITION;
      if (entry) {
        const coord = coordinatesByStation.get(entry.stationId);
        if (coord) {
          target = new THREE.Vector3(coord.x_m, CAR_Y, coord.y_m);
        }
        carIdByInstance.current.set(i, entry.carId);
      }

      current.lerp(target, Math.min(1, delta * LERP_SPEED));
      currentPositions.current.set(i, current);

      dummy.position.copy(current);
      const isSelected = entry?.carId === selectedCarId;
      const isFollowed = entry?.carId === followedCarId;
      const scale = entry ? (isSelected || isFollowed ? 1.15 : 1) : 0.001;
      dummy.scale.setScalar(scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);

      color.set(isFollowed ? COLORS.beaconAmber : COLORS.vellum);
      mesh.setColorAt(i, color);
    }

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, MAX_CARS]}
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
      <meshStandardMaterial roughness={0.6} metalness={0.15} />
    </instancedMesh>
  );
}
