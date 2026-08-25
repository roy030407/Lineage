"""Physical-effect functions: wear drift, operator bias, environmental temperature,
material quality. Pure functions over simulated time / car index -- no I/O, no RNG
state held here (callers pass in a shared numpy Generator so draw order stays
reproducible across the whole simulation)."""

from datetime import datetime

import numpy as np

from lineage.config.specs import MachineSpec, Zone
from lineage.datagen.models import EnvironmentExcursion, OperatorProfile, ShiftAssignment

MANUAL_ROUNDING_STEP = {
    "torque_nm": 0.5,
    "coat_thickness_um": 1.0,
}
DEFAULT_ROUNDING_STEP = 0.1


def elapsed_days_since_maintenance(
    machine: MachineSpec, sim_time: datetime, run_maintenance_events: list[datetime]
) -> float:
    """Days since the most recent maintenance as of sim_time: the latest
    in-run maintenance event before sim_time, or the machine's static
    last_maintenance_date if none has occurred yet in this run."""
    candidates = [dt for dt in run_maintenance_events if dt <= sim_time]
    if candidates:
        last = max(candidates)
    else:
        last = datetime.combine(machine.last_maintenance_date, datetime.min.time())
    return max(0.0, (sim_time - last).total_seconds() / 86400.0)


def wear_z(machine: MachineSpec, elapsed_days: float) -> float:
    """Systematic deviation, in std-devs of the sensed quantity, contributed by
    accumulated wear since the last maintenance. Resets to ~0 at maintenance
    (elapsed_days=0) and grows toward the interval boundary, shaped by
    wear_curve_shape: "bathtub" starts elevated (infant mortality), dips through
    a flat useful-life period, then rises sharply (wear-out); anything else
    ("linear") grows steadily and more mildly across the whole interval."""
    fraction = min(1.0, elapsed_days / machine.maintenance_interval_days)
    if machine.wear_curve_shape == "bathtub":
        infant = 1.0 * np.exp(-fraction * 6)
        wearout = 3.5 * fraction**3
        return float(infant + wearout)
    return 2.5 * fraction


def ambient_temp_c(
    baseline_temp_c: float,
    excursions: list[EnvironmentExcursion],
    car_index: int,
    zone: Zone,
) -> float:
    """Ambient temperature affecting `zone` at the time car `car_index` is being
    processed there. Excursions are scoped to a zone since a car's journey
    passes through every zone at different simulated times -- an excursion
    happening while cars 150-170 are in paint must not also appear to affect
    those same cars back when they were in body, hours earlier in sim time."""
    for excursion in excursions:
        in_range = excursion.start_car_index <= car_index <= excursion.end_car_index
        if excursion.zone == zone and in_range:
            return excursion.temp_c
    return baseline_temp_c


def environment_z(ambient_c: float, envelope_min_c: float, envelope_max_c: float) -> float:
    """Systematic deviation contributed by ambient temperature falling outside the
    line's environment envelope, in "1 std-dev per 2 degrees over/under" units.
    Zero when ambient temperature is within the envelope."""
    if ambient_c > envelope_max_c:
        return (ambient_c - envelope_max_c) / 2.0
    if ambient_c < envelope_min_c:
        return (envelope_min_c - ambient_c) / 2.0
    return 0.0


def material_quality_sequence(num_cars: int, rng: np.random.Generator) -> list[float]:
    """Per-car incoming-material quality score, mildly autocorrelated (AR(1)) so
    that bad batches cluster across consecutive cars rather than behaving as
    pure independent noise. Centered on 1.0; lower is worse."""
    quality = [0.0] * num_cars
    quality[0] = float(rng.normal(1.0, 0.05))
    for i in range(1, num_cars):
        quality[i] = 0.8 * quality[i - 1] + 0.2 * float(rng.normal(1.0, 0.05))
    return quality


def operator_bias_for_car(
    schedule: list[ShiftAssignment],
    profiles: dict[str, OperatorProfile],
    station_id: str,
    car_index: int,
) -> tuple[float, float] | None:
    """Returns (effective_bias, std) for whichever operator covers car_index at
    station_id, or None if no assignment covers it. A flagged handover dampens
    the incoming operator's bias to 30% of the jump from the prior operator's
    bias for the whole assignment, rather than stepping to it immediately."""
    station_schedule = [a for a in schedule if a.station_id == station_id]
    assignment = next(
        (a for a in station_schedule if a.start_car_index <= car_index <= a.end_car_index),
        None,
    )
    if assignment is None:
        return None
    profile = profiles[assignment.operator_id]
    if not assignment.handover_flagged:
        return profile.bias, profile.std

    prior = next(
        (a for a in station_schedule if a.end_car_index == assignment.start_car_index - 1),
        None,
    )
    if prior is None:
        return profile.bias, profile.std
    prior_profile = profiles[prior.operator_id]
    blended_bias = prior_profile.bias + 0.3 * (profile.bias - prior_profile.bias)
    return blended_bias, profile.std


def round_to_step(value: float, quantity: str) -> float:
    step = MANUAL_ROUNDING_STEP.get(quantity, DEFAULT_ROUNDING_STEP)
    return round(round(value / step) * step, 6)
