"""Tests for lineage.twin; to be filled in alongside real logic."""

from datetime import datetime

import pytest

from lineage.twin.car import AmbientConditions, StationVisit
from lineage.twin.genealogy import GenealogyStore


def make_visit(
    station_id: str,
    entry_time: datetime,
    exit_time: datetime | None = None,
    temp_c: float = 22.0,
    wear: float = 0.1,
    operator_id: str | None = None,
) -> StationVisit:
    return StationVisit(
        station_id=station_id,
        entry_time=entry_time,
        exit_time=exit_time or entry_time,
        readings=[],
        operator_id=operator_id,
        machine_wear_state=wear,
        ambient_conditions=AmbientConditions(temp_c=temp_c),
    )


def test_register_and_record_visit_builds_ordered_history():
    store = GenealogyStore()
    store.register_car("CAR-001", "Variant-A", datetime(2024, 1, 1, 8, 0))
    store.record_visit("CAR-001", make_visit("ST-01", datetime(2024, 1, 1, 8, 0)))
    store.record_visit("CAR-001", make_visit("ST-02", datetime(2024, 1, 1, 8, 5)))

    car = store.car("CAR-001")
    assert [v.station_id for v in car.visits] == ["ST-01", "ST-02"]


def test_record_visit_on_unregistered_car_raises():
    store = GenealogyStore()
    with pytest.raises(KeyError):
        store.record_visit("CAR-999", make_visit("ST-01", datetime(2024, 1, 1)))


def test_dwell_time_computed_from_entry_and_exit():
    visit = make_visit(
        "ST-01", datetime(2024, 1, 1, 8, 0, 0), datetime(2024, 1, 1, 8, 1, 30)
    )
    assert visit.dwell_time_s == pytest.approx(90.0)


def test_cars_through_respects_time_window():
    store = GenealogyStore()
    times = [datetime(2024, 1, 1, 8, i) for i in range(5)]
    for i, t in enumerate(times):
        car_id = f"CAR-{i:03d}"
        store.register_car(car_id, "Variant-A", t)
        store.record_visit(car_id, make_visit("ST-05", t))

    result = store.cars_through("ST-05", times[1], times[3])
    assert result == ["CAR-001", "CAR-002", "CAR-003"]


def test_cars_through_empty_for_unvisited_station():
    store = GenealogyStore()
    assert store.cars_through("ST-99", datetime(2024, 1, 1), datetime(2024, 1, 2)) == []


def test_station_conditions_at_reports_pre_change_conditions_not_current():
    """The tricky one: a car that passed a station before a parameter change
    must report the pre-change conditions, not the current ones -- even
    after a later car's differently-conditioned visit has been recorded."""
    store = GenealogyStore()

    t1 = datetime(2024, 1, 1, 8, 0)
    store.register_car("CAR-A", "Variant-A", t1)
    store.record_visit("CAR-A", make_visit("ST-07", t1, temp_c=22.0, wear=0.1))

    # A parameter change happens: ambient temp rises and wear increases before
    # the next car arrives.
    t2 = datetime(2024, 1, 1, 9, 0)
    store.register_car("CAR-B", "Variant-A", t2)
    store.record_visit("CAR-B", make_visit("ST-07", t2, temp_c=30.0, wear=2.5))

    # Querying at CAR-A's timestamp, after CAR-B's record already exists in
    # the store, must still return CAR-A's original conditions.
    conditions = store.station_conditions_at("ST-07", t1)
    assert conditions is not None
    assert conditions.ambient_conditions.temp_c == pytest.approx(22.0)
    assert conditions.machine_wear_state == pytest.approx(0.1)

    # Querying at or after CAR-B's timestamp returns the new conditions.
    later = store.station_conditions_at("ST-07", t2)
    assert later.ambient_conditions.temp_c == pytest.approx(30.0)


def test_station_conditions_at_before_any_visit_returns_none():
    store = GenealogyStore()
    store.register_car("CAR-A", "Variant-A", datetime(2024, 1, 1, 8, 0))
    store.record_visit("CAR-A", make_visit("ST-07", datetime(2024, 1, 1, 8, 0)))

    result = store.station_conditions_at("ST-07", datetime(2024, 1, 1, 7, 0))
    assert result is None
