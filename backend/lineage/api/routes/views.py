"""Role-scoped projections of the live line state.

Each role gets a distinct response shape enforced server-side -- an
Operator's client never receives other stations' data at all, and
Leadership never receives per-station detail, rather than the frontend
simply choosing not to display it.
"""

from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.api.deps import AppState, get_app_state
from lineage.common.types import RiskLevel
from lineage.config.specs import (
    CommissioningBaseline,
    EnvironmentEnvelope,
    LineSpec,
    StationSpec,
    Zone,
)
from lineage.datagen.generators import ambient_temp_c
from lineage.datagen.models import RunConfig
from lineage.predict.bottleneck import BottleneckForecast, BottleneckState, forecast_line
from lineage.predict.risk import RiskModel, assess_risk
from lineage.predict.spc import SPCState, SPCVerdict, evaluate_spc
from lineage.replay.models import (
    LatestReading,
    LineState,
    MachineHealth,
    SensorHealth,
    StationState,
)
from lineage.replay.run_data import RunData
from lineage.trace.lineage_query import traced_failures
from lineage.trace.models import TraceResult
from lineage.twin.genealogy import GenealogyStore

router = APIRouter()


def _representative_quantity(station: StationSpec) -> str | None:
    """The one sensor id (instrumented/mixed) or readable_param name (manual)
    to score SPC against -- same convention predict/risk.py's feature builder
    uses, so a station's live control state and its retrospective risk
    features are never computed two different ways."""
    if station.sensors:
        return station.sensors[0].id
    if station.readable_params:
        return station.readable_params[0]
    return None


def _live_spc_verdict(
    *,
    station: StationSpec,
    run_data: RunData,
    run_config: RunConfig,
    envelope: EnvironmentEnvelope,
    as_of: datetime,
) -> SPCVerdict | None:
    """The station's current SPC control state, scored live against its
    telemetry-to-date -- None if it has no sensor/manual quantity to score at
    all, or hasn't reported anything yet (sensor_health already distinguishes
    those cases; this only answers "given a real reading history, what does
    it say"). Ambient temperature is reconstructed from the run's own
    config (baseline + zone excursions, keyed by the car the most recent
    reading belongs to) rather than assumed, since telemetry.csv never
    persists ambient_c per row -- it's a generation-time input, not a
    recorded quantity."""
    quantity = _representative_quantity(station)
    if quantity is None:
        return None
    history_with_car = run_data.reading_history_at(station.id, quantity, as_of)
    if not history_with_car:
        return None
    shift_changes = run_data.shift_changes_at(station.id, as_of)
    history = [(t, v) for t, v, _ in history_with_car]
    last_car_id = history_with_car[-1][2]
    car_index = int(last_car_id.split("-")[1])
    ambient_c = ambient_temp_c(
        run_config.baseline_temp_c, run_config.environment_excursions, car_index, station.zone
    )
    return evaluate_spc(
        station=station,
        quantity=quantity,
        history=history,
        shift_changes=shift_changes,
        ambient_c=ambient_c,
        envelope=envelope,
    )


_ALARM_SPC_STATES = {SPCState.OUT_OF_CONTROL, SPCState.ENVIRONMENT_INVALID}
_WARNING_BOTTLENECK_STATES = {BottleneckState.STARVED, BottleneckState.BLOCKED}


