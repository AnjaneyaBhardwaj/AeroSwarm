"""Benchmark statistics."""

import pytest

from swarm.stats import quartiles, wilson_interval


def test_wilson_interval_matches_reference_values():
    lo, hi = wilson_interval(1, 5)
    assert lo == pytest.approx(0.0362, abs=1e-4) and hi == pytest.approx(0.6245, abs=1e-4)
    lo, hi = wilson_interval(0, 15)
    assert lo == 0.0 and hi == pytest.approx(0.2039, abs=1e-4)
    lo, hi = wilson_interval(15, 15)
    assert lo == pytest.approx(0.7961, abs=1e-4) and hi == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_quartiles():
    assert quartiles([7.0]) == (7.0, 7.0, 7.0)
    assert quartiles([1.0, 2.0, 3.0, 4.0, 5.0]) == (2.0, 3.0, 4.0)
