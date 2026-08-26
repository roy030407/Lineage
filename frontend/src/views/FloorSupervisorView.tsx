// Floor Supervisor role view: the full line, plus active alerts surfaced up
// front rather than requiring a scan of every station's lamps.

import { getFloorSupervisorView } from "../state/api";
import { useRolePoll } from "./useRolePoll";

export function FloorSupervisorView() {
  const view = useRolePoll(getFloorSupervisorView, []);

  if (!view) {
    return (
      <div style={{ padding: "2rem", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "0.5rem" }}>
          Loading line state…
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "2rem", color: "var(--color-vellum)" }}>
      <p className="eyebrow">Floor Supervisor view</p>

      <p className="eyebrow" style={{ marginTop: "1rem" }}>
        Active alerts ({view.active_alert_station_ids.length})
      </p>
      {view.active_alert_station_ids.length === 0 ? (
        <p>No stations currently in alarm.</p>
      ) : (
        <p style={{ color: "var(--color-beacon-red)" }}>
          {view.active_alert_station_ids.join(", ")}
        </p>
      )}

      <p className="eyebrow" style={{ marginTop: "1.5rem" }}>
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
              <td>{station.sensor_health}</td>
              <td>{station.machine_health}</td>
              <td>{station.upstream_buffer_depth}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
