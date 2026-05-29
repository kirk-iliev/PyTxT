# M1 — Reference domain (.mat I/O, align, diff)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the pure-domain core of Phase 3 — a new `pytxt/domain/reference.py` module that loads/saves MATLAB-interop `.mat` reference trajectories, aligns a reference's BPM set against the current configured prefixes (soft-merge by canonical name), and computes/summarizes `B − R0` diffs. Adds `scipy` as a runtime dep and a handful of new domain dataclasses. Zero PV, REST, AppState, or frontend surface in M1 — the goal is a fully tested domain module ready for M2 to wire into AppState.

**Architecture:** All five public functions (`canonicalize_bpm_name`, `load_reference_mat`, `save_reference_mat`, `align_to_current`, `compute_diff`, plus `summarize_diff`) live in a single file `pytxt/domain/reference.py`. New dataclasses (`Reference`, `DiffSummary`) land in `pytxt/domain/types.py` alongside the existing `RawBPM` / `FirstTurnResult` per the codebase convention (not in `reference.py` as the spec §6.1 sketch suggested — see Task 1 note). Tests exercise the real `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat` sample file plus synthesized round-trips. All tests are pure-domain (no caproto, no FastAPI, no asyncio); they run in milliseconds.

**The MATLAB schema we're targeting** (verified against the real sample file, see Task 3 fixture):

```
Required (MATLAB GUI writes these; PyTxT must read them):
  R0     : (2, n_bpms) float64    row 0 = X mm, row 1 = Y mm; first-turn only
  BPMs   : struct, only .Names is load-bearing (cell array of names like
           'SR01C:BPM1:SA:X' — note the ':SA:[XY]' suffix to strip)

Optional (PyTxT-extended; absent in MATLAB-saved files):
  X_wf, Y_wf, sum_wf      : (n_bpms, n_samples) int32, raw nm / AU
  injection_turn          : (n_bpms,) int32
  bpm_prefixes_canonical  : (n_bpms,) cell of pytxt-form names
  saved_by                : string, e.g. "pytxt v0.1.0"
```

MATLAB's `load(file, 'R0', 'BPMs')` explicitly names variables; extras are silently ignored. That's what makes the schema bidirectionally interop-safe.

**Tech Stack:** Python 3.10+, numpy (existing), scipy ≥1.11 (new — `scipy.io.savemat` / `scipy.io.loadmat`), pytest + pytest-asyncio (existing). No new test infrastructure required.

**Spec source of truth:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-design.md` §6.1 (component design), §10.2 (unit test list), §11 M1 (DoD).

**File map:**

- Modify `pyproject.toml` — Task 1 (add `scipy>=1.11,<2.0` to runtime deps)
- Modify `pytxt/domain/types.py` — Task 1 (add `Reference` and `DiffSummary` dataclasses)
- Create `pytxt/domain/reference.py` — Tasks 1, 2, 3, 4, 5
- Create `tests/unit/test_reference_canonicalize.py` — Task 1
- Create `tests/unit/test_reference_load.py` — Task 2
- Create `tests/unit/test_reference_save.py` — Task 3 (incl. round-trip + MATLAB-loader sim)
- Create `tests/unit/test_reference_align.py` — Task 4
- Create `tests/unit/test_reference_diff.py` — Task 5
- Append to `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md` — Task 6

**Pre-requisite:** `legacy/` must be present on the working machine (516 MB, gitignored). If absent, run the rsync from the brainstorm session. Tests in Task 2 and Task 3 reference real fixture files in that tree; an absent `legacy/` makes them auto-skip rather than fail (see Task 2 fixture helper).

---

## Task 1: Dep + skeleton + `canonicalize_bpm_name`

**Files:**
- Modify: `pyproject.toml` (add scipy)
- Modify: `pytxt/domain/types.py` (add `Reference`, `DiffSummary` dataclasses)
- Create: `pytxt/domain/reference.py` (module skeleton + `ReferenceLoadError` + `canonicalize_bpm_name`)
- Create: `tests/unit/test_reference_canonicalize.py`

**Notes:**
- **Why `Reference` and `DiffSummary` land in `types.py`, not `reference.py`:** the codebase convention (Phase 2) puts pure domain dataclasses in `domain/types.py` (`RawBPM`, `FirstTurnResult`). Functions live in topic-specific modules (`injection_turn.py`, `first_turn_extract.py`). Spec §6.1 sketched the dataclass inside `reference.py` for compactness; the implementation follows the existing convention. Log this in Task 6.
- **`DiffSummary` is a domain dataclass, NOT the Pydantic model in `api/schemas/reference.py`** (spec §5.3 is also Pydantic — that lands in M3 when REST routes wire). The domain version is what `summarize_diff` returns; the Pydantic version mirrors it. Both will coexist, like `RawBPM` (domain) vs `BpmRawWaveforms` (Pydantic) today.
- **`Reference` field set** (per spec §6.1, with one small addition):
  - `first_turn: FirstTurnResult` (NOT aligned yet — alignment is a separate step)
  - `bpm_names: list[str]` (canonicalized, suffix-stripped)
  - `raws: dict[str, RawBPM] | None` (None when MATLAB-only schema)
  - `file_path: pathlib.Path | None` (None for in-memory promotions; populated by `load_reference_mat`)
  - `saved_at: datetime | None` (file mtime when loaded from disk; None for promotions)
- **`DiffSummary` field set** (per spec §5.3):
  - `x_rms_mm: float`
  - `y_rms_mm: float`
  - `x_max_abs_mm: float`
  - `y_max_abs_mm: float`
  - `n_valid: int`
- **`canonicalize_bpm_name` algorithm:** regex-replace trailing `:SA:X` or `:SA:Y` with empty string. Idempotent. Implementation per spec §6.1.

- [ ] **Step 1: Add scipy to `pyproject.toml`**

In the `dependencies = [...]` block in `[project]`, add `"scipy>=1.11,<2.0",` right after `"numpy>=1.26,<3.0",`. Then verify install in the working venv:

```
.venv/bin/python -m pip install -e .
.venv/bin/python -c "import scipy.io; print(scipy.__version__)"
```

Expected: prints a 1.x version (≥1.11). If pip itself is missing from the venv (only an issue on freshly-bootstrapped envs), run `.venv/bin/python -m ensurepip --upgrade` first.

- [ ] **Step 2: Add `Reference` and `DiffSummary` dataclasses to `pytxt/domain/types.py`**

Append below the existing `FirstTurnResult`:

```python
from pathlib import Path
# (datetime already imported)

