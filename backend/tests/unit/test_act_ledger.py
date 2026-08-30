"""Tests for lineage.act.ledger: approval authorization and the audit trail."""

import pytest

from lineage.act.ledger import AuditLedger, approve
from lineage.act.models import ApproverRole, Proposal


def make_proposal() -> Proposal:
    return Proposal(
        proposal_id="p1",
        station_id="ST-01",
        parameter_name="line_speed_pct",
        current_value=100.0,
        proposed_value=105.0,
        rationale="test",
        trace_car_id="CAR-001",
        requires_physical_change=False,
    )


def test_operator_role_cannot_approve():
    ledger = AuditLedger()
    proposal = make_proposal()
    with pytest.raises(PermissionError):
        approve(proposal, ApproverRole.OPERATOR, "operator-1", ledger)
    assert ledger.all_records() == []  # rejected attempt writes no record


@pytest.mark.parametrize(
    "role", [ApproverRole.FLOOR_SUPERVISOR, ApproverRole.PLANT_MANAGER, ApproverRole.LEADERSHIP]
)
def test_floor_supervisor_and_above_can_approve(role):
    ledger = AuditLedger()
    proposal = make_proposal()

    record = approve(proposal, role, "approver-1", ledger)

    assert record.decision == "approved"
    assert record.approver_role == role
    assert ledger.all_records() == [record]


def test_audit_record_is_an_immutable_snapshot_not_a_live_reference():
    ledger = AuditLedger()
    proposal = make_proposal()

    record = approve(proposal, ApproverRole.FLOOR_SUPERVISOR, "approver-1", ledger)
    proposal.status = "rejected"  # mutate the original after the fact

    assert record.proposal_snapshot.status != "rejected"


def test_ledger_persists_records_to_jsonl_and_reloads_them(tmp_path):
    """A path-backed ledger writes each record through as one JSON line and
    a fresh instance over the same file starts with the full history --
    the audit trail survives a process restart."""
    log_path = tmp_path / "audit" / "audit_log.jsonl"

    ledger = AuditLedger(log_path)
    record = approve(make_proposal(), ApproverRole.FLOOR_SUPERVISOR, "sup-1", ledger)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    reloaded = AuditLedger(log_path)
    assert reloaded.all_records() == [record]
    assert reloaded.latest_for("p1") == record


def test_in_memory_ledger_writes_no_files():
    ledger = AuditLedger()
    approve(make_proposal(), ApproverRole.FLOOR_SUPERVISOR, "sup-1", ledger)
    assert len(ledger.all_records()) == 1  # nothing to assert on disk: no path, no file
