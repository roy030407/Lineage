"""Resolves seeded and organic defect mechanisms into per-(car, station, quantity)
readings, with a fixed, outcome-independent RNG draw order so re-runs of the same
seed are bit-identical regardless of which branches fire."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from lineage.config.specs import MachineSpec, SensorKind
from lineage.datagen.generators import environment_z, wear_z
from lineage.datagen.models import DefectMechanism, RunConfig


@dataclass(frozen=True)
class ReadingResult:
    value: float
    mechanism: DefectMechanism | None  # set when |systematic_z| crosses the threshold


@dataclass(frozen=True)
class OriginFlag:
    car_index: int
    car_id: str
    station_id: str
    timestamp: datetime
    mechanism: DefectMechanism


def compute_reading(
    *,
    config: RunConfig,
    machine: MachineSpec,
    sensor_kind: SensorKind | None,
    baseline_mean: float,
    baseline_std: float,
    noise_std: float,
    machine_elapsed_days: float,
    ambient_c: float,
    envelope_min_c: float,
    envelope_max_c: float,
    material_quality: float,
    seed_component: float,
    operator_bias: float,
    rng: np.random.Generator,
) -> ReadingResult:
    """Computes one reading's value and, if its systematic deviation crosses
    config.defect_z_threshold, which single component is the dominant cause.

    `operator_bias` is in the quantity's native units (0.0 for instrumented
    sensors); it's converted to std-devs internally via baseline_std, the same
    unit every other component is already expressed in.

    Every call draws exactly three random numbers -- a material-quality spike
    check, its magnitude, and the reading noise -- regardless of whether the
    spike fires, so the RNG draw count per (car, station, quantity) never
    depends on outcomes.
    """
    spike_roll = float(rng.uniform(0.0, 1.0))
    spike_magnitude = float(rng.normal(config.defect_z_threshold + 1.0, 0.5))
    noise = float(rng.normal(0.0, noise_std))

    wear_component = wear_z(machine, machine_elapsed_days)

    env_component = 0.0
    if sensor_kind == SensorKind.THERMAL:
        env_component = environment_z(ambient_c, envelope_min_c, envelope_max_c)

    spike_prob = config.background_defect_rate * max(0.0, 2.0 - material_quality)
    material_triggered = spike_roll < spike_prob
    material_component = spike_magnitude if material_triggered else 0.0

    operator_component = (operator_bias / baseline_std) if baseline_std else 0.0

    systematic_z = (
        wear_component + seed_component + env_component + material_component + operator_component
    )
    value = baseline_mean + systematic_z * baseline_std + noise

    mechanism = None
    if abs(systematic_z) >= config.defect_z_threshold:
        components = {
            DefectMechanism.TORQUE_DRIFT: seed_component,
            DefectMechanism.ENVIRONMENTAL_EXCURSION: env_component,
            DefectMechanism.OPERATOR_HANDOVER_SHIFT: operator_component,
            DefectMechanism.MATERIAL_QUALITY: material_component,
            DefectMechanism.WEAR: wear_component,
        }
        mechanism = max(components, key=lambda m: abs(components[m]))

    return ReadingResult(value=value, mechanism=mechanism)
