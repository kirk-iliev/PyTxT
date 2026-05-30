"""Unit tests for ``_resolve_in_library`` path safety (M3 Task 2).

The helper must accept only safe bare ``.mat`` basenames and resolve them
inside the library dir, rejecting everything else with
``InvalidReferenceNameError`` (spec §6.3 / §10.3).
"""
from __future__ import annotations

import pytest

from pytxt.handlers.reference import (
    InvalidReferenceNameError,
    _resolve_in_library,
)


REJECT_VECTORS = [
    "",  # empty
    "foo",  # no .mat extension
    "a/b.mat",  # path separator
    "../etc/passwd",  # parent escape + no .mat
    "/etc/passwd",  # absolute + separator
    "..",  # bare parent ref
    "foo.mat/../bar.mat",  # separator (caught before resolve)
]


@pytest.mark.parametrize("name", REJECT_VECTORS)
def test_reject_unsafe_names(tmp_path, name):
    with pytest.raises(InvalidReferenceNameError):
        _resolve_in_library(tmp_path, name)


ACCEPT_VECTORS = [
    "good.mat",
    "2025-03-23_12:43:16_reference_trajectory.mat",
]


@pytest.mark.parametrize("name", ACCEPT_VECTORS)
def test_accept_safe_names(tmp_path, name):
    resolved = _resolve_in_library(tmp_path, name)
    assert resolved == (tmp_path / name).resolve()
    assert resolved.parent == tmp_path.resolve()
    assert resolved.name == name
    assert resolved.is_relative_to(tmp_path.resolve())
