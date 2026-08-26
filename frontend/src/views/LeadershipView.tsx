// Leadership role view: summary counters only -- the backend response has
// no per-station field at all, so there is nothing more detailed to show
// even by accident.

import { getLeadershipView } from "../state/api";
import { useRolePoll } from "./useRolePoll";

export function LeadershipView() {
  const view = useRolePoll(getLeadershipView, []);

  if (!view) {
    return (
      <div style={{ padding: "2rem", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "0.5rem" }}>
          Loading summary…
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "2rem", color: "var(--color-vellum)" }}>
      <p className="eyebrow">Leadership view</p>

      <div style={{ display: "flex", gap: "3rem", marginTop: "1.5rem" }}>
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
    </div>
  );
}
