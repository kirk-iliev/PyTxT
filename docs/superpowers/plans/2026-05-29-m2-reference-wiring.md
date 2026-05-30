# M2 — Reference wiring (AppState + PVs + PROMOTE/CLEAR + diff publication)

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task. Each task ends in a green test run and a commit. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the M1 pure-domain reference core into the live application surface — *the file-free half of Phase 3*. After M2, an operator or agent can promote the current acquisition to an in-memory reference (`CMD:PROMOTE_REF` / `POST /cmd/promote_ref`), see per-BPM `B − R0` diff arrays republished on every subsequent acquire (`RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`), observe reference status (`STATE:REF_*`), and unload it (`CMD:CLEAR_REF` / `POST /cmd/clear_ref`). File LOAD/SAVE and the reference library are **M3**; the 4-panel frontend + e2e are **M4**.

**Architecture:** M2 is the adapter layer that translates M1's pure functions (`align_to_current`, `compute_diff`, `summarize_diff`) into PVs, REST, and AppState. Every command keeps the phase-2 parity guarantee: one canonical async handler in `pytxt/handlers/reference.py`, called identically by the CA putter (`ioc/pvs.py`) and the REST route (`api/routes/cmd.py`). Diff publication piggybacks on the existing atomic `AppState.update` in `handle_acquire`, so subscribers never see a first-turn array update without its matching diff update.

**Scope decisions (deviations from spec — log in Task 8):**

1. **Backend-only.** Spec §11 M2 prose mentions "Frontend hover tooltip extended (no layout switch yet)." The M2 *DoD bullets* require only PV/REST parity + the parity test. We defer **all** frontend work to M4 (where it lands atomically with the e2e spec and 4-panel layout). M2 ships zero `pytxt/frontend/` changes. This keeps M2 fully unit + integration testable with no Playwright dependency.
2. **`ReferenceSource` + `DiffResult` live in `pytxt/domain/types.py`**, not `api/schemas/reference.py` (spec §5.3 sketch) — because `AppState` (in `pytxt/state/`) references both, and `state → api` would invert the layering. The Pydantic `reference.py` schema imports/re-uses the domain `ReferenceSource`. This mirrors the M1 decision (`Reference`/`DiffSummary` in `types.py`).
3. **No LOAD_REF / SAVE_REF in M2.** The `CMD:LOAD_REF` / `CMD:SAVE_REF` PVs, `handlers/reference.py` load/save functions, `reference_dir` settings, path-safety helper, `routes/references.py`, and `/result/ref/raw` are all **M3**. M2 adds only the in-memory `PROMOTE_REF` / `CLEAR_REF` pair. The `reference_file_path` AppState field exists (stays `None` under promote) so M3 drops in without an AppState migration.
4. **Composition is a near-no-op.** `reference_dir` wiring is M3; promote/clear handlers take only `state`, so the composition root is unchanged in M2 (the putters/routes call the handlers directly, mirroring how `cmd_acquire` calls `handle_acquire`).

**The reference/diff state model** (added to `AppState`, all-or-nothing — when `reference_loaded=False` every other `reference_*` field is at its empty default):

```
reference_loaded:      bool                    # sentinel; flips on promote/clear
reference_name:        str                     # "<promoted>" under promote, "" when none
reference_loaded_at:   datetime | None         # UTC, set on promote, None on clear
reference_source:      ReferenceSource         # PROMOTED | NONE (FILE arrives in M3)
reference_first_turn:  FirstTurnResult | None  # the R0 the diff subtracts
reference_file_path:   Path | None             # always None in M2 (file backing is M3)
reference_bpm_names:   list[str] | None        # canonical names the ref was aligned on
last_diff:             DiffResult | None        # dx/dy/summary; None → diff PVs NaN-filled
```

**Tech Stack:** Python 3.10+, caproto (IOC + putters), FastAPI/pydantic (routes + schemas), numpy (existing), pytest + pytest-asyncio (existing). No new dependencies. No new test infrastructure — reuse the phase-2 `SyntheticBpmReader` + IOC/REST integration fixtures.

