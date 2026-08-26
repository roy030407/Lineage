"""Tests for lineage.act.proposals; to be filled in alongside real logic."""

from datetime import date

from lineage.act.proposals import propose, simulate
from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    ParamRange,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)
from lineage.trace.models import ContributionCause, TraceResult


def _machine() -> MachineSpec:
    return MachineSpec(
        model="M",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def make_line() -> LineSpec:
    sensor = SensorSpec(
        id="ST-01-SEN-1",
        kind=SensorKind.TORQUE,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )
    station = StationSpec(
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
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=[station],
        layout=LayoutSpec(
            coordinates=[StationCoordinate(station_id="ST-01", x_m=0.0, y_m=0.0)], segments=[]
        ),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


def make_trace_result(deviation_z: float = 4.5) -> TraceResult:
    return TraceResult(
        car_id="CAR-001",
        originating_station_id="ST-01",
        originating_is_verifiable=True,
        ranked_contributions=[
            ContributionCause(
                station_id="ST-01", contribution_score=0.9, verifiable=True, deviation_z=deviation_z
            )
        ],
        affected_cars=[],
    )


def test_propose_generates_bounded_proposal_with_rationale():
    line = make_line()
    trace_result = make_trace_result()

    proposals = propose(trace_result, line)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.station_id == "ST-01"
    assert proposal.parameter_name == "line_speed_pct"
    assert "ST-01" in proposal.rationale
    assert "CAR-001" in proposal.rationale
    assert 60.0 <= proposal.proposed_value <= 110.0


def test_propose_never_targets_readable_only_parameters():
    line = make_line()
    # Station has no changeable_params matching a readable-only quantity;
    # propose() must only ever iterate changeable_params, never readable_params.
    trace_result = make_trace_result()
    proposals = propose(trace_result, line)
    proposed_params = {p.parameter_name for p in proposals}
    assert "ST-01-SEN-1" not in proposed_params  # the sensor id is a readable_param, not changeable


def test_propose_returns_empty_for_unknown_station():
    line = make_line()
    trace_result = make_trace_result()
    trace_result = trace_result.model_copy(update={"originating_station_id": "ST-NOPE"})
    assert propose(trace_result, line) == []


def test_simulate_never_mutates_the_live_line():
    line = make_line()
    trace_result = make_trace_result(deviation_z=4.5)
    proposal = propose(trace_result, line)[0]

    before = line.model_dump(mode="json")
    simulate(proposal, line, current_deviation_z=4.5)
    after = line.model_dump(mode="json")

    assert before == after


def test_simulate_predicts_defect_rate_improvement_for_a_corrective_proposal():
    line = make_line()
    trace_result = make_trace_result(deviation_z=4.5)
    proposal = propose(trace_result, line)[0]

    effect = simulate(proposal, line, current_deviation_z=4.5)

    assert effect.proposal_id == proposal.proposal_id
    # A corrective step should reduce predicted defect probability (a negative delta).
    assert effect.predicted_defect_rate_delta <= 0.0
    lo, hi = effect.defect_rate_confidence_interval
    assert lo <= effect.predicted_defect_rate_delta <= hi
