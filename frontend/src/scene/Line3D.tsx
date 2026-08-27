// Renders the full line from LineSpec.layout coordinates -- station count is
// dynamic and an L-shaped or square layout renders genuinely differently,
// since positions come straight from the real coordinate data, never a
// synthetic grid.

import { Text } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import { useLineageStore } from "../state/store";
import type { StationCoordinate, StationState, Zone } from "../state/types";
import { PALETTE } from "../styles/tokens";
import { Car3D } from "./Car3D";
import { Station3D } from "./Station3D";
import { toonGradientMap } from "./toonGradient";

const ZONE_LABEL_TEXT: Record<Zone, string> = { body: "BODY", paint: "PAINT", final: "FINAL" };
const ZONE_LABEL_HEIGHT = 4.5; // clears the beacon masts (see Station3D) so it reads as a row header, not clutter

function ZoneLabel({ zone, x, z }: { zone: Zone; x: number; z: number }) {
  return (
    <Text position={[x, ZONE_LABEL_HEIGHT, z]} fontSize={1.1} color={PALETTE.vellum} anchorX="left" anchorY="middle">
      {ZONE_LABEL_TEXT[zone]}
    </Text>
  );
}

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
      <meshToonMaterial color={PALETTE.steelNeutral} gradientMap={toonGradientMap()} />
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
          <meshToonMaterial color={PALETTE.vellum} gradientMap={toonGradientMap()} />
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

  // First station (by sequence order) in each zone, so its label anchors
  // the start of that zone's row -- zone identity should read from the
  // geometry at a glance, not require hunting for a station ID.
  const zoneLabelPositions = useMemo(() => {
    if (!lineSpec) return [];
    const ordered = [...lineSpec.stations].sort((a, b) => a.sequence_index - b.sequence_index);
    const seen = new Set<Zone>();
    const positions: { zone: Zone; x: number; z: number }[] = [];
    for (const station of ordered) {
      if (seen.has(station.zone)) continue;
      const coord = coordinatesByStation.get(station.id);
      if (!coord) continue;
      seen.add(station.zone);
      positions.push({ zone: station.zone, x: coord.x_m, z: coord.y_m });
    }
    return positions;
  }, [lineSpec, coordinatesByStation]);

  if (!lineSpec) return null;

  return (
    <group>
      {zoneLabelPositions.map(({ zone, x, z }) => (
        <ZoneLabel key={zone} zone={zone} x={x} z={z} />
      ))}

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
            stationName={station.name}
            x={coord.x_m}
            z={coord.y_m}
            sensorHealth={state.sensor_health}
            machineHealth={state.machine_health}
            latestReadings={state.latest_readings}
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