@dataclass(frozen=True)
class Reference:
    """In-memory representation of a loaded reference trajectory.

    `first_turn` is always populated (it's the diff math input).
    `raws` is populated only when the .mat included the PyTxT-extended
    waveform variables. MATLAB-GUI-saved references omit these; for
    those refs `raws` is None and the lazy /result/ref/raw endpoint
    (M4) returns 404.

    `bpm_names` is the *canonicalized* (suffix-stripped) list from the
    .mat — preserved separately from `first_turn` for the soft-merge
    audit (M2) and diagnostics.
    """
    first_turn: FirstTurnResult
    bpm_names: list[str]
    raws: dict[str, RawBPM] | None
    file_path: Path | None
    saved_at: datetime | None


@dataclass(frozen=True)
class DiffSummary:
    """Cheap summary of a B − R0 diff. NaN-aware."""
    x_rms_mm: float
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_valid: int
```

- [ ] **Step 3: Create `pytxt/domain/reference.py` skeleton**

```python
"""Reference-trajectory I/O and math.

Pure-numpy + scipy.io module: NO caproto, NO FastAPI, NO asyncio. Only
filesystem-local I/O via scipy.io.{loadmat,savemat}. Per CLAUDE.md
principle #5 — adapters above this layer translate file paths to and
from settings / CMD strings.

MATLAB schema (interop-safe per spec §1, §6.1):

    Required:   R0      : (2, n_bpms) float64, mm — row 0 X, row 1 Y
                BPMs    : struct, .Names cell of 'SR01C:BPM1:SA:X'-style

    Optional:   X_wf, Y_wf, sum_wf      : (n_bpms, n_samples) int32
                injection_turn          : (n_bpms,) int32
                bpm_prefixes_canonical  : (n_bpms,) cell str
                saved_by                : str, "pytxt v<version>"
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from pytxt.domain.types import (
    DiffSummary,
    FirstTurnResult,
    RawBPM,
    Reference,
)


class ReferenceLoadError(ValueError):
    """Raised when a .mat file does not parse as a valid reference."""


_MATLAB_BPM_SUFFIX_RE = re.compile(r":SA:[XY]$")


def canonicalize_bpm_name(name: str) -> str:
    """Strip MATLAB's trailing ':SA:X' or ':SA:Y' channel suffix.

    Idempotent: names without the suffix pass through unchanged.
    """
    return _MATLAB_BPM_SUFFIX_RE.sub("", name)


# load_reference_mat       — Task 2
# save_reference_mat       — Task 3
# align_to_current         — Task 4
# compute_diff             — Task 5
# summarize_diff           — Task 5
```

- [ ] **Step 4: Write tests for `canonicalize_bpm_name`**

Create `tests/unit/test_reference_canonicalize.py`:

```python
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
```

- [ ] **Step 5: Run the suite**

```
.venv/bin/pytest tests/unit/test_reference_canonicalize.py -v
```

Expected: 8 parametrize cases + 1 explicit = 9 PASSED. If anything other than green, **stop** and fix before moving on.

- [ ] **Step 6: Commit**

```
git add pyproject.toml pytxt/domain/types.py pytxt/domain/reference.py tests/unit/test_reference_canonicalize.py
git commit
```

Suggested commit message: `feat(domain): M1 Task 1 — scipy dep, Reference/DiffSummary types, canonicalize_bpm_name`.

---

## Task 2: `load_reference_mat`

**Files:**
- Modify: `pytxt/domain/reference.py` (add `load_reference_mat`)
- Create: `tests/unit/test_reference_load.py`

**Notes:**
- **The real-fixture path:** `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat`. This file has `n_bpms=104`, `nBuffer=100000`, first BPM canonical name `SR01C:BPM1`. Use a `pytest.fixture` to skip cleanly when `legacy/` is absent (CI / fresh checkouts) — the legacy tree is gitignored.
- **scipy.io.loadmat quirks to handle:**
  - Default `squeeze_me=False, struct_as_record=True` returns weird (1,1) wrapping for struct fields. Use `squeeze_me=True, struct_as_record=False` for ergonomic reads (gives you `mat['BPMs'].Names` as a 1D ndarray of strings).
  - `Names` from the real file is `ndarray` of `ndarray([str], dtype='<U…')` (cells of 1-element string arrays). Normalize to a plain `list[str]` via `[str(np.atleast_1d(n)[0]) for n in mat['BPMs'].Names]`.
- **Required-variable validation:** if `R0` or `BPMs` is missing, OR `R0` is not shape `(2, n)`, OR `BPMs` has no `.Names`, raise `ReferenceLoadError` with a precise message naming what was wrong.
- **Optional waveforms:** if all four of `X_wf`, `Y_wf`, `sum_wf`, `injection_turn` are present AND have matching shapes, populate `Reference.raws` as a dict (one `RawBPM` per BPM, in `bpm_names` order). If any are missing OR malformed, set `raws=None` (do NOT raise — MATLAB-only schema is a valid case).
- **`first_turn` construction:** the loaded `R0` is the canonical first-turn extraction; build `FirstTurnResult` directly from it (no need to re-run `extract_first_turn`). For MATLAB-only schemas, `sum_first_turn` and `injection_turn` are not in the file — set them to NaN and -1 respectively. The diff math doesn't use those fields; they're informational.
- **`file_path` and `saved_at`:** populate from the input `Path` and `path.stat().st_mtime` (UTC). Both required for the lazy-raw drill-down (M4).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reference_load.py`:

```python
"""Unit tests for load_reference_mat."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import scipy.io

from pytxt.domain.reference import (
    ReferenceLoadError,
    canonicalize_bpm_name,
    load_reference_mat,
)


# Real MATLAB GUI sample file. Gitignored, transferred from appsdev2.
LEGACY_REF = Path("legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat")


def _skip_if_no_legacy():
    if not LEGACY_REF.exists():
        pytest.skip(f"Missing legacy fixture {LEGACY_REF}; rsync legacy/ from appsdev2 to run this test.")


