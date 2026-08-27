// Single station: a matte painted-metal block topped by a thin beacon mast
// -- the andon-tower silhouette a real plant floor uses, and the signature
// element of the Mirror (see DESIGN.md): status lamps mounted at the mast
// head are legible from across the whole serpentine line, and a station in
// a fault state emits a light beam rising further into the sky, visible at
// a glance the way Factorio's alarm poles or Satisfactory's beacons are.
//
// Both lamps read colour AND shape from the shared status vocabulary
// (styles/tokens.ts): colour alone must never carry a status distinction,
// since that fails on a projector and for a colour-blind viewer. The two
// fault beams (sensor vs. machine) carry the same discipline one level up:
// a steady narrow beam for a sensor fault, a wider *pulsing* beam for a
// machine fault -- an identical red column for both would undo exactly the
// colour-plus-shape rule the beams exist to dramatize.

import { Html, Text } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useRef, useState } from "react";
import type * as THREE from "three";

import { StatusBadge } from "../components/StatusBadge";
import { useLineageStore } from "../state/store";
import type { LatestReading, MachineHealth, SensorHealth } from "../state/types";
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

const MAST_HEIGHT = 1.3;
const MAST_RADIUS = 0.05;
const MAST_TOP_LOCAL_Y = BLOCK_SIZE[1] / 2 + MAST_HEIGHT; // where the mast meets its lamp cap
const LAMP_LOCAL_Y = MAST_TOP_LOCAL_Y + 0.25;
const LAMP_X_OFFSET = 0.3;

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

/** Steady, narrow -- a sensor fault is a persistent condition (a reading has
 * gone stale), so its beam reads the same way: constant, unblinking. */
function SensorFaultBeam({ position }: { position: [number, number, number] }) {
  const height = 6;
  return (
    <mesh position={[position[0], position[1] + height / 2, position[2]]}>
      <coneGeometry args={[0.08, height, 8]} />
      <meshBasicMaterial
        color={PALETTE.beaconRed}
        transparent
        opacity={0.35}
        depthWrite={false}
      />
    </mesh>
  );
}

/** Wider, tapered, and pulsing -- deliberately distinct from the sensor
 * beam's steady column so the two fault types never read as the same
 * signal at a glance, only in a different position. */
function MachineFaultBeam({ position }: { position: [number, number, number] }) {
  const height = 4;
  const materialRef = useRef<THREE.MeshBasicMaterial>(null);

  useFrame(({ clock }) => {
    if (materialRef.current) {
      materialRef.current.opacity = 0.15 + 0.25 * (0.5 + 0.5 * Math.sin(clock.elapsedTime * 4));
    }
  });

  return (
    <mesh position={[position[0], position[1] + height / 2, position[2]]}>
      <cylinderGeometry args={[0.05, 0.2, height, 8]} />
      <meshBasicMaterial
        ref={materialRef}
        color={PALETTE.beaconRed}
        transparent
        opacity={0.3}
        depthWrite={false}
      />
    </mesh>
  );
}

interface Props {
  stationId: string;
  stationName: string;
  x: number;
  z: number;
  sensorHealth: SensorHealth;
  machineHealth: MachineHealth;
  latestReadings: LatestReading[];
  isSelected: boolean;
}

export function Station3D({
  stationId,
  stationName,
  x,
  z,
  sensorHealth,
  machineHealth,
  latestReadings,
  isSelected,
}: Props) {
  const selectStation = useLineageStore((s) => s.selectStation);
  const [hovered, setHovered] = useState(false);

  const sensorToken = SENSOR_HEALTH_TOKENS[sensorHealth];
  const machineToken = MACHINE_HEALTH_TOKENS[machineHealth];
  const sensorLampPos: [number, number, number] = [-LAMP_X_OFFSET, LAMP_LOCAL_Y, 0];
  const machineLampPos: [number, number, number] = [LAMP_X_OFFSET, LAMP_LOCAL_Y, 0];

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
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
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

      {/* Beacon mast -- the signature element; see DESIGN.md */}
      <mesh position={[0, BLOCK_SIZE[1] / 2 + MAST_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[MAST_RADIUS, MAST_RADIUS, MAST_HEIGHT, 8]} />
        <meshStandardMaterial color={PALETTE.castSteel} roughness={0.6} metalness={0.4} />
      </mesh>

      <StatusLamp position={sensorLampPos} color={sensorToken.color} shape={sensorToken.shape} />
      <StatusLamp position={machineLampPos} color={machineToken.color} shape={machineToken.shape} />

      {sensorHealth === "red" && <SensorFaultBeam position={sensorLampPos} />}
      {machineHealth === "red" && <MachineFaultBeam position={machineLampPos} />}

      <Text
        position={[0, -BLOCK_SIZE[1] / 2 - 0.35, 0]}
        fontSize={0.4}
        color={PALETTE.vellum}
        anchorX="center"
        anchorY="top"
      >
        {stationId}
      </Text>

      {hovered && (
        <Html position={[0, LAMP_LOCAL_Y + 0.4, 0]} center distanceFactor={12} zIndexRange={[10, 0]}>
          <div
            style={{
              background: "var(--color-cast-steel)",
              color: "var(--color-vellum)",
              padding: "var(--space-2) var(--space-3)",
              borderRadius: "2px",
              whiteSpace: "nowrap",
              pointerEvents: "none",
              font: "var(--text-body)",
            }}
          >
            <p className="eyebrow">
              {stationName} ({stationId})
            </p>
            <div style={{ display: "flex", gap: "var(--space-3)", marginTop: "var(--space-1)" }}>
              <StatusBadge token={sensorToken} />
              <StatusBadge token={machineToken} />
            </div>
            {latestReadings.length > 0 && (
              <table className="data" style={{ marginTop: "var(--space-1)" }}>
                <tbody>
                  {latestReadings.map((reading) => (
                    <tr key={reading.sensor_id}>
                      <td>{reading.quantity}</td>
                      <td>{reading.value.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Html>
      )}
    </group>
  );
}
