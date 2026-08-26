"""Given current buffer depths and recent cycle times, rolls the line forward
using the twin's own queueing dynamics -- derived directly from StationVisit
entry/exit times, not a separate simulation -- to report where starvation or
blocking will form. The headline output is minutes_to_onset, not a severity
score: the plant currently learns about a bottleneck as an end-of-shift
throughput number, this is meant to be the 10am warning instead."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from lineage.config.specs import LineSpec
from lineage.twin.car import StationVisit
from lineage.twin.genealogy import GenealogyStore

DEFAULT_LOOKBACK_VISITS = 15
DEFAULT_HORIZON_MINUTES = 60.0
DEFAULT_BUFFER_CAPACITY = 3
RATE_TOLERANCE = 0.02
"""Fractional difference between feed and service rate below which they're
considered balanced (HEALTHY) rather than trending toward a bottleneck."""


class BottleneckState(StrEnum):
    STARVED = "starved"
    BLOCKED = "blocked"
    HEALTHY = "healthy"


class BottleneckForecast(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    station_id: str
    predicted_state: BottleneckState
    minutes_to_onset: float | None = None
    confidence: float
    contributing_upstream_station: str | None = None
    """The station driving this prediction. For STARVED this is literally
    upstream (too slow feeding this station). For BLOCKED it's the
    downstream station whose slowness is backing this one up -- the field
    name follows the requested schema, but the direction isn't always
    literally upstream; documented here rather than silently assumed."""


def _recent_visits(
    store: GenealogyStore, station_id: str, as_of: datetime, lookback: int
) -> list[StationVisit]:
    car_ids = store.cars_through(station_id, datetime.min, as_of)[-lookback:]
    visits = []
    for car_id in car_ids:
        visit = next((v for v in store.car(car_id).visits if v.station_id == station_id), None)
        if visit is not None:
            visits.append(visit)
    visits.sort(key=lambda v: v.entry_time)
    return visits


def _service_rate_per_minute(visits: list[StationVisit]) -> tuple[float, float]:
    """Returns (rate, stability) where stability in (0, 1] reflects how
    consistent recent dwell times have been -- noisy samples yield lower
    confidence, not a falsely precise forecast."""
    if len(visits) < 2:
        return 0.0, 0.0
    dwell_minutes = [v.dwell_time_s / 60.0 for v in visits]
    mean_dwell = sum(dwell_minutes) / len(dwell_minutes)
    if mean_dwell <= 0:
        return 0.0, 0.0
    variance = sum((d - mean_dwell) ** 2 for d in dwell_minutes) / len(dwell_minutes)
    stability = 1.0 / (1.0 + variance)
    return 1.0 / mean_dwell, stability


def _arrival_rate_per_minute(visits: list[StationVisit]) -> float:
    if len(visits) < 2:
        return 0.0
    gaps = [
        (visits[i + 1].entry_time - visits[i].entry_time).total_seconds() / 60.0
        for i in range(len(visits) - 1)
    ]
    mean_gap = sum(gaps) / len(gaps)
    return 1.0 / mean_gap if mean_gap > 0 else 0.0


def _current_buffer_depth(
    store: GenealogyStore, upstream_id: str, downstream_id: str, as_of: datetime, lookback: int
) -> int:
    """Cars that have exited `upstream_id` but not yet entered `downstream_id`
    as of `as_of` -- the same idea datagen.writer._derive_buffer_events uses,
    reimplemented here against twin data directly."""
    car_ids = store.cars_through(upstream_id, datetime.min, as_of)[-lookback:]
    depth = 0
    for car_id in car_ids:
        twin = store.car(car_id)
        upstream_visit = next((v for v in twin.visits if v.station_id == upstream_id), None)
        downstream_visit = next((v for v in twin.visits if v.station_id == downstream_id), None)
        if upstream_visit is None or upstream_visit.exit_time > as_of:
            continue
        if downstream_visit is None or downstream_visit.entry_time > as_of:
            depth += 1
    return depth


@dataclass(frozen=True)
class _GapDiagnosis:
    state: BottleneckState
    affected_station_id: str
    contributing_station_id: str
    minutes_to_onset: float
    confidence: float


def _diagnose_gap(
    store: GenealogyStore,
    upstream_id: str,
    downstream_id: str,
    as_of: datetime,
    lookback: int,
    capacity: int,
) -> _GapDiagnosis | None:
    """Diagnoses the single gap between upstream_id and downstream_id, or
    returns None if there's not enough data or the rates are balanced."""
    upstream_visits = _recent_visits(store, upstream_id, as_of, lookback)
    downstream_visits = _recent_visits(store, downstream_id, as_of, lookback)
    if len(upstream_visits) < 2 or len(downstream_visits) < 2:
        return None

    feed_rate = _arrival_rate_per_minute(upstream_visits)
    service_rate, stability = _service_rate_per_minute(downstream_visits)
    if feed_rate <= 0 or service_rate <= 0:
        return None

    depth = _current_buffer_depth(store, upstream_id, downstream_id, as_of, lookback)
    sample_confidence = min(len(upstream_visits), len(downstream_visits)) / lookback
    confidence = max(0.0, min(1.0, sample_confidence * stability))

    relative_diff = (feed_rate - service_rate) / service_rate
    if relative_diff > RATE_TOLERANCE:
        minutes = max(0.0, (capacity - depth) / (feed_rate - service_rate))
        return _GapDiagnosis(
            BottleneckState.BLOCKED, upstream_id, downstream_id, minutes, confidence
        )
    if relative_diff < -RATE_TOLERANCE and depth > 0:
        # A downstream station that's simply faster than it's fed sits idle
        # between cars forever -- that's normal steady-state slack, not a
        # developing problem. STARVED only means something when there's an
        # actual existing buffer draining toward empty.
        minutes = max(0.0, depth / (service_rate - feed_rate))
        return _GapDiagnosis(
            BottleneckState.STARVED, downstream_id, upstream_id, minutes, confidence
        )
    return None


