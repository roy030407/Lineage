// Side panel for a clicked car: its full twin -- every station passed, the
// readings taken there, and how long it dwelled. Fetched once on selection
// via GET /api/cars/{car_id}. Plus on-demand root-cause tracing via
// GET /api/trace/{car_id} (TraceSection below).

import type { CSSProperties } from "react";
import { useState } from "react";

import { ApiError, getCarTrace } from "../state/api";
import { useLineageStore } from "../state/store";
import type { TraceResult } from "../state/types";

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

function dwellSeconds(entry: string, exit: string): number {
  return (new Date(exit).getTime() - new Date(entry).getTime()) / 1000;
}

const TOP_N = 5;

/** Remounted with a fresh `key` per car (see CarPanel below), so a previous
 * car's trace never lingers under a newly selected car's heading. */
function TraceSection({ carId }: { carId: string }) {
  const [loading, setLoading] = useState(false);
  const [trace, setTrace] = useState<TraceResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runTrace() {
    setLoading(true);
    setError(null);
    try {
      setTrace(await getCarTrace(carId));
    } catch (err) {
      setTrace(null);
      if (err instanceof ApiError && err.status === 409) {
        setError("No run loaded — load or simulate a run first.");
      } else if (err instanceof ApiError && err.status === 404) {
        setError("This car is unknown to the loaded run.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ borderTop: "1px solid var(--color-steel-neutral)", marginTop: "var(--space-4)", paddingTop: "var(--space-2)" }}>
      <button onClick={() => void runTrace()} disabled={loading}>
        {loading ? "Tracing…" : "Trace root cause"}
      </button>
      {error && (
        <p className="data" style={{ color: "var(--color-beacon-red)" }}>
          {error}
        </p>
      )}
      {trace && (
        <div>
          <p className="eyebrow" style={{ marginTop: "var(--space-2)" }}>
            Originating station
          </p>
          <p style={{ font: "var(--text-h2)", margin: 0 }}>
            {trace.originating_station_id ?? "unknown"}
            {trace.originating_station_id && !trace.originating_is_verifiable && (
              <span
                className="eyebrow hazard-hatch"
                style={{ marginLeft: "var(--space-2)", padding: "0 var(--space-1)" }}
              >
                unverifiable — manual station
              </span>
            )}
          </p>

          <p className="eyebrow" style={{ marginTop: "var(--space-2)" }}>
            Top contributions
          </p>
          {trace.contributions.length === 0 ? (
            <p className="eyebrow">no contributing stations</p>
          ) : (
            <table className="data" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Station</th>
                  <th>Score</th>
                  <th>z</th>
                </tr>
              </thead>
              <tbody>
                {trace.contributions.slice(0, TOP_N).map((contribution) => (
                  <tr key={contribution.station_id}>
                    <td>{contribution.station_id}</td>
                    <td>{contribution.score.toFixed(2)}</td>
                    <td>{contribution.deviation_z.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="eyebrow" style={{ marginTop: "var(--space-2)" }}>
            Exposed cohort ({trace.exposed_cohort.length})
          </p>
          {trace.exposed_cohort.length === 0 ? (
            <p className="eyebrow">no other cars exposed</p>
          ) : (
            <table className="data" style={{ width: "100%" }}>
              <tbody>
                {trace.exposed_cohort.slice(0, TOP_N).map((member) => (
                  <tr key={member.car_id}>
                    <td>{member.car_id}</td>
                    <td>{(member.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export function CarPanel() {
  const selectedCarId = useLineageStore((s) => s.selectedCarId);
  const carTwin = useLineageStore((s) => s.selectedCarTwin);
  const selectCar = useLineageStore((s) => s.selectCar);
  const runLoaded = useLineageStore((s) => s.lineState !== null);

  if (!selectedCarId) return null;

  return (
    <div className="panel-in" style={panelStyle}>
      <button onClick={() => void selectCar(null)} style={{ float: "right" }} aria-label="Close">
        ✕
      </button>
      <h2 style={{ font: "var(--text-h1)" }}>{selectedCarId}</h2>

      {!carTwin ? (
        <p className="eyebrow">Loading twin history…</p>
      ) : (
        <>
          <p className="eyebrow">{carTwin.model_variant}</p>
          {runLoaded && <TraceSection key={selectedCarId} carId={selectedCarId} />}
          <p className="eyebrow" style={{ marginTop: "var(--space-4)" }}>
            Stations visited ({carTwin.visits.length})
          </p>
          {carTwin.visits.map((visit) => (
            <div
              key={visit.station_id}
              style={{
                borderTop: "1px solid var(--color-steel-neutral)",
                padding: "var(--space-2) 0",
              }}
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
