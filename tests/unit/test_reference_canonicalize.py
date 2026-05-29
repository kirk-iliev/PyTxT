"""Unit tests for canonicalize_bpm_name."""
import pytest

from pytxt.domain.reference import canonicalize_bpm_name


@pytest.mark.parametrize("input_name,expected", [
    ("SR01C:BPM1:SA:X", "SR01C:BPM1"),
    ("SR01C:BPM1:SA:Y", "SR01C:BPM1"),
    ("SR12C:BPM8:SA:X", "SR12C:BPM8"),
    ("SR01C:BPM1", "SR01C:BPM1"),                       # already canonical (idempotent)
    ("SR01C:BPM1:SA:Z", "SR01C:BPM1:SA:Z"),             # only X/Y suffix stripped, not Z
    ("SR01C:BPM1:SA", "SR01C:BPM1:SA"),                 # bare :SA without channel is not stripped
    (":SA:X", ""),                                       # degenerate but well-defined
    ("", ""),                                            # empty in, empty out
])
def test_canonicalize_strips_or_passes(input_name: str, expected: str) -> None:
    assert canonicalize_bpm_name(input_name) == expected


def test_canonicalize_is_idempotent() -> None:
    once = canonicalize_bpm_name("SR01C:BPM1:SA:X")
    twice = canonicalize_bpm_name(once)
    assert once == twice == "SR01C:BPM1"