**Spec source of truth:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-design.md` — §5.1 (PVs), §5.2/§5.3 (REST + schemas), §6.2 (AppState), §6.3 (handlers), §6.4 (acquire extension), §6.5/§6.6 (IOC), §6.7 (cmd routes), §7.3/§7.4/§7.5 (PROMOTE/CLEAR/ACQUIRE flows), §8 (errors), §10.3 (integration tests), §11 M2 (DoD).

**Phase-2 patterns to mirror (verified file anchors):**
- `pytxt/state/app_state.py` — `@dataclass` (mutable) `AppState`; `async def update(**changes)` two-pass atomic, numpy-tolerant equality, per-field listeners via `subscribe(field, cb)`.
- `pytxt/ioc/pvs.py` — `PyTxTPVGroup(PVGroup)`; scalar `pvproperty(value=0, dtype=int, read_only=True, name="STATE:…")`; waveform `pvproperty(value=[0.0]*_BPM_MAX, dtype=float, read_only=True, max_length=_BPM_MAX, name="RESULT:…")`; string `dtype=ca.ChannelType.STRING`; command `pvproperty(... name="CMD:…")` + `@cmd_x.putter async def cmd_x(self, instance, value)` that calls a handler on `self._state` and re-raises typed exceptions for CA alarms. `_BPM_MAX = 128`.
- `pytxt/ioc/server.py` — `_bind_state_changes()` subscribes listeners that write PVs (with 1-retry + 50ms backoff); `_publish_last_acquire(value)` writes a bundle of PVs reading from `self.state`; startup hook pushes initial values after the caproto Context is running. Pad helpers: `_pad_numeric_array`, `_pad_string_array`, `_pad_int_array`, `_coerce_for_write`.
- `pytxt/handlers/acquire.py` — `async def handle_acquire(state, reader)`; builds `first_turn = extract_first_turn(raws)`; the final `await state.update(last_acquire=..., last_acquire_raws=...)` is the seam for `last_diff=...`.
- `pytxt/api/routes/cmd.py` — `router = APIRouter(prefix="/api/v1/cmd")`; `@router.post("/acquire")` reads `request.app.state.app_state`, calls the shared handler, maps typed exceptions → HTTP codes.
- `pytxt/api/schemas/result.py` — `AcquireResponse(BaseModel)`; `STATUS_INT_TO_STR` enum-mapping pattern (single source of truth for IOC enum ↔ REST string).
- `tests/integration/test_parity.py` — `@pytest.mark.parametrize("command_name, ca_pv_suffix, rest_path", [...])`; `_public_state(state)` projection; runs CA and REST on independent states and asserts equal diffs.

**File map:**
- Modify `pytxt/domain/types.py` — Task 1 (`ReferenceSource` enum, `DiffResult` dataclass)
- Modify `pytxt/state/app_state.py` — Task 1 (8 new fields)
- Create `pytxt/api/schemas/reference.py` — Task 2 (`PromoteRefResponse`, `ClearRefResponse`, `ReferenceStatus`, `DiffSummary` pydantic; re-export `ReferenceSource`)
- Create `pytxt/handlers/reference.py` — Task 2 (`handle_promote_ref`, `handle_clear_ref`, `NoLastAcquireError`)
- Modify `pytxt/ioc/pvs.py` — Task 3 (6 new PVs + 2 putters)
- Modify `pytxt/ioc/server.py` — Task 4 (publish status bundle + diff arrays + startup defaults)
- Modify `pytxt/handlers/acquire.py` — Task 5 (compute + bundle `last_diff`)
- Modify `pytxt/api/routes/cmd.py` — Task 6 (2 routes)
- Modify `pytxt/api/schemas/state.py` + `pytxt/api/routes/state.py` — Task 6 (reference block in `/state` snapshot)
- Create `tests/unit/test_handlers_reference.py` — Task 2
- Create `tests/unit/test_cmd_reference_putters.py` — Task 3
- Modify `tests/unit/test_app_state.py`, `tests/unit/test_handlers_acquire.py` — Tasks 1, 5
- Create `tests/integration/test_reference_promote_clear.py` — Task 7
- Modify `tests/integration/test_parity.py` — Task 7 (+2 rows, optional pre-acquire)
- Append `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md` — Task 8

**Pre-requisite:** M1 complete (commits 65c8767→91e7d81). `pytxt/domain/reference.py` exposes `align_to_current`, `compute_diff`, `summarize_diff`; `pytxt/domain/types.py` has `Reference`, `DiffSummary`, `FirstTurnResult`, `RawBPM`.

---

## Task 1: Domain/state types + AppState fields

**Files:**
- Modify: `pytxt/domain/types.py` (add `ReferenceSource`, `DiffResult`)
- Modify: `pytxt/state/app_state.py` (8 new fields)
- Modify: `tests/unit/test_app_state.py` (defaults + a promote-shaped update)

**Notes:**
- **`ReferenceSource`** is a `str, Enum` so it serializes cleanly in both the PV string and pydantic JSON: `NONE = ""`, `FILE = "file"`, `PROMOTED = "promoted"`. `FILE` is defined now (zero cost) even though only `PROMOTED`/`NONE` are reachable until M3.
- **`DiffResult`** is a frozen dataclass: `dx: np.ndarray`, `dy: np.ndarray`, `summary: DiffSummary`. Lives next to `DiffSummary` in `types.py`.
- **AppState fields** must all carry safe empty defaults (the dataclass has other defaulted fields, so these append cleanly). `reference_source` defaults to `ReferenceSource.NONE`. `last_diff` defaults to `None`.
- **numpy-tolerant `update()`** already handles `last_diff` (a `DiffResult` holding arrays) and `reference_first_turn` (holds arrays) — the existing equality guard catches `ValueError/TypeError` and treats uncomparable fields as "changed" (regression-tested in `test_app_state.py`). Confirm no new guard is needed; if a `DiffResult`/`FirstTurnResult` comparison raises, the existing `except (ValueError, TypeError)` path covers it.

- [ ] **Step 1: Add `ReferenceSource` + `DiffResult` to `pytxt/domain/types.py`**

```python
import enum  # if not already imported

