// Selected-node editor: sensors (add by kind, or none -- a manual station is
// a first-class citizen here, not an error state), inter-station distance,
// and the commissioning baseline entry point. Every save round-trips through
// the backend (replace_station/set_segment_distance), which re-validates the
// whole line, so a rejected edit surfaces the same error a form submit would.

import { useState } from "react";

import {
  removeBuilderStation,
  updateBuilderSegmentDistance,
  updateBuilderStationBaseline,
  updateBuilderStationSensors,
} from "../../state/api";
import type {
  AcquisitionMode,
  LineSpec,
  SensorKind,
  SensorSpec,
  StationSpec,
} from "../../state/types";
import { validateSensorsMatchAcquisitionMode } from "../validation";
import { CommissioningWizard } from "./CommissioningWizard";

const ACQUISITION_MODES: AcquisitionMode[] = ["instrumented", "manual", "mixed"];
const SENSOR_KINDS: SensorKind[] = [
  "thermal",
  "infrared",
  "vibration",
  "torque",
  "rpm",
  "cycle_time",
  "none",
];

function blankSensor(): SensorSpec {
  return {
    id: "",
    kind: "torque",
    unit: "",
    sample_rate_hz: 1,
    install_date: new Date().toISOString().slice(0, 10),
    last_calibration_date: new Date().toISOString().slice(0, 10),
    accuracy_class: "1.0",
  };
}

interface Props {
  station: StationSpec;
  line: LineSpec;
  onUpdated: (line: LineSpec) => void;
  onClose: () => void;
}

export function PropertiesPanel({ station, line, onUpdated, onClose }: Props) {
  const [sensors, setSensors] = useState<SensorSpec[]>(station.sensors);
  const [acquisitionMode, setAcquisitionMode] = useState<AcquisitionMode>(
    station.acquisition_mode,
  );
  const [sensorsError, setSensorsError] = useState<string | null>(null);
  const [savingSensors, setSavingSensors] = useState(false);

  const upstreamSegment = line.layout.segments.find((s) => s.to_station_id === station.id);
  const [distanceM, setDistanceM] = useState(upstreamSegment?.distance_m ?? 0);
  const [distanceError, setDistanceError] = useState<string | null>(null);
  const [savingDistance, setSavingDistance] = useState(false);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  function updateSensor(index: number, patch: Partial<SensorSpec>) {
    setSensors((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  async function handleSaveSensors() {
    const error = validateSensorsMatchAcquisitionMode(acquisitionMode, sensors);
    if (error) {
      setSensorsError(error);
      return;
    }
    setSensorsError(null);
    setSavingSensors(true);
    try {
      const updated = await updateBuilderStationSensors(station.id, sensors, acquisitionMode);
      onUpdated(updated);
    } catch (err) {
      setSensorsError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingSensors(false);
    }
  }

  async function handleSaveDistance() {
    if (!upstreamSegment) return;
    setDistanceError(null);
    setSavingDistance(true);
    try {
      const updated = await updateBuilderSegmentDistance(
        upstreamSegment.from_station_id,
        station.id,
        distanceM,
      );
      onUpdated(updated);
    } catch (err) {
      setDistanceError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingDistance(false);
    }
  }

  async function handleClearBaseline() {
    const updated = await updateBuilderStationBaseline(station.id, null);
    onUpdated(updated);
  }

  async function handleRemove() {
    setRemoveError(null);
    try {
      const updated = await removeBuilderStation(station.id);
      onUpdated(updated);
      onClose();
    } catch (err) {
      setRemoveError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div
      style={{
        position: "absolute",
        top: "var(--space-4)",
        right: "var(--space-4)",
        // Capped, not stretched to the bottom -- the spawn tray lives in
        // that bottom-right corner too, and this panel must never cover it.
        maxHeight: "60vh",
        width: "var(--width-side-panel)",
        overflowY: "auto",
        background: "var(--color-cast-steel)",
        border: "1px solid var(--color-steel-neutral)",
        borderRadius: 4,
        padding: "var(--space-4)",
        zIndex: 10,
        color: "var(--color-vellum)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <p className="eyebrow" style={{ margin: 0 }}>
          {station.id} · {station.name}
        </p>
        <button onClick={onClose} aria-label="Close properties panel">
          ×
        </button>
      </div>

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Sensors
      </p>
      <label>
        Acquisition mode
        <select
          value={acquisitionMode}
          onChange={(e) => setAcquisitionMode(e.target.value as AcquisitionMode)}
        >
          {ACQUISITION_MODES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      {sensors.length === 0 && (
        <p className="data" style={{ color: "var(--color-steel-neutral)" }}>
          No sensors -- a manual station.
        </p>
      )}
      {sensors.map((sensor, i) => (
        <div key={i} style={{ display: "flex", gap: "var(--space-1)", alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={sensor.id}
            onChange={(e) => updateSensor(i, { id: e.target.value })}
            placeholder="sensor id"
            style={{ width: 90 }}
          />
          <select
            value={sensor.kind}
            onChange={(e) => updateSensor(i, { kind: e.target.value as SensorKind })}
          >
            {SENSOR_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => setSensors((prev) => prev.filter((_, idx) => idx !== i))}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={() => setSensors((prev) => [...prev, blankSensor()])}>
        Add sensor
      </button>
      {sensorsError && <p style={{ color: "var(--color-beacon-red)" }}>{sensorsError}</p>}
      <button onClick={() => void handleSaveSensors()} disabled={savingSensors}>
        {savingSensors ? "Saving…" : "Save sensors"}
      </button>

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Inter-station distance
      </p>
      {upstreamSegment ? (
        <>
          <label>
            Distance from {upstreamSegment.from_station_id} (m)
            <input
              type="number"
              min={0.01}
              step="any"
              value={distanceM}
              onChange={(e) => setDistanceM(Number(e.target.value))}
            />
          </label>
          {distanceError && <p style={{ color: "var(--color-beacon-red)" }}>{distanceError}</p>}
          <button onClick={() => void handleSaveDistance()} disabled={savingDistance}>
            {savingDistance ? "Saving…" : "Save distance"}
          </button>
        </>
      ) : (
        <p className="data" style={{ color: "var(--color-steel-neutral)" }}>
          First station -- no upstream segment.
        </p>
      )}

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Commissioning baseline
      </p>
      {station.commissioning_baseline ? (
        <p className="data">
          {Object.entries(station.commissioning_baseline.loaded.mean)
            .map(([quantity, mean]) => `${quantity}: ${mean.toFixed(2)}`)
            .join(", ") || "captured, no quantities"}
        </p>
      ) : (
        <p className="data" style={{ color: "var(--color-steel-neutral)" }}>
          No baseline set.
        </p>
      )}
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <button onClick={() => setWizardOpen(true)}>Commissioning wizard</button>
        {station.commissioning_baseline && (
          <button onClick={() => void handleClearBaseline()}>Clear baseline</button>
        )}
      </div>

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Danger zone
      </p>
      {removeError && <p style={{ color: "var(--color-beacon-red)" }}>{removeError}</p>}
      <button onClick={() => void handleRemove()}>Remove station</button>

      {wizardOpen && (
        <CommissioningWizard
          station={station}
          onClose={() => setWizardOpen(false)}
          onSaved={(updated) => {
            onUpdated(updated);
            setWizardOpen(false);
          }}
        />
      )}
    </div>
  );
}
