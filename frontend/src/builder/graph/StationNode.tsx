// Node anatomy per DESIGN.md's Builder section: a zone-colour left stripe,
// id/name, a sensor indicator, the acquisition mode, and in/out connector
// handles (one conveyor segment per edge). This is a config-time editor with
// no live run attached to a draft -- the sensor indicator reuses
// SENSOR_HEALTH_TOKENS.not_applicable for "no sensor" (that token's real,
// documented meaning, not a live-health claim); an instrumented/mixed
// station just states its sensor count as plain data instead of borrowing a
// "Reporting" label that would imply telemetry no draft actually has.

import { Handle, Position } from "@xyflow/react";
import { memo } from "react";

import type { StationSpec } from "../../state/types";
import { SENSOR_HEALTH_TOKENS, ZONE_TOKENS } from "../../styles/tokens";
import { StatusBadge } from "../../components/StatusBadge";
import { NODE_HEIGHT, NODE_WIDTH } from "./canvasLayout";

export interface StationNodeData {
  station: StationSpec;
  isFirst: boolean;
  isLast: boolean;
  [key: string]: unknown;
}

// Zone identity was a 6px side stripe; promoted to a full-width header band
// per Phase 6 of the gamified rebuild -- a tycoon-game "building tile" reads
// its category from a coloured header bar, not a thin accent line. Chunky
// border/radius/shadow tokens (Phase 5's HudPanel system) replace the flat
// 1px/4px card. Selection now shows as an accent-coloured border instead of
// nothing, since React Flow already tracks `selected` for every node type.
function StationNodeComponent({
  data,
  selected,
}: {
  data: StationNodeData;
  selected?: boolean;
}) {
  const { station, isFirst, isLast } = data;
  const zoneToken = ZONE_TOKENS[station.zone];

  return (
    <div
      style={{
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        display: "flex",
        flexDirection: "column",
        background: "var(--color-hud-panel-deep)",
        border: `var(--border-width-chunky) solid ${
          selected ? "var(--color-hud-accent)" : "var(--color-steel-neutral)"
        }`,
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-panel)",
        color: "var(--color-vellum)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: zoneToken.color,
          padding: "var(--space-1) var(--space-2)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <span className="eyebrow" style={{ margin: 0, color: "var(--color-foundry)" }}>
          {zoneToken.label}
        </span>
        <span className="data" style={{ color: "var(--color-foundry)", fontWeight: 700 }}>
          {station.id}
        </span>
      </div>
      <div style={{ padding: "var(--space-2) var(--space-3)", flex: 1, minWidth: 0 }}>
        <p style={{ margin: "0 0 2px", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {station.name}
        </p>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          {station.sensors.length === 0 ? (
            <StatusBadge token={SENSOR_HEALTH_TOKENS.not_applicable} />
          ) : (
            <span className="data">
              {station.sensors.length} sensor{station.sensors.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <p className="eyebrow" style={{ margin: "2px 0 0" }}>
          {station.acquisition_mode}
        </p>
      </div>
      {!isFirst && (
        <Handle
          type="target"
          position={Position.Left}
          id="in"
          style={{ background: "var(--color-hud-accent)" }}
        />
      )}
      {!isLast && (
        <Handle
          type="source"
          position={Position.Right}
          id="out"
          style={{ background: "var(--color-hud-accent)" }}
        />
      )}
    </div>
  );
}

export const StationNode = memo(StationNodeComponent);