def _write_minimal_matlab_ref(tmp_path: Path) -> Path:
    """Synthesize a MATLAB-GUI-shaped .mat (R0 + BPMs only, no extras)."""
    p = tmp_path / "minimal.mat"
    n = 3
    R0 = np.array([[0.1, -0.2, 0.3], [0.4, -0.5, 0.6]], dtype=np.float64)
    bpms = {"Names": np.array([["SR01C:BPM1:SA:X"], ["SR02C:BPM1:SA:X"], ["SR03C:BPM1:SA:X"]], dtype=object)}
    scipy.io.savemat(p, {"R0": R0, "BPMs": bpms})
    return p


def _write_extended_ref(tmp_path: Path) -> Path:
    """Synthesize a PyTxT-extended .mat (R0 + BPMs + waveform extras)."""
    p = tmp_path / "extended.mat"
    n = 2
    n_samples = 100
    R0 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    bpms = {"Names": np.array([["SR01C:BPM1:SA:X"], ["SR02C:BPM1:SA:X"]], dtype=object)}
    X_wf = np.tile(np.arange(n_samples, dtype=np.int32), (n, 1))
    Y_wf = np.full((n, n_samples), -1, dtype=np.int32)
    sum_wf = np.full((n, n_samples), 1000, dtype=np.int32)
    injection_turn = np.array([5, 7], dtype=np.int32)
    scipy.io.savemat(p, {
        "R0": R0, "BPMs": bpms,
        "X_wf": X_wf, "Y_wf": Y_wf, "sum_wf": sum_wf,
        "injection_turn": injection_turn,
        "saved_by": "pytxt vtest",
    })
    return p


# --- happy paths ---

def test_load_real_matlab_file_parses_correctly() -> None:
    _skip_if_no_legacy()
    ref = load_reference_mat(LEGACY_REF)
    assert len(ref.bpm_names) == 104
    assert ref.bpm_names[0] == "SR01C:BPM1"
    assert ref.bpm_names[-1] == "SR12C:BPM8"
    assert ref.first_turn.x_first_turn.shape == (104,)
    assert ref.first_turn.y_first_turn.shape == (104,)
    assert ref.raws is None                              # MATLAB-only schema
    assert ref.file_path == LEGACY_REF
    assert ref.saved_at is not None


def test_load_minimal_synthesized_ref(tmp_path: Path) -> None:
    p = _write_minimal_matlab_ref(tmp_path)
    ref = load_reference_mat(p)
    assert ref.bpm_names == ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    np.testing.assert_allclose(ref.first_turn.x_first_turn, [0.1, -0.2, 0.3])
    np.testing.assert_allclose(ref.first_turn.y_first_turn, [0.4, -0.5, 0.6])
    assert ref.raws is None


def test_load_extended_ref_populates_raws(tmp_path: Path) -> None:
    p = _write_extended_ref(tmp_path)
    ref = load_reference_mat(p)
    assert ref.raws is not None
    assert set(ref.raws) == {"SR01C:BPM1", "SR02C:BPM1"}
    assert ref.raws["SR01C:BPM1"].x_wf.shape == (100,)
    assert ref.raws["SR01C:BPM1"].x_wf.dtype == np.int32
    assert ref.first_turn.injection_turn.tolist() == [5, 7]


# --- error paths ---

def test_load_missing_R0_raises(tmp_path: Path) -> None:
    p = tmp_path / "no_R0.mat"
    scipy.io.savemat(p, {"BPMs": {"Names": np.array([["x"]], dtype=object)}})
    with pytest.raises(ReferenceLoadError, match="R0"):
        load_reference_mat(p)


def test_load_missing_BPMs_raises(tmp_path: Path) -> None:
    p = tmp_path / "no_BPMs.mat"
    scipy.io.savemat(p, {"R0": np.zeros((2, 3))})
    with pytest.raises(ReferenceLoadError, match="BPMs"):
        load_reference_mat(p)


def test_load_wrong_R0_shape_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad_R0.mat"
    scipy.io.savemat(p, {
        "R0": np.zeros((3, 3)),                          # should be (2, n)
        "BPMs": {"Names": np.array([["a"], ["b"], ["c"]], dtype=object)},
    })
    with pytest.raises(ReferenceLoadError, match=r"shape|R0"):
        load_reference_mat(p)


def test_load_R0_BPMs_length_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "mismatched.mat"
    scipy.io.savemat(p, {
        "R0": np.zeros((2, 5)),
        "BPMs": {"Names": np.array([["a"], ["b"]], dtype=object)},
    })
    with pytest.raises(ReferenceLoadError, match=r"mismatch|length|BPMs"):
        load_reference_mat(p)


def test_load_corrupt_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "garbage.mat"
    p.write_bytes(b"not a mat file at all")
    with pytest.raises(ReferenceLoadError):
        load_reference_mat(p)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.mat"
    with pytest.raises((FileNotFoundError, ReferenceLoadError)):
        load_reference_mat(p)


# --- canonicalization ---

def test_loaded_names_are_canonicalized(tmp_path: Path) -> None:
    p = _write_minimal_matlab_ref(tmp_path)
    ref = load_reference_mat(p)
    for n in ref.bpm_names:
        assert ":SA:" not in n
```

- [ ] **Step 2: Implement `load_reference_mat`**

Reference implementation outline (fill in `pytxt/domain/reference.py`):

```python
from datetime import datetime, timezone
import scipy.io

