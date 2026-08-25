"""Trivial golden comparison proving the harness mechanics work before real scenarios exist."""

import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "smoke"


def test_smoke_golden_matches():
    expected = json.loads((GOLDEN_DIR / "expected.json").read_text())
    actual = {"ok": True}
    assert actual == expected
