// Side panel for a clicked station: live readings, commissioning baseline,
// acquisition mode. Readings come straight off the current LineState tick;
// baseline/mode come from LineSpec (already loaded, no extra fetch).

import type { CSSProperties } from "react";

import { useLineageStore } from "../state/store";

const panelStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  right: 0,
  width: "var(--width-side-panel)",
  height: "100%",
  background: "var(--color-cast-steel)",
  color: "var(--color-vellum)",
  padding: "var(--space-4)",
  overflowY: "auto",
  borderLeft: "1px solid var(--color-steel-neutral)",
};

export function StationPanel() {
  const lineSpec = useLineageStore((s) => s.lineSpec);
  const lineState = useLineageStore((s) => s.lineState);
  const selectedStationId = useLineageStore((s) => s.selectedStationId);
  const selectStation = useLineageStore((s) => s.selectStation);

  if (!selectedStationId || !lineSpec || !lineState) return null;

  const station = lineSpec.stations.find((s) => s.id === selectedStationId);
  const state = lineState.stations.find((s) => s.station_id === selectedStationId);
  if (!station || !state) return null;

  return (
    <div style={panelStyle}>
      <button onClick={() => selectStation(null)} style={{ float: "right" }} aria-label="Close">
        ✕
      </button>
      <h2 style={{ font: "var(--text-h1)" }}>{station.name}</h2>
      <p className="eyebrow">{station.id}</p>

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Acquisition mode
      </p>
      <p>{station.acquisition_mode}</p>

      <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
        Live readings
      </p>
      {state.latest_readings.length === 0 ? (
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          No readings reported yet
        </p>
      ) : (
        <table className="data" style={{ width: "100%" }}>
          <tbody>
            {state.latest_readings.map((reading) => (
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
      {station.commissioning_baseline ? (
        <table className="data" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Quantity</th>
              <th>Idle mean</th>
              <th>Loaded mean</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(station.commissioning_baseline.loaded.mean).map((quantity) => (
              <tr key={quantity}>
                <td>{quantity}</td>
                <td>{station.commissioning_baseline!.idle.mean[quantity]?.toFixed(2) ?? "—"}</td>
                <td>{station.commissioning_baseline!.loaded.mean[quantity]?.toFixed(2) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          No baseline commissioned
        </p>
      )}
    </div>
  );
}
