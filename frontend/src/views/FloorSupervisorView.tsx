// Floor Supervisor role view: the Mirror itself, plus a live alert queue --
// SPC alarms, high-risk cars, bottleneck warnings -- surfaced up front
// rather than requiring a scan of every station's lamps. Can assign an
// issue to an operator and approve Act proposals (act/models.py's
// MINIMUM_APPROVER_ROLE is floor_supervisor, so this is the first role that
// can).

import { useState } from "react";

import { HudPanel } from "../components/HudPanel";
import { StatusBadge } from "../components/StatusBadge";
import {
  approveActProposal,
  assignIssue,
  getFloorSupervisorView,
  listActProposals,
  unassignIssue,
} from "../state/api";
import { Scene } from "../scene/Scene";
import {
  MACHINE_HEALTH_TOKENS,
  RISK_LEVEL_TOKENS,
  SENSOR_HEALTH_TOKENS,
  SPC_STATE_TOKENS,
} from "../styles/tokens";
import { useRolePoll } from "./useRolePoll";

function AssignControl({
  issueId,
  assignedTo,
}: {
  issueId: string;
  assignedTo: string | undefined;
}) {
  const [operatorId, setOperatorId] = useState("");
  const [busy, setBusy] = useState(false);

  if (assignedTo) {
    return (
      <span className="eyebrow">
        Assigned: {assignedTo}{" "}
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await unassignIssue(issueId);
            } finally {
              setBusy(false);
            }
          }}
        >
          Unassign
        </button>
      </span>
    );
  }

  return (
    <span style={{ display: "inline-flex", gap: "var(--space-1)", alignItems: "center" }}>
      <input
        value={operatorId}
        onChange={(e) => setOperatorId(e.target.value)}
        placeholder="operator id"
        style={{ width: "8rem" }}
        aria-label={`Assign operator for ${issueId}`}
      />
      <button
        disabled={busy || !operatorId}
        onClick={async () => {
          setBusy(true);
          try {
            await assignIssue(issueId, operatorId);
            setOperatorId("");
          } finally {
            setBusy(false);
          }
        }}
      >
        Assign
      </button>
    </span>
  );
}

function ActProposalsPanel() {
  const proposals = useRolePoll(listActProposals, []);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  if (!proposals) return null;
  const pending = proposals.filter((p) => p.status === "pending");

  return (
    <HudPanel accentColor="var(--color-beacon-amber)">
      <p className="eyebrow" style={{ margin: 0 }}>
        Act proposals pending approval ({pending.length})
      </p>
      {pending.length === 0 ? (
        <p>No pending proposals.</p>
      ) : (
        pending.map((proposal) => (
          <div
            key={proposal.proposal_id}
            style={{ borderTop: "1px solid var(--color-steel-neutral)", padding: "var(--space-2) 0" }}
          >
            <p className="eyebrow">
              {proposal.station_id} · {proposal.parameter_name}
            </p>
            <p>
              {proposal.current_value.toFixed(2)} → {proposal.proposed_value.toFixed(2)}
            </p>
            <p>{proposal.rationale}</p>
            <button
              disabled={approvingId === proposal.proposal_id}
              onClick={async () => {
                setApprovingId(proposal.proposal_id);
                try {
                  await approveActProposal(proposal.proposal_id, "SUPERVISOR");
                } finally {
                  setApprovingId(null);
                }
              }}
            >
              Approve
            </button>
          </div>
        ))
      )}
    </HudPanel>
  );
}