def load_reference_mat(path: Path) -> Reference:
    """Read a reference .mat file. See module docstring for schema."""
    if not path.exists():
        raise FileNotFoundError(f"Reference file not found: {path}")

    try:
        mat = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)
    except Exception as exc:
        raise ReferenceLoadError(f"Failed to parse {path.name}: {exc}") from exc

    if "R0" not in mat:
        raise ReferenceLoadError(f"{path.name}: missing required variable 'R0'")
    if "BPMs" not in mat:
        raise ReferenceLoadError(f"{path.name}: missing required variable 'BPMs'")

    R0 = np.asarray(mat["R0"], dtype=np.float64)
    if R0.ndim != 2 or R0.shape[0] != 2:
        raise ReferenceLoadError(
            f"{path.name}: R0 has shape {R0.shape}, expected (2, n_bpms)"
        )

    bpms_struct = mat["BPMs"]
    if not hasattr(bpms_struct, "Names"):
        raise ReferenceLoadError(f"{path.name}: BPMs struct has no 'Names' field")

    names_raw = np.atleast_1d(bpms_struct.Names)
    raw_names = [str(np.atleast_1d(n)[0]) for n in names_raw]
    bpm_names = [canonicalize_bpm_name(n) for n in raw_names]

    if len(bpm_names) != R0.shape[1]:
        raise ReferenceLoadError(
            f"{path.name}: BPMs.Names length {len(bpm_names)} != R0.shape[1] {R0.shape[1]}"
        )

    n_bpms = R0.shape[1]
    x = R0[0].astype(np.float64)
    y = R0[1].astype(np.float64)
    sum_val = np.full(n_bpms, np.nan, dtype=np.float64)
    injection_turn = np.full(n_bpms, -1, dtype=np.int32)

    raws: dict[str, RawBPM] | None = None
    if all(k in mat for k in ("X_wf", "Y_wf", "sum_wf", "injection_turn")):
        try:
            X_wf = np.asarray(mat["X_wf"], dtype=np.int32)
            Y_wf = np.asarray(mat["Y_wf"], dtype=np.int32)
            sum_wf = np.asarray(mat["sum_wf"], dtype=np.int32)
            inj = np.asarray(mat["injection_turn"], dtype=np.int32)
            assert X_wf.shape == Y_wf.shape == sum_wf.shape
            assert X_wf.shape[0] == n_bpms
            assert inj.shape == (n_bpms,)
            now = datetime.now(timezone.utc)
            raws = {
                bpm_names[i]: RawBPM(
                    prefix=bpm_names[i],
                    x_wf=X_wf[i],
                    y_wf=Y_wf[i],
                    sum_wf=sum_wf[i],
                    armed=0,
                    read_timestamp=now,
                )
                for i in range(n_bpms)
            }
            injection_turn = inj
        except (AssertionError, ValueError):
            raws = None    # malformed extras → silently fall back to MATLAB-only

    first_turn = FirstTurnResult(
        x_first_turn=x,
        y_first_turn=y,
        sum_first_turn=sum_val,
        injection_turn=injection_turn,
        failed_bpm_names=[],
    )

    saved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    return Reference(
        first_turn=first_turn,
        bpm_names=bpm_names,
        raws=raws,
        file_path=path,
        saved_at=saved_at,
    )
```

- [ ] **Step 3: Run**

```
.venv/bin/pytest tests/unit/test_reference_load.py -v
```

Expected: all PASSED (one may SKIP if `legacy/` is absent on the working machine — that's fine for CI).

- [ ] **Step 4: Commit**

`feat(domain): M1 Task 2 — load_reference_mat with real MATLAB + extended-schema parsing`

---

## Task 3: `save_reference_mat`

**Files:**
- Modify: `pytxt/domain/reference.py` (add `save_reference_mat`)
- Create: `tests/unit/test_reference_save.py`

**Notes:**
- **What we write** (per spec §6.1):
  - `R0`: `(2, n_bpms)` float64. Row 0 from `first_turn.x_first_turn`; row 1 from `y_first_turn`. NaN entries preserved as NaN (scipy.io handles NaN in float64 fine).
  - `BPMs`: dict with `Names` (object array of `[[name]]` cells matching MATLAB cell convention), `ORDs` (sequential `uint16` 1..n_bpms — we don't have lattice ordinals in pytxt; document the stub), `nBuffer` (int32 100000 — matches our N_SAMPLES). Other GUI-visible fields (`XGolden`, `YGolden`, `current_mode`, `attenuation`, etc.) are written as empty arrays so they exist but don't carry data. Decision-log entry in Task 6.
  - **Extended (always written by PyTxT):** `X_wf`, `Y_wf`, `sum_wf` as `(n_bpms, 100000)` int32; `injection_turn` as `(n_bpms,)` int32; `bpm_prefixes_canonical` (cell of canonical names); `saved_by` string `"pytxt v<version>"`.
  - **For failed BPMs** (entries absent from `last_acquire_raws` because acquire stripped them): R0 row → NaN; waveform rows → zeros (`int32`); `injection_turn[i]` → -1. The saved file always has a row for every prefix in `bpm_prefixes`, in that order.
- **Writing MATLAB cell arrays from Python:** `np.array([["name1"], ["name2"]], dtype=object)` round-trips as a MATLAB cell array under `scipy.io.savemat`. Verified during the brainstorm.
- **Important MATLAB-loader compatibility check:** the round-trip test must verify that `scipy.io.loadmat(path, variable_names=['R0', 'BPMs'])` returns *only* those two — proving MATLAB's `load(file, 'R0', 'BPMs')` would get the expected variables and silently skip the extras.
- **`pytxt v<version>` string:** get from `importlib.metadata.version("pytxt")` with a fallback to `"0.0.0+dev"`. This matches the pattern in `pytxt/composition.py` already.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reference_save.py`:

