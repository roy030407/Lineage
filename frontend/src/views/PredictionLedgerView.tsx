// Prediction Ledger role view: rolling precision/recall/false-alarm-rate/
// trust-score per station, plus an on-demand post-intervention trend check.
// data/models/ is gitignored, so "no ledger available" (409) is the common,
// expected case in a fresh environment -- shown explicitly, not as an
// endless "Loading..." or a swallowed error.

import { useEffect, useState } from "react";

import { getPredictMetricsByStation, getPredictTrend } from "../state/api";
import type { LedgerMetrics, TrendState } from "../state/types";

function formatRate(value: number | null): string {
  return value === null ? "N/A" : `${(value * 100).toFixed(0)}%`;
}

function MetricsRow({ stationId, metrics }: { stationId: string; metrics: LedgerMetrics }) {
  return (
    <tr>
      <td>{stationId}</td>
      <td>{metrics.sample_size}</td>
      <td>{formatRate(metrics.precision)}</td>
      <td>{formatRate(metrics.recall)}</td>
      <td>{formatRate(metrics.false_alarm_rate)}</td>
      <td>{formatRate(metrics.trust_score)}</td>
    </tr>
  );
}

export function PredictionLedgerView() {
  const [byStation, setByStation] = useState<Record<string, LedgerMetrics> | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [building, setBuilding] = useState(false);

  const [trendStationId, setTrendStationId] = useState("");
  const [interventionAt, setInterventionAt] = useState("");
  const [trend, setTrend] = useState<TrendState | null | undefined>(undefined);
  const [trendError, setTrendError] = useState<string | null>(null);

  // The backend's own first build is real, working, ~105s work -- not a
  // hang -- but this 5s poll used to have no guard against overlapping
  // itself: a poll landing mid-build started an entirely separate,
  // redundant build rather than waiting for the one already running (see
  // predict.py's prediction_ledger_lock for the matching backend fix).
  // inFlight/hasLoadedOnce are plain closure variables, not state, since
  // they only ever gate this effect's own re-entrancy and were never meant
  // to trigger a re-render themselves.
  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let hasLoadedOnce = false;

    async function load() {
      if (inFlight) return;
      inFlight = true;
      if (!hasLoadedOnce) setBuilding(true);
      try {
        const result = await getPredictMetricsByStation();
        if (!cancelled) {
          setByStation(result);
          setUnavailable(false);
          hasLoadedOnce = true;
        }
      } catch {
        if (!cancelled) setUnavailable(true);
      } finally {
        inFlight = false;
        if (!cancelled) setBuilding(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  async function checkTrend() {
    setTrendError(null);
    setTrend(undefined);
    try {
      // Sent as-is (no timezone suffix): run timestamps are naive datetimes
      // with no real timezone concept, and the datetime-local input's value
      // is already in that same "YYYY-MM-DDTHH:mm" shape -- converting via
      // Date.toISOString() would stamp on a UTC "Z" that doesn't belong,
      // and the backend can't compare a naive and an aware datetime.
      const result = await getPredictTrend(trendStationId, interventionAt);
      setTrend(result);
    } catch (err) {
      setTrendError(err instanceof Error ? err.message : String(err));
    }
  }

  if (unavailable) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="eyebrow">Prediction Ledger</p>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          No prediction ledger available for this run -- either no run is loaded, or no
          trained risk model was found under data/models/risk_v1.
        </p>
      </div>
    );
  }

  if (!byStation) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          {building
            ? "Building predictions: assessing every car against every inspection station it reached. This can take up to a couple of minutes the first time, then stays cached."
            : "Loading ledger..."}
        </p>
      </div>
    );
  }

  const stationIds = Object.keys(byStation);

  return (
    <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
      <p className="eyebrow">Prediction Ledger: per station</p>

      {stationIds.length === 0 ? (
        <p>No resolved predictions yet for this run.</p>
      ) : (
        <table className="data" style={{ width: "100%", marginTop: "var(--space-4)" }}>
          <thead>
            <tr>
              <th>Station</th>
              <th>Sample size</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>False alarm rate</th>
              <th>Trust score</th>
            </tr>
          </thead>
          <tbody>
            {stationIds.map((stationId) => (
              <MetricsRow key={stationId} stationId={stationId} metrics={byStation[stationId]} />
            ))}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: "var(--space-8)" }}>
        <p className="eyebrow">Post-intervention trend</p>
        <select value={trendStationId} onChange={(e) => setTrendStationId(e.target.value)}>
          <option value="">Select a station…</option>
          {stationIds.map((stationId) => (
            <option key={stationId} value={stationId}>
              {stationId}
            </option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={interventionAt}
          onChange={(e) => setInterventionAt(e.target.value)}
          style={{ marginLeft: "var(--space-2)" }}
        />
        <button
          onClick={() => void checkTrend()}
          disabled={!trendStationId || !interventionAt}
          style={{ marginLeft: "var(--space-2)" }}
        >
          Check trend
        </button>

        {trend === null && (
          <p style={{ marginTop: "var(--space-2)" }}>Not enough data yet for a verdict.</p>
        )}
        {trend && <p style={{ marginTop: "var(--space-2)" }}>Trend: {trend}</p>}
        {trendError && (
          <p style={{ color: "var(--color-beacon-red)", marginTop: "var(--space-2)" }}>
            {trendError}
          </p>
        )}
      </div>
    </div>
  );
}
