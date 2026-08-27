// Renders the full line from LineSpec.layout coordinates -- station count is
// dynamic and an L-shaped or square layout renders genuinely differently,
// since positions come straight from the real coordinate data, never a
// synthetic grid.

import { useMemo } from "react";
import * as THREE from "three";

import { useLineageStore } from "../state/store";
import type { StationCoordinate, StationState } from "../state/types";
import { PALETTE } from "../styles/tokens";
import { Car3D } from "./Car3D";
import { Station3D } from "./Station3D";

function ConveyorSegment3D({ from, to }: { from: StationCoordinate; to: StationCoordinate }) {
  const { position, length, angle } = useMemo(() => {
    const dx = to.x_m - from.x_m;
    const dz = to.y_m - from.y_m;
    const len = Math.hypot(dx, dz);
    return {
      position: new THREE.Vector3((from.x_m + to.x_m) / 2, 0.15, (from.y_m + to.y_m) / 2),
      length: len,
      angle: Math.atan2(dx, dz),
    };
  }, [from, to]);

  return (
    <mesh position={position} rotation={[0, angle, 0]} receiveShadow>
      <boxGeometry args={[0.6, 0.15, length]} />
      <meshStandardMaterial color={PALETTE.steelNeutral} roughness={0.9} />
    </mesh>
  );
}

function BufferStack({ from, to, depth }: { from: StationCoordinate; to: StationCoordinate; depth: number }) {
  const markers = useMemo(() => {
    if (depth <= 0) return [];
    const dx = to.x_m - from.x_m;
    const dz = to.y_m - from.y_m;
    const len = Math.hypot(dx, dz);
    const dirX = dx / len;
    const dirZ = dz / len;
    const spacing = Math.min(0.6, (len * 0.6) / Math.max(depth, 1));
    // Markers cluster near the downstream (to) station, since that's where
    // the queue is physically waiting to enter.
    return Array.from({ length: Math.min(depth, 12) }, (_, i) => {
      const distanceFromTo = 1.2 + i * spacing;
      return new THREE.Vector3(
        to.x_m - dirX * distanceFromTo,
        0.35,
        to.y_m - dirZ * distanceFromTo,
      );
    });
  }, [from, to, depth]);

  return (
    <>
      {markers.map((position, i) => (
        <mesh key={i} position={position}>
          <boxGeometry args={[0.3, 0.3, 0.3]} />
          <meshStandardMaterial color={PALETTE.vellum} roughness={0.7} />
        </mesh>
      ))}
    </>
  );
}

export function Line3D() {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const lineState = useLineageStore((s) => s.lineState);
  const selectedStationId = useLineageStore((s) => s.selectedStationId);
  const selectedCarId = useLineageStore((s) => s.selectedCarId);
  const followedCarId = useLineageStore((s) => s.followedCarId);
  const selectCar = useLineageStore((s) => s.selectCar);
  const followCar = useLineageStore((s) => s.followCar);

  const coordinatesByStation = useMemo(() => {
    const map = new Map<string, StationCoordinate>();
    lineSpec?.layout.coordinates.forEach((c) => map.set(c.station_id, c));
    return map;
  }, [lineSpec]);

  const stationStateById = useMemo(() => {
    const map = new Map<string, StationState>();
    lineState?.stations.forEach((s) => map.set(s.station_id, s));
    return map;
  }, [lineState]);

  if (!lineSpec) return null;

  return (
    <group>
      {lineSpec.layout.segments.map((segment) => {
        const from = coordinatesByStation.get(segment.from_station_id);
        const to = coordinatesByStation.get(segment.to_station_id);
        if (!from || !to) return null;
        const downstreamState = stationStateById.get(segment.to_station_id);
        return (
          <group key={`${segment.from_station_id}-${segment.to_station_id}`}>
            <ConveyorSegment3D from={from} to={to} />
            <BufferStack from={from} to={to} depth={downstreamState?.upstream_buffer_depth ?? 0} />
          </group>
        );
      })}

      {lineSpec.stations.map((station) => {
        const coord = coordinatesByStation.get(station.id);
        const state = stationStateById.get(station.id);
        if (!coord || !state) return null;
        return (
          <Station3D
            key={station.id}
            stationId={station.id}
            x={coord.x_m}
            z={coord.y_m}
            sensorHealth={state.sensor_health}
            machineHealth={state.machine_health}
            isSelected={selectedStationId === station.id}
          />
        );
      })}

      <Car3D
        lineState={lineState}
        coordinatesByStation={coordinatesByStation}
        selectedCarId={selectedCarId}
        followedCarId={followedCarId}
        onSelectCar={(carId) => {
          void selectCar(carId);
          followCar(carId);
        }}
      />
    </group>
  );
}
