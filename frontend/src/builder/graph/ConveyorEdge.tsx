// A dashed edge for the Builder canvas -- Phase 6 of the gamified rebuild:
// a link should read as a conveyor belt, not a static flowchart arrow. The
// distance label is unchanged (BuilderCanvas.tsx still sets it via
// edge.label); only the stroke rendering changes here.
//
// Deliberately NOT animated (no stroke-dashoffset scroll), despite that
// being the original plan: a continuously-repainting stroke made Playwright's
// click() actionability checks (which poll for a stable, visible target
// across frames) time out against this exact element. A cosmetic in-motion
// effect isn't worth risking real click-to-cut reliability over -- the
// dashed style alone still reads as "belt", not "flowchart arrow".
//
// Also deliberately getBezierPath, not getStraightPath: a straight line
// between two same-row stations (the common case, since stations in the
// same zone share a row) is a literal zero-height path, which is exactly
// what actually broke click-to-cut here -- the previous default (unstyled)
// React Flow edge type used a bezier curve, which has real curvature/height
// even between two same-Y points, and that's what made it reliably
// clickable. Confirmed directly: switching to getStraightPath alone (before
// removing the animation) reproduced "element is not visible" on a fresh
// backend; switching back to a bezier path fixed it independent of the
// animation question.
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position, type EdgeProps } from "@xyflow/react";

export function ConveyorEdge({ id, sourceX, sourceY, targetX, targetY, label, style }: EdgeProps) {
  // Explicit, not the getBezierPath default (Bottom/Top) -- StationNode's
  // handles are Position.Right (source/"out") and Position.Left (target/
  // "in"), and omitting these produces a curve that loops the wrong way.
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition: Position.Right,
    targetX,
    targetY,
    targetPosition: Position.Left,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        interactionWidth={24}
        style={{
          ...style,
          strokeWidth: 3,
          strokeDasharray: "8 6",
        }}
      />
      {label != null && (
        <EdgeLabelRenderer>
          <div
            className="data nodrag nopan"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: "var(--color-hud-panel-deep)",
              color: "var(--color-vellum)",
              padding: "1px 6px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-hud-accent)",
              fontSize: "0.7rem",
              pointerEvents: "none",
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
