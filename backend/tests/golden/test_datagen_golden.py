"""Fixed-seed 400-car default run over example_42.yaml: ground_truth.json must
be byte-identical across regenerations, since it's the answer key every later
prompt's Predict/Trace correctness gets graded against."""

from pathlib import Path

from lineage.config.loader import load_line_spec
from lineage.datagen.cli import DEFAULT_LINE_PATH, build_default_run_config
from lineage.datagen.run import generate_run

GOLDEN_PATH = Path(__file__).parent / "datagen" / "default_400_car_run" / "ground_truth.json"


def test_default_run_ground_truth_matches_golden(tmp_path):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)

    artifacts = generate_run(line, config, output_root=tmp_path)

    actual = artifacts.ground_truth_path.read_text(encoding="utf-8")
    expected = GOLDEN_PATH.read_text(encoding="utf-8")
    assert actual == expected


def test_default_run_ground_truth_is_reproducible_across_runs(tmp_path):
    line = load_line_spec(DEFAULT_LINE_PATH)
    config = build_default_run_config(line)

    first = generate_run(line, config, output_root=tmp_path / "a")
    second = generate_run(line, config, output_root=tmp_path / "b")

    assert first.ground_truth_path.read_text() == second.ground_truth_path.read_text()
