"""Safety envelope bounds for Act proposals.

APPEND-ONLY: never edit or remove an existing bound once committed, only add new ones.

A proposal must satisfy BOTH the station's own StationSpec.changeable_params
range (min/max/step, per-station) AND the hard-coded, type-level bound here
(per parameter name, plant-wide). The envelope can only ever be more
restrictive than a station's configured range, never looser -- a station
misconfigured with too-wide a changeable_params range is still caught here.
"""

from pydantic import BaseModel, ConfigDict


class ParameterEnvelope(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    parameter_name: str
    max_single_step_change_pct: float
    absolute_min: float
    absolute_max: float
    requires_physical_change: bool


ENVELOPES: dict[str, ParameterEnvelope] = {
    "line_speed_pct": ParameterEnvelope(
        parameter_name="line_speed_pct",
        max_single_step_change_pct=0.15,
        absolute_min=50.0,
        absolute_max=120.0,
        requires_physical_change=False,
    ),
}


def envelope_for(parameter_name: str) -> ParameterEnvelope | None:
    return ENVELOPES.get(parameter_name)
