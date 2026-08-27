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

function StationNodeComponent({ data }: { data: StationNodeData }) {
  const { station, isFirst, isLast } = data;
  const zoneToken = ZONE_TOKENS[station.zone];

  return (
    <div
      style={{
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        display: "flex",
        background: "var(--color-cast-steel)",
        border: "1px solid var(--color-steel-neutral)",
        borderRadius: 4,
        color: "var(--color-vellum)",
        overflow: "hidden",
      }}
    >
      <div style={{ width: 6, background: zoneToken.color, flexShrink: 0 }} aria-hidden="true" />
      <div style={{ padding: "var(--space-2) var(--space-3)", flex: 1, minWidth: 0 }}>
        <p className="eyebrow" style={{ margin: 0 }}>
          {zoneToken.label} · {station.id}
        </p>
        <p style={{ margin: "2px 0", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
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
          style={{ background: "var(--color-steel-neutral)" }}
        />
      )}
      {!isLast && (
        <Handle
          type="source"
          position={Position.Right}
          id="out"
          style={{ background: "var(--color-steel-neutral)" }}
        />
      )}
    </div>
  );
}

export const StationNode = memo(StationNodeComponent);
