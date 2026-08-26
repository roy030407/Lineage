"""Golden test: SPC evaluated against the real default 400-car run must fire
at the correct station for the torque-drift and environmental-excursion
scenarios, and must not sustain a false alarm on the operator handover once
recalibration has had a chance to complete."""

import json

import pandas as pd
import pytest

from lineage.config.loader import load_line_spec
from lineage.config.specs import Zone
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
from lineage.datagen.generators import ambient_temp_c
from lineage.datagen.run import generate_run
from lineage.predict.spc import SPCState, evaluate_spc


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)
    output_root = tmp_path_factory.mktemp("spc_golden_run")
    artifacts = generate_run(line, config, output_root=output_root)
    return line, config, artifacts


def _car_index(car_id: str) -> int:
    return int(car_id.split("-")[1])


def _verdict_sequence(line, station_id, quantity, telemetry, shift_changes, ambient_fn):
    """`quantity` here is the baseline key: a sensor_id for instrumented
    stations (telemetry's sensor_id column holds it directly), or the manual
    readable_param name (telemetry's quantity column holds it directly, since
    a manual reading's synthesized sensor_id is station-prefixed instead)."""
    station = next(s for s in line.stations if s.id == station_id)
    same_station = telemetry.station_id == station_id
    matches = (telemetry.sensor_id == quantity) | (telemetry.quantity == quantity)
    rows = telemetry[same_station & matches].sort_values("timestamp")

    history: list[tuple] = []
    results = []
    for _, row in rows.iterrows():
        ts = row.timestamp.to_pydatetime()
        history.append((ts, float(row.value)))
        car_index = _car_index(row.car_id)
        ambient_c = ambient_fn(car_index)
        verdict = evaluate_spc(
            station=station,
            quantity=quantity,
            history=history,
            shift_changes=shift_changes,
            ambient_c=ambient_c,
            envelope=line.environment_envelope,
        )
        results.append((car_index, verdict))
    return results


def test_spc_fires_at_torque_drift_station(default_run):
    line, _config, artifacts = default_run
    telemetry = pd.read_csv(artifacts.telemetry_path, parse_dates=["timestamp"])

    results = _verdict_sequence(
        line, "ST-06", "ST-06-SEN-2", telemetry, shift_changes=[], ambient_fn=lambda i: 22.0
    )

    fired = [
        car_index
        for car_index, v in results
        if 50 <= car_index <= 84 and v.state == SPCState.OUT_OF_CONTROL
    ]
    assert fired, "expected SPC to fire at ST-06 within the seeded torque-drift window"


def test_spc_reports_environment_invalid_during_paint_booth_excursion(default_run):
    line, config, artifacts = default_run
    telemetry = pd.read_csv(artifacts.telemetry_path, parse_dates=["timestamp"])

    def ambient_fn(car_index: int) -> float:
        return ambient_temp_c(
            config.baseline_temp_c, config.environment_excursions, car_index, Zone.PAINT
        )

    results = _verdict_sequence(
        line, "ST-25", "ST-25-SEN-1", telemetry, shift_changes=[], ambient_fn=ambient_fn
    )

    in_window = [v for car_index, v in results if 150 <= car_index <= 170]
    assert in_window, "expected ST-25 readings within the excursion window"
    assert all(v.state == SPCState.ENVIRONMENT_INVALID for v in in_window)
    assert all(v.state != SPCState.IN_CONTROL for v in in_window)


def test_spc_does_not_sustain_false_alarm_after_operator_recalibration(default_run):
    line, _config, artifacts = default_run
    telemetry = pd.read_csv(artifacts.telemetry_path, parse_dates=["timestamp"])
    events = pd.read_csv(artifacts.events_path, parse_dates=["timestamp"])

    shift_rows = events[(events.station_id == "ST-02") & (events.event_type == "shift_change")]
    shift_changes = []
    for _, row in shift_rows.sort_values("timestamp").iterrows():
        detail = json.loads(row.detail)
        shift_changes.append((row.timestamp.to_pydatetime(), bool(detail["handover_flagged"])))

    results = _verdict_sequence(
        line,
        "ST-02",
        "torque_nm",
        telemetry,
        shift_changes=shift_changes,
        ambient_fn=lambda i: 22.0,
    )

    # Manual reports only land ~85% of the time, so the recalibration window's
    # 10th actual reading doesn't fall at a fixed car index -- use the verdict's
    # own recalibrating flag rather than guessing an offset.
    recalibrating_readings = [v for car_index, v in results if car_index >= 200 and v.recalibrating]
    settled = [v for car_index, v in results if car_index >= 200 and not v.recalibrating]
    assert settled, "expected readings after the recalibration window closes"

    recalibrating_alarm_rate = sum(
        v.state == SPCState.OUT_OF_CONTROL for v in recalibrating_readings
    ) / len(recalibrating_readings)
    settled_alarm_rate = sum(v.state == SPCState.OUT_OF_CONTROL for v in settled) / len(settled)

    # Without recalibration, the seeded bias (z ~= 7.4 against the pre-handover
    # baseline) would alarm on essentially every reading -- that's what the
    # still-recalibrating window shows. Rule 4 (8-consecutive-one-side) has a
    # real, nonzero false-alarm rate over long sequences, compounded here by
    # rounding manual readings to human-plausible precision, which creates
    # ties that make "all on one side" more likely by chance. The bar for
    # "recalibration worked" is a settled alarm rate far below the
    # pre-recalibration rate, not literally zero.
    assert recalibrating_alarm_rate > 0.9
    assert settled_alarm_rate < 0.2
