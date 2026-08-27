// Operator role view: exactly one station, nothing else -- the backend
// itself only returns that one station's data (GET /api/view/operator),
// so there is no other line-wide state available here to leak by mistake.

import { useMemo, useState } from "react";

import { StatusBadge } from "../components/StatusBadge";
import { getOperatorView } from "../state/api";
import { useLineageStore } from "../state/store";
import { MACHINE_HEALTH_TOKENS, SENSOR_HEALTH_TOKENS } from "../styles/tokens";
import { useRolePoll } from "./useRolePoll";

export function OperatorView() {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const stations = useMemo(
    () => [...(lineSpec?.stations ?? [])].sort((a, b) => a.sequence_index - b.sequence_index),
    [lineSpec],
  );
  const [stationId, setStationId] = useState<string | null>(null);
  const activeStationId = stationId ?? stations[0]?.id ?? null;

  const view = useRolePoll(
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

      {!view ? (
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading station state…
        </p>
      ) : (
        <>
          <h2 style={{ font: "var(--text-h1)" }}>{view.station_name}</h2>
          <p className="eyebrow">{view.station_id}</p>

          <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
            Sensor health: <StatusBadge token={SENSOR_HEALTH_TOKENS[view.sensor_health]} />
          </p>
          <p className="eyebrow">
            Machine health: <StatusBadge token={MACHINE_HEALTH_TOKENS[view.machine_health]} />
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
                    <td>{view.commissioning_baseline!.idle.mean[quantity]?.toFixed(2) ?? "—"}</td>
                    <td>
                      {view.commissioning_baseline!.loaded.mean[quantity]?.toFixed(2) ?? "—"}
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
        </>
      )}
    </div>
  );
}
