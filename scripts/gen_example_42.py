"""Generates backend/data/lines/example_42.yaml and its insert-at-17 golden fixture.

A reusable capability, not a throwaway: re-run this whenever the example line's
station mix, sensor coverage ratio, or zone clustering needs tuning. Requires the
`lineage` package importable (run with backend/.venv's python) and existing golden
files are frozen per project rules -- regenerating the golden fixture below is
committing a change to a frozen file and needs an explicit diff review first.
"""

from datetime import date
from pathlib import Path

from lineage.config.specs import (
    AcquisitionMode,
    CommissioningBaseline,
    ConditionStats,
    ConveyorSegment,
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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

BODY_MODELS = ["Comau Smart5 NJ4", "Fanuc R-2000iA", "ABB IRB 6640", "Kawasaki BX200"]
PAINT_MODELS = ["Durr EcoRP L133", "Fanuc P-350", "ABB IRB 5500"]
FINAL_MODELS = ["KUKA KR16 R2010", "Atlas Copco Tensor ST", "Fanuc CR-15iA"]

BODY_POOL = [SensorKind.TORQUE, SensorKind.VIBRATION, SensorKind.THERMAL]
PAINT_POOL = [SensorKind.THERMAL, SensorKind.VIBRATION, SensorKind.CYCLE_TIME]
FINAL_POOL = [SensorKind.TORQUE, SensorKind.RPM, SensorKind.CYCLE_TIME]

UNIT_BY_KIND = {
    SensorKind.TORQUE: "N.m",
    SensorKind.VIBRATION: "mm/s",
    SensorKind.THERMAL: "C",
    SensorKind.CYCLE_TIME: "s",
    SensorKind.RPM: "rpm",
}
RATE_BY_KIND = {
    SensorKind.TORQUE: 50.0,
    SensorKind.VIBRATION: 1000.0,
    SensorKind.THERMAL: 1.0,
    SensorKind.CYCLE_TIME: 1.0,
    SensorKind.RPM: 100.0,
}

MANUAL_INDICES = {0, 1, 2, 3} | {16, 17, 18, 19, 20, 21, 22, 23} | {30}
MIXED_INDICES = {5, 33, 38}

# End of body (ST-16), end of paint (ST-26), and final roll test (ST-42): the
# line's three inspection checkpoints, where pass/fail results are recorded.
INSPECTION_INDICES = {15, 25, 41}

MANUAL_QUANTITY_BY_ZONE = {
    Zone.BODY: "torque_nm",
    Zone.PAINT: "coat_thickness_um",
    Zone.FINAL: "torque_nm",
}


def zone_for(i: int) -> Zone:
    if i < 16:
        return Zone.BODY
    if i < 26:
        return Zone.PAINT
    return Zone.FINAL


def build_sensors(station_id: str, i: int, zone: Zone) -> list[SensorSpec]:
    pool = {Zone.BODY: BODY_POOL, Zone.PAINT: PAINT_POOL, Zone.FINAL: FINAL_POOL}[zone]
    kinds = [pool[i % 3], pool[(i + 1) % 3]]
    sensors = []
    for n, kind in enumerate(kinds, start=1):
        sensors.append(
            SensorSpec(
                id=f"{station_id}-SEN-{n}",
                kind=kind,
                unit=UNIT_BY_KIND[kind],
                sample_rate_hz=RATE_BY_KIND[kind],
                install_date=date(2018, 3, 1),
                last_calibration_date=date(2024, 1, 15),
                accuracy_class="0.5" if n == 1 else "1.0",
            )
        )
    return sensors


def build_machine(i: int, zone: Zone, manual: bool) -> MachineSpec:
    if zone is Zone.BODY:
        install_year = 2004 + (i % 6)
        models = BODY_MODELS
    elif zone is Zone.PAINT:
        install_year = 2012 + (i - 16) % 4
        models = PAINT_MODELS
    else:
        install_year = 2018 + (i - 26) % 5
        models = FINAL_MODELS

    model = "Manual Torque Wrench Station" if manual else models[i % len(models)]
    return MachineSpec(
        model=model,
        install_year=install_year,
        last_maintenance_date=date(2024, (i % 12) + 1, 10),
        maintenance_interval_days=180 if manual else 90,
        wear_curve_shape="linear" if manual else "bathtub",
    )


def build_baseline(sensors: list[SensorSpec], i: int) -> CommissioningBaseline:
    idle_mean = {s.id: 10.0 + i for s in sensors}
    idle_std = {s.id: 0.5 + 0.01 * i for s in sensors}
    loaded_mean = {s.id: 15.0 + i for s in sensors}
    loaded_std = {s.id: 0.8 + 0.01 * i for s in sensors}
    return CommissioningBaseline(
        idle=ConditionStats(mean=idle_mean, std=idle_std),
        loaded=ConditionStats(mean=loaded_mean, std=loaded_std),
    )


def build_station(i: int) -> StationSpec:
    station_id = f"ST-{i + 1:02d}"
    zone = zone_for(i)
    manual = i in MANUAL_INDICES
    mixed = i in MIXED_INDICES
    mode = (
        AcquisitionMode.MANUAL
        if manual
        else (AcquisitionMode.MIXED if mixed else AcquisitionMode.INSTRUMENTED)
    )

    sensors = [] if manual else build_sensors(station_id, i, zone)
    machine = build_machine(i, zone, manual)

    if zone is Zone.BODY:
        cycle_time = 60.0 + (i % 5) * 2
    elif zone is Zone.PAINT:
        cycle_time = 70.0 + (i % 4) * 3
    else:
        cycle_time = 45.0 + (i % 6) * 2

    changeable_params = (
        {} if manual else {"line_speed_pct": ParamRange(min=80.0, max=110.0, step=1.0)}
    )

    if manual:
        quantity = MANUAL_QUANTITY_BY_ZONE[zone]
        readable_params = [quantity]
        baseline = CommissioningBaseline(
            idle=ConditionStats(mean={quantity: 10.0 + i}, std={quantity: 0.5 + 0.01 * i}),
            loaded=ConditionStats(mean={quantity: 15.0 + i}, std={quantity: 0.8 + 0.01 * i}),
        )
    else:
        readable_params = [s.id for s in sensors]
        baseline = build_baseline(sensors, i)

    name_prefix = {Zone.BODY: "Body", Zone.PAINT: "Paint", Zone.FINAL: "Final"}[zone]
    name = f"{name_prefix} Station {i + 1}" + (" (Manual)" if manual else "")
    is_inspection_station = i in INSPECTION_INDICES
    if i == 41:
        name = "Final Roll Test"
    elif is_inspection_station:
        name += " (Zone Inspection)"

    return StationSpec(
        id=station_id,
        name=name,
        zone=zone,
        sequence_index=i,
        sensors=sensors,
        acquisition_mode=mode,
        is_inspection_station=is_inspection_station,
        cycle_time_nominal_s=cycle_time,
        commissioning_baseline=baseline,
        changeable_params=changeable_params,
        readable_params=readable_params,
        machine=machine,
        cost_per_hour=(35.0 + i * 0.5) if manual else (60.0 + i * 1.2),
        value_add_pct=1.5 + (i % 5) * 0.3,
    )


def build_line() -> LineSpec:
    stations = [build_station(i) for i in range(42)]
    coords = [
        StationCoordinate(station_id=s.id, x_m=float(i * 8), y_m=0.0)
        for i, s in enumerate(stations)
    ]
    segments = [
        ConveyorSegment(
            from_station_id=stations[i].id,
            to_station_id=stations[i + 1].id,
            distance_m=8.0,
        )
        for i in range(len(stations) - 1)
    ]
    layout = LayoutSpec(coordinates=coords, segments=segments)
    envelope = EnvironmentEnvelope(
        temp_min_c=18.0, temp_max_c=26.0, humidity_min_pct=30.0, humidity_max_pct=60.0
    )
    return LineSpec(
        plant_name="Meridian Assembly Plant",
        site="Meridian, OH, USA",
        stations=stations,
        layout=layout,
        environment_envelope=envelope,
    )


def build_new_station() -> StationSpec:
    sensors = [
        SensorSpec(
            id="ST-43-SEN-1",
            kind=SensorKind.THERMAL,
            unit="C",
            sample_rate_hz=1.0,
            install_date=date(2023, 6, 1),
            last_calibration_date=date(2024, 1, 15),
            accuracy_class="0.5",
        ),
        SensorSpec(
            id="ST-43-SEN-2",
            kind=SensorKind.CYCLE_TIME,
            unit="s",
            sample_rate_hz=1.0,
            install_date=date(2023, 6, 1),
            last_calibration_date=date(2024, 1, 15),
            accuracy_class="1.0",
        ),
    ]
    baseline = CommissioningBaseline(
        idle=ConditionStats(
            mean={"ST-43-SEN-1": 22.0, "ST-43-SEN-2": 0.0},
            std={"ST-43-SEN-1": 0.4, "ST-43-SEN-2": 0.0},
        ),
        loaded=ConditionStats(
            mean={"ST-43-SEN-1": 45.0, "ST-43-SEN-2": 90.0},
            std={"ST-43-SEN-1": 1.2, "ST-43-SEN-2": 2.5},
        ),
    )
    return StationSpec(
        id="ST-43",
        name="Pretreatment Dip Tank",
        zone=Zone.PAINT,
        sequence_index=0,  # overwritten by insert_station
        sensors=sensors,
        acquisition_mode=AcquisitionMode.INSTRUMENTED,
        cycle_time_nominal_s=90.0,
        commissioning_baseline=baseline,
        changeable_params={"line_speed_pct": ParamRange(min=80.0, max=110.0, step=1.0)},
        readable_params=["ST-43-SEN-1", "ST-43-SEN-2"],
        machine=MachineSpec(
            model="Durr EcoClean Dip Line",
            install_year=2023,
            last_maintenance_date=date(2024, 1, 10),
            maintenance_interval_days=90,
            wear_curve_shape="bathtub",
        ),
        cost_per_hour=95.0,
        value_add_pct=2.0,
    )


def main() -> None:
    line = build_line()

    example_path = BACKEND_DIR / "data" / "lines" / "example_42.yaml"
    example_path.parent.mkdir(parents=True, exist_ok=True)
    example_path.write_text(line.to_yaml(), encoding="utf-8")
    print(f"wrote {example_path} ({len(line.stations)} stations)")

    reloaded = LineSpec.from_yaml(example_path)
    new_station = build_new_station()
    after_id = reloaded.stations[15].id  # 1-based position 16 -> last body station
    assert after_id == "ST-16", after_id
    updated = reloaded.insert_station(new_station, after_station_id=after_id)
    assert updated.stations[16].id == "ST-43"
    assert updated.stations[16].sequence_index == 16

    golden_path = BACKEND_DIR / "tests" / "golden" / "config" / "example_42_after_insert_at_17.yaml"
    golden_path.parent.mkdir(parents=True, exist_ok=True)
    golden_path.write_text(updated.to_yaml(), encoding="utf-8")
    print(f"wrote {golden_path} ({len(updated.stations)} stations)")


if __name__ == "__main__":
    main()