```python
"""Unit tests for save_reference_mat (round-trip + MATLAB-loader simulation)."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import scipy.io

from pytxt.domain.reference import (
    canonicalize_bpm_name,
    load_reference_mat,
    save_reference_mat,
)
from pytxt.domain.types import FirstTurnResult, RawBPM


def _synth_first_turn(n: int) -> FirstTurnResult:
    return FirstTurnResult(
        x_first_turn=np.array([0.01 * i for i in range(n)], dtype=np.float64),
        y_first_turn=np.array([-0.02 * i for i in range(n)], dtype=np.float64),
        sum_first_turn=np.full(n, 1234.0, dtype=np.float64),
        injection_turn=np.full(n, 1370, dtype=np.int32),
        failed_bpm_names=[],
    )


def _synth_raws(prefixes: list[str]) -> dict[str, RawBPM]:
    now = datetime.now(timezone.utc)
    n_samples = 100000
    return {
        p: RawBPM(
            prefix=p,
            x_wf=np.full(n_samples, i + 1, dtype=np.int32),
            y_wf=np.full(n_samples, -(i + 1), dtype=np.int32),
            sum_wf=np.full(n_samples, 1000 * (i + 1), dtype=np.int32),
            armed=0,
            read_timestamp=now,
        )
        for i, p in enumerate(prefixes)
    }


def test_save_then_load_round_trips_basic(tmp_path: Path) -> None:
    p = tmp_path / "round_trip.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    first_turn = _synth_first_turn(3)
    raws = _synth_raws(prefixes)

    save_reference_mat(p, first_turn, raws, prefixes)
    assert p.exists()
    ref = load_reference_mat(p)

    assert ref.bpm_names == prefixes
    np.testing.assert_allclose(ref.first_turn.x_first_turn, first_turn.x_first_turn)
    np.testing.assert_allclose(ref.first_turn.y_first_turn, first_turn.y_first_turn)
    assert ref.raws is not None
    np.testing.assert_array_equal(ref.raws["SR01C:BPM1"].x_wf, raws["SR01C:BPM1"].x_wf)


def test_save_handles_failed_bpms_as_nan(tmp_path: Path) -> None:
    """A BPM in prefixes but absent from last_acquire_raws → NaN row in R0."""
    p = tmp_path / "with_failure.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    first_turn = FirstTurnResult(
        x_first_turn=np.array([0.1, np.nan]),
        y_first_turn=np.array([0.2, np.nan]),
        sum_first_turn=np.array([100.0, np.nan]),
        injection_turn=np.array([1370, -1], dtype=np.int32),
        failed_bpm_names=["SR02C:BPM1"],
    )
    raws = _synth_raws(["SR01C:BPM1"])    # SR02C:BPM1 absent

    save_reference_mat(p, first_turn, raws, prefixes)
    ref = load_reference_mat(p)
    assert np.isnan(ref.first_turn.x_first_turn[1])
    assert np.isnan(ref.first_turn.y_first_turn[1])
    # Failed BPM still has a row in the waveform arrays (zero-filled)
    assert ref.raws is not None
    assert np.all(ref.raws["SR02C:BPM1"].x_wf == 0)
    assert ref.first_turn.injection_turn[1] == -1


def test_save_writes_matlab_compatible_R0_BPMs(tmp_path: Path) -> None:
    """Simulate MATLAB's load(file, 'R0', 'BPMs') — extras must be ignored."""
    p = tmp_path / "matlab_compat.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    save_reference_mat(p, _synth_first_turn(2), _synth_raws(prefixes), prefixes)

    # MATLAB's load(file, 'R0', 'BPMs') equivalent:
    only_required = scipy.io.loadmat(p, variable_names=["R0", "BPMs"], squeeze_me=True, struct_as_record=False)
    user_keys = [k for k in only_required if not k.startswith("__")]
    assert set(user_keys) == {"R0", "BPMs"}
    R0 = np.asarray(only_required["R0"])
    assert R0.shape == (2, 2)
    assert hasattr(only_required["BPMs"], "Names")


def test_save_includes_extended_variables(tmp_path: Path) -> None:
    p = tmp_path / "extended.mat"
    prefixes = ["SR01C:BPM1"]
    save_reference_mat(p, _synth_first_turn(1), _synth_raws(prefixes), prefixes)
    full = scipy.io.loadmat(p, squeeze_me=True, struct_as_record=False)
    user_keys = {k for k in full if not k.startswith("__")}
    # Required + extras
    assert {"R0", "BPMs", "X_wf", "Y_wf", "sum_wf", "injection_turn"}.issubset(user_keys)
    assert "saved_by" in user_keys


def test_save_preserves_prefix_order(tmp_path: Path) -> None:
    p = tmp_path / "ordered.mat"
    prefixes = ["SR03C:BPM1", "SR01C:BPM1", "SR02C:BPM1"]   # NOT sorted
    save_reference_mat(p, _synth_first_turn(3), _synth_raws(prefixes), prefixes)
    ref = load_reference_mat(p)
    assert ref.bpm_names == prefixes
```

- [ ] **Step 2: Implement `save_reference_mat`**

Implementation outline:

```python
from importlib.metadata import PackageNotFoundError, version

_N_SAMPLES = 100_000

def _pytxt_version() -> str:
    try:
        return version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


def save_reference_mat(
    path: Path,
    first_turn: FirstTurnResult,
    last_acquire_raws: dict[str, RawBPM],
    bpm_prefixes: list[str],
) -> None:
    """Write a MATLAB-compatible reference .mat with PyTxT extras.

    See module docstring for the schema. Failed BPMs (absent from
    last_acquire_raws) are written with NaN in R0 and zero-filled
    waveform rows.
    """
    n_bpms = len(bpm_prefixes)
    assert first_turn.x_first_turn.shape == (n_bpms,), \
        f"first_turn length {first_turn.x_first_turn.shape[0]} != prefixes {n_bpms}"

    R0 = np.stack([
        first_turn.x_first_turn.astype(np.float64),
        first_turn.y_first_turn.astype(np.float64),
    ])  # (2, n_bpms)

    X_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    Y_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    sum_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    inj = np.full(n_bpms, -1, dtype=np.int32)
    for i, prefix in enumerate(bpm_prefixes):
        raw = last_acquire_raws.get(prefix)
        if raw is None:
            continue
        X_wf[i] = raw.x_wf
        Y_wf[i] = raw.y_wf
        sum_wf[i] = raw.sum_wf
        inj[i] = int(first_turn.injection_turn[i])

    bpms_struct = {
        "Names": np.array([[p] for p in bpm_prefixes], dtype=object),
        "ORDs": np.arange(1, n_bpms + 1, dtype=np.uint16),  # stub; we lack lattice ordinals
        "nBuffer": np.int32(_N_SAMPLES),
        # GUI-visible fields stubbed empty for completeness
        "XGolden": np.array([], dtype=np.float64),
        "YGolden": np.array([], dtype=np.float64),
        "current_mode": "",
        "attenuation": np.uint8(0),
    }

    scipy.io.savemat(path, {
        "R0": R0,
        "BPMs": bpms_struct,
        "X_wf": X_wf,
        "Y_wf": Y_wf,
        "sum_wf": sum_wf,
        "injection_turn": inj,
        "bpm_prefixes_canonical": np.array([[p] for p in bpm_prefixes], dtype=object),
        "saved_by": f"pytxt v{_pytxt_version()}",
    })
```

- [ ] **Step 3: Run**

```
.venv/bin/pytest tests/unit/test_reference_save.py tests/unit/test_reference_load.py -v
```

Both files should pass — saving and loading are now joined by the round-trip.

- [ ] **Step 4: Commit**

`feat(domain): M1 Task 3 — save_reference_mat with MATLAB-compat + extended schema`

---

## Task 4: `align_to_current`

**Files:**
- Modify: `pytxt/domain/reference.py` (add `align_to_current`)
- Create: `tests/unit/test_reference_align.py`

