// Spawn tray, bottom-right per the live Task 8 instruction (DESIGN.md's own
// Builder sketch drew it on the left before this canvas existed -- updated
// to match reality, see that file's Builder layout section). Each tile is a
// native HTML5 drag source; BuilderCanvas reads the template back out of
// dataTransfer on drop and resolves where it landed via findDropTarget.

import type { AcquisitionMode, Zone } from "../../state/types";
import { ZONE_TOKENS } from "../../styles/tokens";

export interface StationTemplate {
  zoneDefault: Zone | null;
  acquisitionModeDefault: AcquisitionMode;
  label: string;
}

export const STATION_TEMPLATE_MIME = "application/x-lineage-station-template";

const TEMPLATES: StationTemplate[] = [
  { zoneDefault: "body", acquisitionModeDefault: "instrumented", label: ZONE_TOKENS.body.label },
  { zoneDefault: "paint", acquisitionModeDefault: "instrumented", label: ZONE_TOKENS.paint.label },
  { zoneDefault: "final", acquisitionModeDefault: "instrumented", label: ZONE_TOKENS.final.label },
  { zoneDefault: null, acquisitionModeDefault: "manual", label: "Manual variant" },
];

export function SpawnTray() {
  return (
    <div
      style={{
        position: "absolute",
        right: "var(--space-4)",
        bottom: "var(--space-4)",
        zIndex: 5,
        background: "var(--color-cast-steel)",
        border: "1px solid var(--color-steel-neutral)",
        borderRadius: 4,
        padding: "var(--space-3)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-2)",
      }}
    >
      <p className="eyebrow" style={{ margin: 0 }}>
        Spawn tray
      </p>
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        {TEMPLATES.map((template) => (
          <div
            key={template.label}
            draggable
            onDragStart={(event) => {
              event.dataTransfer.setData(STATION_TEMPLATE_MIME, JSON.stringify(template));
              event.dataTransfer.effectAllowed = "copy";
            }}
            style={{
              cursor: "grab",
              padding: "var(--space-2)",
              minWidth: 90,
              textAlign: "center",
              background: "var(--color-foundry)",
              border: `1px solid ${template.zoneDefault ? ZONE_TOKENS[template.zoneDefault].color : "var(--color-steel-neutral)"}`,
              borderRadius: 4,
              color: "var(--color-vellum)",
              fontSize: "0.85rem",
            }}
          >
            {template.label}
          </div>
        ))}
      </div>
      <p className="eyebrow" style={{ margin: 0, maxWidth: 280 }}>
        Drag onto a link to insert, or onto either end to append
      </p>
    </div>
  );
}
