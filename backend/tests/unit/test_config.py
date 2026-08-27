"""Tests for lineage.config (LineSpec/StationSpec/SensorSpec); filled in alongside real logic."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from lineage.config.specs import (
    AcquisitionMode,
    ConveyorSegment,
    EnvironmentEnvelope,
    LayoutSpec,
    LineSpec,
    MachineSpec,
    SensorKind,
    SensorSpec,
    StationCoordinate,
    StationSpec,
    Zone,
)


def make_sensor(id_: str = "SEN-1", kind: SensorKind = SensorKind.TORQUE) -> SensorSpec:
    return SensorSpec(
        id=id_,
        kind=kind,
        unit="N.m",
        sample_rate_hz=50.0,
        install_date=date(2020, 1, 1),
        last_calibration_date=date(2024, 1, 1),
        accuracy_class="1.0",
    )


def make_machine() -> MachineSpec:
    return MachineSpec(
        model="Test Robot",
        install_year=2020,
        last_maintenance_date=date(2024, 1, 1),
        maintenance_interval_days=90,
        wear_curve_shape="linear",
    )


def make_station(
    id_: str,
    sequence_index: int,
    acquisition_mode: AcquisitionMode = AcquisitionMode.INSTRUMENTED,
    sensors: list[SensorSpec] | None = None,
) -> StationSpec:
    if sensors is None:
        sensors = (
            [] if acquisition_mode == AcquisitionMode.MANUAL else [make_sensor(f"{id_}-SEN-1")]
        )
    return StationSpec(
        id=id_,
        name=f"Station {id_}",
        zone=Zone.BODY,
        sequence_index=sequence_index,
        sensors=sensors,
        acquisition_mode=acquisition_mode,
        cycle_time_nominal_s=60.0,
        machine=make_machine(),
        cost_per_hour=50.0,
        value_add_pct=2.0,
    )


def make_small_line(n: int = 3) -> LineSpec:
    stations = [make_station(f"ST-{i + 1:02d}", i) for i in range(n)]
    coords = [
        StationCoordinate(station_id=s.id, x_m=float(i * 10), y_m=0.0)
        for i, s in enumerate(stations)
    ]
    segments = [
        ConveyorSegment(
            from_station_id=stations[i].id, to_station_id=stations[i + 1].id, distance_m=10.0
        )
        for i in range(n - 1)
    ]
    return LineSpec(
        plant_name="Test Plant",
        site="Testville",
        stations=stations,
        layout=LayoutSpec(coordinates=coords, segments=segments),
        environment_envelope=EnvironmentEnvelope(
            temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        ),
    )


# --- field validators -------------------------------------------------------


def test_manual_station_with_sensors_rejected():
    with pytest.raises(ValidationError, match="must not declare sensors"):
        make_station("ST-01", 0, acquisition_mode=AcquisitionMode.MANUAL, sensors=[make_sensor()])


def test_instrumented_station_without_sensors_rejected():
    with pytest.raises(ValidationError, match="requires at least one sensor"):
        make_station("ST-01", 0, acquisition_mode=AcquisitionMode.INSTRUMENTED, sensors=[])


def test_mixed_station_without_sensors_rejected():
    with pytest.raises(ValidationError, match="requires at least one sensor"):
        make_station("ST-01", 0, acquisition_mode=AcquisitionMode.MIXED, sensors=[])


def test_manual_station_without_sensors_accepted():
    station = make_station("ST-01", 0, acquisition_mode=AcquisitionMode.MANUAL, sensors=[])
    assert station.sensors == []


def test_is_inspection_station_defaults_false():
    station = make_station("ST-01", 0)
    assert station.is_inspection_station is False


def test_is_inspection_station_can_be_set_true():
    station = make_station("ST-01", 0).model_copy(update={"is_inspection_station": True})
    assert station.is_inspection_station is True


def test_environment_envelope_requires_min_less_than_max():
    with pytest.raises(ValidationError, match="temp_min_c must be < temp_max_c"):
        EnvironmentEnvelope(
            temp_min_c=26.0, temp_max_c=18.0, humidity_min_pct=30.0, humidity_max_pct=60.0
        )


def test_negative_sample_rate_rejected():
    with pytest.raises(ValidationError):
        SensorSpec(
            id="SEN-1",
            kind=SensorKind.TORQUE,
            unit="N.m",
            sample_rate_hz=-1.0,
            install_date=date(2020, 1, 1),
            last_calibration_date=date(2024, 1, 1),
            accuracy_class="1.0",
        )


# --- LineSpec-level validators ----------------------------------------------


def test_duplicate_station_ids_rejected():
    line = make_small_line(3)
    bad_station = make_station(line.stations[0].id, 2)
    with pytest.raises(ValidationError, match="duplicate station ids"):
        LineSpec(
            plant_name=line.plant_name,
            site=line.site,
            stations=[line.stations[0], line.stations[1], bad_station],
            layout=line.layout,
            environment_envelope=line.environment_envelope,
        )


def test_noncontiguous_sequence_index_rejected():
    line = make_small_line(3)
    stations = list(line.stations)
    stations[-1] = stations[-1].model_copy(update={"sequence_index": 99})
    with pytest.raises(ValidationError, match="sequence_index"):
        LineSpec(
            plant_name=line.plant_name,
            site=line.site,
            stations=stations,
            layout=line.layout,
            environment_envelope=line.environment_envelope,
        )


# --- insert_station ----------------------------------------------------------


def test_insert_station_between_renumbers_and_splits_segment():
    line = make_small_line(3)
    new_station = make_station("ST-NEW", 0)

    updated = line.insert_station(new_station, after_station_id="ST-01")

    assert [s.id for s in updated.stations] == ["ST-01", "ST-NEW", "ST-02", "ST-03"]
    assert [s.sequence_index for s in updated.stations] == [0, 1, 2, 3]

    seg_a = updated.layout.segment_between("ST-01", "ST-NEW")
    seg_b = updated.layout.segment_between("ST-NEW", "ST-02")
    assert seg_a.distance_m == pytest.approx(5.0)
    assert seg_b.distance_m == pytest.approx(5.0)

    new_coord = updated.layout.coordinate_for("ST-NEW")
    assert new_coord.x_m == pytest.approx(5.0)
    assert new_coord.y_m == pytest.approx(0.0)


def test_insert_station_unknown_after_id_raises():
    line = make_small_line(3)
    new_station = make_station("ST-NEW", 0)
    with pytest.raises(ValueError, match="unknown after_station_id"):
        line.insert_station(new_station, after_station_id="does-not-exist")


def test_insert_station_after_last_station_raises():
    line = make_small_line(3)
    new_station = make_station("ST-NEW", 0)
    with pytest.raises(ValueError, match="cannot append after the last station"):
        line.insert_station(new_station, after_station_id="ST-03")


def test_insert_station_tail_append_extrapolates_direction():
    line = make_small_line(3)
    new_station = make_station("ST-NEW", 0)

    updated = line.insert_station(new_station, after_station_id=None)

    assert [s.id for s in updated.stations] == ["ST-01", "ST-02", "ST-03", "ST-NEW"]
    assert updated.stations[-1].sequence_index == 3

    new_coord = updated.layout.coordinate_for("ST-NEW")
    # existing coords are (0,0), (10,0), (20,0); direction is +10 on x, extrapolated once more.
    assert new_coord.x_m == pytest.approx(30.0)
    assert new_coord.y_m == pytest.approx(0.0)

    seg = updated.layout.segment_between("ST-03", "ST-NEW")
    assert seg.distance_m == pytest.approx(10.0)


def test_insert_station_tail_append_needs_two_existing_stations():
    line = make_small_line(1)
    new_station = make_station("ST-NEW", 0)
    with pytest.raises(ValueError, match="need at least 2 existing"):
        line.insert_station(new_station, after_station_id=None)


# --- remove_station -----------------------------------------------------------


def test_remove_middle_station_rejoins_and_sums_distance():
    line = make_small_line(3)
    updated = line.remove_station("ST-02")

    assert [s.id for s in updated.stations] == ["ST-01", "ST-03"]
    assert [s.sequence_index for s in updated.stations] == [0, 1]

    seg = updated.layout.segment_between("ST-01", "ST-03")
    assert seg.distance_m == pytest.approx(20.0)
    assert updated.layout.coordinate_for("ST-01").x_m == pytest.approx(0.0)
    assert updated.layout.coordinate_for("ST-03").x_m == pytest.approx(20.0)


def test_remove_last_station_drops_single_segment():
    line = make_small_line(3)
    updated = line.remove_station("ST-03")

    assert [s.id for s in updated.stations] == ["ST-01", "ST-02"]
    assert updated.layout.segment_between("ST-01", "ST-02") is not None
    assert len(updated.layout.segments) == 1


def test_remove_unknown_station_raises():
    line = make_small_line(3)
    with pytest.raises(ValueError, match="unknown station_id"):
        line.remove_station("does-not-exist")


# --- yaml round trip -----------------------------------------------------------


def test_yaml_round_trip(tmp_path):
    line = make_small_line(3)
    path = tmp_path / "line.yaml"
    path.write_text(line.to_yaml(), encoding="utf-8")

    reloaded = LineSpec.from_yaml(path)

    assert reloaded == line


# --- example_42's real layout ---------------------------------------------------

EXAMPLE_42_PATH = Path(__file__).parents[2] / "data" / "lines" / "example_42.yaml"


def test_example_42_segment_distances_match_actual_geometry():
    """distance_m must always be the real Euclidean distance between the two
    endpoint coordinates, never a value set independently -- exactly the kind
    of thing that silently drifts once a layout is edited by hand instead of
    regenerated from coordinates, as example_42's serpentine footprint is."""
    line = LineSpec.from_yaml(EXAMPLE_42_PATH)

    assert line.layout.segments, "expected at least one segment to check"
    for segment in line.layout.segments:
        a = line.layout.coordinate_for(segment.from_station_id)
        b = line.layout.coordinate_for(segment.to_station_id)
        actual_distance = ((b.x_m - a.x_m) ** 2 + (b.y_m - a.y_m) ** 2) ** 0.5
        assert segment.distance_m == pytest.approx(actual_distance), (
            f"{segment.from_station_id} -> {segment.to_station_id}: "
            f"distance_m={segment.distance_m} but actual geometry is {actual_distance}"
        )
