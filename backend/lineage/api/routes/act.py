"""Act proposal listing and approval endpoints.

Proposals are generated lazily from the run's actual failed inspections --
every (car_id, station_id) pair where inspection.csv recorded "fail" gets
traced back to its likely originating station via trace.lineage_query.trace,
then act.proposals.propose turns that into bounded, envelope-checked
proposals. Cached on AppState like the prediction ledger, so approving one
by id later in the same loaded run finds the same object, not a freshly
regenerated uuid.
"""

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lineage.act.ledger import approve as approve_proposal
from lineage.act.models import ApproverRole, AuditRecord, Proposal, ProposalStatus
from lineage.act.proposals import propose
from lineage.api.deps import AppState, get_app_state
from lineage.trace.lineage_query import trace

router = APIRouter()


def _ensure_proposals(state: AppState) -> list[Proposal]:
    if state.act_proposals is not None:
        return state.act_proposals

    if state.engine is None or state.genealogy_store is None or state.current_run_dir is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")
    assert state.line is not None  # a loaded engine implies a loaded line

    inspection_df = pd.read_csv(
        state.current_run_dir / "inspection.csv", parse_dates=["timestamp"]
    )
    failed = inspection_df[inspection_df.result == "fail"]

    proposals: list[Proposal] = []
    seen_ids: set[str] = set()
    for row in failed.itertuples():
        trace_result = trace(
            line=state.line,
            store=state.genealogy_store,
            car_id=row.car_id,
            flagged_at_station_id=row.station_id,
        )
        for proposal in propose(trace_result, state.line):
            if proposal.proposal_id not in seen_ids:
                proposals.append(proposal)
                seen_ids.add(proposal.proposal_id)

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

    record = approve_proposal(
        proposal, ApproverRole.FLOOR_SUPERVISOR, req.approver_id, state.audit_ledger
    )
    assert index is not None
    proposals[index] = proposal.model_copy(update={"status": ProposalStatus.APPROVED})
    return record
