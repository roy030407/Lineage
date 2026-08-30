// Leadership role view: real cost/value-add ROI numbers, replacing the old
// live occupied/alarm/buffer counters -- still no per-station live detail of
// any kind, now backed by StationSpec's cost_per_hour/value_add_pct (read by
// nothing else in the backend before this) and a sensor-retrofit ranking
// grounded in that plus real recurring-defect data, never a fabricated
// dollar "ROI" figure. The payback panel below stays honest the same way:
// the only dollar figures are the user's own clearly-labeled assumptions.
//
// Like Plant Manager, this is a report you pull, not a feed you watch --
// fetch-once plus an explicit Refresh, no 2s auto-poll: nothing here is
// live data, and a judge tweaking the payback assumptions shouldn't race a
// background refetch.

import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";

import { HudPanel } from "../components/HudPanel";
import { StatTile } from "../components/StatTile";
import { getLeadershipView } from "../state/api";
import type { LeadershipView as LeadershipViewData, SensorRetrofitCandidate } from "../state/types";

function formatPct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

function formatCost(perHour: number): string {
  return `${perHour.toFixed(2)}/hr`;
}

/** Runs of the current size needed for the retrofit to pay for itself, or
 * null when there are no traced defects to attribute rework cost to. */
function paybackRuns(
  candidate: SensorRetrofitCandidate,
  retrofitCost: number,
  reworkCostPerDefect: number,
): number | null {
  const attributable = candidate.recurring_defect_occurrences * reworkCostPerDefect;
  if (attributable <= 0 || retrofitCost <= 0) return null;
  return retrofitCost / attributable;
}

function paybackLabel(runs: number | null, occurrences: number): string {
  if (occurrences === 0) return "no traced defects yet";
  if (runs === null) return "—";
  return `pays back in ~${runs.toFixed(1)} run${runs.toFixed(1) === "1.0" ? "" : "s"}`;
}

const MUTED: CSSProperties = { color: "var(--color-steel-neutral)" };

export function LeadershipView() {
  const [view, setView] = useState<LeadershipViewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Assumptions for the payback math -- deliberately editable and defaulted,
  // never presented as measured data.
  const [retrofitCost, setRetrofitCost] = useState(2500);
  const [reworkCost, setReworkCost] = useState(180);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setView(await getLeadershipView());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !view) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="eyebrow">Leadership view</p>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Could not load the summary: {error}
        </p>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "Retrying…" : "Retry"}
        </button>
      </div>
    );
  }

  if (!view) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading summary…
        </p>
      </div>
    );
  }

  const withPayback = view.sensor_retrofit_candidates.map((candidate) => ({
    candidate,
    runs: paybackRuns(candidate, retrofitCost, reworkCost),
  }));
  const phase1 = withPayback
    .filter(({ candidate }) => candidate.recurring_defect_occurrences > 0)
    .sort((a, b) => (a.runs ?? Infinity) - (b.runs ?? Infinity));
  const phase2 = withPayback
    .filter(({ candidate }) => candidate.recurring_defect_occurrences === 0)
    .sort((a, b) => b.candidate.economic_weight - a.candidate.economic_weight);

  return (
    <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-4)" }}>
        <p className="eyebrow">Leadership view</p>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
        {error && (
          <span className="data" style={{ color: "var(--color-beacon-red)" }}>
            Refresh failed: {error}
          </span>
        )}
      </div>

      <HudPanel>
        <div style={{ display: "flex", gap: "var(--space-12)" }}>
          <StatTile label="Total cost" value={view.total_cost_per_hour} format={formatCost} />
          <StatTile
            label="Value-added cost"
            value={view.total_value_added_cost_per_hour}
            format={formatCost}
          />
          <StatTile
            label="Value-added ratio"
            value={view.value_added_ratio * 100}
            format={(n) => `${n.toFixed(1)}%`}
          />
        </div>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
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
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
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
              <th style={MUTED}>of which suspected</th>
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
                <td style={MUTED}>{candidate.suspected_defect_occurrences}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Retrofit payback
        </p>
        <p style={MUTED}>
          Assumptions, adjust to your plant. Defect attribution here is suspected, not verified —
          these stations are uninstrumented, which is the point of the retrofit.
        </p>
        <div style={{ display: "flex", gap: "var(--space-8)", marginBottom: "var(--space-2)" }}>
          <label className="eyebrow" style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
            Sensor retrofit cost per station
            <input
              type="number"
              min={0}
              value={retrofitCost}
              onChange={(e) => setRetrofitCost(e.target.valueAsNumber || 0)}
              style={{ width: "6rem" }}
            />
          </label>
          <label className="eyebrow" style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
            Rework cost per defect
            <input
              type="number"
              min={0}
              value={reworkCost}
              onChange={(e) => setReworkCost(e.target.valueAsNumber || 0)}
              style={{ width: "6rem" }}
            />
          </label>
        </div>
        <table className="data" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Station</th>
              <th>Traced defects</th>
              <th style={MUTED}>of which suspected</th>
              <th>Rework cost this run</th>
              <th>Payback</th>
            </tr>
          </thead>
          <tbody>
            {withPayback.map(({ candidate, runs }) => (
              <tr key={candidate.station_id}>
                <td>{candidate.station_id}</td>
                <td>{candidate.recurring_defect_occurrences}</td>
                <td style={MUTED}>{candidate.suspected_defect_occurrences}</td>
                <td>
                  {(candidate.recurring_defect_occurrences * reworkCost).toFixed(0)}
                </td>
                <td>{paybackLabel(runs, candidate.recurring_defect_occurrences)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Phased rollout
        </p>
        <p className="eyebrow" style={{ marginBottom: 0 }}>
          Phase 1 — defects already traced here (fastest payback first)
        </p>
        {phase1.length === 0 ? (
          <p style={MUTED}>No candidates with traced defects this run.</p>
        ) : (
          <ol style={{ marginTop: "var(--space-1)" }}>
            {phase1.map(({ candidate, runs }) => (
              <li key={candidate.station_id} className="data">
                {candidate.station_id} — {candidate.recurring_defect_occurrences} traced defect
                {candidate.recurring_defect_occurrences === 1 ? "" : "s"},{" "}
                {paybackLabel(runs, candidate.recurring_defect_occurrences)}
              </li>
            ))}
          </ol>
        )}
        <p className="eyebrow" style={{ marginBottom: 0 }}>
          Phase 2 — no traced defects yet (by economic weight)
        </p>
        {phase2.length === 0 ? (
          <p style={MUTED}>Every candidate already has traced defects.</p>
        ) : (
          <ol style={{ marginTop: "var(--space-1)" }}>
            {phase2.map(({ candidate }) => (
              <li key={candidate.station_id} className="data">
                {candidate.station_id} — economic weight {candidate.economic_weight.toFixed(2)}
              </li>
            ))}
          </ol>
        )}
      </HudPanel>
    </div>
  );
}