export function FloorSupervisorView() {
  const view = useRolePoll(getFloorSupervisorView, []);

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
    <div style={{ display: "flex", height: "100%", color: "var(--color-vellum)" }}>
      <div style={{ flex: 2, minWidth: 0, position: "relative" }}>
        <Scene />
      </div>
      <div
        style={{
          flex: 1,
          minWidth: "22rem",
          overflowY: "auto",
          padding: "var(--space-6)",
          borderLeft: "1px solid var(--color-steel-neutral)",
        }}
      >
        <p className="eyebrow">Floor Supervisor view</p>

        <HudPanel accentColor={view.active_alert_station_ids.length > 0 ? "var(--color-beacon-red)" : undefined}>
          <p className="eyebrow" style={{ margin: 0 }}>
            Active alerts ({view.active_alert_station_ids.length})
          </p>
          {view.active_alert_station_ids.length === 0 ? (
            <p>No stations currently in alarm.</p>
          ) : (
            <p style={{ color: "var(--color-beacon-red)" }}>
              {view.active_alert_station_ids.join(", ")}
            </p>
          )}
        </HudPanel>

        <HudPanel>
          <p className="eyebrow" style={{ margin: 0 }}>
            SPC alarms ({view.spc_alarms.length})
          </p>
          {view.spc_alarms.length === 0 ? (
            <p>No stations out of control.</p>
          ) : (
            view.spc_alarms.map((alarm) => (
              <div
                key={alarm.station_id}
                style={{ borderTop: "1px solid var(--color-steel-neutral)", padding: "var(--space-2) 0" }}
              >
                <p className="eyebrow">
                  {alarm.station_id} · {alarm.quantity}
                </p>
                <StatusBadge token={SPC_STATE_TOKENS[alarm.state]} />
                {alarm.rule_triggered && <p>{alarm.rule_triggered}</p>}
                <AssignControl issueId={alarm.station_id} assignedTo={view.issue_assignments[alarm.station_id]} />
              </div>
            ))
          )}
        </HudPanel>

        <HudPanel>
          <p className="eyebrow" style={{ margin: 0 }}>
            High-risk cars ({view.high_risk_cars.length})
          </p>
          {view.high_risk_cars.length === 0 ? (
            <p>No high-risk cars currently on the line.</p>
          ) : (
            view.high_risk_cars.map((car) => (
              <div
                key={car.car_id}
                style={{ borderTop: "1px solid var(--color-steel-neutral)", padding: "var(--space-2) 0" }}
              >
                <p className="eyebrow">
                  {car.car_id} · at {car.current_station_id}
                </p>
                <StatusBadge token={RISK_LEVEL_TOKENS[car.risk_level]} />
                <p>
                  {car.stations_remaining} station{car.stations_remaining === 1 ? "" : "s"} until{" "}
                  {car.next_inspection_station_id}
                </p>
                <AssignControl issueId={car.car_id} assignedTo={view.issue_assignments[car.car_id]} />
              </div>
            ))
          )}
        </HudPanel>

        <HudPanel>
          <p className="eyebrow" style={{ margin: 0 }}>
            Bottleneck warnings ({view.bottleneck_warnings.length})
          </p>
          {view.bottleneck_warnings.length === 0 ? (
            <p>No developing bottlenecks.</p>
          ) : (
            view.bottleneck_warnings.map((warning) => (
              <div
                key={warning.station_id}
                style={{ borderTop: "1px solid var(--color-steel-neutral)", padding: "var(--space-2) 0" }}
              >
                <p className="eyebrow">
                  {warning.station_id} · {warning.predicted_state}
                </p>
                <p>
                  {warning.minutes_to_onset !== null
                    ? `${warning.minutes_to_onset.toFixed(1)} min to onset`
                    : "onset unknown"}
                  {warning.contributing_upstream_station &&
                    ` (from ${warning.contributing_upstream_station})`}
                </p>
                <AssignControl
                  issueId={warning.station_id}
                  assignedTo={view.issue_assignments[warning.station_id]}
                />
              </div>
            ))
          )}
        </HudPanel>

        <ActProposalsPanel />

        <HudPanel>
          <p className="eyebrow" style={{ margin: 0 }}>
            All stations
          </p>
          <table className="data" style={{ width: "100%", marginTop: "var(--space-2)" }}>
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
                  <td>{station.car_id ?? "N/A"}</td>
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
        </HudPanel>
      </div>
    </div>
  );
}
