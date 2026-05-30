# M3 — Reference file library (LOAD/SAVE + path safety + `GET /references`)

> **For agentic workers:** implement this plan task-by-task. Each task ends in a green test run and a commit. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give Phase 3 a file-backed reference library. After M3, an operator/agent can save the current acquisition to a `.mat` in the library (`CMD:SAVE_REF foo.mat` / `POST /cmd/save_ref`), load a named reference from the library so its `B − R0` diff publishes on the next acquire (`CMD:LOAD_REF foo.mat` / `POST /cmd/load_ref`), and list what's available (`GET /api/v1/references`). This completes the CA-reachable half of the reference workflow. Multipart **upload**, **download-by-name**, the lazy **`/result/ref/raw`**, and the **4-panel frontend + e2e** remain **M4**.

**Architecture:** M3 introduces one new injected dependency — `reference_dir: Path` — threaded from `Settings` through `composition.main()` into **both** adapters: the IOC `PyTxTPVGroup` (so the `CMD:LOAD_REF`/`SAVE_REF` putters can reach it via `self._reference_dir`) and the REST app (`app.state.reference_dir`, read by the routes). The two new canonical handlers `handle_load_ref` / `handle_save_ref` live beside the M2 promote/clear handlers in `pytxt/handlers/reference.py` and are called identically by CA and REST — parity by construction. All `.mat` parsing/writing is the M1 domain code (`load_reference_mat`, `save_reference_mat`), invoked through `asyncio.to_thread` because scipy I/O is blocking.

**Scope decisions (deviations from spec — log in Task 7):**

1. **`reference_dir` is created in `composition.main()`, NOT in a `Settings` field-validator.** Spec §6.12 floats a validator that mkdir's the path; doing that fires on every `Settings()` (including the unit-test suite) and would litter the repo with a `data/references` dir. Instead `Settings` only declares the field (default `Path("data/references")`); `composition.main()` does `reference_dir.mkdir(parents=True, exist_ok=True)` per spec §6.13. Tests inject their own `tmp_path` dirs.
2. **M3 ships only `GET /api/v1/references` (the listing).** Multipart `POST /references` (upload), `GET /references/{name}` (download), and `GET /result/ref/raw` are **M4** (spec §11 M4). `routes/references.py` is created in M3 with just the GET-list endpoint; M4 extends it.
3. **SAVE does not mutate AppState** (spec §7.2) — saving doesn't auto-load. Its parity row therefore asserts identical *state* effect (none) across CA/REST; the file-write effect is covered by the dedicated `test_save_ref_*` integration tests. Each parity arm uses its own `tmp_path` reference_dir to avoid a cross-arm 409 collision.
4. **No frontend** (continues the M2 backend-only posture; all frontend lands in M4).

**Error model** (spec §8 — handler exceptions and their mappings; the CA putter re-raises typed exceptions → caproto alarm, the REST route maps them to HTTP codes):

| Condition | Exception | REST | CA |
|---|---|---|---|
| Invalid basename (empty, separators, no `.mat`, escapes library) | `InvalidReferenceNameError` | 422 | alarm |
| Reference file not found in library | `ReferenceNotFoundError` | 404 | alarm |
| `.mat` parse failure (corrupt / wrong schema) | `ReferenceLoadError` (domain, existing) | 422 | alarm |
| SAVE: target file already exists | `ReferenceExistsError` | 409 | alarm |
| SAVE: no `last_acquire` to source from | `NoLastAcquireError` (existing, M2) | 422 | alarm |
| LOAD: ref's BPM set has zero overlap with current | *(no error)* — ref loads, diff all-NaN, `n_aligned=0` | 200 | ok |

**Tech Stack:** Python 3.10+ (`Path.is_relative_to` is 3.9+, fine), caproto, FastAPI/pydantic, scipy via `asyncio.to_thread`, pytest + pytest-asyncio. No new dependencies.