**Notes:**
- **Signature:** `align_to_current(ref: Reference, current_prefixes: list[str]) -> tuple[FirstTurnResult, int, int]`. Returns `(aligned, n_aligned, n_unaligned)` where `n_aligned + n_unaligned == len(current_prefixes)`.
- **Algorithm** (per spec §6.1):
  1. Build a lookup dict `ref_idx = {name: i for i, name in enumerate(ref.bpm_names)}` (already canonical from `load_reference_mat`).
  2. For each `current_prefix` in `current_prefixes` (in order):
     - if `current_prefix in ref_idx`: copy `ref.first_turn.x_first_turn[ref_idx[current_prefix]]` and `y` into the aligned arrays at the current position.
     - else: leave NaN.
  3. Return aligned `FirstTurnResult` shaped like `current_prefixes`, plus counts.
- **`current_prefixes` may already be canonical** (pytxt stores `SR01C:BPM1`-form). But defensively, run them through `canonicalize_bpm_name` too, so an upstream typo doesn't silently produce all-NaN output.
- **The aligned `sum_first_turn` and `injection_turn`** preserve the ref's values for matching BPMs; NaN / -1 for unaligned. (These fields aren't used by the diff math but are useful for diagnostics.)
- **MATLAB GUI parity:** the GUI's load logic is `for n: for i: if strcmp(BPMs.Names{n}, app.SC.EXP.BPM.Names{i}): R0(:,i) = R0(:,n)`. Our `align_to_current` is the inverse-index version of the same operation — produces the same final aligned array.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reference_align.py`:

```python
"""Unit tests for align_to_current (soft-merge by canonical BPM name)."""
from pathlib import Path

import numpy as np
import pytest

from pytxt.domain.reference import align_to_current
from pytxt.domain.types import FirstTurnResult, Reference


def _make_ref(names: list[str], xs: list[float], ys: list[float]) -> Reference:
    n = len(names)
    return Reference(
        first_turn=FirstTurnResult(
            x_first_turn=np.array(xs, dtype=np.float64),
            y_first_turn=np.array(ys, dtype=np.float64),
            sum_first_turn=np.full(n, np.nan, dtype=np.float64),
            injection_turn=np.full(n, -1, dtype=np.int32),
            failed_bpm_names=[],
        ),
        bpm_names=names,
        raws=None,
        file_path=None,
        saved_at=None,
    )


def test_full_overlap_same_order() -> None:
    ref = _make_ref(["SR01C:BPM1", "SR02C:BPM1"], [0.1, 0.2], [0.3, 0.4])
    aligned, n_ok, n_miss = align_to_current(ref, ["SR01C:BPM1", "SR02C:BPM1"])
    assert n_ok == 2 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [0.1, 0.2])
    np.testing.assert_allclose(aligned.y_first_turn, [0.3, 0.4])


def test_full_overlap_different_order() -> None:
    """current_prefixes order drives output, not the ref's order."""
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["B", "A"])
    assert n_ok == 2 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [2.0, 1.0])
    np.testing.assert_allclose(aligned.y_first_turn, [4.0, 3.0])


def test_partial_overlap_leaves_nan() -> None:
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["A", "B", "C"])
    assert n_ok == 2 and n_miss == 1
    assert aligned.x_first_turn[0] == 1.0
    assert aligned.x_first_turn[1] == 2.0
    assert np.isnan(aligned.x_first_turn[2])
    assert np.isnan(aligned.y_first_turn[2])
    assert aligned.injection_turn[2] == -1


def test_zero_overlap_all_nan() -> None:
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["X", "Y"])
    assert n_ok == 0 and n_miss == 2
    assert np.all(np.isnan(aligned.x_first_turn))
    assert np.all(np.isnan(aligned.y_first_turn))


def test_ref_larger_than_current_drops_extras() -> None:
    ref = _make_ref(["A", "B", "C"], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["B"])
    assert n_ok == 1 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [2.0])
    np.testing.assert_allclose(aligned.y_first_turn, [5.0])


def test_aligned_length_matches_current() -> None:
    ref = _make_ref(["A"], [1.0], [2.0])
    aligned, _, _ = align_to_current(ref, ["A", "B", "C", "D"])
    assert aligned.x_first_turn.shape == (4,)
    assert aligned.y_first_turn.shape == (4,)


def test_current_prefixes_are_canonicalized_defensively() -> None:
    """If somehow current_prefixes has the MATLAB :SA:X suffix, still match."""
    ref = _make_ref(["SR01C:BPM1"], [0.5], [0.7])
    aligned, n_ok, n_miss = align_to_current(ref, ["SR01C:BPM1:SA:X"])
    assert n_ok == 1 and n_miss == 0
    assert aligned.x_first_turn[0] == 0.5
```

- [ ] **Step 2: Implement `align_to_current`**

```python
def align_to_current(
    ref: Reference,
    current_prefixes: list[str],
) -> tuple[FirstTurnResult, int, int]:
    """Soft-merge by canonical BPM name. See spec §6.1."""
    ref_idx = {name: i for i, name in enumerate(ref.bpm_names)}
    n = len(current_prefixes)
    x = np.full(n, np.nan, dtype=np.float64)
    y = np.full(n, np.nan, dtype=np.float64)
    sum_val = np.full(n, np.nan, dtype=np.float64)
    inj = np.full(n, -1, dtype=np.int32)
    n_aligned = 0
    for i, prefix in enumerate(current_prefixes):
        canonical = canonicalize_bpm_name(prefix)
        ref_i = ref_idx.get(canonical)
        if ref_i is None:
            continue
        x[i] = ref.first_turn.x_first_turn[ref_i]
        y[i] = ref.first_turn.y_first_turn[ref_i]
        sum_val[i] = ref.first_turn.sum_first_turn[ref_i]
        inj[i] = int(ref.first_turn.injection_turn[ref_i])
        n_aligned += 1
    aligned = FirstTurnResult(
        x_first_turn=x,
        y_first_turn=y,
        sum_first_turn=sum_val,
        injection_turn=inj,
        failed_bpm_names=[],
    )
    return aligned, n_aligned, n - n_aligned
```

- [ ] **Step 3: Run**

```
.venv/bin/pytest tests/unit/test_reference_align.py -v
```

- [ ] **Step 4: Commit**

`feat(domain): M1 Task 4 — align_to_current (soft-merge by canonical name)`

---

## Task 5: `compute_diff` + `summarize_diff`

