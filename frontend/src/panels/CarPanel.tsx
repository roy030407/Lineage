// Side panel for a clicked car: its full twin -- every station passed, the
// readings taken there, and how long it dwelled. Fetched once on selection
// via GET /api/cars/{car_id}.

import type { CSSProperties } from "react";

import { useLineageStore } from "../state/store";

const panelStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  right: 0,
  width: "320px",
  height: "100%",
  background: "var(--color-cast-steel)",
  color: "var(--color-vellum)",
  padding: "1rem",
  overflowY: "auto",
  borderLeft: "1px solid var(--color-steel-neutral)",
};

function dwellSeconds(entry: string, exit: string): number {
  return (new Date(exit).getTime() - new Date(entry).getTime()) / 1000;
}

export function CarPanel() {
  const selectedCarId = useLineageStore((s) => s.selectedCarId);
  const carTwin = useLineageStore((s) => s.selectedCarTwin);
  const selectCar = useLineageStore((s) => s.selectCar);

  if (!selectedCarId) return null;

  return (
    <div style={panelStyle}>
      <button onClick={() => void selectCar(null)} style={{ float: "right" }} aria-label="Close">
        ✕
      </button>
      <h2 style={{ font: "var(--text-h1)" }}>{selectedCarId}</h2>

      {!carTwin ? (
        <p className="eyebrow">Loading twin history…</p>
      ) : (
        <>
          <p className="eyebrow">{carTwin.model_variant}</p>
          <p className="eyebrow" style={{ marginTop: "1rem" }}>
            Stations visited ({carTwin.visits.length})
          </p>
          {carTwin.visits.map((visit) => (
            <div
              key={visit.station_id}
              style={{ borderTop: "1px solid var(--color-steel-neutral)", padding: "0.5rem 0" }}
            >
              <p style={{ font: "var(--text-h2)" }}>{visit.station_id}</p>
              <p className="data">
                dwell: {dwellSeconds(visit.entry_time, visit.exit_time).toFixed(1)}s
              </p>
              {visit.readings.length === 0 ? (
                <p className="eyebrow">no reading recorded</p>
              ) : (
                <table className="data" style={{ width: "100%" }}>
                  <tbody>
                    {visit.readings.map((reading) => (
                      <tr key={reading.sensor_id}>
                        <td>{reading.quantity}</td>
                        <td>{reading.value.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