def forecast_station(
    *,
    line: LineSpec,
    store: GenealogyStore,
    station_id: str,
    as_of: datetime,
    lookback_visits: int = DEFAULT_LOOKBACK_VISITS,
    horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
    buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
) -> BottleneckForecast:
    """Forecasts `station_id`'s state within `horizon_minutes`, checking both
    the gap upstream of it (could starve it) and downstream of it (could
    block it), reporting whichever has the sooner onset."""
    station_ids = [s.id for s in line.stations]
    if station_id not in station_ids:
        return BottleneckForecast(
            station_id=station_id, predicted_state=BottleneckState.HEALTHY, confidence=0.0
        )
    idx = station_ids.index(station_id)

    candidates: list[_GapDiagnosis] = []

    if idx + 1 < len(station_ids):
        diagnosis = _diagnose_gap(
            store, station_id, station_ids[idx + 1], as_of, lookback_visits, buffer_capacity
        )
        if diagnosis is not None and diagnosis.affected_station_id == station_id:
            candidates.append(diagnosis)

    if idx > 0:
        diagnosis = _diagnose_gap(
            store, station_ids[idx - 1], station_id, as_of, lookback_visits, buffer_capacity
        )
        if diagnosis is not None and diagnosis.affected_station_id == station_id:
            candidates.append(diagnosis)

    candidates = [c for c in candidates if c.minutes_to_onset <= horizon_minutes]
    if not candidates:
        return BottleneckForecast(
            station_id=station_id, predicted_state=BottleneckState.HEALTHY, confidence=0.0
        )

    soonest = min(candidates, key=lambda c: c.minutes_to_onset)
    return BottleneckForecast(
        station_id=station_id,
        predicted_state=soonest.state,
        minutes_to_onset=soonest.minutes_to_onset,
        confidence=soonest.confidence,
        contributing_upstream_station=soonest.contributing_station_id,
    )


def forecast_line(
    *,
    line: LineSpec,
    store: GenealogyStore,
    as_of: datetime,
    lookback_visits: int = DEFAULT_LOOKBACK_VISITS,
    horizon_minutes: float = DEFAULT_HORIZON_MINUTES,
    buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
) -> list[BottleneckForecast]:
    return [
        forecast_station(
            line=line,
            store=store,
            station_id=station.id,
            as_of=as_of,
            lookback_visits=lookback_visits,
            horizon_minutes=horizon_minutes,
            buffer_capacity=buffer_capacity,
        )
        for station in line.stations
    ]
