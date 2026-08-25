"""Loads and validates a LineSpec from a YAML file."""

from pathlib import Path

from lineage.config.specs import LineSpec


def load_line_spec(path: Path | str) -> LineSpec:
    return LineSpec.from_yaml(path)
