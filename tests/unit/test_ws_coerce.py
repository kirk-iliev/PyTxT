"""Unit tests for ws_bridge._coerce_value.

Pure transformation: caproto value → JSON-friendly Python primitive.
The integration test at tests/integration/test_ws_bridge.py covers the
end-to-end WS path; this file pins the shape rules explicitly.
"""
import math

import numpy as np
import pytest

from pytxt.api.ws_bridge import _coerce_value


# --- scalars ---------------------------------------------------------------


def test_bytes_scalar_decoded():
    assert _coerce_value(b"OK") == "OK"


def test_one_element_byte_array_unwrapped_and_decoded():
    # Mirrors caproto's habit of delivering string scalars as DbrStringArray([b"..."])
    assert _coerce_value([b"hello"]) == "hello"


def test_numpy_scalar_unboxed():
    assert _coerce_value(np.int32(42)) == 42
    assert _coerce_value(np.float64(3.14)) == pytest.approx(3.14)


def test_one_element_numpy_array_unwrapped():
    assert _coerce_value(np.array([7], dtype=np.int32)) == 7


def test_plain_python_scalar_passthrough():
    assert _coerce_value(0) == 0
    assert _coerce_value("ready") == "ready"


def test_nan_scalar_mapped_to_none():
    assert _coerce_value(float("nan")) is None


def test_nan_numpy_scalar_mapped_to_none():
    assert _coerce_value(np.float64("nan")) is None


# --- numeric waveforms -----------------------------------------------------


def test_numpy_int_array_becomes_list():
    arr = np.arange(5, dtype=np.int32)
    assert _coerce_value(arr) == [0, 1, 2, 3, 4]


def test_numpy_float_array_becomes_list_of_floats():
    out = _coerce_value(np.array([1.0, 2.5, -3.25], dtype=np.float64))
    assert out == pytest.approx([1.0, 2.5, -3.25])


def test_float_array_with_nan_maps_nan_to_none():
    out = _coerce_value(np.array([1.0, float("nan"), 3.0], dtype=np.float64))
    assert out[0] == 1.0
    assert out[1] is None
    assert out[2] == 3.0


def test_large_array_preserves_length():
    arr = np.zeros(128, dtype=np.float64)
    assert len(_coerce_value(arr)) == 128


# --- string waveforms ------------------------------------------------------


def test_multi_element_bytes_list_becomes_list_of_strs():
    # Mirrors DbrStringArray([b"SR01C:BPM3", b"SR01C:BPM4"]) duck-type
    out = _coerce_value([b"SR01C:BPM3", b"SR01C:BPM4", b"SR02C:BPM3"])
    assert out == ["SR01C:BPM3", "SR01C:BPM4", "SR02C:BPM3"]


def test_string_array_with_empty_padding_preserved_verbatim():
    """_coerce_value does not strip padding; the frontend filters if needed."""
    out = _coerce_value([b"A", b"B", b""])
    assert out == ["A", "B", ""]


def test_mixed_str_and_bytes_array():
    """Tolerate elements already as str (rare but possible across caproto versions)."""
    out = _coerce_value([b"A", "B"])
    assert out == ["A", "B"]


# --- JSON safety -----------------------------------------------------------


def test_output_is_json_serialisable_for_typical_pv_shapes():
    """Smoke test: every output the bridge emits must round-trip through json.dumps."""
    import json
    cases = [
        np.int32(0),
        np.float64("nan"),
        b"OK",
        np.zeros(128, dtype=np.float64),
        np.array([float("nan")] * 3, dtype=np.float64),
        [b"SR01C:BPM3", b"SR01C:BPM4"],
        np.array([1.0], dtype=np.float64),
    ]
    for raw in cases:
        # Must not raise; non-finite floats become None upstream.
        json.dumps(_coerce_value(raw))
