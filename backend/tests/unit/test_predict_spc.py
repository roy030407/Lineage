"""Tests for lineage.predict.spc; to be filled in alongside real logic."""

from datetime import date, datetime, timedelta

from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    EnvironmentEnvelope,
    MachineSpec,
    SensorKind,
    SensorSpec,
    StationSpec,
    Zone,
)
from lineage.predict.spc import SPCState, evaluate_spc

ENVELOPE = EnvironmentEnvelope(
    temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
)
T0 = datetime(2024, 1, 1, 8, 0)


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def make_station(manual: bool = False) -> StationSpec:
    sensors = (
        []
        if manual
        else [
            SensorSpec(
                id="ST-01-SEN-1",
                kind=SensorKind.TORQUE,
                unit="N.m",
                sample_rate_hz=50.0,
                install_date=date(2020, 1, 1),
                last_calibration_date=date(2024, 1, 1),
                accuracy_class="1.0",
            )
        ]
    )
    quantity = "torque_nm" if manual else "ST-01-SEN-1"
    return StationSpec(
        id="ST-01",
        name="Test Station",
        zone=Zone.BODY,
        sequence_index=0,
        sensors=sensors,
        acquisition_mode=AcquisitionMode.MANUAL if manual else AcquisitionMode.INSTRUMENTED,
        cycle_time_nominal_s=10.0,
        commissioning_baseline=CommissioningBaseline(
            idle=ConditionStats(mean={quantity: 5.0}, std={quantity: 1.0}),
            loaded=ConditionStats(mean={quantity: 10.0}, std={quantity: 2.0}),
        ),
        readable_params=[quantity] if manual else [],
        machine=_machine(),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def times(n: int, step_s: float = 1.0) -> list[datetime]:
    return [T0 + timedelta(seconds=i * step_s) for i in range(n)]


def test_normal_readings_are_in_control():
    station = make_station()
    ts = times(5)
    history = list(zip(ts, [10.0, 9.8, 10.2, 10.1, 9.9], strict=False))  # mean=10, std=2
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.IN_CONTROL
    assert verdict.rule_triggered is None


def test_beyond_3_sigma_fires():
    station = make_station()
    ts = times(1)
    history = list(zip(ts, [20.0], strict=False))  # (20-10)/2 = 5 sigma
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.OUT_OF_CONTROL
    assert verdict.rule_triggered == "beyond_3_sigma"


def test_2_of_3_beyond_2_sigma_fires():
    station = make_station()
    ts = times(3)
    history = list(zip(ts, [10.0, 15.0, 15.0], strict=False))  # last two at 2.5 sigma
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.OUT_OF_CONTROL
    assert verdict.rule_triggered == "2_of_3_beyond_2_sigma"


def test_4_of_5_beyond_1_sigma_fires():
    station = make_station()
    ts = times(5)
    history = list(zip(ts, [10.0, 12.5, 12.5, 12.5, 12.5], strict=False))  # 1.25 sigma each
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.OUT_OF_CONTROL
    assert verdict.rule_triggered == "4_of_5_beyond_1_sigma"


def test_8_consecutive_one_side_fires():
    station = make_station()
    ts = times(8)
    history = list(zip(ts, [10.5] * 8, strict=False))  # slightly above mean, no other rule trips
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.OUT_OF_CONTROL
    assert verdict.rule_triggered == "8_consecutive_one_side"


def test_unknown_for_missing_quantity():
    station = make_station()
    verdict = evaluate_spc(
        station=station, quantity="not-a-real-quantity", history=[(T0, 1.0)], shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.UNKNOWN


def test_unknown_for_empty_history():
    station = make_station()
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=[], shift_changes=[],
        ambient_c=22.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.UNKNOWN


def test_environment_invalid_takes_precedence_over_alarms():
    station = make_station()
    history = [(T0, 100.0)]  # would obviously alarm, if it were even checked
    verdict = evaluate_spc(
        station=station, quantity="ST-01-SEN-1", history=history, shift_changes=[],
        ambient_c=40.0, envelope=ENVELOPE,
    )
    assert verdict.state == SPCState.ENVIRONMENT_INVALID
    assert verdict.rule_triggered is None


def test_unflagged_handover_widens_band_and_avoids_alarm():
    station = make_station(manual=True)
    change_time = T0
    # bias of +3.5 over 10 readings post-handover: (13.5-10)/2 = 1.75 sigma,
    # would not alarm on its own, but demonstrates the widened band is applied.
    ts = times(3, step_s=1.0)
    history = [(t, 13.5) for t in ts]
    verdict = evaluate_spc(
        station=station, quantity="torque_nm", history=history,
        shift_changes=[(change_time, False)],
        ambient_c=22.0, envelope=ENVELOPE, recalibration_n=10,
    )
    assert verdict.recalibrating is True
    assert verdict.uncertainty_band_multiplier == 2.0


def test_flagged_handover_does_not_widen_band():
    station = make_station(manual=True)
    change_time = T0
    ts = times(3, step_s=1.0)
    history = [(t, 13.5) for t in ts]
    verdict = evaluate_spc(
        station=station, quantity="torque_nm", history=history,
        shift_changes=[(change_time, True)],
        ambient_c=22.0, envelope=ENVELOPE, recalibration_n=10,
    )
    assert verdict.recalibrating is True
    assert verdict.uncertainty_band_multiplier == 1.0


def test_after_recalibration_window_mean_is_re_estimated_and_stops_alarming():
    station = make_station(manual=True)
    change_time = T0
    # new operator's genuine level is 15.0 (2.5 sigma from the OLD mean of 10,
    # which would otherwise alarm forever) -- 12 readings, recalibration_n=10.
    ts = times(12, step_s=1.0)
    history = [(t, 15.0) for t in ts]
    verdict = evaluate_spc(
        station=station, quantity="torque_nm", history=history,
        shift_changes=[(change_time, True)],
        ambient_c=22.0, envelope=ENVELOPE, recalibration_n=10,
    )
    assert verdict.recalibrating is False
    assert verdict.state == SPCState.IN_CONTROL