**Files:**
- Modify: `pytxt/domain/reference.py` (add both)
- Create: `tests/unit/test_reference_diff.py`

**Notes:**
- **`compute_diff` signature:** `compute_diff(live: FirstTurnResult, aligned_ref: FirstTurnResult) -> tuple[np.ndarray, np.ndarray]`. Returns `(dx, dy)` each shape `(n_bpms,)`. NaN propagates naturally via numpy: `B - NaN = NaN`, `NaN - R0 = NaN`. No special handling needed.
- **`summarize_diff` signature:** `summarize_diff(dx: np.ndarray, dy: np.ndarray) -> DiffSummary`. RMS uses `np.nanmean(x**2)`; max-abs uses `np.nanmax(|x|)`. `n_valid` = count of indices where BOTH `dx[i]` and `dy[i]` are non-NaN.
- **Edge case — all-NaN input:** `np.nanmean` raises a RuntimeWarning and returns NaN for all-NaN input. That's fine; the summary fields will be NaN, `n_valid=0`. Tests must cover this.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_reference_diff.py`:

```python
"""Unit tests for compute_diff and summarize_diff."""
import math

import numpy as np
import pytest

from pytxt.domain.reference import compute_diff, summarize_diff
from pytxt.domain.types import FirstTurnResult


def _ft(xs: list[float], ys: list[float]) -> FirstTurnResult:
    n = len(xs)
    return FirstTurnResult(
        x_first_turn=np.array(xs, dtype=np.float64),
        y_first_turn=np.array(ys, dtype=np.float64),
        sum_first_turn=np.full(n, np.nan, dtype=np.float64),
        injection_turn=np.full(n, -1, dtype=np.int32),
        failed_bpm_names=[],
    )


# --- compute_diff ---

def test_compute_diff_straight_subtraction() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),
                          _ft([0.5, 1.5, 2.5], [3.5, 4.5, 5.5]))
    np.testing.assert_allclose(dx, [0.5, 0.5, 0.5])
    np.testing.assert_allclose(dy, [0.5, 0.5, 0.5])


def test_compute_diff_nan_in_live_propagates() -> None:
    dx, dy = compute_diff(_ft([1.0, np.nan, 3.0], [4.0, np.nan, 6.0]),
                          _ft([0.5, 1.5, 2.5],     [3.5, 4.5, 5.5]))
    assert np.isnan(dx[1])
    assert np.isnan(dy[1])


def test_compute_diff_nan_in_ref_propagates() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0, 3.0],     [4.0, 5.0, 6.0]),
                          _ft([0.5, np.nan, 2.5], [3.5, np.nan, 5.5]))
    assert np.isnan(dx[1])
    assert np.isnan(dy[1])


def test_compute_diff_preserves_shape() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0], [3.0, 4.0]),
                          _ft([0.0, 0.0], [0.0, 0.0]))
    assert dx.shape == (2,)
    assert dy.shape == (2,)


# --- summarize_diff ---

def test_summarize_basic() -> None:
    dx = np.array([1.0, -1.0, 2.0, -2.0])
    dy = np.array([0.0, 0.0, 0.0, 0.0])
    s = summarize_diff(dx, dy)
    assert math.isclose(s.x_rms_mm, math.sqrt((1+1+4+4)/4))
    assert s.y_rms_mm == 0.0
    assert s.x_max_abs_mm == 2.0
    assert s.y_max_abs_mm == 0.0
    assert s.n_valid == 4


def test_summarize_ignores_nan_for_rms() -> None:
    dx = np.array([1.0, np.nan, 1.0])
    dy = np.array([1.0, 1.0,    1.0])
    s = summarize_diff(dx, dy)
    # x_rms over the 2 valid entries
    assert math.isclose(s.x_rms_mm, 1.0)
    # n_valid counts where BOTH are non-NaN
    assert s.n_valid == 2


def test_summarize_n_valid_requires_both() -> None:
    dx = np.array([1.0, np.nan, 1.0, np.nan])
    dy = np.array([1.0, 1.0,    np.nan, np.nan])
    s = summarize_diff(dx, dy)
    assert s.n_valid == 1   # only index 0 has both non-NaN


def test_summarize_all_nan() -> None:
    dx = np.array([np.nan, np.nan])
    dy = np.array([np.nan, np.nan])
    s = summarize_diff(dx, dy)
    assert math.isnan(s.x_rms_mm)
    assert math.isnan(s.y_rms_mm)
    assert math.isnan(s.x_max_abs_mm)
    assert math.isnan(s.y_max_abs_mm)
    assert s.n_valid == 0


def test_summarize_max_abs_picks_largest_magnitude() -> None:
    s = summarize_diff(np.array([-5.0, 3.0, -1.0]), np.array([0.0, 0.0, 0.0]))
    assert s.x_max_abs_mm == 5.0
```

- [ ] **Step 2: Implement both**

```python
import warnings

def compute_diff(
    live: FirstTurnResult,
    aligned_ref: FirstTurnResult,
) -> tuple[np.ndarray, np.ndarray]:
    """NaN-propagating B − R0. See spec §6.1."""
    return (
        live.x_first_turn - aligned_ref.x_first_turn,
        live.y_first_turn - aligned_ref.y_first_turn,
    )


def summarize_diff(dx: np.ndarray, dy: np.ndarray) -> DiffSummary:
    """RMS/max/n_valid — NaN-aware. n_valid counts indices non-NaN in BOTH."""
    both_valid = ~np.isnan(dx) & ~np.isnan(dy)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        x_rms = float(np.sqrt(np.nanmean(dx ** 2)))
        y_rms = float(np.sqrt(np.nanmean(dy ** 2)))
        x_max = float(np.nanmax(np.abs(dx)))
        y_max = float(np.nanmax(np.abs(dy)))
    return DiffSummary(
        x_rms_mm=x_rms,
        y_rms_mm=y_rms,
        x_max_abs_mm=x_max,
        y_max_abs_mm=y_max,
        n_valid=int(np.sum(both_valid)),
    )
```

- [ ] **Step 3: Run the full M1 suite**

```
.venv/bin/pytest tests/unit/test_reference_canonicalize.py tests/unit/test_reference_load.py tests/unit/test_reference_save.py tests/unit/test_reference_align.py tests/unit/test_reference_diff.py -v
```

