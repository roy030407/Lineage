"""Tests for lineage.act.envelope; to be filled in alongside real logic."""

from datetime import date

import pytest

from lineage.act.models import Proposal
from lineage.act.validator import validate_proposal
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    MachineSpec,
    ParamRange,
    SensorKind,
    SensorSpec,
    StationSpec,
    Zone,
)


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def make_station() -> StationSpec:
    sensor = SensorSpec(
        id="ST-01-SEN-1",
        kind=SensorKind.TORQUE,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )
    return StationSpec(
        id="ST-01",
        name="Test Station",
        zone=Zone.BODY,
        sequence_index=0,
        sensors=[sensor],
        acquisition_mode=AcquisitionMode.INSTRUMENTED,
        cycle_time_nominal_s=10.0,
        commissioning_baseline=CommissioningBaseline(
            idle=ConditionStats(mean={"ST-01-SEN-1": 5.0}, std={"ST-01-SEN-1": 1.0}),
            loaded=ConditionStats(mean={"ST-01-SEN-1": 10.0}, std={"ST-01-SEN-1": 2.0}),
        ),
        changeable_params={"line_speed_pct": ParamRange(min=60.0, max=110.0, step=1.0)},
        readable_params=["ST-01-SEN-1"],
        machine=_machine(),
        cost_per_hour=10.0,
        value_add_pct=1.0,
    )


def make_proposal(**overrides) -> Proposal:
    defaults = dict(
        proposal_id="p1",
        station_id="ST-01",
        parameter_name="line_speed_pct",
        current_value=100.0,
        proposed_value=105.0,
        rationale="test",
        trace_car_id="CAR-001",
        requires_physical_change=False,
    )
    defaults.update(overrides)
    return Proposal(**defaults)


def test_valid_proposal_passes():
    station = make_station()
    proposal = make_proposal(proposed_value=105.0)
    validate_proposal(proposal, station)  # must not raise


def test_proposal_outside_station_range_is_rejected():
    station = make_station()
    proposal = make_proposal(proposed_value=200.0)  # station range caps at 110
    with pytest.raises(ValueError, match="outside station"):
        validate_proposal(proposal, station)


def test_proposal_outside_absolute_envelope_is_rejected():
    station = make_station()
    # Widen the station's own range so only the plant-wide envelope catches this.
    station = station.model_copy(
        update={"changeable_params": {"line_speed_pct": ParamRange(min=60.0, max=150.0, step=1.0)}}
    )
    proposal = make_proposal(proposed_value=130.0)  # envelope absolute_max is 120
    with pytest.raises(ValueError, match="plant-wide safety envelope"):
        validate_proposal(proposal, station)


def test_proposal_exceeding_max_step_change_is_rejected():
    station = make_station()
    # 80.0 is within the station's own [60, 110] range, but a 20% drop from
    # current_value=100 exceeds the envelope's 15% max single-step change.
    proposal = make_proposal(current_value=100.0, proposed_value=80.0)
    with pytest.raises(ValueError, match="max single-step change"):
        validate_proposal(proposal, station)


def test_proposal_for_non_changeable_parameter_is_rejected():
    station = make_station()
    proposal = make_proposal(parameter_name="torque_setpoint", proposed_value=10.0)
    with pytest.raises(ValueError, match="not a changeable parameter"):
        validate_proposal(proposal, station)


def test_proposal_for_undefined_envelope_is_rejected():
    station = make_station()
    station = station.model_copy(
        update={
            "changeable_params": {
                "undefined_param": ParamRange(min=0.0, max=100.0, step=1.0)
            }
        }
    )
    proposal = make_proposal(parameter_name="undefined_param", proposed_value=50.0)
    with pytest.raises(ValueError, match="no safety envelope defined"):
        validate_proposal(proposal, station)
