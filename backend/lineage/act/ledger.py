"""Append-only JSON audit log of every proposal and its accept/reject/execute outcome."""

from datetime import datetime

from lineage.act.models import MINIMUM_APPROVER_ROLE, ROLE_RANK, ApproverRole, AuditRecord, Proposal


class AuditLedger:
    """In-memory, append-only. No database, no edits, no deletes."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def record(self, audit_record: AuditRecord) -> None:
        self._records.append(audit_record)

    def all_records(self) -> list[AuditRecord]:
        return list(self._records)


def approve(
    proposal: Proposal,
    approver_role: ApproverRole,
    approver_id: str,
    ledger: AuditLedger,
) -> AuditRecord:
    """Only floor_supervisor and above may approve. Raises PermissionError
    for anyone below that, in code -- not left to a caller's discipline."""
    if ROLE_RANK[approver_role] < ROLE_RANK[MINIMUM_APPROVER_ROLE]:
        raise PermissionError(
            f"role {approver_role.value!r} is not authorized to approve Act proposals; "
            f"{MINIMUM_APPROVER_ROLE.value!r} or above required"
        )

    record = AuditRecord(
        proposal_id=proposal.proposal_id,
        approver_role=approver_role,
        approver_id=approver_id,
        decision="approved",
        timestamp=datetime.now(),
        proposal_snapshot=proposal.model_copy(deep=True),
    )
    ledger.record(record)
    return record
