"""Unit tests for injection one-shot request math (fine delay + TimInjReq build)."""
from __future__ import annotations

import pytest

from pytxt.domain.injection import (
    build_tim_inj_req,
    fine_delay_counts,
    next_seq_num,
)


# --- fine_delay_counts ---------------------------------------------------

def test_fine_delay_is_integer_in_range():
    for bucket in range(1, 329):
        c = fine_delay_counts(bucket)
        assert isinstance(c, int)
        assert 0 <= c <= 1023


def test_fine_delay_is_deterministic():
    assert fine_delay_counts(308) == fine_delay_counts(308)


def test_fine_delay_matches_legacy_formula():
    # Recompute the legacy expression independently for a couple of buckets.
    for bucket in (1, 100, 308):
        folded = (21 * bucket) % 328
        frac = (31.25 * folded) % 1.0
        expected = max(0, min(1023, round(100 * 8 * frac)))
        assert fine_delay_counts(bucket) == expected


# --- next_seq_num --------------------------------------------------------

def test_seq_increments():
    assert next_seq_num(19133) == 19134


def test_seq_wraps_at_20000():
    assert next_seq_num(20000) == 1
    assert next_seq_num(20001) == 1


# --- build_tim_inj_req ---------------------------------------------------

def test_build_sets_fields_and_bumps_seq():
    current = [57, 4, 40, 0, 0, 0, 19133]
    req = build_tim_inj_req(current, bucket=308, gun_bunches=4, mode=40, inhibit=1)
    assert req == [308, 4, 40, 1, 0, 0, 19134]


def test_build_forces_unused_elements_zero():
    current = [1, 1, 1, 1, 99, 99, 5]
    req = build_tim_inj_req(current, bucket=308, gun_bunches=2, mode=42, inhibit=1)
    assert req[4] == 0 and req[5] == 0


def test_build_wraps_seq():
    current = [1, 1, 40, 0, 0, 0, 20000]
    req = build_tim_inj_req(current, bucket=1, gun_bunches=1, mode=40, inhibit=1)
    assert req[6] == 1


def test_build_rejects_short_request():
    with pytest.raises(ValueError, match="7 elements"):
        build_tim_inj_req([1, 2, 3], bucket=1, gun_bunches=1, mode=40, inhibit=1)
