// Single station: a matte painted-metal block with two andon-style lamp
// meshes mounted on top -- one for sensor health, one for machine health.
// Both read colour AND shape from the shared status vocabulary
// (styles/tokens.ts): colour alone must never carry a status distinction,
// since that fails on a projector and for a colour-blind viewer.

import { Text } from "@react-three/drei";

import { useLineageStore } from "../state/store";
import type { MachineHealth, SensorHealth } from "../state/types";
import {
  MACHINE_HEALTH_TOKENS,
  PALETTE,
  SENSOR_HEALTH_TOKENS,
  type ShapeToken,
} from "../styles/tokens";

// Exported so Car3D can position cars relative to the station's actual
// height instead of duplicating the literal -- a car nested inside the
// station's own box (invisible, unclickable) was a real bug caused by
// exactly that kind of drift.
export const BLOCK_SIZE: [number, number, number] = [2.2, 1.4, 1.6];

// The shared 5-shape vocabulary rendered as three.js primitives -- picked
// so every shape reads as a distinct silhouette even in monochrome:
// sphere (circle), a 3-sided cone (triangle), an octahedron (diamond), a
// 6-sided cylinder (hexagon), and a torus (ring/hollow -- no signal).
function ShapeGeometry({ shape }: { shape: ShapeToken }) {
  switch (shape) {
    case "circle":
      return <sphereGeometry args={[0.22, 16, 16]} />;
    case "triangle":
      return <coneGeometry args={[0.26, 0.42, 3]} />;
    case "diamond":
      return <octahedronGeometry args={[0.26, 0]} />;
    case "hexagon":
      return <cylinderGeometry args={[0.24, 0.24, 0.18, 6]} />;
    case "ring":
      return <torusGeometry args={[0.16, 0.07, 8, 16]} />;
  }
}

function StatusLamp({
  position,
  color,
  shape,
}: {
  position: [number, number, number];
  color: string;
  shape: ShapeToken;
}) {
  return (
    <mesh position={position}>
      <ShapeGeometry shape={shape} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.9} />
    </mesh>
  );
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

  const sensorToken = SENSOR_HEALTH_TOKENS[sensorHealth];
  const machineToken = MACHINE_HEALTH_TOKENS[machineHealth];

  return (
    <group
      position={[x, BLOCK_SIZE[1] / 2, z]}
      userData={{ lineageKind: "station", stationId }}
    >
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
          color={PALETTE.castSteel}
          roughness={0.85}
          metalness={0.1}
          emissive={PALETTE.beaconAmber}
          emissiveIntensity={isSelected ? 0.25 : 0}
        />
      </mesh>

      {/* Sensor health lamp */}
      <StatusLamp
        position={[-0.55, BLOCK_SIZE[1] / 2 + 0.25, 0]}
        color={sensorToken.color}
        shape={sensorToken.shape}
      />

      {/* Machine health lamp */}
      <StatusLamp
        position={[0.55, BLOCK_SIZE[1] / 2 + 0.25, 0]}
        color={machineToken.color}
        shape={machineToken.shape}
      />

      <Text
        position={[0, -BLOCK_SIZE[1] / 2 - 0.35, 0]}
        fontSize={0.4}
        color={PALETTE.vellum}
        anchorX="center"
        anchorY="top"
      >
        {stationId}
      </Text>
    </group>
  );
}
