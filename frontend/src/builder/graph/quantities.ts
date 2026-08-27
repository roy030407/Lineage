import type { StationSpec } from "../../state/types";

// Every quantity name SPC/root-cause code actually looks up for this station:
// one per sensor kind (a sensor's own readings are keyed by sensor.kind, not
// sensor.id -- see backend datagen/writer.py) plus every manual
// readable_param, deduplicated. This is what a commissioning baseline (idle/
// loaded mean+std) needs an entry per, whether entered by hand or captured
// via "run to learn".
export function stationQuantities(station: StationSpec): string[] {
  const kinds = station.sensors.map((s) => s.kind as string);
  return Array.from(new Set([...kinds, ...station.readable_params]));
}
