// Form fields for a single station/sensor definition within the builder.
// Builds a full StationSpec locally, then hands it up on submit -- the
// backend is still the source of truth (it re-validates and re-numbers
// sequence_index via insert_station), this is just so a user gets an
// immediate "a manual station can't have sensors" instead of a round trip.

import type { FormEvent } from "react";
import { useState } from "react";

import type {
  AcquisitionMode,
  SensorKind,
  SensorSpec,
  StationSpec,
  Zone,
} from "../state/types";
import { validateNewStationId, validateSensorsMatchAcquisitionMode } from "./validation";

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

interface Props {
  existingStationIds: string[];
  onSubmit: (station: StationSpec, afterStationId: string | null) => void;
  submitting: boolean;
  error: string | null;
}

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

export function StationBuilderForm({ existingStationIds, onSubmit, submitting, error }: Props) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [zone, setZone] = useState<Zone>("body");
  const [acquisitionMode, setAcquisitionMode] = useState<AcquisitionMode>("manual");
  const [cycleTimeNominalS, setCycleTimeNominalS] = useState(30);
  const [costPerHour, setCostPerHour] = useState(0);
  const [valueAddPct, setValueAddPct] = useState(0);
  const [isInspectionStation, setIsInspectionStation] = useState(false);
  const [machineModel, setMachineModel] = useState("");
  const [machineInstallYear, setMachineInstallYear] = useState(new Date().getFullYear());
  const [machineLastMaintenanceDate, setMachineLastMaintenanceDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [machineMaintenanceIntervalDays, setMachineMaintenanceIntervalDays] = useState(90);
  const [machineWearCurveShape, setMachineWearCurveShape] = useState("linear");
  const [sensors, setSensors] = useState<SensorSpec[]>([]);
  // null ("at the end") is the only way to append after the current last
  // station -- insert_station explicitly rejects after_station_id set to
  // the last station's own id, so defaulting to it would guarantee a 400.
  const [afterStationId, setAfterStationId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  function updateSensor(index: number, patch: Partial<SensorSpec>) {
    setSensors((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();

    const idError = validateNewStationId(id, existingStationIds);
    if (idError) {
      setLocalError(idError);
      return;
    }
    const sensorError = validateSensorsMatchAcquisitionMode(acquisitionMode, sensors);
    if (sensorError) {
      setLocalError(sensorError);
      return;
    }
    setLocalError(null);

    const station: StationSpec = {
      id,
      name,
      zone,
      sequence_index: 0, // overwritten by insert_station on the backend
      sensors,
      acquisition_mode: acquisitionMode,
      is_inspection_station: isInspectionStation,
      cycle_time_nominal_s: cycleTimeNominalS,
      commissioning_baseline: null,
      changeable_params: {},
      readable_params: [],
      machine: {
        model: machineModel,
        install_year: machineInstallYear,
        last_maintenance_date: machineLastMaintenanceDate,
        maintenance_interval_days: machineMaintenanceIntervalDays,
        wear_curve_shape: machineWearCurveShape,
      },
      cost_per_hour: costPerHour,
      value_add_pct: valueAddPct,
    };
    onSubmit(station, afterStationId);
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <p className="eyebrow">Insert a new station</p>

      <label>
        Station ID
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder="ST-99" required />
      </label>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
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
        <input
          type="checkbox"
          checked={isInspectionStation}
          onChange={(e) => setIsInspectionStation(e.target.checked)}
        />
        Inspection station
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

      <p className="eyebrow" style={{ marginTop: "0.5rem" }}>
        Machine
      </p>
      <label>
        Model
        <input value={machineModel} onChange={(e) => setMachineModel(e.target.value)} required />
      </label>
      <label>
        Install year
        <input
          type="number"
          value={machineInstallYear}
          onChange={(e) => setMachineInstallYear(Number(e.target.value))}
          required
        />
      </label>
      <label>
        Last maintenance date
        <input
          type="date"
          value={machineLastMaintenanceDate}
          onChange={(e) => setMachineLastMaintenanceDate(e.target.value)}
          required
        />
      </label>
      <label>
        Maintenance interval (days)
        <input
          type="number"
          min={1}
          value={machineMaintenanceIntervalDays}
          onChange={(e) => setMachineMaintenanceIntervalDays(Number(e.target.value))}
          required
        />
      </label>
      <label>
        Wear curve shape
        <input
          value={machineWearCurveShape}
          onChange={(e) => setMachineWearCurveShape(e.target.value)}
          required
        />
      </label>

      <p className="eyebrow" style={{ marginTop: "0.5rem" }}>
        Sensors ({sensors.length})
      </p>
      {sensors.map((sensor, i) => (
        <div
          key={i}
          style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}
        >
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
          <input
            value={sensor.unit}
            onChange={(e) => updateSensor(i, { unit: e.target.value })}
            placeholder="unit"
          />
          <input
            type="number"
            step="any"
            min={0.01}
            value={sensor.sample_rate_hz}
            onChange={(e) => updateSensor(i, { sample_rate_hz: Number(e.target.value) })}
            aria-label="sample rate hz"
          />
          <button
            type="button"
            onClick={() => setSensors((prev) => prev.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={() => setSensors((prev) => [...prev, blankSensor()])}>
        Add sensor
      </button>

      <label style={{ marginTop: "0.5rem" }}>
        Insert after
        <select
          value={afterStationId ?? ""}
          onChange={(e) => setAfterStationId(e.target.value || null)}
        >
          <option value="">(at the end)</option>
          {existingStationIds.map((sid) => (
            <option key={sid} value={sid}>
              {sid}
            </option>
          ))}
        </select>
      </label>

      {(localError ?? error) && (
        <p style={{ color: "var(--color-beacon-red)" }}>{localError ?? error}</p>
      )}

      <button type="submit" disabled={submitting} style={{ marginTop: "0.5rem" }}>
        {submitting ? "Inserting…" : "Insert station"}
      </button>
    </form>
  );
}