Expected: all PASSED (or 1 SKIP if `legacy/` is absent). Suite size should be roughly 30+ cases.

Also re-run the full project suite to confirm no phase-2 regressions:

```
.venv/bin/pytest -q
```

Expected: 121 phase-2 + ~30 new = ~151 PASSED.

- [ ] **Step 4: Commit**

`feat(domain): M1 Task 5 — compute_diff (NaN-propagating) and summarize_diff`

---

## Task 6: Closeout — decision log + commit

**Files:**
- Modify: `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md`

**Notes:**
- Append two or three log entries: (1) the dataclass-placement deviation from spec §6.1 (Reference/DiffSummary in `types.py` not `reference.py`); (2) the `BPMs` struct stub field choices on save (XGolden/YGolden empty, ORDs sequential); (3) any surprises encountered during implementation (e.g. specific scipy.io quirks worth documenting for the next milestone).
- This is the only place the spec is acknowledged-but-deviated-from in M1; everything else hews to the spec.
- M1 has no public surface change, so the roadmap update is minimal — leave the recent-activity entries for the next commit; just bump the `M1 ✓` indicator if you're feeling thorough (otherwise defer to M2/M3/M4 closeouts which DO change surface).

- [ ] **Step 1: Append decision log entries**

Append to `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md` (newest at bottom). Suggested entries:

```markdown
## 2026-MM-DD — Reference and DiffSummary dataclasses in types.py, not reference.py

**Context:** M1 Task 1 — implementing the new `Reference` and `DiffSummary` dataclasses.

**Decision:** Both dataclasses landed in `pytxt/domain/types.py` alongside `RawBPM` and `FirstTurnResult`, NOT inside `pytxt/domain/reference.py` as the spec §6.1 sketch implied.

**Why:** The codebase convention since Phase 2 is "all pure domain dataclasses live in `domain/types.py`; topic-specific modules hold the functions." Following that convention keeps imports simple (callers always grab `from pytxt.domain.types import ...`) and avoids a circular-import risk if `reference.py` ever needs to import another dataclass.

**Spec relationship:** Minor deviation from §6.1; functional surface identical.

**Forward impact:** None. `DiffResult` (mentioned in spec §6.2 for AppState) should also land in `types.py` when M2 wires it.


## 2026-MM-DD — BPMs struct stub fields on save

**Context:** M1 Task 3 — implementing `save_reference_mat`, deciding what to put in the `BPMs` struct beyond `Names`.

**Decision:** PyTxT-saved files include `BPMs.Names` (canonical pytxt prefixes), `BPMs.ORDs` (sequential 1..n_bpms `uint16`; we don't have lattice ordinals in pytxt), `BPMs.nBuffer` (int32 100000). Other GUI-visible fields are written as empty arrays: `XGolden`, `YGolden`, `current_mode`, `attenuation`.

**Why:** The MATLAB GUI's loader only consumes `BPMs.Names` and (implicitly) the shape of `R0`. Other fields are GUI display metadata. Stubbing keeps interop honest (a downstream MATLAB script reading `BPMs.XGolden` gets an empty array, not bad data) without requiring pytxt to invent or fetch values it doesn't track.

**Spec relationship:** Fills gap (spec §6.1 said "stub the rest" without enumerating).

**Forward impact:** If a real downstream MATLAB script breaks on empty `XGolden`, populate it from a static config file. Watch for this during M2/M3 control-room testing.
```

(Use the actual implementation date for the `## YYYY-MM-DD` headers.)

- [ ] **Step 2: Commit**

```
git add docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md
git commit
```

Suggested message: `docs(decisions): M1 closeout — dataclass placement + BPMs stub-field choices`.

- [ ] **Step 3: Final verification**

```
.venv/bin/pytest -q                                # full suite
.venv/bin/python -c "from pytxt.domain.reference import load_reference_mat, save_reference_mat, align_to_current, compute_diff, summarize_diff, canonicalize_bpm_name, ReferenceLoadError; print('domain.reference public surface ok')"
git log --oneline -7                               # ~6 M1 commits visible
git status                                         # clean (modulo pre-existing unstaged)
```

Expected: full pytest suite green; import smoke passes; ~5–6 M1 commits on `main`.

---

## Notes for the implementer

- **Per CLAUDE.md §5 (Domain logic is I/O-free):** M1 is a pure-domain module. `scipy.io.{loadmat,savemat}` IS allowed (filesystem-local I/O is fine per spec §2; the boundary we don't cross is network I/O: caproto, FastAPI, asyncio). If you find yourself reaching for any of those three, stop — that work belongs in M2 (handlers + AppState) or later.
- **Per CLAUDE.md §1 (Agent-callable first):** M1 has no agent-callable surface yet — that lands in M2. Don't worry about CA/REST parity in this milestone.
- **`legacy/` fixture handling:** the real MATLAB sample file is gitignored and 516 MB. Tests in Task 2/3 that reference it must use the `_skip_if_no_legacy()` helper so CI / fresh checkouts skip cleanly. If you're on a fresh machine, run the rsync from the brainstorm transcript:
  ```
  rsync -avh --progress kirkiliev@Kirks-MacBook-Pro.local:/Users/kirkiliev/Documents/coding/PyTxT/legacy /home/kiliev/Documents/Code/LBL/PyTxT/
  ```
- **`scipy.io` quirks to remember:**
  - `loadmat(squeeze_me=True, struct_as_record=False)` is the ergonomic combo — gives you `mat['BPMs'].Names` as a real attribute access.
  - MATLAB cell arrays of strings round-trip as `np.array([[s] for s in strs], dtype=object)`.
  - NaN in float64 arrays round-trips fine; int32 has no NaN, so failed BPMs in waveform rows go to zero, not NaN.
- **Subagent command shape:** use `.venv/bin/pytest`, not `source .venv/bin/activate && pytest`. (Memory entry: `feedback_subagent_command_shape`.)
- **No mocking of scipy:** all tests synthesize real `.mat` files in `tmp_path` and read them back. Faster than mocking, catches real format issues.
- **Test count target:** ≥15 unit tests per spec §11 M1 DoD. The task breakdown above lands around 30, which exceeds the bar comfortably and gives the M2 wiring something to lean on.
- **No public surface change in M1:** no PVs added, no REST routes, no AppState fields, no frontend. If the implementer finds themselves editing any of those packages, stop and re-read this plan's Goal section.
