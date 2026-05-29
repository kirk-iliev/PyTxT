# PyTxT Phase 3 — Reference Trajectory (.mat I/O, ΔX/ΔY Diff, Reference Library)

**Status:** Design (drafted via brainstorming; awaiting Kirk's review)
**Date:** 2026-05-29
**Scope:** Phase 3 of 6 (per `PyTxT-project-plan.html`)
**Owner:** Kirk
**Drafted with:** Claude (Opus 4.7, 1M context)
**Builds on:** [Phase 2 spec](2026-05-18-phase-2-read-path-design.md)

---

## 1. Purpose

Phase 3 delivers the **compare** half of the operator workflow. Given a known-good "reference" trajectory `R0` taken on a prior good injection, every subsequent acquire publishes not just the live first-turn `B` but the per-BPM deviation `B − R0` as `ΔX/ΔY` PVs and a 4-panel browser plot. The operator (or agent) gains three new operations: **load** a reference from a server-side library, **save** the current trajectory as a new reference, and **promote** the current trajectory to in-memory reference without writing a file.

Phase 3 is the first phase whose primary artifact is a **file** rather than a PV waveform — reference `.mat` files live on disk in a server-side library directory. The library is browsable, downloadable, and (via REST multipart) uploadable; loading a chosen reference by name has full CA parity. Reference files are MATLAB-GUI-compatible by design: PyTxT-saved references can be loaded by the legacy `TxT_GUI.mlapp` (and vice versa), so operators can migrate references across the two tools during the transition.

Phase 3 does **not** introduce trajectory correction (response-matrix inverse → corrector-magnet steps). That is phase 4. Phase 3 only computes and publishes the deviation; what to do about it remains an operator decision.

---

## 2. North-star principles binding this design

The five north-star principles from `CLAUDE.md` and the [phase-2 spec §2](2026-05-18-phase-2-read-path-design.md#2-north-star-principles-binding-this-design) continue to apply. Phase 3's concrete obligations:

- **Agent-callable first** — All four reference operations (LOAD, SAVE, PROMOTE, CLEAR) exist as both CA PVs and REST endpoints, routed through one canonical handler per op. The keystone parity test grows by four parametrize rows.
- **PVs are the canonical state interface** — Reference status (`STATE:REF_LOADED`, `STATE:REF_NAME`, `STATE:REF_SOURCE`, `STATE:REF_LOADED_AT`) and difference results (`RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`) are published as PVs. The reference *file content* (.mat blobs) lives on disk per principle #3 — file bytes are not a PV concern.
- **REST/WS handles only what PVs can't** — Bulk file transfer (upload, download) and library listing use REST. Loading a reference by name remains a string-PV write so CA-only agents are first-class. The honest gap: there is no CA-only path to *upload a brand-new file* into the library (a file's bytes cannot be a PV). Loading by name from the existing library always works. This asymmetry is the fundamental "file content > PV" tradeoff and is logged in §15.
- **Forward-looking package layout** — Every phase-3 file lands in a package that already exists from phase 2. The composition root grows by ~2 lines.
- **Domain logic is I/O-free** — `pytxt/domain/reference.py` is a pure numpy + scipy.io module: no caproto, no FastAPI, no asyncio. The file-I/O surface (`load_reference_mat`, `save_reference_mat`) is local filesystem I/O only, not network I/O — adapters above the domain layer translate file paths to and from settings/CMD strings.

---

## 3. Architectural recap — where phase 3 lands on the phase-2 foundation

```
                          ┌────────────────────────────────────────┐
                          │ Reference library (on appsdev2 disk)   │
                          │ ${PYTXT_REFERENCE_DIR}/                │
                          │   2025-03-23_12:43:16_…trajectory.mat  │
                          │   2026-05-29_09:15:00_…trajectory.mat  │
                          │   …                                    │
                          └──────────────┬─────────────────────────┘
                                         │ scipy.io.{loadmat,savemat}
                                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  AppState (single source of truth)                      │
│                                                                         │
│  …phase 1 & 2 fields unchanged…                                         │
│  reference_loaded: bool                  ← NEW                          │
│  reference_name: str                     ← NEW (basename or "")         │
│  reference_loaded_at: datetime | None    ← NEW                          │
│  reference_source: ReferenceSource       ← NEW ("file"|"promoted"|"")   │
│  reference_first_turn: FirstTurnResult|None  ← NEW (tiny: 2×128 mm)     │
│  reference_file_path: Path | None        ← NEW (None when promoted)     │
│  reference_bpm_names: list[str] | None   ← NEW (for soft-merge audit)   │
│  last_diff: DiffResult | None            ← NEW (B − R0, tiny)           │
└─────────▲──────────────────────────────────────────┬────────────────────┘
          │                                          │
          │ mutate via handlers                      │ mirror via IOC publisher
          │                                          ▼
   ┌──────┴──────────┐                  ┌────────────────────────────────┐
   │ handlers/       │                  │ External surface (new)         │
   │  acquire ← ext  │                  │  - CMD:LOAD_REF (string)       │
   │  reference ← NEW│                  │  - CMD:SAVE_REF (string)       │
   │   .load_ref     │                  │  - CMD:PROMOTE_REF (int)       │
   │   .save_ref     │                  │  - CMD:CLEAR_REF (int)         │
   │   .promote_ref  │                  │  - POST /api/v1/cmd/{4 mirrors}│
   │   .clear_ref    │                  │  - STATE:REF_*  PVs            │
   └─────────────────┘                  │  - RESULT:BPM:{X,Y}_DIFF_*     │
                                        │  - GET  /api/v1/references     │
                                        │  - POST /api/v1/references     │
                                        │       (multipart upload)       │
                                        │  - GET  /api/v1/references/{n} │
                                        │       (download)               │
                                        │  - GET  /api/v1/result/ref/raw │
                                        │       ?bpm=<prefix>            │
                                        └────────────────────────────────┘
```

**Invariants preserved from phases 1 and 2:**

1. Every CMD is one Python function called by both the IOC dispatcher and the REST route. No transport-specific code paths exist.
2. AppState is the single source of in-process truth; the IOC publisher mirrors changes outward to PVs. Handlers never write to PVs directly.
3. The PV namespace (`OSPREY:TEST:TXT:*` dev, `TxT:*` prod) is config-driven; no hardcoding.
4. The domain layer has no I/O dependency on caproto, FastAPI, or asyncio. (Phase 3 adds local filesystem I/O via scipy.io but no network.)
5. ACQUIRE handler enforces atomic `AppState.update`; readers (incl. `/result/bpm/raw`) never see half-written data. The new diff computation extends this — the diff is published in the same atomic update as the first-turn arrays.

---

## 4. Package additions

```
pytxt/
├── domain/
│   └── reference.py            ← NEW: load/save/align/diff, scipy.io.{loadmat,savemat}
├── handlers/
│   └── reference.py            ← NEW: load_ref, save_ref, promote_ref, clear_ref handlers
├── api/
│   ├── routes/
│   │   └── references.py       ← NEW: GET list / POST upload / GET download (multipart)
│   └── schemas/
│       └── reference.py        ← NEW: pydantic models for ref ops + diff
└── (no new top-level packages)
```

Extended (no structural change):
- `pytxt/state/app_state.py` — 7 new fields.
- `pytxt/handlers/acquire.py` — compute diff after first-turn extraction when a ref is loaded.
- `pytxt/ioc/pvs.py` and `pytxt/ioc/server.py` — new PVs and their `AppState`-field bindings.
- `pytxt/api/routes/cmd.py` — 4 new POST routes (mirroring the 4 CMD PVs).
- `pytxt/api/routes/result.py` — `/result/ref/raw` endpoint for reference waveform drill-down.
- `pytxt/config/settings.py` — one new env var `PYTXT_REFERENCE_DIR`.
- `pytxt/composition.py` — pass `reference_dir` into the handlers' partial-application bindings.
- `pytxt/frontend/` — 4-panel layout, reference sidebar, picker/save dialogs.
- `pyproject.toml` — add `scipy>=1.11,<2.0` to runtime dependencies.

---

## 5. Phase 3 feature surface

### 5.1 New PVs published by the IOC

| PV (after prefix) | Type | RW | Purpose |
|---|---|---|---|
| `STATE:REF_LOADED` | int (0/1) | R | Whether a reference is currently loaded |
| `STATE:REF_NAME` | string | R | Basename of the loaded reference file, or `""` if none / `"<promoted>"` if promoted from current |
| `STATE:REF_LOADED_AT` | string | R | ISO-8601 UTC when the reference was loaded/promoted, or `""` |
| `STATE:REF_SOURCE` | string | R | `"file"`, `"promoted"`, or `""` |
| `RESULT:BPM:X_DIFF_FIRST_TURN` | float[128] | R | Per-BPM `B − R0` for X (mm); NaN at indices where either side is NaN or no ref is loaded |
| `RESULT:BPM:Y_DIFF_FIRST_TURN` | float[128] | R | Per-BPM `B − R0` for Y (mm); same semantics |
| `CMD:LOAD_REF` | string | W | Write a reference filename (basename only) to load it from the library |
| `CMD:SAVE_REF` | string | W | Write a target filename (basename only) to save current `last_acquire_raws` as a reference |
| `CMD:PROMOTE_REF` | int | W | Write any value → promote current `last_acquire` to in-memory R0 (no file written) |
| `CMD:CLEAR_REF` | int | W | Write any value → unload current reference, NaN-fill diff PVs |

Waveform arrays reuse the phase-2 `max_length=128` (`_BPM_MAX`). Only the first N entries (where N = number of configured BPMs, currently 107) are meaningful.

### 5.2 New / extended REST endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/cmd/load_ref` | REST mirror of `CMD:LOAD_REF`; body `{"name": "<basename>"}`; 200/404/422 |
| `POST` | `/api/v1/cmd/save_ref` | REST mirror of `CMD:SAVE_REF`; body `{"name": "<basename>"}` (or omit for timestamp default); 200/409/422 |
| `POST` | `/api/v1/cmd/promote_ref` | REST mirror of `CMD:PROMOTE_REF`; empty body; 200/409 |
| `POST` | `/api/v1/cmd/clear_ref` | REST mirror of `CMD:CLEAR_REF`; empty body; 200 |
| `GET` | `/api/v1/references` | List the reference library — array of `{name, size_bytes, modified_at}` |
| `POST` | `/api/v1/references` | Multipart `.mat` file upload into the library; 201/409 (name collision)/422 (bad .mat) |
| `GET` | `/api/v1/references/{name}` | Download a reference file; `Content-Type: application/octet-stream`; 200/404 |
| `GET` | `/api/v1/result/ref/raw?bpm=<prefix>` | Reference's full TBT waveforms for one BPM (when loaded ref has waveforms); 200/404/409-never |

Extended `/api/v1/state` snapshot includes all new `STATE:REF_*` fields and a `last_diff` summary (or `null` if no ref).

### 5.3 Pydantic schemas (sketches)

```python
# pytxt/api/schemas/reference.py

class ReferenceSource(str, Enum):
    NONE = ""
    FILE = "file"
    PROMOTED = "promoted"

class LoadRefRequest(BaseModel):
    name: str = Field(min_length=1, description="Reference filename (basename only).")

class SaveRefRequest(BaseModel):
    name: str | None = Field(
        default=None,
        description="Reference filename (basename only). If omitted, a timestamp default is generated.",
    )

class ReferenceLibraryEntry(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime

class ReferenceLibraryList(BaseModel):
    references: list[ReferenceLibraryEntry]

class ReferenceStatus(BaseModel):
    loaded: bool
    name: str
    loaded_at: datetime | None
    source: ReferenceSource
    n_aligned: int        # how many BPMs matched on the last load/promote
    n_unaligned: int      # current_prefixes − ref_names; populated with NaN in diff

class DiffSummary(BaseModel):
    """Cheap summary that fits in /api/v1/state without dumping 128 floats."""
    x_rms_mm: float        # ignoring NaN
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_valid: int           # BPMs contributing to RMS (non-NaN on both sides)
```

The full `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN` arrays remain PV-only; REST callers wanting per-BPM diff numbers subscribe via the WS bridge.

### 5.4 Browser page additions

Trajectory page extends in two ways when `STATE:REF_LOADED=1`:

- **Layout switch**: from 2-panel (X, Y) to **4-panel** (X, Y, ΔX, ΔY). Switch is driven by the `REF_LOADED` PV subscription. Panels share the BPM-index x-axis; ΔX/ΔY panels auto-range to ±max(|diff|).
- **Reference sidebar** (compact, on the right of the canvas row):
  - Displays current `REF_NAME` + `REF_SOURCE` ("file" / "promoted") + `REF_LOADED_AT` (HH:MM:SS local), or "No reference loaded".
  - `[Promote current]` button — POST `/cmd/promote_ref`; disabled when no `last_acquire`.
  - `[Load…]` button — opens picker dialog; fetches `GET /references`, lists names with modified_at, click to POST `/cmd/load_ref`.
  - `[Save current…]` button — opens save dialog with name input prefilled to the MATLAB timestamp default; POST `/cmd/save_ref`.
  - `[Upload .mat]` button — file input → POST `/references` (multipart). On success, refreshes picker list.
  - `[Clear]` button — POST `/cmd/clear_ref`.
- **Status header** gains one row: when ref is loaded, show `Δ rms: X=<x_rms_mm> · Y=<y_rms_mm> mm` (from `last_diff` in the state snapshot, recomputed each acquire).
- **Hover tooltip** (existing) extends: when a ref is loaded, the tooltip line gains `ΔX=<dx> ΔY=<dy>` for that BPM.

The page subscribes via WS to the existing phase-2 PVs plus the new `STATE:REF_*` and `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`.

---

## 6. Component design

### 6.1 `pytxt/domain/reference.py`

The pure-domain core. No caproto, no FastAPI, no asyncio — only `numpy`, `scipy.io`, and `pathlib`/`datetime` for filesystem path handling.

```python
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import scipy.io
from pytxt.domain.types import FirstTurnResult, RawBPM
from pytxt.domain.first_turn_extract import extract_first_turn

# MATLAB BPM naming convention: 'SR01C:BPM1:SA:X' — has a ':SA:X' or ':SA:Y' suffix
# tacked on per channel. Our pytxt prefix is just 'SR01C:BPM1'. Strip the trailing
# ':SA:X' / ':SA:Y' to canonicalize. Idempotent — names without the suffix pass through.
_MATLAB_BPM_SUFFIX_RE = re.compile(r":SA:[XY]$")

def canonicalize_bpm_name(name: str) -> str:
    return _MATLAB_BPM_SUFFIX_RE.sub("", name)


@dataclass(frozen=True)
class Reference:
    """In-memory representation of a loaded reference trajectory.

    `first_turn` is always populated (it's the diff math input).
    `raws` is populated only when the .mat included the PyTxT-extended
    waveform variables (X_wf/Y_wf/sum_wf). MATLAB-GUI-saved references
    omit these; for those refs `raws` is None and `/result/ref/raw`
    returns 404.

    `bpm_names` is the *canonicalized* (suffix-stripped) list from the
    .mat — preserved separately from `first_turn` for the soft-merge
    audit and for diagnostics.
    """
    first_turn: FirstTurnResult
    bpm_names: list[str]
    raws: dict[str, RawBPM] | None
    file_path: Path | None         # None when promoted (no file on disk)
    saved_at: datetime | None      # mtime, or None when promoted


def load_reference_mat(path: Path) -> Reference:
    """Read a reference .mat file and return a Reference.

    Reads at minimum:
        R0     : (2, n_bpms) float64, mm — row 0 = X, row 1 = Y
        BPMs   : MATLAB struct with at least a .Names cell array

    Optionally reads (PyTxT-extended schema; absent in MATLAB-GUI files):
        X_wf, Y_wf, sum_wf : (n_bpms, n_samples) int32, raw nm/AU
        injection_turn      : (n_bpms,) int32

    Raises ReferenceLoadError on missing required variables, shape
    mismatches, or scipy parse failure. Never raises on missing
    *optional* variables — `Reference.raws` is set to None in that case.
    """
    ...


def save_reference_mat(
    path: Path,
    first_turn: FirstTurnResult,
    last_acquire_raws: dict[str, RawBPM],
    bpm_prefixes: list[str],
) -> None:
    """Write a reference .mat that round-trips through MATLAB's
    load(file, 'R0', 'BPMs') AND carries PyTxT's full-waveform extras.

    The MATLAB-required variables:
        R0    : (2, n_bpms) float64, mm — built from first_turn.x/y, NaN→NaN
        BPMs  : struct with only the field the MATLAB GUI loader actually
                uses (Names) plus a stub ORDs/nBuffer for completeness.
                Other GUI-visible fields are written as empty arrays.

    The PyTxT-extended variables (ignored by MATLAB's load()):
        X_wf, Y_wf, sum_wf : (n_bpms, n_samples) int32
        injection_turn      : (n_bpms,) int32
        bpm_prefixes_canonical : (n_bpms,) cell of pytxt-form names
        saved_by               : string "pytxt v<version>"

    Failed BPMs in `last_acquire_raws` (entries stripped at acquire time)
    are written as NaN in R0 and as zero-filled int32 arrays in X_wf/Y_wf/
    sum_wf with `injection_turn=-1`, so the saved file always has a row
    for every configured BPM in `bpm_prefixes`.
    """
    ...


def align_to_current(
    ref: Reference,
    current_prefixes: list[str],
) -> tuple[FirstTurnResult, int, int]:
    """Soft-merge by BPM name. Returns (aligned, n_aligned, n_unaligned).

    For each i in current_prefixes:
      - if a matching canonical name exists in ref.bpm_names: copy R0
        values into position i
      - otherwise: leave x[i]/y[i] as NaN, injection_turn[i]=-1

    Matches MATLAB GUI behavior (`if strcmp(BPMs.Names{n}, app.SC.EXP.BPM.Names{i})`)
    closely. Non-matching slots in the current set get NaN so the diff
    visibly shows "undefined" for those BPMs.
    """
    ...


def compute_diff(
    live: FirstTurnResult,
    aligned_ref: FirstTurnResult,
) -> tuple[np.ndarray, np.ndarray]:
    """NaN-propagating B − R0. Returns (dx, dy) of shape (n_bpms,)."""
    return live.x_first_turn - aligned_ref.x_first_turn, \
           live.y_first_turn - aligned_ref.y_first_turn


def summarize_diff(dx: np.ndarray, dy: np.ndarray) -> DiffSummary:
    """RMS/max/n_valid — ignoring NaN; n_valid is BPMs non-NaN in BOTH."""
    ...


class ReferenceLoadError(ValueError):
    """Raised when a .mat file does not parse as a valid reference."""
```

Pure-numpy unit tests exercise every branch in milliseconds — including round-tripping a PyTxT-saved file back through `load_reference_mat`, and loading the real `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat` to confirm interop.

### 6.2 `pytxt/state/app_state.py` (extension)

```python
@dataclass
class AppState:
    # …existing phase 1 + 2 fields unchanged…

    # Phase 3 reference state — all-or-nothing: when reference_loaded=False,
    # every other reference_* field is at its empty default.
    reference_loaded: bool = False
    reference_name: str = ""
    reference_loaded_at: datetime | None = None
    reference_source: ReferenceSource = ReferenceSource.NONE
    reference_first_turn: FirstTurnResult | None = None
    reference_file_path: Path | None = None
    reference_bpm_names: list[str] | None = None

    # Latest computed diff — cleared when reference unloads OR a new acquire
    # supersedes it. When None, RESULT:BPM:*_DIFF_* are NaN-filled.
    last_diff: DiffResult | None = None
```

`DiffResult` is a tiny dataclass: `dx`, `dy` (numpy arrays), plus the summary. Listeners on these fields drive PV publication via the existing IOC publisher.

### 6.3 `pytxt/handlers/reference.py`

Four handlers, one per operation. Each is the canonical function called by both the IOC putter and the REST route — parity by construction.

```python
async def handle_load_ref(state: AppState, reference_dir: Path, name: str) -> LoadRefResponse:
    """Validate basename, resolve path inside reference_dir, parse via
    domain.load_reference_mat, align to current prefixes, atomic AppState
    update (reference_*, last_diff if there's a last_acquire to diff against).
    Raises ReferenceNotFoundError (→ 404/CA alarm) and ReferenceLoadError
    (→ 422/CA alarm)."""

async def handle_save_ref(state: AppState, reference_dir: Path, name: str | None) -> SaveRefResponse:
    """Validate basename (or generate timestamp default), refuse if file
    exists (→ 409), refuse if no last_acquire (→ 422). Calls
    domain.save_reference_mat synchronously inside a thread executor
    (scipy.io.savemat is blocking). Returns the saved path's basename
    and size_bytes."""

async def handle_promote_ref(state: AppState) -> PromoteRefResponse:
    """In-memory promotion: copy last_acquire's first-turn into
    reference_first_turn, set source=PROMOTED, name='<promoted>',
    file_path=None. Refuse if no last_acquire (→ 422). Recompute diff
    against the same last_acquire (which is now self-diff = zero — that's
    the correct semantic; an immediate post-promote acquire produces the
    real diff)."""

async def handle_clear_ref(state: AppState) -> ClearRefResponse:
    """Reset all reference_* fields to defaults and last_diff to None.
    Idempotent — succeeds even when nothing is loaded."""
```

All four enforce **path safety** via a single helper `_resolve_in_library(reference_dir, name)`: rejects empty names, names with path separators, names that don't end in `.mat`, and any resolved path not strictly inside `reference_dir` (defends against `../` traversal). Tested with a dedicated parametrized integration test.

### 6.4 `pytxt/handlers/acquire.py` (extension)

```python
async def handle_acquire(state, reader) -> AcquireResponse:
    # …existing flow unchanged up to the last AppState.update…

    # NEW: compute diff if a reference is loaded
    diff = None
    if state.reference_loaded:
        dx, dy = compute_diff(first_turn, state.reference_first_turn)
        diff = DiffResult(dx=dx, dy=dy, summary=summarize_diff(dx, dy))

    await state.update(
        last_acquire=last,
        last_acquire_raws=successful_raws,
        last_diff=diff,  # None when no ref → IOC publishes NaN arrays
    )
    # …rest unchanged…
```

The diff publication piggybacks on the same atomic `AppState.update` that publishes the first-turn arrays — readers never see one without the other.

### 6.5 `pytxt/ioc/pvs.py` (extension)

Add records for the new state and command PVs. Each carries a `.DESC` string (agent-readable). The four CMD PVs each have a putter that delegates to its handler and translates exceptions into CA alarms (matches the existing `CMD:ACQUIRE` pattern). String PVs use caproto `ChannelType.STRING`.

### 6.6 `pytxt/ioc/server.py` (field → PV map extension)

Extends the field→PV listener map to mirror the seven new state fields and the diff arrays. When `state.reference_loaded` flips, the publisher updates `STATE:REF_LOADED` + the four siblings atomically.

### 6.7 `pytxt/api/routes/cmd.py` (extension)

Four new POST routes — `load_ref`, `save_ref`, `promote_ref`, `clear_ref` — each ~10 lines: parse body via the request pydantic model, call the corresponding handler, translate `ReferenceNotFoundError` → 404, `ReferenceLoadError` → 422, file-exists → 409, return the response model.

### 6.8 `pytxt/api/routes/references.py` (new)

```python
@router.get("/references", response_model=ReferenceLibraryList)
async def list_references(request: Request) -> ReferenceLibraryList:
    """Return all .mat files in reference_dir, sorted by mtime desc."""

@router.post("/references", status_code=201, response_model=ReferenceLibraryEntry)
async def upload_reference(request: Request, file: UploadFile) -> ReferenceLibraryEntry:
    """Validate basename, refuse collisions (→ 409), write into reference_dir,
    parse-validate via load_reference_mat (→ 422 on bad .mat), return entry."""

@router.get("/references/{name}")
async def download_reference(request: Request, name: str) -> FileResponse:
    """Return the .mat file bytes (Content-Type: application/octet-stream)."""
```

All three reuse the same path-safety helper as the handlers. Upload size cap defaults to 200 MB (configurable; covers our ~144 MB worst case with headroom). Streaming is fine — scipy.io can read what we write to disk, and the post-write validation pass catches corrupt uploads cheaply.

### 6.9 `pytxt/api/routes/result.py` (extension)

Add one endpoint:

```python
@router.get("/result/ref/raw", response_model=BpmRawWaveforms)
async def get_ref_bpm_raw(request: Request, bpm: str = "") -> BpmRawWaveforms:
    """Reference's full TBT waveforms for one BPM.

    400: missing bpm
    404: no reference loaded; ref has no waveforms (MATLAB-saved file);
         bpm not in ref's BPM set.
    """
```

Reads the reference file *lazily* on demand (re-parses the .mat via `load_reference_mat` and pulls the requested BPM's row from `raws`). For PyTxT-saved refs only (those with the extended schema). MATLAB-saved refs return 404 with `detail="Reference has no full waveforms (loaded from MATLAB-only schema)"`.

### 6.10 `pytxt/api/schemas/*` (extension)

`reference.py` (new, §5.3 sketches) and small additions to `state.py` to include the reference status block in the `/state` snapshot.

### 6.11 `pytxt/frontend/` additions

- `js/reference.js` — module owning the sidebar state and dialogs; subscribes to `STATE:REF_*` over WS; issues the four CMD POSTs and the multipart upload.
- `js/trajectory.js` — extended: switch from 2-panel to 4-panel render when `REF_LOADED=1`; subscribe to the diff arrays; tooltip extension.
- `css/theme.css` — extended: 4-panel grid layout, sidebar styling.
- `trajectory.html` — extended: add the sidebar container; add hidden 4-panel grid that activates via CSS class when ref loaded.

### 6.12 `pytxt/config/settings.py` (extension)

```python
class Settings(BaseSettings):
    # …existing fields…

    # Phase 3
    reference_dir: Path = Path("data/references")  # dev default; prod sets via env
```

Add `reference_dir` to the `Settings._reject_unknown_pytxt_env_vars` known set automatically (model_validator already iterates `cls.model_fields`). Add a `@field_validator("reference_dir")` that ensures the path exists and is a writable directory at startup (creates it if missing? probably yes — `mkdir(parents=True, exist_ok=True)` to be dev-friendly).

### 6.13 `pytxt/composition.py` extension

```python
# Add to the bindings constructed in composition.main():
ref_dir = settings.reference_dir.resolve()
ref_dir.mkdir(parents=True, exist_ok=True)

# Handlers get reference_dir bound via functools.partial (mirror existing pattern)
load_ref_bound = partial(handle_load_ref, state, ref_dir)
save_ref_bound = partial(handle_save_ref, state, ref_dir)
# promote / clear take only `state`
```

The composition root grows by ~3–5 lines.

---

## 7. Data flow

### 7.1 LOAD_REF (file → in-memory ref → diff)

```
1. Trigger        CA write CMD:LOAD_REF=<name>   OR   POST /api/v1/cmd/load_ref {name}
                       │                                   │
                       └──────────┬────────────────────────┘
                                  ▼
2. handle_load_ref(state, reference_dir, name)
                   _resolve_in_library() → Path or raises (→ 422 / CA alarm)
                   path doesn't exist → ReferenceNotFoundError (→ 404)
3. domain.load_reference_mat(path)
                   scipy.io.loadmat → extract R0, BPMs.Names, optional extras
                   → Reference (raws=None if MATLAB-only schema)
                   bad schema → ReferenceLoadError (→ 422)
4. domain.align_to_current(ref, state.bpm_prefixes)
                   soft-merge by canonical name → aligned FirstTurnResult,
                   n_aligned, n_unaligned
5. diff = compute_diff(state.last_acquire (if any), aligned)   # else None
6. AppState.update(
       reference_loaded=True,
       reference_name=path.name,
       reference_loaded_at=now,
       reference_source=FILE,
       reference_first_turn=aligned,
       reference_file_path=path,
       reference_bpm_names=ref.bpm_names,
       last_diff=diff,
   )
      → IOC publishes STATE:REF_* + RESULT:BPM:{X,Y}_DIFF_*
      → browser receives via WS, swaps layout to 4-panel, renders ΔX/ΔY
7. Return LoadRefResponse (REST) / complete CA putter.
```

### 7.2 SAVE_REF (in-memory → file)

```
1. Trigger        CA write CMD:SAVE_REF=<name>   OR   POST /cmd/save_ref {name?}
2. handle_save_ref:
     no last_acquire → 422
     name=None → name=datetime.now().strftime("%Y-%m-%d_%H:%M:%S_reference_trajectory.mat")
     _resolve_in_library(name) → Path or 422
     path exists → 409 (refuse overwrite; agent must DELETE first or use a different name)
3. await asyncio.to_thread(domain.save_reference_mat,
                            path, state.last_acquire's first_turn,
                            state.last_acquire_raws, state.bpm_prefixes)
4. Return SaveRefResponse{name, size_bytes, saved_at}
```

State is NOT mutated by SAVE — saving does not auto-load the just-saved file. (Two reasons: it's surprising, and the operator may want to compare current vs current — which is what PROMOTE is for.) A subsequent `LOAD_REF` against the saved name is the explicit way to make it active.

### 7.3 PROMOTE_REF (in-memory copy)

```
1. Trigger        CA write CMD:PROMOTE_REF   OR   POST /cmd/promote_ref
2. handle_promote_ref:
     no last_acquire → 422
3. Build aligned reference directly from state.last_acquire's first_turn
   (no .mat I/O). reference_bpm_names = state.bpm_prefixes (current set,
   already canonical).
4. diff = compute_diff(last_acquire, aligned)   # self-diff: all zeros (or NaN where live was NaN)
5. AppState.update(
       reference_loaded=True,
       reference_name="<promoted>",
       reference_loaded_at=now,
       reference_source=PROMOTED,
       reference_first_turn=aligned,
       reference_file_path=None,         # ← no file backing
       reference_bpm_names=list(state.bpm_prefixes),
       last_diff=diff,                   # zeros initially; next acquire computes the real diff
   )
6. Return PromoteRefResponse.
```

### 7.4 CLEAR_REF

```
1. Trigger        CA write CMD:CLEAR_REF   OR   POST /cmd/clear_ref
2. handle_clear_ref:
     Idempotent — sets reference_loaded=False, all reference_* fields back to defaults,
     last_diff=None
3. AppState.update → IOC publishes STATE:REF_LOADED=0, REF_NAME="", REF_SOURCE="",
                                   RESULT:BPM:{X,Y}_DIFF_* NaN-filled.
```

### 7.5 ACQUIRE (extended)

The phase-2 flow is unchanged through step 5 (`extract_first_turn`). Step 6 (`AppState.update`) now additionally:

- If `reference_loaded`, computes `(dx, dy) = compute_diff(first_turn, reference_first_turn)` and bundles them with a fresh `DiffSummary` into `last_diff=DiffResult(...)`.
- If not loaded, sets `last_diff=None`.

Both branches publish atomically — the diff arrays update in the same listener fire as the first-turn arrays. Operators/agents subscribing only to `RESULT:BPM:X_DIFF_FIRST_TURN` see exactly one update per acquire, aligned with the corresponding `RESULT:BPM:X_FIRST_TURN` update.

### 7.6 Upload (REST-only; no CA equivalent)

```
1. Browser POSTs multipart .mat to /api/v1/references
2. FastAPI receives UploadFile (streamed)
3. Validate filename (basename, .mat extension, no traversal)
4. Refuse if path exists → 409
5. Write bytes to <reference_dir>/<name>
6. Post-write: load_reference_mat to validate the file parses as a real reference
       parse-fail → delete uploaded file, return 422
7. Return ReferenceLibraryEntry (201).
```

Note the explicit gap: an agent on **CA only** cannot upload — it can only `LOAD_REF` against names already in the library. To get a new file into the library, the agent must either ssh+scp out-of-band or use REST. This is the file-content-vs-PV asymmetry; see §15.

---

## 8. Error handling

| Condition | CA side | REST side |
|---|---|---|
| Invalid basename (path traversal, no `.mat` ext, empty) | CA alarm + log | 422 |
| Reference file not found in library | CA alarm + log | 404 |
| .mat parse failure (corrupt, wrong schema, no R0/BPMs) | CA alarm + log | 422 |
| SAVE: file already exists | CA alarm + log | 409 |
| SAVE/PROMOTE: no `last_acquire` to source from | CA alarm + log | 422 |
| LOAD: reference's BPM set has zero overlap with current | log warning, ref still loads (all-NaN diff) | 200 with warning in response |
| UPLOAD: name collision | n/a | 409 |
| UPLOAD: bad .mat (post-write validation) | n/a | 422 (file deleted) |
| `/result/ref/raw`: no ref loaded | n/a | 404 |
| `/result/ref/raw`: ref has no waveforms (MATLAB-only schema) | n/a | 404 with explanatory `detail` |
| `/result/ref/raw`: bpm not in ref's BPM set | n/a | 404 |
| ACQUIRE while ref loaded — diff math raises (numpy shape mismatch) | should be impossible (align_to_current guarantees same length); if it happens, AppState still updates first-turn, `last_diff=None`, `STATE:LAST_ACQUIRE_FAIL_REASON` carries the message | same |

The CA-alarm pattern matches phase 2's `CMD:ACQUIRE` putter — putters re-raise typed exceptions which caproto translates into the appropriate alarm severity.

---

## 9. Configuration

### 9.1 Settings additions

```python
class Settings(BaseSettings):
    # …existing…
    reference_dir: Path = Path("data/references")
```

Env var: `PYTXT_REFERENCE_DIR`. The validator ensures the path is a writable directory at startup; creates it (with parents) if missing. Production deployment on appsdev2 will set this via env to whatever directory the operations team designates — likely under the same `/home/als/physbase/users/thellert/...` tree as the MATLAB GUI's existing references for shared access.

### 9.2 The reference directory layout

Flat: `<reference_dir>/<basename>.mat`. No subdirectories, no metadata sidecars, no index file. The library listing is a directory scan + `stat` per entry, sorted by `mtime` descending. With expected library sizes <1000 files this is trivially cheap.

### 9.3 Phase 1 & 2 settings unchanged.

---

## 10. Testing strategy

### 10.1 Three tiers, extended

Same three tiers as phase 2:

1. **Unit** — pure-domain, milliseconds, no caproto / no FastAPI / no asyncio. Phase 3 adds tests for `domain/reference.py`.
2. **Integration** — composition fixture with a `SyntheticBpmReader` and a tmp_path `reference_dir`. Tests cover the full handler → AppState → PV / REST pipeline with real `.mat` files. Phase 3 grows the parity test by 4 rows (LOAD, SAVE, PROMOTE, CLEAR).
3. **E2E** — Playwright; full browser click-through.

### 10.2 Unit tests (new — `tests/unit/test_reference_domain.py` and friends)

- `canonicalize_bpm_name` — strips `:SA:X` and `:SA:Y`; idempotent on already-canonical names; no-op on names without the suffix.
- `load_reference_mat` against the real `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat` — assert `n_bpms=104`, `R0.shape=(2,104)`, first BPM canonical name = `SR01C:BPM1`, `raws=None` (MATLAB-only schema).
- `save_reference_mat` round-trip — write a synthesized `FirstTurnResult`+`last_acquire_raws`, read back, assert structural equality on R0/BPMs.Names + `raws` present and matching shape.
- `save → MATLAB-loader simulation` — after saving, do `scipy.io.loadmat(path, variable_names=['R0', 'BPMs'])` and verify only those two come back (proving MATLAB-GUI would load it correctly).
- `align_to_current` — full overlap, partial overlap, zero overlap, ref-larger-than-current, current-larger-than-ref, name order differs.
- `compute_diff` — straight subtraction; NaN propagates (`B=5, R0=NaN → diff=NaN`; `B=NaN, R0=5 → diff=NaN`).
- `summarize_diff` — RMS with NaN handling, `n_valid` count.
- `ReferenceLoadError` paths — missing R0; missing BPMs; wrong R0 shape; corrupt .mat file (write garbage bytes).

### 10.3 Integration tests (new — `tests/integration/test_reference_*.py`)

- `test_load_ref_via_ca` and `test_load_ref_via_rest` — full pipeline; assert `STATE:REF_*` PVs update; assert `RESULT:BPM:{X,Y}_DIFF_*` after a subsequent acquire.
- `test_save_ref_via_ca` and `test_save_ref_via_rest` — assert file appears in `reference_dir`; assert a `LOAD` of that name brings the state back.
- `test_promote_ref` — assert `REF_SOURCE=promoted`, `REF_FILE_PATH=None`, self-diff is all zeros (modulo pre-existing NaN).
- `test_clear_ref` — assert idempotent, NaN-fills diff PVs.
- `test_path_safety` (parametrized) — `'../etc/passwd'`, `'/etc/passwd'`, `'foo'` (no extension), `''`, `'a/b.mat'` all rejected with 422.
- `test_upload_round_trip` — multipart upload → GET /references shows it → LOAD_REF → diff PVs populate.
- `test_upload_collision` — second upload of same name → 409.
- `test_upload_garbage` — POST a non-.mat blob → 422, file removed.
- `test_download` — GET /references/{name} returns the same bytes as POST sent.
- `test_result_ref_raw` — for PyTxT-saved ref, returns waveforms; for MATLAB-saved ref, returns 404 with the explanatory `detail`.
- `test_parity` — extended with 4 rows (LOAD/SAVE/PROMOTE/CLEAR); each asserts CA and REST paths produce identical final state.
- `test_acquire_diff_publication` — load a ref, acquire, assert diff PVs match `B − R0` exactly.
- `test_legacy_mat_file_loads` — load the real `legacy/TxT_GUI/2025-03-23_…_reference_trajectory.mat` through the full HTTP+CA stack.

### 10.4 E2E (Playwright; new spec — `tests/e2e/reference.spec.js`)

Single happy-path scenario, mirroring the phase-2 trajectory spec:

1. Page loads, no reference state.
2. Click `[▶ ACQUIRE]` → trajectory renders.
3. Click `[Promote current]` → layout switches to 4-panel; ΔX/ΔY render at zero.
4. Click `[▶ ACQUIRE]` again → ΔX/ΔY now show real values (the synthetic reader varies per-BPM amplitude per call when seeded — assertion is that diff is non-zero somewhere).
5. Click `[Save current…]`, accept default name → POST succeeds; file exists.
6. Click `[Clear]` → layout returns to 2-panel.
7. Click `[Load…]`, pick the just-saved file → 4-panel returns; diff = zero everywhere.

### 10.5 What's NOT tested

- Concurrent LOAD/SAVE (single-user assumption for phase 3; concurrent ACQUIRE is already covered).
- Multi-MB upload performance (functional correctness only; performance characterization deferred).
- The `XGolden`/`YGolden` fields in the MATLAB BPMs struct — we read `Names` only; the rest is preserved-but-ignored on load and stubbed on save (per §6.1 note).

---

## 11. Build sequence — 4 milestones

### M1 — Pure domain (~2 days)

`pytxt/domain/reference.py` with all five public functions and the `Reference` dataclass. scipy added to `pyproject.toml`. Unit tests cover every branch incl. round-trip against the real `legacy/` sample file.

**DoD:**
- Unit suite for `domain/reference.py` passes (≥15 cases).
- Round-trip: save a synthetic ref → load → assert structural equality.
- Real MATLAB file loads: `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat` parses without error and produces the expected `n_bpms=104`, canonical first name `SR01C:BPM1`.
- No PVs, no REST, no AppState changes yet — purely a new `domain/` module.

### M2 — In-memory ops + diff publication (~2 days)

AppState fields, IOC PVs (`STATE:REF_*`, `RESULT:BPM:*_DIFF_*`), handlers for `PROMOTE_REF` and `CLEAR_REF` (the file-free pair). `handle_acquire` extended to compute & publish diff. Frontend hover tooltip extended (no layout switch yet).

**DoD:**
- CA: `caput CMD:PROMOTE_REF 1` after an acquire → `STATE:REF_LOADED=1`, `STATE:REF_SOURCE='promoted'`. Subsequent acquire publishes the diff arrays. `caput CMD:CLEAR_REF 1` → diff arrays go NaN.
- REST: `POST /cmd/promote_ref` and `POST /cmd/clear_ref` mirror identically.
- Parity test extended by 2 rows (PROMOTE, CLEAR).

### M3 — File library + LOAD/SAVE (~2–3 days)

`settings.reference_dir`, the path-safety helper, `pytxt/handlers/reference.py` LOAD/SAVE handlers, `CMD:LOAD_REF` / `CMD:SAVE_REF` string-PV putters, REST mirrors, `GET /references`, error paths.

**DoD:**
- `caput CMD:SAVE_REF foo.mat` → file appears in `reference_dir`. `caput CMD:LOAD_REF foo.mat` → state populates, diff PVs come alive on next acquire.
- REST mirrors all error codes (404/409/422).
- Path-safety integration test passes for all 5+ traversal vectors.
- Parity test extended by 2 more rows (LOAD, SAVE) — now 4 new rows total.

### M4 — Upload/download + 4-panel frontend + e2e (~2–3 days)

Multipart `POST /references` + `GET /references/{name}` + `GET /result/ref/raw`. Frontend reference sidebar, layout switch on `REF_LOADED`, dialogs (load picker, save name, upload). Playwright e2e spec.

**DoD:**
- Browser shows 4-panel layout when a ref is loaded; sidebar buttons all functional.
- Upload round-trip works via the upload dialog.
- Playwright spec passes (acquire → promote → see diff → save → clear → load → diff returns).
- `/api/v1/result/ref/raw` returns waveforms for PyTxT-saved refs, 404 with explanatory detail for MATLAB-saved refs.
- Full suite still green: 121 phase-2 pytest cases + ~25 new phase-3 cases; 5 phase-2 Playwright specs + 1 new.

---

## 12. Definition of done (phase 3 overall)

Phase 3 is complete when, on appsdev2 against the real ring:

1. An operator can load any reference from the existing legacy MATLAB library (`/home/als/physbase/users/thellert/automated_startup/GUI/*.mat`) via the browser, see the ΔX/ΔY panels populate, run a fresh ACQUIRE, and see the deviation update.
2. An operator can save the current trajectory as a new reference; that file is readable by the legacy MATLAB `TxT_GUI.mlapp` `Load Reference from file` button (validated by loading it in the GUI on appsdev2).
3. An Osprey agent (CA-only) can load a reference by name, trigger an acquire, and read the diff arrays via `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`.
4. An Osprey agent (REST) can list, upload, load, acquire, and download a reference round-trip.
5. `/api/v1/state` snapshot accurately reflects the loaded reference + latest diff summary at all times.
6. Full pytest + Playwright suite green; no regressions in phase-2 behavior.

---

## 13. Explicit non-scope

- **Trajectory correction.** Phase 4 introduces response-matrix inversion + corrector-magnet steps. Phase 3 publishes the deviation; deciding what to do about it remains the operator's (or Phase 4's) job.
- **BPM topology changes mid-session.** `bpm_prefixes` is still loaded once at startup. If the configured BPM set changes, restart. (Same as phase 2.)
- **Reference library garbage collection / quota.** Files accumulate in `reference_dir`; manual cleanup or external retention policy. `DELETE /api/v1/references/{name}` is *deferred to phase 4 or beyond* unless explicitly requested — keeping it out means accidental deletion isn't a worry during initial rollout.
- **Multi-turn references.** The MATLAB GUI's comment says "1-turn only right now"; we honor that. Reference `R0` is a `(2, n_bpms)` first-turn matrix.
- **Reference versioning / provenance metadata.** PyTxT-saved files include a `saved_by="pytxt v<version>"` string for forensics, but there's no formal lineage tracking (no "this ref was derived from acquire X at time Y").
- **Concurrent reference operations.** Implicit single-user assumption (matches phase 2's `acquire_in_flight` semantics). A LOAD and a concurrent SAVE could interleave AppState updates; both call `AppState.update` atomically so individual state is never corrupt, but the order of completion is unspecified. Acceptable.

---

## 14. Forward compatibility — what phase 4 looks like on this foundation

Concrete additions phase 4 should require:

- New domain code: `pytxt/domain/response_matrix.py` (pySC bindings) and `pytxt/domain/correction.py` (SVD pseudo-inverse, `(dx, dy) → (dPhiHCM, dPhiVCM)`).
- New AppState fields: `response_matrix`, `cm_step_proposal`, `cm_step_applied_at`.
- New PVs: `STATE:RESPONSE_MATRIX_LOADED`, `RESULT:CM:DPHI_H`, `RESULT:CM:DPHI_V`, `CMD:CALC_CM_STEP`, `CMD:APPLY_CM_STEP`, `CMD:ARM_BPMS`, `CMD:INJECT_ONE_SHOT`.
- New REST routes: `POST /cmd/{calc_cm_step, apply_cm_step, arm_bpms, inject_one_shot}`; `GET /response_matrix` for inspection.
- New `handlers/correction.py` + the MML-wrapper ports (`srinjectoneshot`, `steppv`) for arm + inject + corrector writes.
- New frontend tab: "Correction" — shows proposed CM steps, [Apply] / [Discard] buttons.

**Zero structural changes from phase 3** — every addition lands in a package that already exists. The composition root grows by a few lines.

The diff arrays Phase 3 publishes (`RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`) are exactly the input Phase 4 needs for `SCexp_ALS_calcCMstep(B, R0, Mplus, …)` — so Phase 4 is "compute Mplus once, then for each acquire feed the diff arrays through SVD and propose CM steps." The reference work done here is the foundation, not a sideshow.

---

## 15. Open questions / deferred decisions

- **CA-only upload path.** PVs cannot carry file content, so an agent on CA-only has no way to introduce a new `.mat` into the library — only load names that are already there. Mitigations: out-of-band scp/ssh; or a future `CMD:UPLOAD_REF_FROM_URL` (PV string write of a URL the server fetches; introduces new attack surface; defer until proven needed).
- **WS message `type` discriminator.** Phase 2 deferred this; phase 3 adds enough new state-update message variants (the seven `STATE:REF_*` fields) that the client logic is getting branchy. Recommend adding `{type: "pv_update", pv, value, ts}` in phase 3 or early phase 4.
- **Reference dir on production.** The exact path on appsdev2 is an ops decision — likely under `/home/als/physbase/...` for cross-tool access with the MATLAB GUI. Confirm with the team before deploy.
- **MATLAB `BPMs` struct fields on save.** The GUI loader uses only `.Names` and (implicitly) the shape of `R0`. PyTxT's save populates `Names + ORDs + nBuffer=100000` and stubs the rest (`XGolden`/`YGolden`/`current_mode`/etc.) as empty. If a downstream MATLAB script reads `BPMs.XGolden` (the "golden orbit"), it'll get an empty array. Acceptable for now; if a real script breaks, populate from a static config.
- **`DELETE /api/v1/references/{name}`.** Deferred — adds risk of accidental ref loss with little benefit until operators have built a meaningful library. Revisit after a few months of phase-3 use.
- **Runtime reload of `bpm_prefixes`.** Still deferred from phase 2. The phase-3 alignment logic would handle topology changes gracefully if and when this lands.
- **Per-BPM raw waveforms as PVs.** Still REST-only; phase 3 follows phase 2's lead. If the archiver wants CA-native access to reference waveforms, revisit.

---

*End of design spec. Implementation plan to follow via `superpowers:writing-plans` once the user signs off.*
