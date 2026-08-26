"""Statistical process control charts (Xbar-R / EWMA) per sensor, per station.

Control limits come from the station's commissioning_baseline -- what a station
looks like when healthy, measured once at commissioning -- never from a rolling
window over recent data. The one exception is the mean (not the variance)
following an operator handover at a manual station: see evaluate_spc's docstring.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from lineage.config.specs import EnvironmentEnvelope, StationSpec

RULE_CONFIDENCE = {
    "beyond_3_sigma": 0.997,
    "2_of_3_beyond_2_sigma": 0.95,
    "4_of_5_beyond_1_sigma": 0.90,
    "8_consecutive_one_side": 0.85,
}


class SPCState(StrEnum):
    IN_CONTROL = "in_control"
    OUT_OF_CONTROL = "out_of_control"
    UNKNOWN = "unknown"
    ENVIRONMENT_INVALID = "environment_invalid"


class SPCVerdict(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    quantity: str
    state: SPCState
    rule_triggered: str | None = None
    confidence: float
    recalibrating: bool = False
    uncertainty_band_multiplier: float = 1.0


def evaluate_spc(
    *,
    station: StationSpec,
    quantity: str,
    history: list[tuple[datetime, float]],
    shift_changes: list[tuple[datetime, bool]],
    ambient_c: float,
    envelope: EnvironmentEnvelope,
    recalibration_n: int = 10,
    unflagged_band_multiplier: float = 2.0,
) -> SPCVerdict:
    """Evaluates the SPC verdict as of the last (most recent) point in `history`.

    `quantity` must be the key that indexes into the station's
    commissioning_baseline -- a sensor's id for instrumented/mixed stations
    (not its `kind` label; telemetry.csv's own `sensor_id` column, not its
    `quantity` column), or the manual station's readable_param name.

    `history` is (timestamp, value) pairs for this station+quantity, in time
    order, up to and including the point being evaluated. `shift_changes` is
    (timestamp, handover_flagged) pairs for this station, in time order.

    Environment gating runs first and applies uniformly, regardless of
    quantity: a run outside the envelope is not a run, so no alarm is
    produced during that window, only ENVIRONMENT_INVALID.

    Recalibration: for the first `recalibration_n` readings after a shift
    change, the *mean* (not the std, re-estimating variance from ~10 samples
    is too noisy to trust) still compares against the pre-handover baseline,
    but the effective std is widened by `unflagged_band_multiplier` if the
    handover was unflagged (never widened if it was flagged) -- this is what
    keeps a legitimate operator-to-operator bias difference from reading as a
    permanent alarm. After the window, the mean is re-estimated from those
    readings and used as the new center for the rest of the shift.
    """
    if ambient_c > envelope.temp_max_c or ambient_c < envelope.temp_min_c:
        return SPCVerdict(
            station_id=station.id, quantity=quantity, state=SPCState.ENVIRONMENT_INVALID,
            confidence=0.0,
        )

    baseline = station.commissioning_baseline
    if (
        baseline is None
        or quantity not in baseline.loaded.mean
        or baseline.loaded.std.get(quantity, 0.0) <= 0
        or not history
    ):
        return SPCVerdict(
            station_id=station.id, quantity=quantity, state=SPCState.UNKNOWN, confidence=0.0
        )

    commissioning_mean = baseline.loaded.mean[quantity]
    std = baseline.loaded.std[quantity]

    now = history[-1][0]
    effective_mean = commissioning_mean
    band_multiplier = 1.0
    recalibrating = False

    past_changes = [sc for sc in shift_changes if sc[0] <= now]
    if past_changes:
        last_change_time, handover_flagged = past_changes[-1]
        post_change_values = [v for t, v in history if t >= last_change_time]
        if len(post_change_values) <= recalibration_n:
            recalibrating = True
            band_multiplier = 1.0 if handover_flagged else unflagged_band_multiplier
        else:
            calibration_sample = post_change_values[:recalibration_n]
            effective_mean = sum(calibration_sample) / len(calibration_sample)

    effective_std = std * band_multiplier
    z_values = [(value - effective_mean) / effective_std for _, value in history]

    state, rule, confidence = _apply_western_electric(z_values)

    return SPCVerdict(
        station_id=station.id,
        quantity=quantity,
        state=state,
        rule_triggered=rule,
        confidence=confidence,
        recalibrating=recalibrating,
        uncertainty_band_multiplier=band_multiplier,
    )


def _apply_western_electric(z_values: list[float]) -> tuple[SPCState, str | None, float]:
    latest = z_values[-1]

    if abs(latest) > 3.0:
        confidence = min(0.999, RULE_CONFIDENCE["beyond_3_sigma"] + 0.001 * (abs(latest) - 3.0))
        return SPCState.OUT_OF_CONTROL, "beyond_3_sigma", confidence

    if len(z_values) >= 3:
        last3 = z_values[-3:]
        rule = "2_of_3_beyond_2_sigma"
        if sum(1 for z in last3 if z > 2.0) >= 2 or sum(1 for z in last3 if z < -2.0) >= 2:
            return SPCState.OUT_OF_CONTROL, rule, RULE_CONFIDENCE[rule]

    if len(z_values) >= 5:
        last5 = z_values[-5:]
        rule = "4_of_5_beyond_1_sigma"
        if sum(1 for z in last5 if z > 1.0) >= 4 or sum(1 for z in last5 if z < -1.0) >= 4:
            return SPCState.OUT_OF_CONTROL, rule, RULE_CONFIDENCE[rule]

    if len(z_values) >= 8:
        last8 = z_values[-8:]
        rule = "8_consecutive_one_side"
        if all(z > 0 for z in last8) or all(z < 0 for z in last8):
            return SPCState.OUT_OF_CONTROL, rule, RULE_CONFIDENCE[rule]

    margin = 1.0 - min(abs(latest), 3.0) / 3.0
    return SPCState.IN_CONTROL, None, 0.5 + 0.5 * margin