class ReferenceSource(str, enum.Enum):
    """Provenance of the currently-loaded reference trajectory."""
    NONE = ""
    FILE = "file"          # reachable in M3 (LOAD_REF)
    PROMOTED = "promoted"  # reachable in M2 (PROMOTE_REF)


@dataclass(frozen=True)
class DiffResult:
    """Latest per-BPM B − R0 diff plus its cheap summary.

    `dx`/`dy` are (n_bpms,) float64, NaN where either side is NaN. When
    AppState.last_diff is None, the IOC NaN-fills the diff PVs.
    """
    dx: np.ndarray
    dy: np.ndarray
    summary: DiffSummary
```

- [ ] **Step 2: Add the 8 fields to `AppState`** (append after the existing phase-2 fields, before `_listeners`)

```python
from pytxt.domain.types import DiffResult, FirstTurnResult, ReferenceSource
from pathlib import Path
from datetime import datetime

    # --- Phase 3 reference state (all-or-nothing) ---
    reference_loaded: bool = False
    reference_name: str = ""
    reference_loaded_at: datetime | None = None
    reference_source: ReferenceSource = ReferenceSource.NONE
    reference_first_turn: FirstTurnResult | None = None
    reference_file_path: Path | None = None
    reference_bpm_names: list[str] | None = None
    last_diff: DiffResult | None = None
```

- [ ] **Step 3: Extend `tests/unit/test_app_state.py`**

Add: (a) a test that a fresh `AppState` has `reference_loaded is False`, `reference_source is ReferenceSource.NONE`, `last_diff is None`; (b) a test that `await state.update(reference_loaded=True, reference_name="<promoted>", reference_source=ReferenceSource.PROMOTED, last_diff=DiffResult(dx=np.array([0.0]), dy=np.array([0.0]), summary=DiffSummary(0,0,0,0,1)))` applies atomically and fires listeners for exactly the changed fields (subscribe a counter to `reference_loaded` and `last_diff`). Reuse the existing numpy-update regression test's style.

- [ ] **Step 4: Run + commit**

```
.venv/bin/pytest tests/unit/test_app_state.py tests/unit/test_domain_types.py -v
```

Commit: `feat(state): M2 Task 1 — ReferenceSource/DiffResult types + AppState reference fields`

---

## Task 2: `handlers/reference.py` (promote/clear) + response schemas

**Files:**
- Create: `pytxt/api/schemas/reference.py`
- Create: `pytxt/handlers/reference.py`
- Create: `tests/unit/test_handlers_reference.py`

**Notes:**
- **`NoLastAcquireError`** (define in `handlers/reference.py`): raised by `handle_promote_ref` when `state.last_acquire_raws` is empty / there's been no successful acquire. CA putter re-raises it (→ alarm); REST maps it → 422. (Mirrors how `AcquisitionInFlightError` is shared between the acquire putter and route.)
- **What counts as "has a last_acquire to source from":** promote needs a real first-turn to copy. Use `state.last_acquire.status` — refuse when status is the initial sentinel / `FAILED` with zero ok, OR when `reference`-able arrays are absent. Concretely: refuse if `state.last_acquire.ok_count == 0` (no BPM produced a position). Confirm the exact field name on `LastAcquireResult` while implementing.
- **Building the promoted reference** (spec §7.3): the promoted R0 is the current live first-turn. We need the *array* form. `handle_acquire` stores `last_acquire_raws` (dict) and the `LastAcquireResult` summary, but not the `FirstTurnResult` arrays. Two honest options — pick (A), log the choice:
  - **(A) Recompute** `first_turn = extract_first_turn(_realign(state.last_acquire_raws, state.bpm_prefixes))` inside the handler. The IOC publisher already re-derives first-turn arrays from `last_acquire_raws + bpm_prefixes` this same way (`server.py:_publish_last_acquire`), so there's a proven helper pattern to mirror. This keeps AppState from storing a redundant array copy.
  - (B) Add a `last_first_turn: FirstTurnResult | None` field to AppState populated by `handle_acquire`. More storage, but no recompute. Defer unless (A) proves awkward.
  - Use **(A)**. If `extract_first_turn` needs the full prefix-aligned dict (including `None` for failed BPMs), reconstruct it: `{p: state.last_acquire_raws.get(p) for p in state.bpm_prefixes}`.
- **`reference_first_turn` under promote** is exactly this recomputed `first_turn` (it IS aligned to current prefixes already, since we built it from `bpm_prefixes`). `align_to_current` is therefore a no-op for promote — but for symmetry/clarity, set `reference_bpm_names = list(state.bpm_prefixes)`.
- **Self-diff:** `compute_diff(first_turn, first_turn)` → zeros (NaN where live was NaN). `summarize_diff` → `DiffResult`. Set `last_diff` to it. (Next real acquire computes the true diff via Task 5.)
- **`handle_clear_ref`** is idempotent: set all eight reference/diff fields to defaults in one `state.update(...)`. Succeeds even when nothing was loaded.
- **Response schemas** (`schemas/reference.py`): keep them small. `PromoteRefResponse(loaded: bool, name: str, source: ReferenceSource, n_aligned: int, n_unaligned: int, x_rms_mm: float, y_rms_mm: float)`. `ClearRefResponse(loaded: bool = False)`. Re-export `ReferenceSource` from `pytxt.domain.types`. Also add the pydantic `ReferenceStatus` + `DiffSummary` models here for Task 6's `/state` extension (per spec §5.3).

- [ ] **Step 1: Write `pytxt/api/schemas/reference.py`** (per spec §5.3, trimmed to M2 needs)

```python
from datetime import datetime
from pydantic import BaseModel, Field
from pytxt.domain.types import ReferenceSource  # re-use the domain enum

