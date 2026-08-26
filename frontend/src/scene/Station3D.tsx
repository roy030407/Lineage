// Single station: a matte painted-metal block with two andon-style lamp
// meshes mounted on top -- a sphere for sensor health, a cube for machine
// health -- colored from the beacon palette. NOT_APPLICABLE substitutes a
// distinct shape (an octahedron) rather than a texture, since sensor health
// must never be signalled by color alone.

import { Text } from "@react-three/drei";
import { useMemo } from "react";

import { useLineageStore } from "../state/store";
import type { MachineHealth, SensorHealth } from "../state/types";
import { COLORS } from "../styles/colors";

// Exported so Car3D can position cars relative to the station's actual
// height instead of duplicating the literal -- a car nested inside the
// station's own box (invisible, unclickable) was a real bug caused by
// exactly that kind of drift.
export const BLOCK_SIZE: [number, number, number] = [2.2, 1.4, 1.6];

function sensorColor(health: SensorHealth): string {
  if (health === "green") return COLORS.beaconGreen;
  if (health === "red") return COLORS.beaconRed;
  return COLORS.steelNeutral;
}

function machineColor(health: MachineHealth): string {
  return health === "green" ? COLORS.beaconGreen : COLORS.beaconRed;
}

interface Props {
  stationId: string;
  x: number;
  z: number;
  sensorHealth: SensorHealth;
  machineHealth: MachineHealth;
  isSelected: boolean;
}

export function Station3D({ stationId, x, z, sensorHealth, machineHealth, isSelected }: Props) {
  const selectStation = useLineageStore((s) => s.selectStation);

  const sensorGeometry = useMemo(
    () => (sensorHealth === "not_applicable" ? "octahedron" : "sphere"),
    [sensorHealth],
  );

  return (
    <group position={[x, BLOCK_SIZE[1] / 2, z]}>
      <mesh
        castShadow
        receiveShadow
        onClick={(event) => {
          event.stopPropagation();
          selectStation(stationId);
        }}
      >
        <boxGeometry args={BLOCK_SIZE} />
        <meshStandardMaterial
          color={COLORS.castSteel}
          roughness={0.85}
          metalness={0.1}
          emissive={isSelected ? COLORS.beaconAmber : "#000000"}
          emissiveIntensity={isSelected ? 0.25 : 0}
        />
      </mesh>

      {/* Sensor health lamp */}
      <mesh position={[-0.55, BLOCK_SIZE[1] / 2 + 0.25, 0]}>
        {sensorGeometry === "sphere" ? (
          <sphereGeometry args={[0.22, 16, 16]} />
        ) : (
          <octahedronGeometry args={[0.26, 0]} />
        )}
        <meshStandardMaterial
          color={sensorColor(sensorHealth)}
          emissive={sensorColor(sensorHealth)}
          emissiveIntensity={0.9}
        />
      </mesh>

      {/* Machine health lamp */}
      <mesh position={[0.55, BLOCK_SIZE[1] / 2 + 0.25, 0]}>
        <boxGeometry args={[0.32, 0.32, 0.32]} />
        <meshStandardMaterial
          color={machineColor(machineHealth)}
          emissive={machineColor(machineHealth)}
          emissiveIntensity={0.9}
        />
      </mesh>

      <Text
        position={[0, -BLOCK_SIZE[1] / 2 - 0.35, 0]}
        fontSize={0.4}
        color={COLORS.vellum}
        anchorX="center"
        anchorY="top"
      >
        {stationId}
      </Text>
    </group>
  );
}
