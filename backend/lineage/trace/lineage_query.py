"""Car-centric and station-centric root-cause trace queries."""

from datetime import timedelta
from pathlib import Path

import pandas as pd

from lineage.config.specs import LineSpec
from lineage.trace.models import ExposedCar, TraceResult
from lineage.trace.rootcause import (
    DEFAULT_DEVIATION_THRESHOLD,
    DEFAULT_FLEET_WINDOW,
    _commissioning_z,
    _reading_value,
    find_originating_station,
    rank_contributions,
    score_visits,
)
from lineage.twin.genealogy import GenealogyStore

DEFAULT_COHORT_WINDOW = timedelta(minutes=30)


def find_affected_cars(
    line: LineSpec,
    store: GenealogyStore,
    originating_station_id: str,
    quantity: str,
    flagged_car_id: str,
    threshold: float = DEFAULT_DEVIATION_THRESHOLD,
    cohort_window: timedelta = DEFAULT_COHORT_WINDOW,
) -> list[ExposedCar]:
    """Every other car that passed the implicated station under similar
    conditions in the same window -- a concrete, named list with per-car
    exposure confidence, not a blanket sweep of everyone nearby in time.
    `quantity` must be the specific sensor/readable_param that produced the
    originating deviation (from score_visits), not re-derived here -- a
    station can have more than one sensor, and only one of them may be
    the one that actually deviated."""
    station = next((s for s in line.stations if s.id == originating_station_id), None)
    if station is None:
        return []

    flagged_twin = store.car(flagged_car_id)
    flagged_visit = next(
        (v for v in flagged_twin.visits if v.station_id == originating_station_id), None
    )
    if flagged_visit is None:
        return []

    flagged_value = _reading_value(flagged_visit, quantity)
    if flagged_value is None:
        return []
    flagged_z = _commissioning_z(station, quantity, flagged_value)
    if flagged_z is None:
        return []

    window_start = flagged_visit.entry_time - cohort_window
    window_end = flagged_visit.entry_time + cohort_window
    car_ids = store.cars_through(originating_station_id, window_start, window_end)

    results = []
    for car_id in car_ids:
        if car_id == flagged_car_id:
            continue  # the flagged car is the query, not part of its own cohort
        visit = next(
            (v for v in store.car(car_id).visits if v.station_id == originating_station_id), None
        )
        if visit is None:
            continue
        value = _reading_value(visit, quantity)
        if value is None:
            continue
        z = _commissioning_z(station, quantity, value)
        if z is None or abs(z) < threshold * 0.5:
            continue
        if (z < 0) != (flagged_z < 0):
            continue  # opposite direction: not the same underlying condition

        similarity = 1.0 - min(1.0, abs(abs(z) - abs(flagged_z)) / max(abs(flagged_z), 1e-6))
        results.append(ExposedCar(car_id=car_id, exposure_confidence=max(0.0, similarity)))

    results.sort(key=lambda c: c.exposure_confidence, reverse=True)
    return results


def trace(
    *,
    line: LineSpec,
    store: GenealogyStore,
    car_id: str,
    flagged_at_station_id: str,
    threshold: float = DEFAULT_DEVIATION_THRESHOLD,
    fleet_window: timedelta = DEFAULT_FLEET_WINDOW,
    cohort_window: timedelta = DEFAULT_COHORT_WINDOW,
) -> TraceResult:
    """Given a car flagged by Predict or failed at inspection at
    `flagged_at_station_id`, answers all three trace questions at once."""
    car = store.car(car_id)
    deviations = score_visits(line, store, car, flagged_at_station_id, fleet_window)
    ranked = rank_contributions(deviations, threshold)
    origin = find_originating_station(deviations, threshold)

    if origin is None:
        return TraceResult(
            car_id=car_id,
            originating_station_id=flagged_at_station_id,
            originating_is_verifiable=False,
            ranked_contributions=ranked,
            affected_cars=[],
        )

    affected = (
        find_affected_cars(
            line, store, origin.station_id, origin.quantity, car_id, threshold, cohort_window
        )
        if origin.quantity is not None
        else []
    )

    return TraceResult(
        car_id=car_id,
        originating_station_id=origin.station_id,
        originating_is_verifiable=origin.verifiable,
        ranked_contributions=ranked,
        affected_cars=affected,
    )


def traced_failures(line: LineSpec, store: GenealogyStore, run_dir: Path) -> list[TraceResult]:
    """Traces every (car_id, station_id) pair inspection.csv recorded as a
    real "fail" -- the shared input both Act's proposal generation and Plant
    Manager's recurring-root-cause reporting need, computed once rather than
    twice: real per-car Trace work, not free."""
    inspection_df = pd.read_csv(run_dir / "inspection.csv", parse_dates=["timestamp"])
    failed = inspection_df[inspection_df.result == "fail"]
    return [
        trace(line=line, store=store, car_id=row.car_id, flagged_at_station_id=row.station_id)
        for row in failed.itertuples()
    ]