class ReferenceStatus(BaseModel):
    loaded: bool
    name: str
    loaded_at: datetime | None
    source: ReferenceSource
    n_aligned: int
    n_unaligned: int

class DiffSummary(BaseModel):
    x_rms_mm: float
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_valid: int

class PromoteRefResponse(BaseModel):
    loaded: bool
    name: str
    source: ReferenceSource
    n_aligned: int
    n_unaligned: int
    summary: DiffSummary

class ClearRefResponse(BaseModel):
    loaded: bool = False
```

- [ ] **Step 2: Write `pytxt/handlers/reference.py`** (promote + clear only)

```python
"""Reference command handlers — the canonical functions both the CA
putters and the REST routes call. Parity by construction.

M2 covers the file-free pair (PROMOTE/CLEAR). LOAD/SAVE land in M3.
"""
from __future__ import annotations
from datetime import datetime, timezone

from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.reference import compute_diff, summarize_diff
from pytxt.domain.types import DiffResult, ReferenceSource
from pytxt.state.app_state import AppState
from pytxt.api.schemas.reference import (
    ClearRefResponse, DiffSummary, PromoteRefResponse,
)


class NoLastAcquireError(Exception):
    """Promote/save attempted with no successful acquisition to source from."""


def _current_first_turn(state: AppState):
    """Re-derive the live first-turn arrays aligned to current prefixes,
    mirroring server.py:_publish_last_acquire."""
    aligned = {p: state.last_acquire_raws.get(p) for p in state.bpm_prefixes}
    return extract_first_turn(aligned)


async def handle_promote_ref(state: AppState) -> PromoteRefResponse:
    if state.last_acquire.ok_count == 0:        # confirm field name
        raise NoLastAcquireError("No successful acquisition to promote.")

    first_turn = _current_first_turn(state)
    dx, dy = compute_diff(first_turn, first_turn)   # self-diff → zeros
    summary = summarize_diff(dx, dy)
    diff = DiffResult(dx=dx, dy=dy, summary=summary)
    now = datetime.now(timezone.utc)

    await state.update(
        reference_loaded=True,
        reference_name="<promoted>",
        reference_loaded_at=now,
        reference_source=ReferenceSource.PROMOTED,
        reference_first_turn=first_turn,
        reference_file_path=None,
        reference_bpm_names=list(state.bpm_prefixes),
        last_diff=diff,
    )
    return PromoteRefResponse(
        loaded=True, name="<promoted>", source=ReferenceSource.PROMOTED,
        n_aligned=summary.n_valid, n_unaligned=len(state.bpm_prefixes) - summary.n_valid,
        summary=DiffSummary(**summary.__dict__),
    )


async def handle_clear_ref(state: AppState) -> ClearRefResponse:
    await state.update(
        reference_loaded=False,
        reference_name="",
        reference_loaded_at=None,
        reference_source=ReferenceSource.NONE,
        reference_first_turn=None,
        reference_file_path=None,
        reference_bpm_names=None,
        last_diff=None,
    )
    return ClearRefResponse(loaded=False)
