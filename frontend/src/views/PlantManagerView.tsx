// Plant Manager role view: weekly, not live -- defect-rate trends, rework
// volume, recurring root causes from Trace history, and maintenance
// schedule versus predicted need. Deliberately no real-time firehose (that's
// Floor Supervisor's job): no live per-station table, and no auto-polling
// every couple of seconds like the other role views -- this is a report you
// pull, not a feed you watch.

import { useCallback, useEffect, useState } from "react";

import { HudPanel } from "../components/HudPanel";
import { StatTile } from "../components/StatTile";
import { getPlantManagerView } from "../state/api";
import type { PlantManagerView as PlantManagerViewData } from "../state/types";

function formatPct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

export function PlantManagerView() {
  const [view, setView] = useState<PlantManagerViewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setView(await getPlantManagerView());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="eyebrow">Plant Manager view</p>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Could not load the weekly report: {error}
        </p>
      </div>
    );
  }

  if (!view) {
    return (
      <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
        <p className="hazard-hatch" style={{ padding: "var(--space-2)" }}>
          Loading weekly report…
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "var(--space-8)", color: "var(--color-vellum)" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-4)" }}>
        <p className="eyebrow">Plant Manager view: weekly report</p>
        <button onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Defect rate by zone
        </p>
        <div style={{ display: "flex", gap: "var(--space-8)", marginTop: "var(--space-2)" }}>
          {view.defect_rate_by_zone.map((zone) => (
            <div key={zone.zone}>
              <StatTile label={zone.zone} value={zone.fail_rate * 100} format={(n) => `${n.toFixed(1)}%`} />
              <p className="data">
                {zone.fail_count} / {zone.total_inspections}
              </p>
            </div>
          ))}
        </div>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Defect rate by station
        </p>
        <table className="data" style={{ width: "100%", marginTop: "var(--space-2)" }}>
          <thead>
            <tr>
              <th>Station</th>
              <th>Zone</th>
              <th>Inspections</th>
              <th>Fails</th>
              <th>Fail rate</th>
            </tr>
          </thead>
          <tbody>
            {view.defect_rate_by_station.map((station) => (
              <tr key={station.station_id}>
                <td>{station.station_id}</td>
                <td>{station.zone}</td>
                <td>{station.total_inspections}</td>
                <td>{station.fail_count}</td>
                <td>{formatPct(station.fail_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Rework volume
        </p>
        <div style={{ display: "flex", gap: "var(--space-8)", marginTop: "var(--space-2)" }}>
          <StatTile label="Defect events" value={view.rework.total_defect_events} />
          <StatTile label="Cars requiring rework" value={view.rework.cars_requiring_rework} />
          <StatTile
            label="Rework rate"
            value={view.rework.rework_rate * 100}
            format={(n) => `${n.toFixed(1)}%`}
          />
        </div>
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Recurring root causes
        </p>
        {view.recurring_root_causes.length === 0 ? (
          <p>No traced defects yet for this run.</p>
        ) : (
          <table className="data" style={{ width: "100%", marginTop: "var(--space-2)" }}>
            <thead>
              <tr>
                <th>Origin station</th>
                <th>Occurrences</th>
                <th>Example cars</th>
              </tr>
            </thead>
            <tbody>
              {view.recurring_root_causes.map((cause) => (
                <tr key={cause.station_id}>
                  <td>{cause.station_id}</td>
                  <td title={`${cause.occurrence_count} total`}>
                    {cause.verified_occurrences} verified{" "}
                    <span style={{ color: "var(--color-steel-neutral)" }}>
                      · {cause.suspected_occurrences} suspected
                    </span>
                  </td>
                  <td>{cause.example_car_ids.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </HudPanel>

      <HudPanel>
        <p className="eyebrow" style={{ margin: 0 }}>
          Maintenance: schedule vs. predicted need
        </p>
        <table className="data" style={{ width: "100%", marginTop: "var(--space-2)" }}>
          <thead>
            <tr>
              <th>Station</th>
              <th>Machine</th>
              <th>Days since maintenance</th>
              <th>Days until due</th>
              <th>Recent wear state</th>
            </tr>
          </thead>
          <tbody>
            {view.maintenance_status.map((status) => (
              <tr key={status.station_id}>
                <td>{status.station_id}</td>
                <td>{status.machine_model}</td>
                <td>{status.days_since_maintenance.toFixed(1)}</td>
                <td style={{ color: status.days_until_due < 0 ? "var(--color-beacon-red)" : undefined }}>
                  {status.days_until_due.toFixed(1)}
                </td>
                <td>
                  {status.recent_wear_state === null ? "N/A" : status.recent_wear_state.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </HudPanel>
    </div>
  );
}
