// Pure layout/geometry helpers for the node-graph Builder canvas. Node
// positions here are a visual abstraction (rows grouped by zone, columns by
// sequence order) -- NOT the real x_m/y_m layout coordinates the backend
// tracks. Dragging a node around this canvas never rewrites the physical
// geometry; only insert/remove/prepend/set_segment_distance do that, and
// those are driven by explicit actions (tray drop, distance field), not by
// where a node happens to be sitting on screen.

import type { StationSpec, Zone } from "../../state/types";

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 90;
export const COLUMN_SPACING = 260;
export const ROW_SPACING = 160;

const ZONE_ROW: Record<Zone, number> = { body: 0, paint: 1, final: 2 };

export interface Point {
  x: number;
  y: number;
}

export function stationPosition(index: number, zone: Zone): Point {
  return { x: index * COLUMN_SPACING, y: ZONE_ROW[zone] * ROW_SPACING };
}

export function positionsFor(stations: StationSpec[]): Map<string, Point> {
  const positions = new Map<string, Point>();
  stations.forEach((station, index) => {
    positions.set(station.id, stationPosition(index, station.zone));
  });
  return positions;
}

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;
  return Math.hypot(p.x - projX, p.y - projY);
}

export type DropTarget =
  | { kind: "insert"; upstreamId: string; downstreamId: string }
  | { kind: "prepend" }
  | { kind: "append" };

const PORT_HIT_RADIUS = 55;
const EDGE_HIT_RADIUS = 60;

/** Where a tray drop at `point` (in flow coordinates) should land: onto an
 * existing link (insert, splitting that segment), onto the first station's
 * inbound end (prepend), onto the last station's outbound end (append), or
 * nowhere recognizable (null -- the caller should not create a station). */
export function findDropTarget(
  point: Point,
  stations: StationSpec[],
  positions: Map<string, Point>,
): DropTarget | null {
  if (stations.length === 0) return null;

  const first = stations[0];
  const last = stations[stations.length - 1];
  const firstPos = positions.get(first.id);
  const lastPos = positions.get(last.id);

  if (firstPos) {
    const inPort = { x: firstPos.x, y: firstPos.y + NODE_HEIGHT / 2 };
    if (Math.hypot(point.x - inPort.x, point.y - inPort.y) < PORT_HIT_RADIUS) {
      return { kind: "prepend" };
    }
  }
  if (lastPos) {
    const outPort = { x: lastPos.x + NODE_WIDTH, y: lastPos.y + NODE_HEIGHT / 2 };
    if (Math.hypot(point.x - outPort.x, point.y - outPort.y) < PORT_HIT_RADIUS) {
      return { kind: "append" };
    }
  }

  let best: { dist: number; upstreamId: string; downstreamId: string } | null = null;
  for (let i = 0; i < stations.length - 1; i++) {
    const a = positions.get(stations[i].id);
    const b = positions.get(stations[i + 1].id);
    if (!a || !b) continue;
    const p1 = { x: a.x + NODE_WIDTH, y: a.y + NODE_HEIGHT / 2 };
    const p2 = { x: b.x, y: b.y + NODE_HEIGHT / 2 };
    const dist = distanceToSegment(point, p1, p2);
    if (!best || dist < best.dist) {
      best = { dist, upstreamId: stations[i].id, downstreamId: stations[i + 1].id };
    }
  }
  if (best && best.dist < EDGE_HIT_RADIUS) {
    return { kind: "insert", upstreamId: best.upstreamId, downstreamId: best.downstreamId };
  }
  return null;
}