**Spec source of truth:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-design.md` — §5.1 (`CMD:LOAD_REF`/`SAVE_REF` PVs), §5.2/§5.3 (REST + schemas), §6.3 (handlers + `_resolve_in_library`), §6.7 (cmd routes), §6.8 (`references.py` — GET only in M3), §6.12/§6.13 (settings + composition), §7.1/§7.2 (LOAD/SAVE flows), §8 (errors), §9 (config), §10.3 (integration tests incl. `test_path_safety`), §11 M3 (DoD).

**Phase-2/M2 patterns to mirror (verified anchors):**
- `pytxt/config/settings.py` — `Settings(BaseSettings)`, `env_prefix="PYTXT_"`, `extra="forbid"`, a `@model_validator(mode="before")` that rejects unknown `PYTXT_*` vars by iterating `cls.model_fields` (adding a field auto-whitelists it — **verify** this during impl). `bpm_prefixes_path: str` is the existing path-field precedent. Test: `tests/unit/test_settings.py`.
- `pytxt/composition.py` — `settings = Settings()`; `state = AppState(...)`; `ioc = PyTxTIOC(prefix=..., state=state, reader=reader)`; `api_app = create_app(state=state, settings=settings, bpm_reader=reader)`. No `functools.partial` today — handlers are plain async functions; M3 injects `reference_dir` rather than binding partials (simpler, matches the `state`/`reader` injection style).
- `pytxt/ioc/pvs.py` — `PyTxTPVGroup.__init__(self, *args, state, reader=None, **kwargs)` stores `self._state`/`self._reader`; string PV = `pvproperty(value="", dtype=ca.ChannelType.STRING, name="CMD:…")`; putter `@cmd_x.putter async def cmd_x(self, instance, value)` calls a handler and re-raises typed exceptions.
- `pytxt/ioc/server.py` — `PyTxTIOC.__init__(... state, reader=None)` constructs `PyTxTPVGroup(prefix=prefix, state=state, reader=reader)`.
- `pytxt/api/server.py` — `create_app(state, settings=None, bpm_reader=None)` sets `app.state.app_state`, `app.state.settings`, `app.state.bpm_reader`, and includes routers.
- `pytxt/api/routes/cmd.py` — routes read `request.app.state.app_state` (+ `getattr(request.app.state, "bpm_reader", None)`), call the shared handler, map typed exceptions → `HTTPException`.
- `pytxt/handlers/reference.py` (M2) — `NoLastAcquireError`, `_current_first_turn(state)` (reconstructs live first-turn from `last_acquire_raws + bpm_prefixes`), `handle_promote_ref`, `handle_clear_ref`. M3 adds beside them.
- `pytxt/domain/reference.py` (M1) — `load_reference_mat(path) -> Reference` (raises `ReferenceLoadError`), `save_reference_mat(path, first_turn, last_acquire_raws, bpm_prefixes) -> None`, `align_to_current`, `compute_diff`, `summarize_diff`.
- `tests/integration/test_reference_promote_clear.py` (M2) — CA arm (`PyTxTIOC` + `ClientContext` + `caput`/`caget`) and REST arm (`create_app` + `AsyncClient`/`ASGITransport`) setup to mirror; `tests/integration/test_parity.py` — table + `_public_state` projection.

**File map:**
- Modify `pytxt/config/settings.py` — Task 1 (`reference_dir` field)
- Modify `pytxt/api/server.py` — Task 1 (`create_app(... reference_dir=None)` → `app.state.reference_dir`)
- Modify `pytxt/ioc/server.py`, `pytxt/ioc/pvs.py` — Task 1 (`reference_dir` injection into PVGroup)
- Modify `pytxt/composition.py` — Task 1 (resolve + mkdir + thread into IOC and app)
- Modify `tests/unit/test_settings.py` — Task 1
- Modify `pytxt/handlers/reference.py` — Tasks 2, 3 (`_resolve_in_library`, exceptions, load/save handlers)
- Modify `pytxt/api/schemas/reference.py` — Task 3 (`LoadRefRequest`, `SaveRefRequest`, `LoadRefResponse`, `SaveRefResponse`, `ReferenceLibraryEntry`, `ReferenceLibraryList`)
- Create `tests/unit/test_reference_path_safety.py` — Task 2
- Create `tests/unit/test_handlers_reference_load_save.py` — Task 3
- Modify `pytxt/ioc/pvs.py` — Task 4 (`CMD:LOAD_REF`/`SAVE_REF` PVs + putters)
- Create `tests/unit/test_cmd_load_save_putters.py` — Task 4
- Modify `pytxt/api/routes/cmd.py` — Task 5 (2 routes)
- Create `pytxt/api/routes/references.py` — Task 5 (`GET /references`)
- Modify `pytxt/api/server.py` — Task 5 (include the references router)
- Create `tests/integration/test_reference_load_save.py`, `tests/integration/test_reference_path_safety_rest.py` — Task 6
- Modify `tests/integration/test_parity.py` — Task 6 (+2 rows)
- Append `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md`; modify `PyTxT-roadmap.html` — Task 7

**Pre-requisite:** M1 + M2 complete (commits through 3577bbb). `handlers/reference.py` has the promote/clear handlers + `_current_first_turn`; `domain/reference.py` has load/save/align/diff; `AppState` has the reference fields incl. `reference_file_path`.

---

## Task 1: Thread `reference_dir` through settings → composition → IOC + REST

**Files:** `pytxt/config/settings.py`, `pytxt/api/server.py`, `pytxt/ioc/server.py`, `pytxt/ioc/pvs.py`, `pytxt/composition.py`, `tests/unit/test_settings.py`

**Notes:**
- **Settings:** add `reference_dir: Path = Path("data/references")`. Import `Path`. Do **not** add a mkdir validator (decision §1). After adding, **verify** the unknown-env-var `@model_validator` still accepts `PYTXT_REFERENCE_DIR` (it should, if it iterates `cls.model_fields`); if it uses a hardcoded allowlist set, add `reference_dir` to it.
- **`create_app`:** add `reference_dir: Optional[Path] = None` param; set `app.state.reference_dir = reference_dir`. Keep it optional (existing call sites / tests that don't pass it still work; routes `getattr(..., "reference_dir", None)` and 503/raise if a load/save route is hit without it — but tests will pass it).
- **IOC:** add `reference_dir: Optional[Path] = None` to `PyTxTIOC.__init__` and pass it to `PyTxTPVGroup(...)`. Add `reference_dir=None` to `PyTxTPVGroup.__init__`, store `self._reference_dir`.
- **Composition:** after settings load, `reference_dir = settings.reference_dir.resolve(); reference_dir.mkdir(parents=True, exist_ok=True)`; log it; pass `reference_dir=reference_dir` to both `PyTxTIOC(...)` and `create_app(...)`.
- Nothing consumes `reference_dir` yet — this task is pure plumbing. The existing suite must stay green (IOC + app still construct).

- [ ] **Step 1:** Add the `Settings.reference_dir` field; verify env-var acceptance.
- [ ] **Step 2:** Thread `reference_dir` into `create_app` / `PyTxTIOC` / `PyTxTPVGroup` / `composition.main()`.
- [ ] **Step 3:** Extend `tests/unit/test_settings.py` — default value + `PYTXT_REFERENCE_DIR` override accepted.
- [ ] **Step 4:** Run + commit.

```
.venv/bin/pytest tests/unit/test_settings.py tests/unit/test_composition.py tests/integration/test_ioc_lifecycle.py tests/integration/test_health_endpoint.py -v
```

Commit: `feat(config): M3 Task 1 — thread reference_dir through settings, composition, IOC, REST app`

---

## Task 2: Path-safety helper + exceptions

**Files:** `pytxt/handlers/reference.py`, `tests/unit/test_reference_path_safety.py`

**Notes:**
- **Exceptions** (define near `NoLastAcquireError`): `InvalidReferenceNameError(Exception)` (→422), `ReferenceNotFoundError(Exception)` (→404), `ReferenceExistsError(Exception)` (→409). `ReferenceLoadError` is imported from `pytxt.domain.reference` (don't redefine).
- **`_resolve_in_library(reference_dir: Path, name: str) -> Path`** (spec §6.3) — rejects, in order, then resolves:

```python
def _resolve_in_library(reference_dir: Path, name: str) -> Path:
    if not name:
        raise InvalidReferenceNameError("Reference name must not be empty.")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise InvalidReferenceNameError(f"Reference name must be a bare basename: {name!r}")
    if not name.endswith(".mat"):
        raise InvalidReferenceNameError(f"Reference name must end in '.mat': {name!r}")
    candidate = (reference_dir / name)
    resolved = candidate.resolve()
    base = reference_dir.resolve()
    if not resolved.is_relative_to(base):     # 3.9+; defends against ../ and symlink escapes
        raise InvalidReferenceNameError(f"Reference path escapes the library: {name!r}")
    return resolved
