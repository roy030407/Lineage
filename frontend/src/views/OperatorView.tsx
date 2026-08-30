// Operator role view: exactly one station, nothing else -- the backend
// itself only returns that one station's data (GET /api/view/operator),
// so there is no other line-wide state available here to leak by mistake.
// Deliberately narrow per DESIGN.md: an operator sees their own station in
// depth (readings vs. baseline, sensor/machine/handover/calibration status,
// a handover checklist), never the rest of the line.

import { useEffect, useMemo, useRef, useState } from "react";

import { HudPanel } from "../components/HudPanel";
import { StatusBadge } from "../components/StatusBadge";
import { getOperatorView } from "../state/api";
import { useLineageStore } from "../state/store";
import {
  MACHINE_HEALTH_TOKENS,
  SENSOR_HEALTH_TOKENS,
  SPC_STATE_TOKENS,
} from "../styles/tokens";
import { useRolePoll } from "./useRolePoll";

const CHECKLIST_ITEMS = [
  "Confirm sensor readings are within baseline",
  "Acknowledge any active sensor or machine alarms",
  "Verify machine maintenance is current",
  "Log handover notes for the next shift",
];

function checklistStorageKey(stationId: string): string {
  return `lineage.handover-checklist.${stationId}`;
}

function loadChecklist(stationId: string): boolean[] {
  try {
    const raw = localStorage.getItem(checklistStorageKey(stationId));
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (Array.isArray(parsed) && parsed.length === CHECKLIST_ITEMS.length) {
      return parsed as boolean[];
    }
  } catch {
    // localStorage can throw (private browsing, quota) -- fall through to a
    // fresh checklist; it still works for this session, just won't persist.
  }
  return CHECKLIST_ITEMS.map(() => false);
}

/** Remounted with a fresh `key` per station (see OperatorView below), so its
 * local state never leaks between stations when the operator switches. */
function HandoverChecklist({
  stationId,
  recalibrating,
}: {
  stationId: string;
  recalibrating: boolean;
}) {
  const [checked, setChecked] = useState<boolean[]>(() => loadChecklist(stationId));
  const wasRecalibrating = useRef(recalibrating);

  useEffect(() => {
    // A false -> true transition is a real, backend-detected handover (see
    // SPCVerdict.recalibrating) -- the previous shift's checklist is done,
    // reset it for whoever is coming on now, not just whenever this
    // component happens to remount.
    if (recalibrating && !wasRecalibrating.current) {
      setChecked(CHECKLIST_ITEMS.map(() => false));
    }
    wasRecalibrating.current = recalibrating;
  }, [recalibrating]);

  useEffect(() => {
    try {
      localStorage.setItem(checklistStorageKey(stationId), JSON.stringify(checked));
    } catch {
      // see loadChecklist's comment -- non-fatal if storage isn't available.
    }
  }, [stationId, checked]);

  return (
    <div>
      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Handover checklist
      </p>
      {CHECKLIST_ITEMS.map((item, i) => (
        <label key={item} style={{ display: "block", marginTop: "var(--space-1)" }}>
          <input
            type="checkbox"
            checked={checked[i] ?? false}
            onChange={() =>
              setChecked((prev) => prev.map((value, index) => (index === i ? !value : value)))
            }
          />{" "}
          {item}
        </label>
      ))}
      <button
        onClick={() => setChecked(CHECKLIST_ITEMS.map(() => false))}
        style={{ marginTop: "var(--space-2)" }}
      >
        Reset checklist
      </button>
    </div>
  );
}

export function OperatorView() {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const stations = useMemo(
    () => [...(lineSpec?.stations ?? [])].sort((a, b) => a.sequence_index - b.sequence_index),
    [lineSpec],
  );
  const [stationId, setStationId] = useState<string | null>(null);
  const activeStationId = stationId ?? stations[0]?.id ?? null;

  const { data: view, error } = useRolePoll(
    () => (activeStationId ? getOperatorView(activeStationId) : Promise.resolve(null)),
    [activeStationId],
  );

  if (!lineSpec) return null;

  return (
    <div
      style={{
        padding: "var(--space-8)",
        color: "var(--color-vellum)",
        maxWidth: "var(--width-readable-measure)",
      }}
    >
      <p className="eyebrow">Operator view</p>
      <select
        value={activeStationId ?? ""}
        onChange={(event) => setStationId(event.target.value)}
        aria-label="My station"
        style={{ marginBottom: "var(--space-6)" }}
      >
        {stations.map((station) => (
          <option key={station.id} value={station.id}>
            {station.name} ({station.id})
          </option>
        ))}
      </select>

      {view && error && (
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Backend unreachable, retrying… (showing last known state)
        </p>
      )}

      {!view ? (
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          {error ? "Backend unreachable, retrying…" : "Loading station state…"}
        </p>
      ) : (
        <HudPanel>
          <h2 style={{ font: "var(--text-h1)", marginTop: 0 }}>{view.station_name}</h2>
          <p className="eyebrow">{view.station_id}</p>

          <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
            Sensor health: <StatusBadge token={SENSOR_HEALTH_TOKENS[view.sensor_health]} />
          </p>
          <p className="eyebrow">
            Machine health: <StatusBadge token={MACHINE_HEALTH_TOKENS[view.machine_health]} />
          </p>
          <p className="eyebrow">
            Handover status:{" "}
            {view.spc_verdict?.recalibrating
              ? "Recalibrating after handover"
              : "Settled, no active handover"}
          </p>
          <p className="eyebrow">
            Calibration state:{" "}
            {view.spc_verdict ? (
              <StatusBadge token={SPC_STATE_TOKENS[view.spc_verdict.state]} />
            ) : (
              "No reading history yet"
            )}
          </p>

          <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
            Live readings
          </p>
          {view.latest_readings.length === 0 ? (
            <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
              No readings reported yet
            </p>
          ) : (
            <table className="data" style={{ width: "100%" }}>
              <tbody>
                {view.latest_readings.map((reading) => (
                  <tr key={reading.sensor_id}>
                    <td>{reading.quantity}</td>
                    <td>{reading.value.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
            Commissioning baseline
          </p>
          {view.commissioning_baseline ? (
            <table className="data" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Quantity</th>
                  <th>Idle mean</th>
                  <th>Loaded mean</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(view.commissioning_baseline.loaded.mean).map((quantity) => (
                  <tr key={quantity}>
                    <td>{quantity}</td>
                    <td>{view.commissioning_baseline!.idle.mean[quantity]?.toFixed(2) ?? "N/A"}</td>
                    <td>
                      {view.commissioning_baseline!.loaded.mean[quantity]?.toFixed(2) ?? "N/A"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
              No baseline commissioned
            </p>
          )}

          <HandoverChecklist
            key={view.station_id}
            stationId={view.station_id}
            recalibrating={view.spc_verdict?.recalibrating ?? false}
          />
        </HudPanel>
      )}
    </div>
  );
}
