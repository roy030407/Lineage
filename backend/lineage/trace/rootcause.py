"""Correlates anomaly timing with upstream station events and sensor drift:
scores each visit a car made against that station's commissioning baseline
and the fleet's readings at that station in the same window."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from lineage.config.specs import LineSpec, StationSpec
from lineage.trace.models import ContributionCause
from lineage.twin.car import CarTwin, StationVisit
from lineage.twin.genealogy import GenealogyStore

DEFAULT_DEVIATION_THRESHOLD = 3.0
DEFAULT_FLEET_WINDOW = timedelta(minutes=30)


def _all_quantities(station: StationSpec) -> list[str]:
    """Every quantity worth checking at this station -- all of its sensors
    for instrumented/mixed stations, or its manual readable_params. A
    station can have more than one sensor, and a defect may hit only one of
    them, so every quantity is scored, never just "the first sensor"."""
    if station.sensors:
        return [s.id for s in station.sensors]
    return list(station.readable_params)


def _reading_value(visit: StationVisit, quantity: str) -> float | None:
    reading = next(
        (r for r in visit.readings if r.sensor_id == quantity or r.quantity == quantity), None
    )
    return reading.value if reading is not None else None


def _commissioning_z(station: StationSpec, quantity: str, value: float) -> float | None:
    baseline = station.commissioning_baseline
    if baseline is None or quantity not in baseline.loaded.mean:
        return None
    std = baseline.loaded.std.get(quantity, 0.0)
    if std <= 0:
        return None
    return (value - baseline.loaded.mean[quantity]) / std


def _fleet_z(
    store: GenealogyStore,
    station_id: str,
    quantity: str,
    value: float,
    around: datetime,
    window: timedelta,
    exclude_car_id: str,
) -> float | None:
    """This car's deviation relative to *other* cars' readings at the same
    station in the same window -- catches a fleet-wide drift the static
    commissioning baseline alone might not flag as unusual for this one car,
    or the reverse: a car that stands out from its immediate peers even when
    still within the original commissioning bounds."""
    car_ids = store.cars_through(station_id, around - window, around + window)
    values = []
    for car_id in car_ids:
        if car_id == exclude_car_id:
            continue
        visit = next((v for v in store.car(car_id).visits if v.station_id == station_id), None)
        if visit is None:
            continue
        other_value = _reading_value(visit, quantity)
        if other_value is not None:
            values.append(other_value)
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance**0.5
    if std <= 0:
        return None
    return (value - mean) / std


def _quantity_deviation(
    store: GenealogyStore,
    station: StationSpec,
    quantity: str,
    value: float,
    around: datetime,
    window: timedelta,
    exclude_car_id: str,
) -> float | None:
    commissioning_z = _commissioning_z(station, quantity, value)
    fleet_z = _fleet_z(store, station.id, quantity, value, around, window, exclude_car_id)
    candidates = [z for z in (commissioning_z, fleet_z) if z is not None]
    return max(candidates, key=abs) if candidates else None


@dataclass(frozen=True)
class StationDeviation:
    """Internal scoring record for one station a car visited. `deviation_z`
    and `quantity` are None exactly when `verifiable` is False -- there was
    no numeric reading for this car at this station to score at all.
    `quantity` names whichever of the station's sensors/readable_params
    produced the largest deviation, so downstream cohort queries compare
    apples to apples."""

    station_id: str
    sequence_index: int
    verifiable: bool
    deviation_z: float | None
    quantity: str | None = None


def score_visits(
    line: LineSpec,
    store: GenealogyStore,
    car: CarTwin,
    up_to_station_id: str,
    fleet_window: timedelta = DEFAULT_FLEET_WINDOW,
) -> list[StationDeviation]:
    """Scores every station the car visited, from the start of the line up
    to (and including) `up_to_station_id`, against both its commissioning
    baseline and the fleet's readings at that station in the same window --
    checking every quantity the station has, not just one representative
    sensor, since a defect may hit only one of several."""
    sequence_by_id = {s.id: s.sequence_index for s in line.stations}
    visits_by_station = {v.station_id: v for v in car.visits}
    up_to_index = sequence_by_id.get(up_to_station_id, len(line.stations) - 1)

    results = []
    for station in line.stations:
        if station.sequence_index > up_to_index:
            break
        visit = visits_by_station.get(station.id)
        if visit is None:
            continue

        best_quantity = None
        best_z = None
        for quantity in _all_quantities(station):
            value = _reading_value(visit, quantity)
            if value is None:
                continue
            z = _quantity_deviation(
                store, station, quantity, value, visit.entry_time, fleet_window, car.car_id
            )
            if z is not None and (best_z is None or abs(z) > abs(best_z)):
                best_z, best_quantity = z, quantity

        if best_z is None:
            results.append(StationDeviation(station.id, station.sequence_index, False, None))
        else:
            results.append(
                StationDeviation(station.id, station.sequence_index, True, best_z, best_quantity)
            )

    return results


def find_originating_station(
    deviations: list[StationDeviation], threshold: float = DEFAULT_DEVIATION_THRESHOLD
) -> StationDeviation | None:
    """Earliest verifiable station whose deviation exceeds threshold is the
    primary answer. If none exists anywhere, falls back to the earliest
    UNVERIFIABLE station rather than reporting nothing -- it may look clean
    and still be the cause, so it's never eliminated, only deprioritized
    behind actual evidence when evidence exists."""
    verifiable_exceeding = [
        d
        for d in deviations
        if d.verifiable and d.deviation_z is not None and abs(d.deviation_z) >= threshold
    ]
    if verifiable_exceeding:
        return min(verifiable_exceeding, key=lambda d: d.sequence_index)

    unverifiable = [d for d in deviations if not d.verifiable]
    if unverifiable:
        return min(unverifiable, key=lambda d: d.sequence_index)
    return None


def rank_contributions(
    deviations: list[StationDeviation], threshold: float = DEFAULT_DEVIATION_THRESHOLD
) -> list[ContributionCause]:
    """Every upstream station gets a contribution entry -- never just the
    top one, since multi-causal defects are the norm. Unverifiable stations
    get a fixed, honest mid-level score (can't confirm, can't rule out),
    never zero (which would silently eliminate them) and never inflated."""
    causes = []
    for d in deviations:
        if not d.verifiable:
            causes.append(
                ContributionCause(
                    station_id=d.station_id, contribution_score=0.3, verifiable=False
                )
            )
            continue
        score = min(1.0, abs(d.deviation_z) / (threshold * 2))
        causes.append(
            ContributionCause(
                station_id=d.station_id,
                contribution_score=score,
                verifiable=True,
                deviation_z=d.deviation_z,
            )
        )
    causes.sort(key=lambda c: c.contribution_score, reverse=True)
    return causes
