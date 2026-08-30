"""Act proposal listing and approval endpoints.

Proposals are generated lazily from the run's actual failed inspections --
every (car_id, station_id) pair where inspection.csv recorded "fail", traced
back to its likely originating station. That trace pass is shared with Plant
Manager's recurring-root-cause report (api/routes/views.py's
_ensure_trace_results), since both need the exact same, real per-car work
computed once, not twice. act.proposals.propose then turns each trace result
into bounded, envelope-checked proposals, cached separately here so approving
one by id later in the same loaded run finds the same object, not a freshly
regenerated uuid.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.act.ledger import approve as approve_proposal
from lineage.act.models import ApproverRole, AuditRecord, Proposal, ProposalStatus
from lineage.act.proposals import propose, simulate
from lineage.api.deps import AppState, get_app_state
from lineage.api.routes.views import _ensure_trace_results

router = APIRouter()


def _ensure_proposals(state: AppState) -> list[Proposal]:
    if state.act_proposals is not None:
        return state.act_proposals

    if state.engine is None or state.genealogy_store is None or state.current_run_dir is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")
    assert state.line is not None  # a loaded engine implies a loaded line

    proposals: list[Proposal] = []
    seen_targets: set[tuple[str, str]] = set()
    for trace_result in _ensure_trace_results(state):
        for proposal in propose(trace_result, state.line, state.act_setpoints):
            # Dedup by what the proposal would actually change, not by its
            # (always-fresh) uuid: many failed inspections tracing to the
            # same station would otherwise stack near-identical proposals.
            target = (proposal.station_id, proposal.parameter_name)
            if target not in seen_targets:
                proposals.append(proposal)
                seen_targets.add(target)

    state.act_proposals = proposals
    return proposals


@router.get("/api/act/proposals")
def list_proposals(state: AppState = Depends(get_app_state)) -> list[Proposal]:
    return _ensure_proposals(state)


class ApproveRequest(BaseModel):
    approver_id: str


@router.post("/api/act/proposals/{proposal_id}/approve")
def approve_proposal_endpoint(
    proposal_id: str, req: ApproveRequest, state: AppState = Depends(get_app_state)
) -> AuditRecord:
    """Approves as floor_supervisor -- the only role this endpoint
    represents. act/models.py's MINIMUM_APPROVER_ROLE is floor_supervisor,
    so this always clears that bar; a client can't claim a different role
    to approve through some other endpoint, since there isn't one."""
    proposals = _ensure_proposals(state)
    index, proposal = next(
        ((i, p) for i, p in enumerate(proposals) if p.proposal_id == proposal_id), (None, None)
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"unknown proposal {proposal_id!r}")

    if proposal.status == ProposalStatus.APPROVED:
        # Idempotent: re-approving returns the original audit record instead
        # of appending a duplicate to the append-only trail.
        existing = state.audit_ledger.latest_for(proposal_id)
        assert existing is not None  # an APPROVED proposal always has its record
        return existing

    record = approve_proposal(
        proposal, ApproverRole.FLOOR_SUPERVISOR, req.approver_id, state.audit_ledger
    )
    assert index is not None
    proposals[index] = proposal.model_copy(update={"status": ProposalStatus.APPROVED})
    # The approved value becomes the parameter's known setpoint, so future
    # proposal generation moves from where the line actually is now.
    state.act_setpoints[(proposal.station_id, proposal.parameter_name)] = proposal.proposed_value
    return record


class SimulateResponse(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    proposal_id: str
    station_id: str
    parameter_name: str
    current_value: float
    proposed_value: float
    predicted_defect_rate_delta: float
    ci_low: float
    ci_high: float
    predicted_throughput_delta: float


@router.post("/api/act/proposals/{proposal_id}/simulate")
def simulate_proposal_endpoint(
    proposal_id: str, state: AppState = Depends(get_app_state)
) -> SimulateResponse:
    """Runs act.proposals.simulate for one proposal -- a read-only analytical
    projection; nothing about the live line or the proposal changes."""
    proposals = _ensure_proposals(state)
    proposal = next((p for p in proposals if p.proposal_id == proposal_id), None)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"unknown proposal {proposal_id!r}")
    assert state.line is not None  # _ensure_proposals already required a loaded line

    # The deviation that motivated this proposal: the origin station's own
    # contribution in the trace that produced it.
    deviation_z = 0.0
    for trace_result in _ensure_trace_results(state):
        if (
            trace_result.car_id == proposal.trace_car_id
            and trace_result.originating_station_id == proposal.station_id
        ):
            contribution = next(
                (
                    c
                    for c in trace_result.ranked_contributions
                    if c.station_id == proposal.station_id
                ),
                None,
            )
            if contribution is not None and contribution.deviation_z is not None:
                deviation_z = contribution.deviation_z
            break

    effect = simulate(proposal, state.line, current_deviation_z=deviation_z)
    ci_low, ci_high = effect.defect_rate_confidence_interval
    return SimulateResponse(
        proposal_id=proposal.proposal_id,
        station_id=proposal.station_id,
        parameter_name=proposal.parameter_name,
        current_value=proposal.current_value,
        proposed_value=proposal.proposed_value,
        predicted_defect_rate_delta=effect.predicted_defect_rate_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        predicted_throughput_delta=effect.predicted_throughput_delta,
    )