```

- This helper raises **only** `InvalidReferenceNameError`; existence checks (`ReferenceNotFoundError`) and collision checks (`ReferenceExistsError`) live in the load/save handlers (Task 3), since "not found" is a LOAD concern and "exists" is a SAVE concern.
- **Path-safety test vectors** (spec §10.3): `''`, `'foo'` (no ext), `'a/b.mat'` (separator), `'../etc/passwd'`, `'/etc/passwd'`, `'..'`, `'foo.mat/../bar.mat'` → all raise `InvalidReferenceNameError`. Positive: `'good.mat'`, `'2025-03-23_12:43:16_reference_trajectory.mat'` → resolve cleanly inside a `tmp_path` library.

- [ ] **Step 1:** Add the three exceptions + `_resolve_in_library`.
- [ ] **Step 2:** Write `tests/unit/test_reference_path_safety.py` (parametrized reject vectors + accept cases, using `tmp_path`).
- [ ] **Step 3:** Run + commit.

```
.venv/bin/pytest tests/unit/test_reference_path_safety.py -v
```

Commit: `feat(handlers): M3 Task 2 — _resolve_in_library path-safety helper + reference exceptions`

---

## Task 3: `handle_load_ref` + `handle_save_ref` + schemas

**Files:** `pytxt/handlers/reference.py`, `pytxt/api/schemas/reference.py`, `tests/unit/test_handlers_reference_load_save.py`

**Notes:**
- **Schemas** (`schemas/reference.py`, add to the M2 file):

```python
class LoadRefRequest(BaseModel):
    name: str = Field(min_length=1, description="Reference filename (basename, incl. .mat).")

