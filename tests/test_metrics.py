"""Behavioural tests for the discrimination, scaling and stability functions."""
from __future__ import annotations

import numpy as np
import pytest

from src.models.metrics import BASE_ODDS, BASE_SCORE, PDO, ks_statistic, to_score
from src.monitor.stability import (
    SIGNIFICANT_THRESHOLD,
    STABLE_THRESHOLD,
    population_stability_index,
    verdict,
)

NEAR_PERFECT = 0.99
NEAR_ZERO = 0.05
TOLERANCE = 1e-6


def test_ks_is_near_one_under_perfect_separation(perfectly_separated):
    labels, scores = perfectly_separated
    assert ks_statistic(labels, scores) > NEAR_PERFECT


def test_ks_is_near_zero_when_the_score_is_uninformative(uninformative):
    labels, scores = uninformative
    assert ks_statistic(labels, scores) < NEAR_ZERO


def test_ks_is_invariant_to_a_monotone_rescaling(uninformative):
    labels, scores = uninformative
    assert ks_statistic(labels, scores) == pytest.approx(
        ks_statistic(labels, scores * 3 + 7), abs=TOLERANCE
    )


def test_ks_rejects_a_single_class_sample():
    with pytest.raises(ValueError, match="one class"):
        ks_statistic(np.zeros(10), np.linspace(0, 1, 10))


def test_scorecard_anchors_the_base_score_at_the_base_odds():
    anchored = to_score(np.array([1 / (BASE_ODDS + 1)]))
    assert anchored[0] == pytest.approx(BASE_SCORE, abs=0.5)


def test_scorecard_adds_pdo_points_when_the_odds_double():
    at_base = to_score(np.array([1 / (BASE_ODDS + 1)]))
    at_double = to_score(np.array([1 / (2 * BASE_ODDS + 1)]))
    assert (at_double[0] - at_base[0]) == pytest.approx(PDO, abs=0.5)


def test_scorecard_is_decreasing_in_probability_of_default():
    scores = to_score(np.array([0.01, 0.05, 0.20, 0.50]))
    assert np.all(np.diff(scores) < 0)


def test_psi_is_zero_for_a_sample_against_itself(stable_samples):
    expected, _ = stable_samples
    assert population_stability_index(expected, expected) < TOLERANCE


def test_psi_stays_low_for_two_draws_from_one_distribution(stable_samples):
    expected, actual = stable_samples
    assert population_stability_index(expected, actual) < STABLE_THRESHOLD


def test_psi_flags_a_shifted_distribution(shifted_samples):
    expected, actual = shifted_samples
    assert population_stability_index(expected, actual) > SIGNIFICANT_THRESHOLD


def test_psi_is_symmetric(shifted_samples):
    expected, actual = shifted_samples
    assert population_stability_index(expected, actual) == pytest.approx(
        population_stability_index(actual, expected), rel=0.05
    )


def test_psi_bins_are_fixed_on_the_development_sample(rng):
    """A shift must register even though the later sample is internally smooth.

    Recomputing quantiles per sample would map both onto their own deciles and
    return near zero, which is the implementation error this guards against.
    """
    development = rng.normal(0, 1, 20_000)
    later = rng.normal(0, 1, 20_000) * 0.25 + 3.0
    assert population_stability_index(development, later) > SIGNIFICANT_THRESHOLD


def test_psi_rejects_an_empty_sample():
    with pytest.raises(ValueError, match="non-empty"):
        population_stability_index(np.array([]), np.array([1.0, 2.0]))


def test_verdict_bands_map_to_the_documented_thresholds():
    assert verdict(STABLE_THRESHOLD / 2) == "STABLE"
    assert verdict((STABLE_THRESHOLD + SIGNIFICANT_THRESHOLD) / 2) == "MODERATE SHIFT"
    assert verdict(SIGNIFICANT_THRESHOLD * 2) == "SIGNIFICANT SHIFT"
