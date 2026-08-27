// Leadership role view: real cost/value-add ROI numbers, replacing the old
// live occupied/alarm/buffer counters -- still no per-station live detail of
// any kind, now backed by StationSpec's cost_per_hour/value_add_pct (read by
// nothing else in the backend before this) and a sensor-retrofit ranking
// grounded in that plus real recurring-defect data, never a fabricated
// dollar "ROI" figure.

import { getLeadershipView } from "../state/api";
import { useRolePoll } from "./useRolePoll";

function formatPct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

function formatCost(perHour: number): string {
  return `${perHour.toFixed(2)}/hr`;
}

export function LeadershipView() {
  const view = useRolePoll(getLeadershipView, []);

  if (!view) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading summary…
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
      <p className="eyebrow">Leadership view</p>

      <div style={{ display: "flex", gap: "var(--space-12)", marginTop: "var(--space-6)" }}>
        <div>
          <p className="eyebrow">Total cost</p>
          <p style={{ font: "var(--text-h1)" }}>{formatCost(view.total_cost_per_hour)}</p>
        </div>
        <div>
          <p className="eyebrow">Value-added cost</p>
          <p style={{ font: "var(--text-h1)" }}>
            {formatCost(view.total_value_added_cost_per_hour)}
          </p>
        </div>
        <div>
          <p className="eyebrow">Value-added ratio</p>
          <p style={{ font: "var(--text-h1)" }}>{formatPct(view.value_added_ratio)}</p>
        </div>
      </div>

      <p className="eyebrow" style={{ marginTop: "var(--space-6)" }}>
        Cost by zone
      </p>
      <div style={{ display: "flex", gap: "var(--space-8)", marginTop: "var(--space-2)" }}>
        {view.cost_by_zone.map((zone) => (
          <div key={zone.zone}>
            <p className="eyebrow">{zone.zone}</p>
            <p className="data">{formatCost(zone.total_cost_per_hour)}</p>
            <p className="data">{formatPct(zone.value_added_ratio)} value-added</p>
          </div>
        ))}
      </div>

      <p className="eyebrow" style={{ marginTop: "var(--space-6)" }}>
        Sensor retrofit candidates ({view.sensor_retrofit_candidates.length})
      </p>
      <p>Manual stations, ranked by recurring defect impact and economic weight.</p>
      <table className="data" style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>Station</th>
            <th>Zone</th>
            <th>Cost</th>
            <th>Value-add</th>
            <th>Economic weight</th>
            <th>Recurring defects</th>
          </tr>
        </thead>
        <tbody>
          {view.sensor_retrofit_candidates.map((candidate) => (
            <tr key={candidate.station_id}>
              <td>{candidate.station_id}</td>
              <td>{candidate.zone}</td>
              <td>{formatCost(candidate.cost_per_hour)}</td>
              <td>{candidate.value_add_pct.toFixed(1)}%</td>
              <td>{candidate.economic_weight.toFixed(2)}</td>
              <td>{candidate.recurring_defect_occurrences}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