class SaveRefRequest(BaseModel):
    name: str | None = Field(default=None, description="Basename incl. .mat; omit for timestamp default.")

class LoadRefResponse(BaseModel):
    loaded: bool
    name: str
    source: ReferenceSource          # FILE
    n_aligned: int
    n_unaligned: int

class SaveRefResponse(BaseModel):
    name: str
    size_bytes: int
    saved_at: datetime

class ReferenceLibraryEntry(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime

class ReferenceLibraryList(BaseModel):
    references: list[ReferenceLibraryEntry]
```

- **`handle_load_ref(state, reference_dir, name)`** (spec §7.1):
  1. `path = _resolve_in_library(reference_dir, name)` (→ `InvalidReferenceNameError`).
  2. `if not path.exists(): raise ReferenceNotFoundError(name)`.
  3. `ref = await asyncio.to_thread(load_reference_mat, path)` (→ `ReferenceLoadError` on bad `.mat`).
  4. `aligned, n_aligned, n_unaligned = align_to_current(ref, state.bpm_prefixes)`.
  5. Diff against current live first-turn **if** there's been a successful acquire: `if state.last_acquire.ok_count > 0: live = _current_first_turn(state); dx, dy = compute_diff(live, aligned); diff = DiffResult(dx, dy, summarize_diff(dx, dy))` else `diff = None`.
  6. `await state.update(reference_loaded=True, reference_name=path.name, reference_loaded_at=now, reference_source=ReferenceSource.FILE, reference_first_turn=aligned, reference_file_path=path, reference_bpm_names=list(ref.bpm_names), last_diff=diff)`.
  7. `return LoadRefResponse(loaded=True, name=path.name, source=ReferenceSource.FILE, n_aligned=n_aligned, n_unaligned=n_unaligned)`.
  - Zero-overlap loads succeed (n_aligned=0, diff all-NaN) — no error (spec §8).
- **`handle_save_ref(state, reference_dir, name)`** (spec §7.2):
  1. `if state.last_acquire.ok_count == 0: raise NoLastAcquireError(...)`.
  2. `if name is None: name = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H:%M:%S_reference_trajectory.mat")` (matches the MATLAB GUI's naming; the real legacy sample is named exactly this way).
  3. `path = _resolve_in_library(reference_dir, name)`.
  4. `if path.exists(): raise ReferenceExistsError(name)` (refuse overwrite → 409).
  5. `first_turn = _current_first_turn(state)`.
  6. `await asyncio.to_thread(save_reference_mat, path, first_turn, state.last_acquire_raws, state.bpm_prefixes)`.
  7. `size = path.stat().st_size`; `return SaveRefResponse(name=path.name, size_bytes=size, saved_at=datetime.now(timezone.utc))`.
  - **No `state.update`** — SAVE leaves state untouched (decision §3, spec §7.2).
- **Imports:** `import asyncio`; `from datetime import datetime, timezone`; `from pytxt.domain.reference import load_reference_mat, save_reference_mat, align_to_current, compute_diff, summarize_diff, ReferenceLoadError`; `from pytxt.domain.types import DiffResult, ReferenceSource`. Watch the existing import block for duplicates.

- [ ] **Step 1:** Add the schemas.
- [ ] **Step 2:** Add `handle_load_ref` + `handle_save_ref`.
- [ ] **Step 3:** Write `tests/unit/test_handlers_reference_load_save.py` — async tests on a real `AppState` with a `tmp_path` reference_dir:
  - save (after a synthetic acquire) writes a file; load it back → `reference_loaded`, `source==FILE`, `reference_file_path` set, `n_aligned == len(prefixes)`; a subsequent acquire-shaped diff is finite.
  - save with no acquire → `NoLastAcquireError`; save over an existing file → `ReferenceExistsError`; save with `name=None` → timestamp-named file appears.
  - load missing name → `ReferenceNotFoundError`; load a garbage `.mat` (write junk bytes) → `ReferenceLoadError`; load with bad name → `InvalidReferenceNameError`.
  - load a ref whose names don't overlap current prefixes → loads, `n_aligned==0`, diff arrays all-NaN.
  - Use `save_reference_mat` (or the real `legacy/` sample if present) to create fixture `.mat` files; reuse the M2 `RawBPM`/synthetic helpers for `last_acquire_raws`.
- [ ] **Step 4:** Run + commit.

```
.venv/bin/pytest tests/unit/test_handlers_reference_load_save.py tests/unit/test_handlers_reference.py -v
```

Commit: `feat(handlers): M3 Task 3 — handle_load_ref/handle_save_ref + library schemas`

---

## Task 4: IOC `CMD:LOAD_REF` / `CMD:SAVE_REF` PVs + putters

**Files:** `pytxt/ioc/pvs.py`, `tests/unit/test_cmd_load_save_putters.py`

**Notes:**
- String command PVs grouped with the existing `CMD:*` records:
  - `CMD:LOAD_REF` — `value="", dtype=ca.ChannelType.STRING`, doc per spec §5.1.
  - `CMD:SAVE_REF` — `value="", dtype=ca.ChannelType.STRING`.
- Putters (mirror `cmd_acquire`/`cmd_promote_ref`; re-raise typed exceptions → CA alarm). They use `self._reference_dir` (injected in Task 1):

```python
@cmd_load_ref.putter
async def cmd_load_ref(self, instance, value):
    await handle_load_ref(self._state, self._reference_dir, value)
    return value

@cmd_save_ref.putter
async def cmd_save_ref(self, instance, value):
    name = value or None          # empty CA string → timestamp default
    await handle_save_ref(self._state, self._reference_dir, name)
    return value
```

- Import `handle_load_ref, handle_save_ref` at module top (alongside the M2 promote/clear imports). Verify no import cycle.
- If `self._reference_dir is None` (e.g. a unit-constructed PVGroup without injection), the handler will fail at `_resolve_in_library` — fine for prod (always injected); tests pass a `tmp_path`.

- [ ] **Step 1:** Add the 2 PVs + 2 putters.
- [ ] **Step 2:** Write `tests/unit/test_cmd_load_save_putters.py` — mirror `test_cmd_reference_putters.py`: construct PVGroup with a stub state + `tmp_path` reference_dir, call the putter coroutine directly; assert save writes a file (after a synthetic acquire) and load populates state; assert a bad name surfaces `InvalidReferenceNameError`, a missing file surfaces `ReferenceNotFoundError`.
- [ ] **Step 3:** Run + commit.

```
.venv/bin/pytest tests/unit/test_cmd_load_save_putters.py tests/integration/test_ioc_lifecycle.py -v
```

Commit: `feat(ioc): M3 Task 4 — CMD:LOAD_REF / CMD:SAVE_REF string PVs + putters`

---

## Task 5: REST routes (`/cmd/load_ref`, `/cmd/save_ref`, `GET /references`)

**Files:** `pytxt/api/routes/cmd.py`, `pytxt/api/routes/references.py` (new), `pytxt/api/server.py`

**Notes:**
- **`cmd.py`** — two routes mirroring `post_acquire`, reading `request.app.state.reference_dir`:

```python
@router.post("/load_ref", response_model=LoadRefResponse)
async def post_load_ref(request: Request, body: LoadRefRequest) -> LoadRefResponse:
    state = request.app.state.app_state
    reference_dir = getattr(request.app.state, "reference_dir", None)
    try:
        return await handle_load_ref(state, reference_dir, body.name)
    except InvalidReferenceNameError as e:   raise HTTPException(422, str(e))
    except ReferenceNotFoundError as e:      raise HTTPException(404, str(e))
    except ReferenceLoadError as e:          raise HTTPException(422, str(e))

@router.post("/save_ref", response_model=SaveRefResponse)
async def post_save_ref(request: Request, body: SaveRefRequest) -> SaveRefResponse:
    state = request.app.state.app_state
    reference_dir = getattr(request.app.state, "reference_dir", None)
    try:
        return await handle_save_ref(state, reference_dir, body.name)
    except NoLastAcquireError as e:           raise HTTPException(422, str(e))
    except InvalidReferenceNameError as e:    raise HTTPException(422, str(e))
    except ReferenceExistsError as e:         raise HTTPException(409, str(e))
```

(`SaveRefRequest` has an optional `name`; an empty `{}` body → `name=None` → timestamp default.)
- **`references.py`** (new) — GET listing only (M3 scope):

```python
router = APIRouter(prefix="/api/v1", tags=["references"])

@router.get("/references", response_model=ReferenceLibraryList)
async def list_references(request: Request) -> ReferenceLibraryList:
    reference_dir = getattr(request.app.state, "reference_dir", None)
    if reference_dir is None:
        raise HTTPException(503, "Reference library not configured")
    entries = []
    for p in sorted(Path(reference_dir).glob("*.mat"), key=lambda q: q.stat().st_mtime, reverse=True):
        st = p.stat()
        entries.append(ReferenceLibraryEntry(
            name=p.name, size_bytes=st.st_size,
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        ))
    return ReferenceLibraryList(references=entries)
```

- **`server.py`** — `from pytxt.api.routes import references` and `app.include_router(references.router)` (mirror the existing router includes).

- [ ] **Step 1:** Add the two cmd routes (imports for handlers + exceptions + request/response schemas).
- [ ] **Step 2:** Create `references.py` + include its router in `create_app`.
- [ ] **Step 3:** Run + commit (integration coverage lands in Task 6; here just confirm the app builds and existing route tests pass).

```
.venv/bin/pytest tests/integration/test_acquire_via_rest.py tests/integration/test_health_endpoint.py tests/unit/test_schemas.py -v
```

Commit: `feat(api): M3 Task 5 — /cmd/load_ref + /cmd/save_ref routes + GET /references`

---

## Task 6: Integration + parity tests

**Files:** `tests/integration/test_reference_load_save.py` (new), `tests/integration/test_reference_path_safety_rest.py` (new), `tests/integration/test_parity.py`

**Notes:**
- **`test_reference_load_save.py`** (spec §10.3) — CA arm builds `PyTxTIOC(..., reference_dir=tmp_path)`, REST arm builds `create_app(state=..., reference_dir=tmp_path)`; reuse the M2 `test_reference_promote_clear.py` setup:
  - `test_save_then_load_via_ca`: acquire → `caput CMD:SAVE_REF foo.mat` → assert `(tmp/foo.mat).exists()` → `caput CMD:LOAD_REF foo.mat` → assert `STATE:REF_LOADED==1`, `STATE:REF_SOURCE=="file"`, `STATE:REF_NAME=="foo.mat"`; a subsequent acquire → diff PVs finite.
  - `test_save_then_load_via_rest`: `POST /cmd/acquire` → `POST /cmd/save_ref {"name":"foo.mat"}` (assert 200 + file) → `GET /references` shows it → `POST /cmd/load_ref {"name":"foo.mat"}` → `GET /state` shows `reference.source=="file"`.
  - `test_save_no_acquire`: save on fresh state → CA alarm / REST 422.
  - `test_save_exists`: save foo.mat twice → second → CA alarm / REST 409.
  - `test_load_not_found`: load missing → CA alarm / REST 404.
  - `test_save_default_name`: `POST /cmd/save_ref {}` → file with the timestamp pattern appears; `GET /references` lists it.
- **`test_reference_path_safety_rest.py`** — parametrized over `''`, `'foo'`, `'a/b.mat'`, `'../etc/passwd'`, `'/etc/passwd'`: `POST /cmd/load_ref {"name": vector}` → 422 (and `POST /cmd/save_ref` → 422). (Empty `''` may be rejected by pydantic `min_length=1` as 422 before reaching the handler — that's still a 422, fine; note it.)
- **Parity** — add 2 rows; LOAD needs a pre-seeded file, SAVE needs a prior acquire and its own dir:

```python
# columns: command_name, ca_pv_suffix, rest_path, requires_acquire
("load_ref", "CMD:LOAD_REF", "/api/v1/cmd/load_ref", False),   # harness pre-seeds a .mat + sends the name
("save_ref", "CMD:SAVE_REF", "/api/v1/cmd/save_ref", True),    # needs a prior acquire
```

Extend the harness: give **each arm its own `tmp_path` reference_dir**; wire it into `PyTxTIOC`/`create_app`. For `load_ref`, pre-seed an identical `.mat` into both arms' dirs (via `save_reference_mat` on synthetic data) and have the CA arm `caput CMD:LOAD_REF <name>` / REST arm `POST {"name": <name>}`. For string-valued CMD PVs the trigger writes the name, not `1`. Extend `_public_state` with `reference_file_path` → `"<set>"|None`. SAVE mutates no state → both arms project identical (post-acquire) state → parity holds; the file artifact differs per-arm dir, so no 409.
- **Known flake:** if the full run fails only on `test_acquire_partial_fail.py::test_partial_fail_state_pvs_published`, re-run it in isolation (may need 2 retries) before treating as a regression.

- [ ] **Step 1:** Write `test_reference_load_save.py`.
- [ ] **Step 2:** Write `test_reference_path_safety_rest.py`.
- [ ] **Step 3:** Extend `test_parity.py` (2 rows + per-arm reference_dir + string-PV trigger handling + projection).
- [ ] **Step 4:** Run the new tests, then the full suite.

```
.venv/bin/pytest tests/integration/test_reference_load_save.py tests/integration/test_reference_path_safety_rest.py tests/integration/test_parity.py -v
.venv/bin/pytest -q
```

Report exact pass/fail/skip counts (account for the known CA flake).

- [ ] **Step 5:** Commit.

Commit: `test(integration): M3 Task 6 — load/save pipeline, REST path-safety, parity rows (LOAD, SAVE)`

---

## Task 7: Closeout — decision log + roadmap + final verification

**Files:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md`, `PyTxT-roadmap.html`

**Decision-log entries (dated 2026-05-29, match the file template):**
1. `reference_dir` created in composition, not a Settings validator (keeps `Settings()` side-effect-free for tests).
2. M3 ships only `GET /references`; upload/download/`/result/ref/raw` deferred to M4.
3. SAVE does not mutate AppState; parity SAVE-row asserts identical (none) state effect with per-arm tmp dirs; file-write tested separately.
4. Path-safety rules + `is_relative_to` (3.9+) choice; the exact reject vectors.
5. Blocking scipy `load`/`save` run via `asyncio.to_thread`.
6. Exception taxonomy + HTTP mappings (`InvalidReferenceNameError`/`ReferenceNotFoundError`/`ReferenceExistsError` + reused `ReferenceLoadError`/`NoLastAcquireError`).
7. Any surprises (env-var whitelist behavior for the new field; whether empty-name hits pydantic vs the handler).

**Roadmap (`PyTxT-roadmap.html`) — flip to M3 ✓:**
- Hero `<h2>`: `M1 ✓ · M2 ✓ · M3 · M4` → `M1 ✓ · M2 ✓ · M3 ✓ · M4`; `.progress-fill` width `50%` → `75%`; `.progress-text` likewise; narrative → "M3 (file library + LOAD/SAVE) landed", next = M4 (upload/download + 4-panel frontend + e2e).
- Phase 3 milestone tracker: M3 card `ms now` → `ms done` / `✓ Done` (+ meta); M4 card `ms todo` → `ms now` / `Next`; section hint → `M3 done · M4 next`.
- Phase 3 `<details>` badge: `… · M2 ✓` → `… · M3 ✓`; mark the M3 `<li>` done.
- Stats: tests count; unpushed commits (compute `git rev-list --count origin/main..HEAD` + 1 for the closeout commit).
- Recent activity: prepend an `M3 ✓` milestone entry + the M3 commits.
- Verify CSS classes exist (`ms done/now/todo`, `badge-done/now/plan`, `phase now`), `<details>` open/close balance, and an `html.parser` parse — before committing.

- [ ] **Step 1:** Append decision-log entries.
- [ ] **Step 2:** Update + validate the roadmap.
- [ ] **Step 3:** Final verification.

```
.venv/bin/pytest -q
.venv/bin/python -c "from pytxt.handlers.reference import handle_load_ref, handle_save_ref, _resolve_in_library, ReferenceNotFoundError, ReferenceExistsError, InvalidReferenceNameError; print('M3 surface ok')"
git log --oneline -10
git status
```

- [ ] **Step 4:** Commit (stage only the decision-log + roadmap; leave the pre-existing unstaged `.claude/settings.json` untouched).

Commit: `docs(roadmap+decisions): M3 closeout — reference file library (LOAD/SAVE) shipped`

---

## Notes for the implementer

- **Parity is the contract** (CLAUDE.md §1): `CMD:LOAD_REF`/`SAVE_REF` and their REST routes call the same handlers; don't let validation drift between the putter and the route.
- **Observability** (CLAUDE.md §1–2): LOAD confirms via `STATE:REF_LOADED=1` + `STATE:REF_SOURCE="file"` + `STATE:REF_NAME`. SAVE confirms via the file appearing + `GET /references` listing it (SAVE has no state PV by design).
- **Domain stays I/O-free** (CLAUDE.md §5): no new logic in `domain/reference.py`; M3 only calls M1's load/save/align/diff from the adapter layer, wrapping the blocking scipy calls in `asyncio.to_thread`.
- **Test-IOC isolation:** integration tests keep the `OSPREY:TEST:TXT:*` prefix + test ports per the existing fixtures.
- **Subagent command shape:** `.venv/bin/pytest`, not `source .venv/bin/activate`.
- **Known flake:** `test_acquire_partial_fail.py::test_partial_fail_state_pvs_published` (CA loopback); re-run in isolation before treating as a regression.
- **No scope creep into M4:** multipart upload (`POST /references`), download (`GET /references/{name}`), `/result/ref/raw`, and ANY `pytxt/frontend/` change are M4 — stop if you reach for them.
