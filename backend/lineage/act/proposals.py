"""Generates ActProposal objects from predict/trace output."""

import math
import uuid
from datetime import datetime, timedelta

from lineage.act.envelope import envelope_for
from lineage.act.models import PredictedEffect, Proposal
from lineage.act.validator import validate_proposal
from lineage.config.specs import LineSpec, StationSpec
from lineage.trace.models import TraceResult

DEFAULT_CORRECTION_FRACTION = 0.5
"""How far toward baseline a single proposal aims to move things -- half the
allowed step, not the full envelope limit, so a first correction is
conservative rather than maximal."""


def propose(
    trace_result: TraceResult,
    line: LineSpec,
    setpoints: dict[tuple[str, str], float] | None = None,
) -> list[Proposal]:
    """One bounded, single-parameter proposal per changeable parameter at the
    trace's originating station, each carrying a rationale that cites the
    trace evidence directly. Never proposes a readable_param -- only
    parameters present in station.changeable_params are considered at all.

    `setpoints` maps (station_id, parameter_name) -> the last approved value
    for that parameter, so successive proposals move from where the line
    actually is rather than restarting from the nominal midpoint every time.
    With no entry (or no mapping at all -- there is no live OT link in this
    prototype), the range midpoint stands in as the nominal operating point,
    stated in the rationale rather than hidden."""
    station = next(
        (s for s in line.stations if s.id == trace_result.originating_station_id), None
    )
    if station is None or not station.changeable_params:
        return []

    origin_cause = next(
        (c for c in trace_result.ranked_contributions if c.station_id == station.id), None
    )
    deviation_z = origin_cause.deviation_z if origin_cause is not None else None

    proposals = []
    for parameter_name, param_range in station.changeable_params.items():
        envelope = envelope_for(parameter_name)
        if envelope is None:
            continue  # no defined safety envelope -- never propose changes to it

        known_setpoint = (setpoints or {}).get((station.id, parameter_name))
        current_value = (
            known_setpoint
            if known_setpoint is not None
            else (param_range.min + param_range.max) / 2  # nominal operating point
        )
        proposed_value = current_value
        if deviation_z is not None and deviation_z != 0:
            direction = -1.0 if deviation_z > 0 else 1.0
            step = (
                current_value * envelope.max_single_step_change_pct * DEFAULT_CORRECTION_FRACTION
            )
            proposed_value = current_value + direction * step

        proposed_value = max(param_range.min, min(param_range.max, proposed_value))
        proposed_value = max(envelope.absolute_min, min(envelope.absolute_max, proposed_value))

        verifiable_word = "verifiable" if trace_result.originating_is_verifiable else "unverifiable"
        z_clause = f" with deviation_z={deviation_z:.2f}" if deviation_z is not None else ""
        setpoint_clause = (
            ""
            if known_setpoint is not None
            else " (current value assumed at the nominal midpoint; no approved setpoint on record)"
        )
        rationale = (
            f"Trace identified {station.id} as the {verifiable_word} origin for car "
            f"{trace_result.car_id}{z_clause}; proposing to adjust {parameter_name} "
            f"toward baseline{setpoint_clause}."
        )

        proposal = Proposal(
            proposal_id=str(uuid.uuid4()),
            station_id=station.id,
            parameter_name=parameter_name,
            current_value=current_value,
            proposed_value=proposed_value,
            rationale=rationale,
            trace_car_id=trace_result.car_id,
            requires_physical_change=envelope.requires_physical_change,
            next_maintenance_window=(
                _next_maintenance_window(station) if envelope.requires_physical_change else None
            ),
        )

        try:
            validate_proposal(proposal, station)
        except ValueError:
            continue  # never emit a proposal that wouldn't itself pass validation

        proposals.append(proposal)

    return proposals


def _next_maintenance_window(station: StationSpec) -> datetime:
    last = datetime.combine(station.machine.last_maintenance_date, datetime.min.time())
    return last + timedelta(days=station.machine.maintenance_interval_days)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _defect_probability(z: float) -> float:
    """Probability that a reading this far from baseline reflects a genuine
    defect rather than ordinary noise: 0 at z=0, approaching 1 as |z| grows.

    Deliberately NOT `2*(1-normal_cdf(|z|))` -- that's the p-value of
    observing a deviation this extreme under the healthy/null hypothesis,
    which *shrinks* as |z| grows (a bigger deviation is rarer under the
    null). What we want is the opposite direction: confidence that this
    deviation is real, which grows with |z|. That's `2*normal_cdf(|z|) - 1`.
    """
    return 2 * _normal_cdf(abs(z)) - 1


def simulate(
    proposal: Proposal, line: LineSpec, current_deviation_z: float = 0.0
) -> PredictedEffect:
    """Analytical projection of a proposal's effect -- NOT a re-simulation.
    Nothing here mutates `line` (nothing is written anywhere): current
    defect probability is derived from `current_deviation_z` via
    `_defect_probability` (grows with |z|, not a shrinking p-value), and the
    predicted probability assumes the proposed change moves the process a
    fraction of the way back toward baseline, proportional to how large a
    step it is relative to the envelope's allowed single-step change. The
    confidence intervals are stated model assumptions (wider for smaller
    corrective steps), not empirically fitted -- a full datagen re-run on a
    forked LineSpec is the honest upgrade path if a real predictive claim
    is ever needed here."""
    envelope = envelope_for(proposal.parameter_name)
    step_fraction = 0.0
    if envelope is not None:
        # A current value of exactly 0 would make a relative step undefined;
        # measure the step against the envelope's absolute span instead, so
        # the check degrades to "how big is this move within the legal range"
        # rather than silently skipping (mirrors act/validator.py).
        step_base = (
            abs(proposal.current_value)
            if proposal.current_value != 0
            else envelope.absolute_max - envelope.absolute_min
        )
        relative_step = abs(proposal.proposed_value - proposal.current_value) / step_base
        step_fraction = min(1.0, relative_step / envelope.max_single_step_change_pct)

    current_defect_probability = _defect_probability(current_deviation_z)
    projected_z = current_deviation_z * (1 - DEFAULT_CORRECTION_FRACTION * step_fraction)
    projected_defect_probability = _defect_probability(projected_z)

    defect_rate_delta = projected_defect_probability - current_defect_probability
    ci_width = 0.1 * (1.0 - step_fraction) + 0.02

    throughput_delta = 0.0
    throughput_ci_width = 0.01
    if "speed" in proposal.parameter_name and proposal.current_value != 0:
        throughput_delta = (
            proposal.proposed_value - proposal.current_value
        ) / proposal.current_value
        throughput_ci_width = 0.03

    return PredictedEffect(
        proposal_id=proposal.proposal_id,
        predicted_defect_rate_delta=defect_rate_delta,
        defect_rate_confidence_interval=(
            defect_rate_delta - ci_width,
            defect_rate_delta + ci_width,
        ),
        predicted_throughput_delta=throughput_delta,
        throughput_confidence_interval=(
            throughput_delta - throughput_ci_width,
            throughput_delta + throughput_ci_width,
        ),
    )
