"""Unit tests for corrector-step decision logic (clamp + compare-and-set)."""
from __future__ import annotations

import pytest

from pytxt.domain.correctors import clamp_setpoint, plan_cm_step


# --- clamp ---------------------------------------------------------------

def test_clamp_within_range_unchanged():
    assert clamp_setpoint(5.0, 35.0) == (5.0, False)


def test_clamp_above_max():
    assert clamp_setpoint(40.0, 35.0) == (35.0, True)


def test_clamp_below_negative_max():
    assert clamp_setpoint(-40.0, 35.0) == (-35.0, True)


def test_clamp_exact_boundary_not_clamped():
    assert clamp_setpoint(35.0, 35.0) == (35.0, False)
    assert clamp_setpoint(-35.0, 35.0) == (-35.0, False)


# --- plan_cm_step: happy path -------------------------------------------

def test_plan_applies_deltas_when_cas_matches():
    plan = plan_cm_step(
        names=["A", "B"],
        readbacks_a=[10.0, -5.0],
        deltas_a=[2.0, 1.0],
        expected_prior_a=[10.0, -5.0],
        max_abs_a=[35.0, 35.0],
        tol_a=0.01,
    )
    assert plan.ok
    assert plan.refused == []
    assert plan.channels[0].new_value_a == 12.0
    assert plan.channels[1].new_value_a == -4.0
    assert not plan.any_clamped


def test_plan_marks_clamped_channels():
    plan = plan_cm_step(
        names=["A"], readbacks_a=[34.0], deltas_a=[5.0],
        expected_prior_a=[34.0], max_abs_a=[35.0], tol_a=0.01,
    )
    assert plan.ok
    assert plan.channels[0].new_value_a == 35.0
    assert plan.channels[0].clamped
    assert plan.any_clamped


# --- plan_cm_step: compare-and-set refusal ------------------------------

def test_plan_refuses_when_readback_differs_beyond_tol():
    plan = plan_cm_step(
        names=["A", "B"],
        readbacks_a=[10.5, -5.0],   # A drifted 0.5 from expected
        deltas_a=[2.0, 1.0],
        expected_prior_a=[10.0, -5.0],
        max_abs_a=[35.0, 35.0],
        tol_a=0.1,                  # 0.5 > 0.1 -> refuse
    )
    assert not plan.ok
    assert plan.refused == ["A"]


def test_plan_within_tol_is_not_refused():
    plan = plan_cm_step(
        names=["A"], readbacks_a=[10.05], deltas_a=[1.0],
        expected_prior_a=[10.0], max_abs_a=[35.0], tol_a=0.1,
    )
    assert plan.ok  # 0.05 <= 0.1


def test_plan_refuses_whole_step_if_any_channel_misses():
    plan = plan_cm_step(
        names=["A", "B", "C"],
        readbacks_a=[10.0, 99.0, 30.0],  # B way off
        deltas_a=[1.0, 1.0, 1.0],
        expected_prior_a=[10.0, 20.0, 30.0],
        max_abs_a=[35.0, 35.0, 35.0],
        tol_a=0.1,
    )
    assert not plan.ok
    assert plan.refused == ["B"]


# --- validation ----------------------------------------------------------

def test_plan_rejects_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        plan_cm_step(
            names=["A", "B"], readbacks_a=[1.0], deltas_a=[1.0],
            expected_prior_a=[1.0], max_abs_a=[1.0], tol_a=0.1,
        )


def test_plan_rejects_negative_tolerance():
    with pytest.raises(ValueError, match="tol_a"):
        plan_cm_step(
            names=["A"], readbacks_a=[1.0], deltas_a=[1.0],
            expected_prior_a=[1.0], max_abs_a=[1.0], tol_a=-0.1,
        )
