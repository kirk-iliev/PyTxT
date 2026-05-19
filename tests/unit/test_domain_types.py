"""Domain dataclasses: frozen, type-correct, no I/O imports."""
from datetime import datetime, timezone
import numpy as np
import pytest

from pytxt.domain.types import RawBPM, FirstTurnResult


def test_raw_bpm_is_frozen():
    raw = RawBPM(
        prefix="SR01C:BPM1",
        x_wf=np.zeros(100000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=np.zeros(100000, dtype=np.int32),
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises((TypeError, AttributeError)):
        raw.prefix = "other"   # frozen


def test_first_turn_result_shape():
    n = 5
    r = FirstTurnResult(
        x_first_turn=np.full(n, np.nan),
        y_first_turn=np.full(n, np.nan),
        sum_first_turn=np.full(n, np.nan),
        injection_turn=np.full(n, -1, dtype=np.int32),
        failed_bpm_names=["A", "B"],
    )
    assert r.x_first_turn.shape == (n,)
    assert r.injection_turn.dtype == np.int32


def test_domain_imports_no_io():
    """domain/ must not import caproto, fastapi, or asyncio anywhere."""
    import inspect
    import pytxt.domain.types as m
    src = inspect.getsource(m)
    assert "caproto" not in src
    assert "fastapi" not in src
    assert "import asyncio" not in src
