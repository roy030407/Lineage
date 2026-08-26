"""Validates an ActProposal against the safety envelope; rejects or clips out-of-bounds cases."""

from lineage.act.envelope import envelope_for
from lineage.act.models import Proposal
from lineage.config.specs import StationSpec


def validate_proposal(proposal: Proposal, station: StationSpec) -> None:
    """Raises ValueError if `proposal` exits the safety envelope in any way.
    Never mutates or clips the proposal -- a rejection is a rejection, not a
    silent adjustment. Checked in code, not left to a caller's discipline."""
    if proposal.station_id != station.id:
        raise ValueError(
            f"proposal is for station {proposal.station_id!r}, not {station.id!r}"
        )

    param_range = station.changeable_params.get(proposal.parameter_name)
    if param_range is None:
        raise ValueError(
            f"{proposal.parameter_name!r} is not a changeable parameter at station "
            f"{station.id!r} (it may be a readable_param, which Act may never propose "
            "changes to)"
        )

    if not (param_range.min <= proposal.proposed_value <= param_range.max):
        raise ValueError(
            f"proposed value {proposal.proposed_value} for {proposal.parameter_name!r} "
            f"is outside station {station.id!r}'s configured range "
            f"[{param_range.min}, {param_range.max}]"
        )

    envelope = envelope_for(proposal.parameter_name)
    if envelope is None:
        raise ValueError(
            f"no safety envelope defined for parameter {proposal.parameter_name!r}; "
            "rejecting rather than assuming it's safe"
        )

    if not (envelope.absolute_min <= proposal.proposed_value <= envelope.absolute_max):
        raise ValueError(
            f"proposed value {proposal.proposed_value} for {proposal.parameter_name!r} "
            f"is outside the plant-wide safety envelope "
            f"[{envelope.absolute_min}, {envelope.absolute_max}]"
        )

    if proposal.current_value != 0:
        relative_change = abs(
            (proposal.proposed_value - proposal.current_value) / proposal.current_value
        )
        if relative_change > envelope.max_single_step_change_pct:
            raise ValueError(
                f"proposed change to {proposal.parameter_name!r} is a "
                f"{relative_change:.1%} step, exceeding the envelope's "
                f"{envelope.max_single_step_change_pct:.1%} max single-step change"
            )
