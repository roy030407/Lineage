"""Role-scoped projections of the live line state.

Each role gets a distinct response shape enforced server-side -- an
Operator's client never receives other stations' data at all, and
Leadership never receives per-station detail, rather than the frontend
simply choosing not to display it.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from lineage.api.deps import AppState, get_app_state
from lineage.config.specs import CommissioningBaseline
from lineage.replay.models import (
    LatestReading,
    LineState,
    MachineHealth,
    SensorHealth,
    StationState,
)

router = APIRouter()


def _require_engine(state: AppState) -> None:
    if state.engine is None:
        raise HTTPException(status_code=409, detail="no run loaded; send action='load' first")


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


class LineSummary(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    occupied_station_count: int
    alarm_station_count: int
    average_upstream_buffer_depth: float


def _summarize(line_state: LineState) -> LineSummary:
    stations = line_state.stations
    occupied = sum(1 for s in stations if s.car_id is not None)
    alarms = sum(1 for s in stations if _is_alarm(s))
    depths = [s.upstream_buffer_depth for s in stations]
    average_depth = sum(depths) / len(depths) if depths else 0.0
    return LineSummary(
        occupied_station_count=occupied,
        alarm_station_count=alarms,
        average_upstream_buffer_depth=average_depth,
    )


class OperatorView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    station_name: str
    sensor_health: SensorHealth
    machine_health: MachineHealth
    latest_readings: list[LatestReading]
    commissioning_baseline: CommissioningBaseline | None


class FloorSupervisorView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    line_state: LineState
    active_alert_station_ids: list[str]


class PlantManagerView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    line_state: LineState
    summary: LineSummary


class LeadershipView(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    summary: LineSummary


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
    return OperatorView(
        station_id=spec.id,
        station_name=spec.name,
        sensor_health=station_state.sensor_health,
        machine_health=station_state.machine_health,
        latest_readings=station_state.latest_readings,
        commissioning_baseline=spec.commissioning_baseline,
    )


@router.get("/api/view/floor_supervisor")
def get_floor_supervisor_view(state: AppState = Depends(get_app_state)) -> FloorSupervisorView:
    _require_engine(state)
    line_state = _current_line_state(state)
    alerts = [s.station_id for s in line_state.stations if _is_alarm(s)]
    return FloorSupervisorView(line_state=line_state, active_alert_station_ids=alerts)


@router.get("/api/view/plant_manager")
def get_plant_manager_view(state: AppState = Depends(get_app_state)) -> PlantManagerView:
    _require_engine(state)
    line_state = _current_line_state(state)
    return PlantManagerView(line_state=line_state, summary=_summarize(line_state))


@router.get("/api/view/leadership")
def get_leadership_view(state: AppState = Depends(get_app_state)) -> LeadershipView:
    _require_engine(state)
    line_state = _current_line_state(state)
    return LeadershipView(summary=_summarize(line_state))