class SPCAlarm(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    quantity: str
    state: SPCState
    rule_triggered: str | None
    confidence: float


def _spc_alarms(
    *, line: LineSpec, run_data: RunData, run_config: RunConfig, as_of: datetime
) -> list[SPCAlarm]:
    """Every station currently OUT_OF_CONTROL or ENVIRONMENT_INVALID -- never
    IN_CONTROL/UNKNOWN, since those aren't alarms. Live per-request cost is
    proportional to line length (one evaluate_spc call per station); this is
    the same class of scan-cost tradeoff already flagged for RunData/
    build_features and hasn't been measured as a problem at 42 stations."""
    alarms = []
    for station in line.stations:
        verdict = _live_spc_verdict(
            station=station,
            run_data=run_data,
            run_config=run_config,
            envelope=line.environment_envelope,
            as_of=as_of,
        )
        if verdict is not None and verdict.state in _ALARM_SPC_STATES:
            alarms.append(
                SPCAlarm(
                    station_id=verdict.station_id,
                    quantity=verdict.quantity,
                    state=verdict.state,
                    rule_triggered=verdict.rule_triggered,
                    confidence=verdict.confidence,
                )
            )
    return alarms


class HighRiskCar(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    car_id: str
    current_station_id: str
    next_inspection_station_id: str
    stations_remaining: int
    risk_level: RiskLevel
    probability: float | None
    confidence: float


def _next_inspection_station(line: LineSpec, after_sequence_index: int) -> StationSpec | None:
    candidates = [
        s
        for s in line.stations
        if s.is_inspection_station and s.sequence_index > after_sequence_index
    ]
    return min(candidates, key=lambda s: s.sequence_index) if candidates else None


def _high_risk_cars(
    *, line: LineSpec, store: GenealogyStore, line_state: LineState, model: RiskModel | None
) -> list[HighRiskCar]:
    """Cars currently on the line, assessed against whichever inspection
    station they'll reach next. Each car's twin is truncated to visits that
    have already ended as of `line_state.timestamp` -- GenealogyStore is
    built once from the complete generated run at 'load' time, so an
    untruncated twin would hand assess_risk station visits that haven't
    "happened" yet in replay time, a real future-data leak, not a
    hypothetical one."""
    if model is None:
        return []

    station_by_id = {s.id: s for s in line.stations}
    as_of = line_state.timestamp
    results = []
    for station_state in line_state.stations:
        if station_state.car_id is None:
            continue
        current = station_by_id[station_state.station_id]
        target = _next_inspection_station(line, current.sequence_index)
        if target is None:
            continue

        car = store.car(station_state.car_id)
        truncated = car.model_copy(
            update={"visits": [v for v in car.visits if v.exit_time <= as_of]}
        )
        assessment = assess_risk(
            car=truncated, line=line, store=store, inspection_station_id=target.id, model=model
        )
        if assessment.risk_level != RiskLevel.HIGH:
            continue
        results.append(
            HighRiskCar(
                car_id=station_state.car_id,
                current_station_id=current.id,
                next_inspection_station_id=target.id,
                stations_remaining=target.sequence_index - current.sequence_index,
                risk_level=assessment.risk_level,
                probability=assessment.probability,
                confidence=assessment.confidence,
            )
        )
    return results


def _try_load_risk_model(state: AppState) -> RiskModel | None:
    """None whenever no trained risk model is found -- data/models/ is
    gitignored (a locally-trained artifact, not committed), so a fresh clone
    or CI environment legitimately has none. High-risk-car reporting is one
    feature among several in the Floor Supervisor view; its absence
    shouldn't 409 the whole view the way /api/predict/* does for its own,
    single-purpose endpoints."""
    try:
        return RiskModel(state.models_root / "risk_v1")
    except Exception:
        return None


def _require_engine(state: AppState) -> None:
    if state.engine is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")


def _load_run_config(state: AppState) -> RunConfig:
    assert state.current_run_dir is not None  # set alongside engine at 'load' time
    return RunConfig.model_validate_json((state.current_run_dir / "run_config.json").read_text())


def _current_line_state(state: AppState) -> LineState:
    """The engine's own tick loop already computes this once per second and
    broadcasts it; reuse that instead of recomputing it again per request --
    RunData's per-station queries scan proportionally more of the run as
    simulated time advances, so a naive re-call here would double an
    already-growing cost on every poll from every open role view.
    Falls back to a direct call only when nothing has ticked yet (e.g.
    right after 'load', before the first 'play')."""
    recent = state.snapshot_history.recent()
    if recent:
        return recent[-1]
    assert state.engine is not None  # _require_engine already checked this
    return state.engine.current_state()


def _is_alarm(station: StationState) -> bool:
    return station.sensor_health == SensorHealth.RED or station.machine_health == MachineHealth.RED


class OperatorView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    station_name: str
    sensor_health: SensorHealth
    machine_health: MachineHealth
    latest_readings: list[LatestReading]
    commissioning_baseline: CommissioningBaseline | None
    spc_verdict: SPCVerdict | None
    """The station's live control/handover/calibration status -- None only
    when there's no quantity to score at all or nothing has reported yet
    (sensor_health already distinguishes those); otherwise a real verdict,
    including recalibrating, straight from predict/spc.py's evaluate_spc."""


class FloorSupervisorView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    line_state: LineState
    active_alert_station_ids: list[str]
    spc_alarms: list[SPCAlarm]
    high_risk_cars: list[HighRiskCar]
    bottleneck_warnings: list[BottleneckForecast]
    issue_assignments: dict[str, str]
    """issue_id (a station_id or car_id from one of the lists above) ->
    operator_id. See AppState.issue_assignments and
    POST /api/floor_supervisor/assignments."""


def _ensure_trace_results(state: AppState) -> list[TraceResult]:
    """Shared with api/routes/act.py's proposal generation -- both need every
    real failed inspection traced back to its likely origin, and tracing is
    real per-car work, not free. Cached on AppState.trace_results so it's
    only ever computed once per loaded run, whichever of the two features
    asks for it first."""
    if state.trace_results is not None:
        return state.trace_results
    if state.line is None or state.genealogy_store is None or state.current_run_dir is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")
    results = traced_failures(state.line, state.genealogy_store, state.current_run_dir)
    state.trace_results = results
    return results


class DefectRateByStation(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    zone: Zone
    total_inspections: int
    fail_count: int
    fail_rate: float


class DefectRateByZone(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    zone: Zone
    total_inspections: int
    fail_count: int
    fail_rate: float


class ReworkSummary(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    total_defect_events: int
    cars_requiring_rework: int
    total_cars_inspected: int
    rework_rate: float


class RecurringRootCause(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    occurrence_count: int
    verified_occurrences: int
    """Traces whose named origin had sensor data confirming the deviation."""
    suspected_occurrences: int
    """Traces that fell back to an unverifiable (manual) origin -- nothing
    confirmable crossed threshold, so the earliest unverifiable station was
    named. Counted separately so manual stations aren't silently over-blamed
    with the same weight as sensor-confirmed origins."""
    example_car_ids: list[str]


class MaintenanceStatus(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    machine_model: str
    maintenance_interval_days: int
    days_since_maintenance: float
    days_until_due: float
    recent_wear_state: float | None
    """Mean machine_wear_state across the station's most recent visits --
    None if it has no visits yet. A high value despite still being within
    the scheduled interval is exactly the "predicted need ahead of
    schedule" signal this field exists to catch; schedule and prediction
    are reported side by side rather than collapsed into one score."""


_MAINTENANCE_WEAR_LOOKBACK = 5


def _recent_wear_state(store: GenealogyStore, station_id: str) -> float | None:
    car_ids = store.cars_through(station_id, datetime.min, datetime.max)[
        -_MAINTENANCE_WEAR_LOOKBACK:
    ]
    wear_states = []
    for car_id in car_ids:
        visit = next((v for v in store.car(car_id).visits if v.station_id == station_id), None)
        if visit is not None:
            wear_states.append(visit.machine_wear_state)
    return sum(wear_states) / len(wear_states) if wear_states else None


class PlantManagerView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    defect_rate_by_station: list[DefectRateByStation]
    defect_rate_by_zone: list[DefectRateByZone]
    rework: ReworkSummary
    recurring_root_causes: list[RecurringRootCause]
    maintenance_status: list[MaintenanceStatus]


class CostByZone(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    zone: Zone
    total_cost_per_hour: float
    value_added_cost_per_hour: float
    value_added_ratio: float


class SensorRetrofitCandidate(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    zone: Zone
    cost_per_hour: float
    value_add_pct: float
    economic_weight: float
    """cost_per_hour * value_add_pct / 100 -- how much value-adding cost
    currently runs through this station with no automated way to catch a
    defect at the source."""
    recurring_defect_occurrences: int
    """How often this station shows up as a traced defect origin this run
    (Plant Manager's recurring_root_causes, reused directly -- a manual
    station implicated often is a real, data-backed retrofit signal, not
    an invented one)."""
    suspected_defect_occurrences: int
    """The subset of recurring_defect_occurrences where the trace could not
    confirm the origin with sensor data and fell back to naming this
    (unverifiable, manual) station. For a sensorless station this is
    typically all of them -- which is itself the retrofit argument: the
    line keeps suspecting this station and cannot check."""


class LeadershipView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    total_cost_per_hour: float
    total_value_added_cost_per_hour: float
    value_added_ratio: float
    cost_by_zone: list[CostByZone]
    sensor_retrofit_candidates: list[SensorRetrofitCandidate]
    """Manual (no-sensor) stations only, ranked by recurring defect
    occurrences first, then economic weight -- never a fabricated dollar
    "ROI" figure, since there's no real cost-per-defect input anywhere in
    the data model to compute one from."""


@router.get("/api/view/operator")
def get_operator_view(
    station_id: str, state: AppState = Depends(get_app_state)
) -> OperatorView:
    _require_engine(state)
    assert state.line is not None  # a loaded engine implies a loaded line
    spec = next((s for s in state.line.stations if s.id == station_id), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown station {station_id!r}")

    line_state = _current_line_state(state)
    station_state = next(s for s in line_state.stations if s.station_id == station_id)

    assert state.engine is not None  # _require_engine already checked this
    run_config = _load_run_config(state)
    spc_verdict = _live_spc_verdict(
        station=spec,
        run_data=state.engine.run_data,
        run_config=run_config,
        envelope=state.line.environment_envelope,
        as_of=line_state.timestamp,
    )

    return OperatorView(
        station_id=spec.id,
        station_name=spec.name,
        sensor_health=station_state.sensor_health,
        machine_health=station_state.machine_health,
        latest_readings=station_state.latest_readings,
        commissioning_baseline=spec.commissioning_baseline,
        spc_verdict=spc_verdict,
    )


@router.get("/api/view/floor_supervisor")
def get_floor_supervisor_view(state: AppState = Depends(get_app_state)) -> FloorSupervisorView:
    _require_engine(state)
    assert state.line is not None  # a loaded engine implies a loaded line
    assert state.engine is not None
    assert state.genealogy_store is not None  # built alongside engine at 'load' time

    line_state = _current_line_state(state)
    alerts = [s.station_id for s in line_state.stations if _is_alarm(s)]

    run_config = _load_run_config(state)
    spc_alarms = _spc_alarms(
        line=state.line,
        run_data=state.engine.run_data,
        run_config=run_config,
        as_of=line_state.timestamp,
    )
    high_risk_cars = _high_risk_cars(
        line=state.line,
        store=state.genealogy_store,
        line_state=line_state,
        model=_try_load_risk_model(state),
    )
    bottleneck_warnings = [
        forecast
        for forecast in forecast_line(
            line=state.line, store=state.genealogy_store, as_of=line_state.timestamp
        )
        if forecast.predicted_state in _WARNING_BOTTLENECK_STATES
    ]

    return FloorSupervisorView(
        line_state=line_state,
        active_alert_station_ids=alerts,
        spc_alarms=spc_alarms,
        high_risk_cars=high_risk_cars,
        bottleneck_warnings=bottleneck_warnings,
        issue_assignments=dict(state.issue_assignments),
    )


class AssignIssueRequest(BaseModel):
    issue_id: str
    operator_id: str


@router.post("/api/floor_supervisor/assignments")
def assign_issue(
    req: AssignIssueRequest, state: AppState = Depends(get_app_state)
) -> dict[str, str]:
    """Records that `operator_id` has been asked to handle `issue_id` (a
    station_id or car_id from the alert queue above). A minimal in-memory
    record, not a real assignment/notification system -- see
    AppState.issue_assignments."""
    _require_engine(state)
    state.issue_assignments[req.issue_id] = req.operator_id
    return dict(state.issue_assignments)


@router.delete("/api/floor_supervisor/assignments/{issue_id}")
def unassign_issue(issue_id: str, state: AppState = Depends(get_app_state)) -> dict[str, str]:
    _require_engine(state)
    state.issue_assignments.pop(issue_id, None)
    return dict(state.issue_assignments)


@router.get("/api/view/plant_manager")
def get_plant_manager_view(state: AppState = Depends(get_app_state)) -> PlantManagerView:
    """Weekly, not live -- defect trends, rework volume, recurring root
    causes, and maintenance schedule vs. predicted need, never a live
    per-station firehose (that's Floor Supervisor's job). Aggregates are
    computed over the whole run to date, so this does still change as more
    of the simulated week completes, but there is no live LineState here at
    all, unlike the field this replaced."""
    _require_engine(state)
    assert state.line is not None  # a loaded engine implies a loaded line
    assert state.engine is not None
    assert state.genealogy_store is not None  # built alongside engine at 'load' time
    assert state.current_run_dir is not None

    inspection_df = pd.read_csv(
        state.current_run_dir / "inspection.csv", parse_dates=["timestamp"]
    )
    station_by_id = {s.id: s for s in state.line.stations}

    defect_rate_by_station = []
    for station_id, group in inspection_df.groupby("station_id"):
        station = station_by_id.get(station_id)
        if station is None:
            continue
        total = len(group)
        fails = int((group.result == "fail").sum())
        defect_rate_by_station.append(
            DefectRateByStation(
                station_id=station_id,
                zone=station.zone,
                total_inspections=total,
                fail_count=fails,
                fail_rate=fails / total if total else 0.0,
            )
        )
    defect_rate_by_station.sort(key=lambda d: d.station_id)

    zone_totals: dict[Zone, list[int]] = {}
    for d in defect_rate_by_station:
        totals = zone_totals.setdefault(d.zone, [0, 0])
        totals[0] += d.total_inspections
        totals[1] += d.fail_count
    defect_rate_by_zone = [
        DefectRateByZone(
            zone=zone, total_inspections=total, fail_count=fails,
            fail_rate=fails / total if total else 0.0,
        )
        for zone, (total, fails) in zone_totals.items()
    ]

    failed = inspection_df[inspection_df.result == "fail"]
    cars_requiring_rework = int(failed.car_id.nunique())
    total_cars_inspected = int(inspection_df.car_id.nunique())
    rework = ReworkSummary(
        total_defect_events=len(failed),
        cars_requiring_rework=cars_requiring_rework,
        total_cars_inspected=total_cars_inspected,
        rework_rate=(
            cars_requiring_rework / total_cars_inspected if total_cars_inspected else 0.0
        ),
    )

    origin_cars: dict[str, list[str]] = {}
    origin_verified: dict[str, int] = {}
    for result in _ensure_trace_results(state):
        origin_cars.setdefault(result.originating_station_id, []).append(result.car_id)
        if result.originating_is_verifiable:
            origin_verified[result.originating_station_id] = (
                origin_verified.get(result.originating_station_id, 0) + 1
            )
    recurring_root_causes = sorted(
        (
            RecurringRootCause(
                station_id=station_id,
                occurrence_count=len(car_ids),
                verified_occurrences=origin_verified.get(station_id, 0),
                suspected_occurrences=len(car_ids) - origin_verified.get(station_id, 0),
                example_car_ids=car_ids[:5],
            )
            for station_id, car_ids in origin_cars.items()
        ),
        key=lambda cause: cause.occurrence_count,
        reverse=True,
    )

    as_of = _current_line_state(state).timestamp
    maintenance_status = []
    for station in state.line.stations:
        days_since = state.engine.run_data.days_since_maintenance_at(station, as_of)
        maintenance_status.append(
            MaintenanceStatus(
                station_id=station.id,
                machine_model=station.machine.model,
                maintenance_interval_days=station.machine.maintenance_interval_days,
                days_since_maintenance=days_since,
                days_until_due=station.machine.maintenance_interval_days - days_since,
                recent_wear_state=_recent_wear_state(state.genealogy_store, station.id),
            )
        )

    return PlantManagerView(
        defect_rate_by_station=defect_rate_by_station,
        defect_rate_by_zone=defect_rate_by_zone,
        rework=rework,
        recurring_root_causes=recurring_root_causes,
        maintenance_status=maintenance_status,
    )


@router.get("/api/view/leadership")
def get_leadership_view(state: AppState = Depends(get_app_state)) -> LeadershipView:
    """Replaces the old live occupied/alarm/buffer triple entirely -- no
    per-station detail, live or otherwise. Real cost/value-add numbers from
    StationSpec (previously read by nothing anywhere in the backend), and a
    sensor-retrofit ranking grounded in that plus Task 6's real
    recurring-root-cause data, never a fabricated dollar "ROI" figure."""
    _require_engine(state)
    assert state.line is not None  # a loaded engine implies a loaded line

    total_cost = 0.0
    total_value_added_cost = 0.0
    zone_totals: dict[Zone, list[float]] = {}
    for station in state.line.stations:
        value_added_cost = station.cost_per_hour * (station.value_add_pct / 100.0)
        total_cost += station.cost_per_hour
        total_value_added_cost += value_added_cost
        totals = zone_totals.setdefault(station.zone, [0.0, 0.0])
        totals[0] += station.cost_per_hour
        totals[1] += value_added_cost

    cost_by_zone = [
        CostByZone(
            zone=zone,
            total_cost_per_hour=cost,
            value_added_cost_per_hour=value_added_cost,
            value_added_ratio=value_added_cost / cost if cost else 0.0,
        )
        for zone, (cost, value_added_cost) in zone_totals.items()
    ]

    origin_counts: dict[str, int] = {}
    suspected_counts: dict[str, int] = {}
    for result in _ensure_trace_results(state):
        origin_counts[result.originating_station_id] = (
            origin_counts.get(result.originating_station_id, 0) + 1
        )
        if not result.originating_is_verifiable:
            suspected_counts[result.originating_station_id] = (
                suspected_counts.get(result.originating_station_id, 0) + 1
            )

    candidates = [
        SensorRetrofitCandidate(
            station_id=station.id,
            zone=station.zone,
            cost_per_hour=station.cost_per_hour,
            value_add_pct=station.value_add_pct,
            economic_weight=station.cost_per_hour * (station.value_add_pct / 100.0),
            recurring_defect_occurrences=origin_counts.get(station.id, 0),
            suspected_defect_occurrences=suspected_counts.get(station.id, 0),
        )
        for station in state.line.stations
        if not station.sensors
    ]
    candidates.sort(
        key=lambda c: (c.recurring_defect_occurrences, c.economic_weight), reverse=True
    )

    return LeadershipView(
        total_cost_per_hour=total_cost,
        total_value_added_cost_per_hour=total_value_added_cost,
        value_added_ratio=total_value_added_cost / total_cost if total_cost else 0.0,
        cost_by_zone=cost_by_zone,
        sensor_retrofit_candidates=candidates,
    )
