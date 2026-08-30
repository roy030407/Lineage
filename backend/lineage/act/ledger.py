"""Append-only audit log of every proposal decision.

In-memory list, optionally backed by an append-only JSONL file: given a
path, every record is serialized and appended to disk the moment it is
recorded, so the trail survives a process restart. The file is only ever
opened for append -- no edits, no deletes, no rewrites.
"""

from datetime import UTC, datetime
from pathlib import Path

from lineage.act.models import MINIMUM_APPROVER_ROLE, ROLE_RANK, ApproverRole, AuditRecord, Proposal


class AuditLedger:
    """Append-only. `path=None` keeps it purely in-memory (unit tests, ad-hoc
    scripts); with a path, existing records are loaded at startup and every
    new record is written through to disk before `record` returns."""

    def __init__(self, path: Path | None = None) -> None:
        self._records: list[AuditRecord] = []
        self._path = path
        if path is not None and path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._records.append(AuditRecord.model_validate_json(line))

    def record(self, audit_record: AuditRecord) -> None:
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(audit_record.model_dump_json() + "\n")
        self._records.append(audit_record)

    def latest_for(self, proposal_id: str) -> AuditRecord | None:
        return next((r for r in reversed(self._records) if r.proposal_id == proposal_id), None)

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
        timestamp=datetime.now(UTC),
        proposal_snapshot=proposal.model_copy(deep=True),
    )
    ledger.record(record)
    return record