```

Note: `DiffSummary(**summary.__dict__)` converts the domain dataclass → pydantic model; if field names ever diverge, map explicitly. Verify `summarize_diff`'s `n_valid` is the right value for `n_aligned` (BPMs non-NaN on both sides).

- [ ] **Step 3: Write `tests/unit/test_handlers_reference.py`**

Cover: promote with a synthetic `AppState` carrying `bpm_prefixes` + `last_acquire_raws` (use the phase-2 `RawBPM` synth helper / SyntheticBpmReader output) → asserts `reference_loaded`, `reference_source == PROMOTED`, `reference_file_path is None`, `last_diff.dx` all-zero (modulo NaN), response `n_aligned`/summary; promote with empty `last_acquire_raws` raises `NoLastAcquireError`; clear from loaded → all defaults + `last_diff is None`; clear from already-clear → idempotent success. These are async tests (`pytest.mark.asyncio`) driving the handler against a real `AppState`.

- [ ] **Step 4: Run + commit**

```
.venv/bin/pytest tests/unit/test_handlers_reference.py tests/unit/test_schemas.py -v
```

Commit: `feat(handlers): M2 Task 2 — promote/clear reference handlers + pydantic schemas`

---

## Task 3: IOC PVs + putters

**Files:**
- Modify: `pytxt/ioc/pvs.py` (6 new PVs + 2 putters)
- Create: `tests/unit/test_cmd_reference_putters.py`

**Notes:**
- **State PVs** (read-only, published by listeners in Task 4):
  - `STATE:REF_LOADED` — `value=0, dtype=int`
  - `STATE:REF_NAME` — `value="", dtype=ca.ChannelType.STRING`
  - `STATE:REF_LOADED_AT` — `value="", dtype=ca.ChannelType.STRING` (ISO-8601 or "")
  - `STATE:REF_SOURCE` — `value="", dtype=ca.ChannelType.STRING`
- **Diff result PVs** (read-only, waveform, mirror the existing first-turn arrays):
  - `RESULT:BPM:X_DIFF_FIRST_TURN` — `value=[0.0]*_BPM_MAX, dtype=float, max_length=_BPM_MAX`
  - `RESULT:BPM:Y_DIFF_FIRST_TURN` — same. Doc: "Per-BPM B−R0 (mm); NaN where either side NaN or no ref loaded."
- **Command PVs + putters** (mirror `cmd_acquire`, but they do **not** require a reader — they act on `self._state`):
  - `CMD:PROMOTE_REF` — `value=0, dtype=int`; putter calls `await handle_promote_ref(self._state)`; re-raises `NoLastAcquireError` so caproto surfaces a CA alarm; returns `value`.
  - `CMD:CLEAR_REF` — `value=0, dtype=int`; putter calls `await handle_clear_ref(self._state)`; returns `value`.
- Import the handlers at module top: `from pytxt.handlers.reference import handle_promote_ref, handle_clear_ref, NoLastAcquireError`. Watch for import cycles (`handlers/reference.py` imports `AppState` from `state/app_state.py`; `pvs.py` already imports `AppState` and `handle_acquire` — same shape, no new cycle).

- [ ] **Step 1: Add the 6 pvproperties + 2 putters** to `PyTxTPVGroup`, grouped with the existing `STATE:*` / `RESULT:BPM:*` / `CMD:*` records respectively.

- [ ] **Step 2: Write `tests/unit/test_cmd_reference_putters.py`**

Mirror `tests/unit/test_cmd_acquire_putter.py`: instantiate the PVGroup with a stub `AppState` (no caproto Context needed — call the putter coroutine directly with a dummy `instance`), assert `CMD:PROMOTE_REF` putter invokes the handler and that a no-acquire state surfaces `NoLastAcquireError`; assert `CMD:CLEAR_REF` putter clears. (The existing acquire-putter unit test shows how to call a putter without a running IOC.)

- [ ] **Step 3: Run + commit**

```
.venv/bin/pytest tests/unit/test_cmd_reference_putters.py tests/integration/test_ioc_lifecycle.py -v
```

Commit: `feat(ioc): M2 Task 3 — REF_* state PVs, diff waveform PVs, PROMOTE/CLEAR putters`

---

## Task 4: IOC publisher — status bundle + diff arrays

**Files:**
- Modify: `pytxt/ioc/server.py` (`_bind_state_changes` + new publish methods + startup defaults)

**Notes:**
- **Two listeners, two triggers** (this is the load-bearing design choice — log it):
  - Subscribe `reference_loaded` → `_publish_reference_status()`: reads `self.state.reference_*` and writes `STATE:REF_LOADED` (bool→int), `STATE:REF_NAME`, `STATE:REF_LOADED_AT` (ISO-8601 or ""), `STATE:REF_SOURCE` (the enum's `.value`). This fires on promote (`False→True`) and clear (`True→False`).
  - Subscribe `last_diff` → `_publish_diff_arrays()`: writes `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`. If `last_diff is None`, write NaN-filled arrays (`_pad_numeric_array` with `np.nan`); else pad `last_diff.dx`/`.dy` to `_BPM_MAX`.
- **Why `last_diff` drives the diff arrays (not `reference_loaded`):** on a normal acquire while a ref stays loaded, `reference_loaded` doesn't change (no fire) but `last_diff` does → the diff arrays refresh every acquire, in lockstep with the first-turn arrays. On clear, `last_diff → None` fires → NaN-fill. Exactly the spec §7.5 semantic.
- **Known cosmetic edge (log it):** a re-promote while already loaded leaves `reference_loaded` True→True (status listener won't fire), so `STATE:REF_LOADED_AT` won't refresh. Acceptable for M2 — name/source are unchanged under re-promote; only the timestamp is stale until the next clear/promote cycle. If it matters later, switch the status trigger to `reference_loaded_at`.
- Reuse the existing retry/backoff write wrapper and the pad helpers. Match `_publish_last_acquire`'s single try/except-wraps-all-writes style.
- **Startup defaults:** in the startup hook, push initial `STATE:REF_LOADED=0`, `REF_NAME=""`, `REF_LOADED_AT=""`, `REF_SOURCE=""`, and NaN-filled diff arrays, so the PVs read sane values before the first promote.

- [ ] **Step 1: Add `_publish_reference_status` + `_publish_diff_arrays`; subscribe both; add startup defaults.**

- [ ] **Step 2: Run + commit**

```
.venv/bin/pytest tests/integration/test_ioc_lifecycle.py tests/integration/test_state_endpoint.py -v
```

Commit: `feat(ioc): M2 Task 4 — publish REF_* status + diff arrays on state changes`

---

## Task 5: `handle_acquire` diff extension

**Files:**
- Modify: `pytxt/handlers/acquire.py`
- Modify: `tests/unit/test_handlers_acquire.py`

**Notes:**
- Insert between `extract_first_turn` and the final `state.update`, per spec §6.4/§7.5:

```python
from pytxt.domain.reference import compute_diff, summarize_diff
from pytxt.domain.types import DiffResult

    diff = None
    if state.reference_loaded and state.reference_first_turn is not None:
        dx, dy = compute_diff(first_turn, state.reference_first_turn)
        diff = DiffResult(dx=dx, dy=dy, summary=summarize_diff(dx, dy))

    await state.update(
        last_acquire=last,
        last_acquire_raws=successful_raws,
        last_diff=diff,            # None when no ref → IOC NaN-fills
    )
