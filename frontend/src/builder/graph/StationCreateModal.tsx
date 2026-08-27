// The form that actually fills in a StationSpec after a tray drop resolves
// to a DropTarget (insert/prepend/append) -- a drop alone only tells us
// *where*, not the station's own id/name/machine/etc, so this always
// appears before the station is actually created. A manual station with no
// sensors is a first-class submit here, not an error: validation only
// blocks the one real invariant (sensors must match acquisition_mode), never
// "must have at least one sensor".

import type { FormEvent } from "react";
import { useState } from "react";

import {
  insertBuilderStation,
  prependBuilderStation,
} from "../../state/api";
import type {
  AcquisitionMode,
  LineSpec,
  SensorKind,
  SensorSpec,
  StationSpec,
  Zone,
} from "../../state/types";
import { validateNewStationId, validateSensorsMatchAcquisitionMode } from "../validation";
import type { DropTarget } from "./canvasLayout";
import type { StationTemplate } from "./SpawnTray";

const ZONES: Zone[] = ["body", "paint", "final"];
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
  target: DropTarget;
  template: StationTemplate;
  existingStationIds: string[];
  onCancel: () => void;
  onCreated: (line: LineSpec) => void;
}

function targetLabel(target: DropTarget): string {
  if (target.kind === "prepend") return "Insert at the front of the line";
  if (target.kind === "append") return "Append to the end of the line";
  return `Insert between ${target.upstreamId} and ${target.downstreamId}`;
}

export function StationCreateModal({ target, template, existingStationIds, onCancel, onCreated }: Props) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [zone, setZone] = useState<Zone>(template.zoneDefault ?? "body");
  const [acquisitionMode, setAcquisitionMode] = useState<AcquisitionMode>(
    template.acquisitionModeDefault,
  );
  const [cycleTimeNominalS, setCycleTimeNominalS] = useState(30);
  const [costPerHour, setCostPerHour] = useState(0);
  const [valueAddPct, setValueAddPct] = useState(0);
  const [machineModel, setMachineModel] = useState("");
  const [sensors, setSensors] = useState<SensorSpec[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function updateSensor(index: number, patch: Partial<SensorSpec>) {
    setSensors((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const idError = validateNewStationId(id, existingStationIds);
    if (idError) {
      setError(idError);
      return;
    }
    const sensorError = validateSensorsMatchAcquisitionMode(acquisitionMode, sensors);
    if (sensorError) {
      setError(sensorError);
      return;
    }
    setError(null);
    setSubmitting(true);

    const station: StationSpec = {
      id,
      name: name || id,
      zone,
      sequence_index: 0, // overwritten by the backend on insert/prepend
      sensors,
      acquisition_mode: acquisitionMode,
      is_inspection_station: false,
      cycle_time_nominal_s: cycleTimeNominalS,
      commissioning_baseline: null,
      changeable_params: {},
      readable_params: [],
      machine: {
        model: machineModel || "generic",
        install_year: new Date().getFullYear(),
        last_maintenance_date: new Date().toISOString().slice(0, 10),
        maintenance_interval_days: 90,
        wear_curve_shape: "linear",
      },
      cost_per_hour: costPerHour,
      value_add_pct: valueAddPct,
    };

    try {
      const line =
        target.kind === "prepend"
          ? await prependBuilderStation(station)
          : target.kind === "append"
            ? await insertBuilderStation(station, null)
            : await insertBuilderStation(station, target.upstreamId);
      onCreated(line);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Create station"
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 20,
      }}
    >
      <form
        onSubmit={(e) => void handleSubmit(e)}
        style={{
          background: "var(--color-cast-steel)",
          border: "1px solid var(--color-steel-neutral)",
          borderRadius: 4,
          padding: "var(--space-6)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-2)",
          maxHeight: "80vh",
          overflowY: "auto",
          width: 420,
        }}
      >
        <p className="eyebrow" style={{ margin: 0 }}>
          {targetLabel(target)}
        </p>
        <label>
          Station ID
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder="ST-99" required />
        </label>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Zone
          <select value={zone} onChange={(e) => setZone(e.target.value as Zone)}>
            {ZONES.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
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
        <label>
          Cycle time (s)
          <input
            type="number"
            min={0.01}
            step="any"
            value={cycleTimeNominalS}
            onChange={(e) => setCycleTimeNominalS(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Cost per hour
          <input
            type="number"
            min={0}
            step="any"
            value={costPerHour}
            onChange={(e) => setCostPerHour(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Value-add %
          <input
            type="number"
            min={0}
            max={100}
            step="any"
            value={valueAddPct}
            onChange={(e) => setValueAddPct(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Machine model
          <input value={machineModel} onChange={(e) => setMachineModel(e.target.value)} />
        </label>

        <p className="eyebrow" style={{ margin: "var(--space-2) 0 0" }}>
          Sensors ({sensors.length})
        </p>
        {sensors.map((sensor, i) => (
          <div key={i} style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
            <input
              value={sensor.id}
              onChange={(e) => updateSensor(i, { id: e.target.value })}
              placeholder="sensor id"
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

        {error && <p style={{ color: "var(--color-beacon-red)" }}>{error}</p>}

        <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
          <button type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create station"}
          </button>
          <button type="button" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
