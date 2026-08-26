// Client-side validation mirroring the backend LineSpec/StationSpec schema
// (config/specs.py's model_validators) -- catches the same two rules before
// a round trip to the API, not a replacement for it.

import type { AcquisitionMode, SensorSpec } from "../state/types";

export function validateSensorsMatchAcquisitionMode(
  acquisitionMode: AcquisitionMode,
  sensors: SensorSpec[],
): string | null {
  if (acquisitionMode === "manual" && sensors.length > 0) {
    return "A manual station must not declare any sensors.";
  }
  if (
    (acquisitionMode === "instrumented" || acquisitionMode === "mixed") &&
    sensors.length === 0
  ) {
    return `A ${acquisitionMode} station requires at least one sensor.`;
  }
  return null;
}

export function validateNewStationId(id: string, existingIds: string[]): string | null {
  if (!id.trim()) return "Station ID is required.";
  if (existingIds.includes(id)) return `Station ID "${id}" already exists on this line.`;
  return null;
}