```

- `first_turn` here and `reference_first_turn` are both aligned to `bpm_prefixes` (same length) → `compute_diff` is shape-safe. If a mismatch somehow occurs, the spec §8 says: still publish first-turn, set `last_diff=None`, and surface the message in `STATE:LAST_ACQUIRE_FAIL_REASON`. Implement defensively: wrap the diff block in try/except, on exception set `diff=None` (the first-turn publication must never be lost to a diff bug).
- **Do not** recompute or alter the first-turn publication path; `last_diff` is purely additive to the existing atomic update.

- [ ] **Step 1: Add the diff block (with the defensive guard).**

- [ ] **Step 2: Extend `tests/unit/test_handlers_acquire.py`**

Add: acquire with no ref loaded → `state.last_diff is None`; acquire after a promote (ref loaded) → `state.last_diff is not None`, `dx`/`dy` shaped `(len(bpm_prefixes),)`. Reuse the existing synthetic-reader handler test harness.

- [ ] **Step 3: Run + commit**

```
.venv/bin/pytest tests/unit/test_handlers_acquire.py -v
```

Commit: `feat(handlers): M2 Task 5 — handle_acquire computes & publishes last_diff when a ref is loaded`

---

## Task 6: REST routes + `/state` snapshot extension

**Files:**
- Modify: `pytxt/api/routes/cmd.py` (2 routes)
- Modify: `pytxt/api/schemas/state.py` + `pytxt/api/routes/state.py` (reference block)

**Notes:**
- **Routes** (mirror `post_acquire`; promote/clear take only `state`, no reader):

```python
from pytxt.handlers.reference import handle_promote_ref, handle_clear_ref, NoLastAcquireError
from pytxt.api.schemas.reference import PromoteRefResponse, ClearRefResponse

