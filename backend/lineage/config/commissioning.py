"""Simulates a short idle + loaded commissioning run to capture a
CommissioningBaseline from real (synthetic) samples, for a station that
doesn't have a hand-entered baseline yet -- "run to learn" in the Builder.

Not a fabricated number: given a rough expected center value per quantity
(what a real commissioning engineer would note from watching the machine
run empty, then loaded) and each sensor's own stated accuracy_class, this
actually draws `sample_count` random samples per quantity and computes the
baseline's mean/std from those real samples, the same way a real
commissioning capture would average noisy readings -- it's a simulated
capture, clearly labelled as such, not a real one, but the numbers in it are
genuinely computed, not invented."""

import numpy as np

from lineage.config.specs import CommissioningBaseline, ConditionStats

DEFAULT_SAMPLE_COUNT = 30
MINIMUM_NOISE_STD = 1e-6
"""Floor for noise_std when a quantity's nominal center is 0 -- a sensor
reading exactly zero variance would make every subsequent SPC calculation
divide by zero, and no real sensor is perfectly noiseless."""


def run_to_learn(
    *,
    accuracy_fractions: dict[str, float],
    idle_nominal: dict[str, float],
    loaded_nominal: dict[str, float],
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    seed: int | None = None,
) -> CommissioningBaseline:
    """`accuracy_fractions` maps each quantity to a fractional noise level
    (e.g. 0.01 for a sensor whose accuracy_class is "1.0", read as +/-1%```
    of the reading) -- missing entries default to 1%, a reasonable generic
    instrumentation-grade assumption, not a claim about any real sensor.
    `idle_nominal`/`loaded_nominal` are the rough expected center values a
    commissioning engineer supplies per quantity; both must cover the same
    quantities."""
    rng = np.random.default_rng(seed)

    def _capture(nominal: dict[str, float]) -> ConditionStats:
        mean: dict[str, float] = {}
        std: dict[str, float] = {}
        for quantity, center in nominal.items():
            fraction = accuracy_fractions.get(quantity, 0.01)
            noise_std = max(abs(center) * fraction, MINIMUM_NOISE_STD)
            samples = rng.normal(center, noise_std, size=sample_count)
            mean[quantity] = float(samples.mean())
            std[quantity] = float(samples.std(ddof=1)) if sample_count > 1 else noise_std
        return ConditionStats(mean=mean, std=std)

    return CommissioningBaseline(idle=_capture(idle_nominal), loaded=_capture(loaded_nominal))
