"""Builds and maintains each car's history graph as it moves station to station.

In-memory, append-only, no database: this is the historical record Trace reads
from later, indexed both by car (a car's own visit list) and by station+time
(which cars passed through a given station in a given window)."""

import bisect
from datetime import datetime

from lineage.twin.car import CarTwin, StationVisit


class GenealogyStore:
    def __init__(self) -> None:
        self._cars: dict[str, CarTwin] = {}
        self._by_station: dict[str, list[tuple[datetime, str]]] = {}

    def register_car(self, car_id: str, model_variant: str, entry_timestamp: datetime) -> CarTwin:
        if car_id in self._cars:
            raise ValueError(f"car {car_id!r} is already registered")
        twin = CarTwin(car_id=car_id, model_variant=model_variant, entry_timestamp=entry_timestamp)
        self._cars[car_id] = twin
        return twin

    def record_visit(self, car_id: str, visit: StationVisit) -> None:
        """Records `visit` against an already-registered car. Raises KeyError
        for an unregistered car_id rather than silently creating one -- a
        missing registration should surface as a bug, not be papered over."""
        twin = self._cars[car_id]
        twin.record_visit(visit)
        station_entries = self._by_station.setdefault(visit.station_id, [])
        bisect.insort(station_entries, (visit.entry_time, car_id))

    def car(self, car_id: str) -> CarTwin:
        return self._cars[car_id]

    def all_car_ids(self) -> list[str]:
        return list(self._cars.keys())

    def cars_through(self, station_id: str, t_start: datetime, t_end: datetime) -> list[str]:
        """Every car whose visit to `station_id` began within [t_start, t_end].
        This is what powers the at-risk cohort list: given a station and a
        window, who passed through it under similar conditions."""
        entries = self._by_station.get(station_id, [])
        lo = bisect.bisect_left(entries, t_start, key=lambda e: e[0])
        hi = bisect.bisect_right(entries, t_end, key=lambda e: e[0])
        return [car_id for _, car_id in entries[lo:hi]]

    def station_conditions_at(self, station_id: str, timestamp: datetime) -> StationVisit | None:
        """What the station's state was when the car that was there at
        `timestamp` visited it -- not whatever the most recently recorded
        visit happens to say. Finds the specific historical visit whose entry
        time is at or before `timestamp` and returns that visit's own
        recorded conditions, however much later other cars have since passed
        through the same station under different conditions."""
        entries = self._by_station.get(station_id, [])
        idx = bisect.bisect_right(entries, timestamp, key=lambda e: e[0]) - 1
        if idx < 0:
            return None
        entry_time, car_id = entries[idx]
        return next(
            v
            for v in self._cars[car_id].visits
            if v.station_id == station_id and v.entry_time == entry_time
        )