@router.post("/promote_ref", response_model=PromoteRefResponse)
async def post_promote_ref(request: Request) -> PromoteRefResponse:
    state = request.app.state.app_state
    try:
        return await handle_promote_ref(state)
    except NoLastAcquireError as e:
        raise HTTPException(422, str(e))

@router.post("/clear_ref", response_model=ClearRefResponse)
async def post_clear_ref(request: Request) -> ClearRefResponse:
    return await handle_clear_ref(request.app.state.app_state)
```

Use underscore paths (`/promote_ref`, `/clear_ref`) to match spec §5.2 exactly. (Phase-2 used `/acquire`; the spec's table lists `promote_ref`/`clear_ref`.)
- **`/state` extension** (spec §5.2: "Extended `/state` snapshot includes all new `STATE:REF_*` fields and a `last_diff` summary (or `null`)"). Add to `StateSnapshot`:

```python
reference: ReferenceStatus | None = None     # null when nothing loaded
last_diff: DiffSummary | None = None         # null when no diff
```

Populate in `routes/state.py` from `AppState`: build `ReferenceStatus` when `state.reference_loaded`, else `None`; build `DiffSummary` from `state.last_diff.summary` when present. `n_aligned/n_unaligned` come from `last_diff.summary.n_valid` and `len(bpm_prefixes) - n_valid` (or store counts on promote/load — for M2, derive from the summary).
- Update `tests/unit/test_schemas.py` / `test_state_endpoint.py` for the new optional fields (default `None` keeps phase-2 assertions green).

- [ ] **Step 1: Add the two routes.**
- [ ] **Step 2: Extend the `/state` snapshot schema + route.**
- [ ] **Step 3: Run + commit**

```
.venv/bin/pytest tests/integration/test_state_endpoint.py tests/unit/test_schemas.py tests/integration/test_acquire_via_rest.py -v
```

Commit: `feat(api): M2 Task 6 — /cmd/promote_ref + /cmd/clear_ref routes; reference block in /state`

---

## Task 7: Integration + parity tests

**Files:**
- Create: `tests/integration/test_reference_promote_clear.py`
- Modify: `tests/integration/test_parity.py` (+2 rows)

**Notes:**
- **`test_reference_promote_clear.py`** (per spec §10.3, M2 subset) — use the phase-2 composition/IOC + REST integration fixtures with a `SyntheticBpmReader`:
  - `test_promote_ref_via_ca`: acquire → `caput CMD:PROMOTE_REF 1` → assert `STATE:REF_LOADED==1`, `STATE:REF_SOURCE=="promoted"`, `STATE:REF_NAME=="<promoted>"`; a second acquire → assert `RESULT:BPM:X_DIFF_FIRST_TURN` is finite (zeros for unchanged synthetic data) for aligned indices.
  - `test_promote_ref_via_rest`: same via `POST /cmd/promote_ref` + `GET /state` (assert `reference.source == "promoted"`, `last_diff` present).
  - `test_promote_ref_no_acquire`: promote on a fresh state → CA alarm / REST 422.
  - `test_clear_ref`: promote → `CMD:CLEAR_REF` → assert `STATE:REF_LOADED==0` and `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN` are NaN-filled (check `np.isnan` on the first N entries). Assert idempotent: a second clear still 200/no-alarm.
- **Parity rows** — `PROMOTE_REF` needs a prior acquire; `CLEAR_REF` is standalone. Extend the parametrize table and add a per-row optional pre-step so the harness acquires before promote on **both** paths (keeping the comparison honest):

```python
# columns: command_name, ca_pv_suffix, rest_path, requires_acquire
("promote_ref", "CMD:PROMOTE_REF", "/api/v1/cmd/promote_ref", True),
("clear_ref",   "CMD:CLEAR_REF",   "/api/v1/cmd/clear_ref",   False),
```

In both the CA and REST arms, if `requires_acquire`, trigger an acquire first, then the command. Extend `_public_state(state)` to project the new fields: `reference_loaded`, `reference_source` (`.value`), `reference_name`, `reference_loaded_at` → `"<set>"|None`, and `last_diff` → a stable shape (e.g. `None` or `{"n_valid": last_diff.summary.n_valid}` — avoid raw arrays which differ by identity). Assert CA-diff == REST-diff as before.
- **Flaky-test caution:** the M1 closeout flagged `tests/integration/test_acquire_partial_fail.py::test_partial_fail_state_pvs_published` as a known CA-loopback flake. If it fails during a full run, re-run it once in isolation before treating it as a regression — it is unrelated to M2.

- [ ] **Step 1: Write `test_reference_promote_clear.py`.**
- [ ] **Step 2: Extend `test_parity.py` (table + pre-acquire + projection).**
- [ ] **Step 3: Run the reference + parity integration tests, then the full suite.**

```
.venv/bin/pytest tests/integration/test_reference_promote_clear.py tests/integration/test_parity.py -v
.venv/bin/pytest -q
```

Expected: all green except possibly the one known CA flake (re-run in isolation to confirm). Report actual counts.

- [ ] **Step 4: Commit**

Commit: `test(integration): M2 Task 7 — promote/clear pipeline + parity rows (PROMOTE, CLEAR)`

---

## Task 8: Closeout — decision log + roadmap + final verification

**Files:**
- Modify: `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md`
- Modify: `PyTxT-roadmap.html`

**Notes — decision-log entries to append (dated 2026-05-29 or actual date), matching the file's template:**
1. **M2 is backend-only; frontend deferred to M4.** (Deviation from spec §11 M2 prose; DoD bullets unaffected.)
2. **`ReferenceSource` + `DiffResult` in `domain/types.py`, not `api/schemas`** — avoids a `state → api` layering inversion; pydantic re-uses the domain enum.
3. **Two publish triggers** — `reference_loaded` drives the `STATE:REF_*` status bundle; `last_diff` drives the diff arrays — so diff PVs refresh every acquire while status only republishes on load/clear. Includes the re-promote `REF_LOADED_AT` cosmetic-staleness note.
4. **Promote recomputes the live first-turn** from `last_acquire_raws + bpm_prefixes` (option A) rather than adding a `last_first_turn` AppState field — mirrors `server.py:_publish_last_acquire`.
5. Any surprises (exact `LastAcquireResult` field used for the no-acquire guard; whether the numpy-tolerant `update()` needed touching for `DiffResult`).

**Roadmap update (`PyTxT-roadmap.html`):**
- Hero: `M1 ✓ · M2 · M3 · M4` → `M1 ✓ · M2 ✓ · M3 · M4`; progress 25% → 50%; refresh the narrative to "M2 (in-memory ops + diff publication) landed" and point "next" at M3.
- Phase 3 milestone tracker: flip the M2 card to `ms done` / `✓ Done`; flip M3 to `ms now` / `Next`.
- Phase 3 `<details>` badge: `🔨 In progress · M1 ✓` → `🔨 In progress · M2 ✓`.
- Stats: update "Tests passing" to the new count; update "Unpushed commits".
- Recent activity: prepend an `M2 ✓` milestone entry + the M2 commits.
- "Last updated" date.

- [ ] **Step 1: Append decision-log entries.**
- [ ] **Step 2: Update the roadmap (verify CSS classes `ms done/now/todo`, `phase now`, `badge-now` exist; check `<details>` open/close balance after editing).**
- [ ] **Step 3: Final verification.**

```
.venv/bin/pytest -q
.venv/bin/python -c "from pytxt.handlers.reference import handle_promote_ref, handle_clear_ref, NoLastAcquireError; from pytxt.domain.types import ReferenceSource, DiffResult; print('M2 surface ok')"
git log --oneline -10
git status
```

Expected: full suite green (modulo the known CA flake); import smoke passes; ~7–8 M2 commits on `main`.

- [ ] **Step 4: Commit**

Commit: `docs(roadmap+decisions): M2 closeout — promote/clear + diff publication shipped`

---

## Notes for the implementer

- **Parity is the contract** (CLAUDE.md §1): every CMD must have identical effect via CA and REST. Both call the same `handle_promote_ref`/`handle_clear_ref`. The parity test enforces it — don't let the two paths diverge (e.g. don't put validation in the route that isn't in the putter).
- **Observability** (CLAUDE.md §1, §2): every command has a confirming state PV. Promote → `STATE:REF_LOADED=1`; clear → `=0`. An agent verifies the outcome by reading the PV, not by trusting the 200.
- **Domain stays I/O-free** (CLAUDE.md §5): no new logic in `domain/reference.py` this milestone — M2 only *calls* the M1 functions from the adapter layer.
- **Subagent command shape:** use `.venv/bin/pytest`, not `source .venv/bin/activate && pytest`.
- **Test-IOC isolation:** integration tests must keep using the `OSPREY:TEST:TXT:*` prefix + ports 59064/59065 per the existing fixtures — do not point at production `TxT:*`.
- **Known flake:** `test_acquire_partial_fail.py::test_partial_fail_state_pvs_published` intermittently fails on CA loopback; re-run in isolation before treating as a regression.
- **No silent scope creep into M3/M4:** if you find yourself adding `reference_dir`, a path-safety helper, `routes/references.py`, `CMD:LOAD_REF`/`SAVE_REF`, `/result/ref/raw`, or any `pytxt/frontend/` change — stop; that's M3/M4. Re-read the Scope decisions above.
