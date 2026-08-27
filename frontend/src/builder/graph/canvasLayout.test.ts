// findDropTarget is the crux of "drag a station from the tray onto a link
// to insert" actually working, not just rendering -- these pin down its
// three outcomes (insert mid-line, prepend, append) plus the "drop nowhere
// recognizable" case, against the exact node layout positionsFor() produces.

import { describe, expect, it } from "vitest";

import type { StationSpec } from "../../state/types";
import { findDropTarget, NODE_HEIGHT, NODE_WIDTH, positionsFor } from "./canvasLayout";

function station(id: string, zone: StationSpec["zone"] = "body"): StationSpec {
  return {
    id,
    name: id,
    zone,
    sequence_index: 0,
    sensors: [],
    acquisition_mode: "manual",
    is_inspection_station: false,
    cycle_time_nominal_s: 10,
    commissioning_baseline: null,
    changeable_params: {},
    readable_params: [],
    machine: {
      model: "M",
      install_year: 2020,
      last_maintenance_date: "2024-01-01",
      maintenance_interval_days: 90,
      wear_curve_shape: "linear",
    },
    cost_per_hour: 10,
    value_add_pct: 1,
  };
}

describe("findDropTarget", () => {
  const stations = [station("ST-01"), station("ST-02"), station("ST-03")];
  const positions = positionsFor(stations);

  it("finds the link between two adjacent stations when dropped near its midpoint", () => {
    const p1 = positions.get("ST-01")!;
    const p2 = positions.get("ST-02")!;
    const midpoint = {
      x: (p1.x + NODE_WIDTH + p2.x) / 2,
      y: p1.y + NODE_HEIGHT / 2,
    };
    expect(findDropTarget(midpoint, stations, positions)).toEqual({
      kind: "insert",
      upstreamId: "ST-01",
      downstreamId: "ST-02",
    });
  });

  it("finds prepend when dropped on the first station's inbound port", () => {
    const firstPos = positions.get("ST-01")!;
    const point = { x: firstPos.x, y: firstPos.y + NODE_HEIGHT / 2 };
    expect(findDropTarget(point, stations, positions)).toEqual({ kind: "prepend" });
  });

  it("finds append when dropped on the last station's outbound port", () => {
    const lastPos = positions.get("ST-03")!;
    const point = { x: lastPos.x + NODE_WIDTH, y: lastPos.y + NODE_HEIGHT / 2 };
    expect(findDropTarget(point, stations, positions)).toEqual({ kind: "append" });
  });

  it("returns null when dropped far from any link or end", () => {
    const point = { x: 100000, y: 100000 };
    expect(findDropTarget(point, stations, positions)).toBeNull();
  });

  it("picks the nearer link when dropped closer to the second segment", () => {
    const p2 = positions.get("ST-02")!;
    const p3 = positions.get("ST-03")!;
    const midpoint = {
      x: (p2.x + NODE_WIDTH + p3.x) / 2,
      y: p2.y + NODE_HEIGHT / 2,
    };
    expect(findDropTarget(midpoint, stations, positions)).toEqual({
      kind: "insert",
      upstreamId: "ST-02",
      downstreamId: "ST-03",
    });
  });
});
