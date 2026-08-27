// Plant Manager role view: line-wide summary counters up front, full
// per-station detail below for anyone drilling in.

import { StatusBadge } from "../components/StatusBadge";
import { getPlantManagerView } from "../state/api";
import { MACHINE_HEALTH_TOKENS, SENSOR_HEALTH_TOKENS } from "../styles/tokens";
import { useRolePoll } from "./useRolePoll";

export function PlantManagerView() {
  const view = useRolePoll(getPlantManagerView, []);

  if (!view) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading line state…
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
      <p className="eyebrow">Plant Manager view</p>

      <div style={{ display: "flex", gap: "var(--space-8)", marginTop: "var(--space-4)" }}>
        <div>
          <p className="eyebrow">Occupied stations</p>
          <p style={{ font: "var(--text-h1)" }}>{view.summary.occupied_station_count}</p>
        </div>
        <div>
          <p className="eyebrow">Stations in alarm</p>
          <p style={{ font: "var(--text-h1)" }}>{view.summary.alarm_station_count}</p>
        </div>
        <div>
          <p className="eyebrow">Avg. upstream buffer</p>
          <p style={{ font: "var(--text-h1)" }}>
            {view.summary.average_upstream_buffer_depth.toFixed(1)}
          </p>
        </div>
      </div>

      <p className="eyebrow" style={{ marginTop: "var(--space-6)" }}>
        All stations
      </p>
      <table className="data" style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>Station</th>
            <th>Car</th>
            <th>Sensor</th>
            <th>Machine</th>
            <th>Buffer</th>
          </tr>
        </thead>
        <tbody>
          {view.line_state.stations.map((station) => (
            <tr key={station.station_id}>
              <td>{station.station_id}</td>
              <td>{station.car_id ?? "—"}</td>
              <td>
                <StatusBadge token={SENSOR_HEALTH_TOKENS[station.sensor_health]} />
              </td>
              <td>
                <StatusBadge token={MACHINE_HEALTH_TOKENS[station.machine_health]} />
              </td>
              <td>{station.upstream_buffer_depth}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
