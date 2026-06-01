# M4 — Upload/download + `/result/ref/raw` + 4-panel frontend + e2e

> **For agentic workers:** implement this plan task-by-task. Each task ends in a green test run and a commit. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close Phase 3 by giving the reference workflow its two remaining surfaces — **bulk file transfer over REST** and the **operator-facing browser UI**. After M4: an operator/agent can upload a `.mat` into the library (`POST /api/v1/references`, multipart), download one back (`GET /api/v1/references/{name}`), and drill into a PyTxT-saved reference's full TBT waveforms (`GET /api/v1/result/ref/raw?bpm=…`). In the browser, loading a reference switches the trajectory page from a 2-panel (X, Y) to a 4-panel (X, Y, ΔX, ΔY) layout, and a reference sidebar drives promote / load / save / upload / clear. A Playwright spec walks the full happy path. This completes Phase 3 (spec §12).

**What is already done (M1–M3 — do NOT re-implement):** the pure domain (`load/save/align/diff`), the in-memory ops + diff PVs (`STATE:REF_*`, `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`), the LOAD/SAVE handlers + `CMD:LOAD_REF`/`SAVE_REF` PVs + REST `/cmd/{load,save}_ref` mirrors, `GET /api/v1/references` (listing), the path-safety helper, and the 4 parity rows (PROMOTE/CLEAR/LOAD/SAVE). M4 is **upload + download + ref/raw + all frontend + e2e** — nothing else.

**Architecture:** M4 adds **no new injected dependencies** and **no new AppState fields**. The three new REST endpoints reuse what M3 wired:
- Upload/download read `request.app.state.reference_dir` and reuse `_resolve_in_library` (from `pytxt/handlers/reference.py`) for basename/traversal safety — identical rules to LOAD/SAVE so an uploaded name and a `CMD:LOAD_REF` name validate the same way (parity of the path contract).
- `/result/ref/raw` reads the loaded reference **lazily from disk**: it re-parses `state.reference_file_path` via `load_reference_mat` and pulls the requested BPM's `RawBPM` out of `Reference.raws`. No reference waveforms are held in AppState — consistent with "don't put bulk content in process state / PVs" (CLAUDE.md §3). A **promoted** reference (`reference_file_path is None`) therefore has no `ref/raw` → 404, same as a MATLAB-only file whose `raws is None`.

The frontend is the first Phase-3 UI work. It extends the existing phase-2 trajectory page in place: same WS-CA bridge (`connection.subscribe`), same canvas `render()` primitive (called 4× instead of 2× when a ref is loaded), plus a new `js/reference.js` module owning the sidebar + dialogs.

**New dependency (REAL — verified absent):** FastAPI's `UploadFile` requires **`python-multipart`**, which is **not installed and not declared**. Task 1 adds `python-multipart>=0.0.9` to `pyproject.toml` `dependencies` and installs it into `.venv`. Without it, `POST /references` raises at route-registration/runtime. (scipy + FastAPI are already present.)

**Endpoint surface added (spec §5.2, §6.8, §6.9):**

| Method | Path | Effect | Codes |
|---|---|---|---|
| `POST` | `/api/v1/references` | Multipart upload of a `.mat`; basename-safe, no overwrite, parse-validated | 201 / 409 / 422 |
| `GET` | `/api/v1/references/{name}` | Download a library `.mat` (`application/octet-stream`) | 200 / 404 / 422 |
| `GET` | `/api/v1/result/ref/raw?bpm=<prefix>` | Loaded ref's full TBT waveforms for one BPM | 200 / 400 / 404 |

**Error model (spec §8, §6.9):**

| Condition | REST |
|---|---|
| Upload: invalid basename (sep / no `.mat` / escapes lib / empty) | 422 (`InvalidReferenceNameError`, or pydantic for empty) |
| Upload: target already exists | 409 (`ReferenceExistsError`) |
| Upload: bytes are not a valid reference `.mat` | 422 (`ReferenceLoadError`) — **delete the partial write first** |
| Upload: body exceeds size cap | 413 (cap default 200 MB; see Task 1) |
| Download: name invalid | 422 (`InvalidReferenceNameError`) |
| Download: file not in library | 404 (`ReferenceNotFoundError`) |
| `ref/raw`: missing `bpm` query param | 400 |
| `ref/raw`: no reference loaded | 404 |
| `ref/raw`: ref has no waveforms (promoted, or MATLAB-only schema) | 404, `detail="Reference has no full waveforms (loaded from MATLAB-only schema)"` |
| `ref/raw`: `bpm` not in ref's BPM set | 404 |

**Tech stack:** Python 3.10+, FastAPI `UploadFile` + `FileResponse` (+ `python-multipart`), scipy via `asyncio.to_thread` (re-parse for `ref/raw` is blocking I/O), pytest + `httpx.AsyncClient`/`ASGITransport`, Playwright. Frontend: vanilla JS + Canvas, no framework.

**Spec source of truth:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-design.md` — §5.2 (REST table), §5.3 (schemas), §5.4 (browser additions: 4-panel + sidebar + status Δrms row + tooltip), §6.8 (`references.py` upload/download), §6.9 (`result.py` `/result/ref/raw` lazy re-parse), §6.11 (frontend file map), §10.3 (integration tests: `test_upload_round_trip`, `test_download`, `test_result_ref_raw`, `test_legacy_mat_file_loads`), §10.4 (e2e `reference.spec.js` 7-step happy path), §11 M4 (DoD), §12 (phase DoD).

**Verified code anchors (current state — confirmed by exploration 2026-06-01):**
- `pytxt/api/routes/references.py` (43 lines) — `GET /references` only; reads `request.app.state.reference_dir`, returns 503 if None. Upload/download append here.
- `pytxt/api/routes/result.py` (43 lines) — `GET /result/bpm/raw?bpm=` reads `request.app.state.app_state.last_acquire_raws[bpm]` → `BpmRawWaveforms` (400 missing bpm / 404 unknown). **This is the template for `/result/ref/raw`.**
- `pytxt/api/schemas/result.py:56` — `BpmRawWaveforms{bpm_prefix, x_nm, y_nm, sum_au, armed, read_timestamp}` (reuse as-is for ref/raw).
- `pytxt/api/schemas/reference.py` — `ReferenceLibraryEntry{name,size_bytes,modified_at}` (upload returns this), `ReferenceLibraryList`.
- `pytxt/handlers/reference.py` — `_resolve_in_library(reference_dir, name)`, `InvalidReferenceNameError`, `ReferenceNotFoundError`, `ReferenceExistsError`; `ReferenceLoadError` imported from `pytxt.domain.reference`.
- `pytxt/api/server.py:64-69` — router includes; `:51-54` — `app.state.{app_state,settings,bpm_reader,reference_dir}`. Frontend mounted at root `:71-73`.
- `pytxt/config/settings.py` — numeric-field precedent (`bpm_read_timeout_s: float = 2.0`); `@model_validator` whitelists fields via `cls.model_fields` (a new field auto-accepts `PYTXT_*`).
- `pytxt/domain/reference.py:52` — `load_reference_mat(path) -> Reference`; populates `raws: dict[str,RawBPM]|None` only when the `.mat` has `X_wf/Y_wf/sum_wf/injection_turn` (lines ~97-122), else `raws=None`.
- `pytxt/state/app_state.py:54-65` — `reference_loaded`, `reference_file_path: Optional[Path]`, `reference_bpm_names`, etc.
- **Frontend:** `pytxt/frontend/trajectory.html` (2 `.canvas-wrap` → `#canvasX`/`#canvasY`, `#trajectoryTooltip`, `#trajectoryStatus`/`#trajectoryCounts`, `#acquireButton`); `js/trajectory.js` (`render(canvas, data, color)` lines 148-250, `redraw()` lines 252-261 calls render 2×, WS subs lines 278-309, tooltip `showTooltipAt()` lines 57-70, status header lines 256-260); `js/connection.js` (`connection.subscribe(pv, cb)`, `connection.command(name, body)` = POST `/api/v1/cmd/<name>`, WS `/api/v1/pvs`); `css/theme.css` (`--canvas-{bg,grid,x,y}` lines 111-116, `.trajectory-panel` flex column lines 135-182).
- **Diff/ref PV names (M2):** `STATE:REF_LOADED`, `STATE:REF_NAME`, `STATE:REF_LOADED_AT`, `STATE:REF_SOURCE`, `RESULT:BPM:X_DIFF_FIRST_TURN`, `RESULT:BPM:Y_DIFF_FIRST_TURN` (`pytxt/ioc/pvs.py:99-139`). `ReferenceSource`: `NONE=""`, `FILE="file"`, `PROMOTED="promoted"`.
- **e2e:** `tests/e2e/{playwright.config.js,package.json,trajectory.spec.js,smoke.spec.js,ping.spec.js}`. Web server `command: .venv/bin/python -m pytxt`, `env: {PYTXT_USE_SYNTHETIC_READER:'1'}`, baseURL `http://127.0.0.1:8008`. trajectory.spec waits `#connectionStatus[data-state="connected"]`, clicks `#acquireButton`, waits `#trajectoryStatus` contains "OK", validates canvas pixels via `getImageData()`.

**Scope decisions (deviations / gap-fills — log in Task 6):**

1. **`/result/ref/raw` re-parses from disk; it does NOT cache ref waveforms in AppState.** Spec §6.9 says "lazily on demand." Keeps AppState free of ~100k-sample arrays. Cost: one scipy re-parse per drill-down call (acceptable — operator-driven, not per-acquire). Promoted refs (`reference_file_path is None`) → 404 by the same path that handles MATLAB-only files.
2. **Upload size cap is a `Settings` field** (`max_upload_bytes: int = 200 * 1024 * 1024`), enforced in the route by reading `content-length` and/or streaming with a running byte count → 413. Spec §6.8 says "200 MB default, configurable."
3. **Upload validates by parse, then keeps-or-deletes.** Write the streamed bytes to the resolved path, then `await asyncio.to_thread(load_reference_mat, path)`; on `ReferenceLoadError` **unlink the file** and raise → 422. No half-written junk survives a bad upload. Collision (`path.exists()`) is checked *before* writing → 409.
4. **No `DELETE /references/{name}`** — explicitly deferred (spec §15, §11 notes). Do not add it.
5. **`python-multipart` added as a hard dependency** (not optional) — upload is core to the M4 DoD.
6. **Frontend split across two tasks** (3 = layout/render, 4 = sidebar/dialogs) so each ends green and reviewable; `js/reference.js` is new, `trajectory.js`/`.html`/`.css` are extended in place.
7. **e2e diff assertion is "non-zero somewhere," not exact values** (spec §10.4 step 4) — the synthetic reader varies per call; asserting exact ΔX/ΔY would be flaky.

**Pre-requisite:** M1–M3 complete (through commit `b86343a`, plus the M3-hardening fix `9087972`). `reference_dir` is threaded into both adapters; `GET /references` works; `_resolve_in_library` + the three exceptions exist.

---

## Task 1: Multipart upload + download endpoints (+ `python-multipart`, size cap)

**Files:** `pyproject.toml`, `pytxt/config/settings.py`, `pytxt/api/routes/references.py`, `pytxt/api/server.py` (only if cap needs `app.state`), `tests/integration/test_reference_upload_download.py` (new), `tests/unit/test_settings.py`

**Notes:**
- **Dependency:** add `"python-multipart>=0.0.9"` to `pyproject.toml` `[project].dependencies`, then `.venv/bin/pip install python-multipart` (or `.venv/bin/pip install -e .`). Verify `import multipart` works before writing the route.
- **Settings:** add `max_upload_bytes: int = 200 * 1024 * 1024`. Confirm `PYTXT_MAX_UPLOAD_BYTES` is accepted by the unknown-env-var validator (it iterates `cls.model_fields`, so it should). Surface it to routes via `request.app.state.settings.max_upload_bytes` (settings is already on `app.state`).
- **`references.py` — upload** (spec §6.8). Mirror the GET's `reference_dir` lookup (503 if None):

```python
@router.post("/references", status_code=201, response_model=ReferenceLibraryEntry)
async def upload_reference(request: Request, file: UploadFile = File(...)) -> ReferenceLibraryEntry:
    reference_dir = getattr(request.app.state, "reference_dir", None)
    if reference_dir is None:
        raise HTTPException(503, "Reference library not configured")
    cap = request.app.state.settings.max_upload_bytes
    try:
        path = _resolve_in_library(reference_dir, file.filename or "")
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    if path.exists():
        raise HTTPException(409, f"Reference already exists: {path.name}")
    # stream to disk with a running cap; unlink + 413 on overflow
    written = 0
    try:
        with open(path, "wb") as fh:
            while chunk := await file.read(1 << 20):
                written += len(chunk)
                if written > cap:
                    fh.close(); path.unlink(missing_ok=True)
                    raise HTTPException(413, f"Upload exceeds {cap} bytes")
                fh.write(chunk)
        # parse-validate; bad .mat → delete + 422
        await asyncio.to_thread(load_reference_mat, path)
    except ReferenceLoadError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Not a valid reference .mat: {e}")
    except HTTPException:
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise
    st = path.stat()
    return ReferenceLibraryEntry(name=path.name, size_bytes=st.st_size,
                                 modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc))
```

- **`references.py` — download** (spec §6.8). `FileResponse` with octet-stream + attachment filename:

```python
@router.get("/references/{name}")
async def download_reference(request: Request, name: str) -> FileResponse:
    reference_dir = getattr(request.app.state, "reference_dir", None)
    if reference_dir is None:
        raise HTTPException(503, "Reference library not configured")
    try:
        path = _resolve_in_library(reference_dir, name)
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    if not path.exists():
        raise HTTPException(404, f"Reference not found: {name}")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)
```

- **Imports:** `from fastapi import UploadFile, File, HTTPException, Request`; `from fastapi.responses import FileResponse`; `import asyncio`; `from datetime import datetime, timezone`; `from pytxt.handlers.reference import _resolve_in_library, InvalidReferenceNameError`; `from pytxt.domain.reference import load_reference_mat, ReferenceLoadError`. Reuse `ReferenceExistsError`/`ReferenceNotFoundError` semantics via inline HTTPExceptions (or import + raise-then-map for symmetry with cmd.py — pick one and note it).
- **`{name}` route ordering:** define `/references/{name}` **after** the static `/references` GET/POST so FastAPI doesn't shadow them — they differ by method/path so it's fine, but keep `{name}` last for clarity.

**Tests (`test_reference_upload_download.py`, spec §10.3):**
- `test_upload_round_trip`: build a synthetic `.mat` in `tmp_path` via `save_reference_mat`, read its bytes; `POST /api/v1/references` multipart (`files={"file": ("foo.mat", data, "application/octet-stream")}`) → 201 + entry; `GET /api/v1/references` now lists `foo.mat`; `POST /cmd/load_ref {"name":"foo.mat"}` → 200, `reference_loaded`.
- `test_download`: after upload, `GET /api/v1/references/foo.mat` → 200 and `resp.content == data`.
- `test_upload_collision`: upload `foo.mat` twice → second is 409.
- `test_upload_bad_mat`: `POST` junk bytes as `bad.mat` → 422, **and assert the file was deleted** (`not (reference_dir/"bad.mat").exists()`).
- `test_upload_bad_name`: filename `../escape.mat` / `a/b.mat` / `noext` → 422.
- `test_download_not_found` / `test_download_bad_name`: 404 / 422.
- (Optional) `test_upload_over_cap`: set `PYTXT_MAX_UPLOAD_BYTES` small (or inject settings) and upload larger → 413. If injecting a custom cap is awkward through `create_app`, note it and cover the cap path in a focused unit test instead.
- Build the app with `create_app(state=..., settings=Settings(...), reference_dir=tmp_path)` so `app.state.settings.max_upload_bytes` exists.

**Settings test:** extend `tests/unit/test_settings.py` — default `max_upload_bytes == 200*1024*1024`; `PYTXT_MAX_UPLOAD_BYTES=1048576` override accepted.

- [ ] **Step 1:** Add `python-multipart` to `pyproject.toml`; install; verify `import multipart`.
- [ ] **Step 2:** Add `Settings.max_upload_bytes` + test.
- [ ] **Step 3:** Add upload + download routes to `references.py`.
- [ ] **Step 4:** Write `test_reference_upload_download.py`.
- [ ] **Step 5:** Run + commit.

```
.venv/bin/pytest tests/integration/test_reference_upload_download.py tests/unit/test_settings.py tests/integration/test_reference_load_save.py -v
```

Commit: `feat(api): M4 Task 1 — multipart POST /references + GET /references/{name} + upload cap`

---

## Task 2: `GET /result/ref/raw` (lazy re-parse drill-down)

**Files:** `pytxt/api/routes/result.py`, `tests/integration/test_result_ref_raw.py` (new)

**Notes:**
- Mirror `get_bpm_raw` (`result.py:9-42`) but source from the **loaded reference file**, not `last_acquire_raws`. Re-parse lazily (decision §1):

```python
@router.get("/result/ref/raw", response_model=BpmRawWaveforms)
async def get_ref_bpm_raw(request: Request, bpm: str = "") -> BpmRawWaveforms:
    if not bpm:
        raise HTTPException(400, "Query param 'bpm' is required")
    state = request.app.state.app_state
    if not state.reference_loaded:
        raise HTTPException(404, "No reference loaded")
    path = state.reference_file_path
    if path is None:                      # promoted ref → no file, no waveforms
        raise HTTPException(404, _NO_WF_DETAIL)
    ref = await asyncio.to_thread(load_reference_mat, path)
    if ref.raws is None:                  # MATLAB-only schema
        raise HTTPException(404, _NO_WF_DETAIL)
    raw = ref.raws.get(bpm)
    if raw is None:
        raise HTTPException(404, f"BPM not in reference: {bpm}")
    return BpmRawWaveforms(
        bpm_prefix=raw.prefix,
        x_nm=raw.x_wf.tolist(), y_nm=raw.y_wf.tolist(), sum_au=raw.sum_wf.tolist(),
        armed=raw.armed, read_timestamp=raw.read_timestamp,
    )

_NO_WF_DETAIL = "Reference has no full waveforms (loaded from MATLAB-only schema)"
```

- **Imports:** `import asyncio`; `from pytxt.domain.reference import load_reference_mat`; reuse the existing `BpmRawWaveforms` import (already used by `get_bpm_raw`).
- Note: `bpm` keys in `ref.raws` are the **canonicalized** names (`load_reference_mat` strips `:SA:X` suffixes). The query `bpm=SR01C:BPM1` matches the canonical key — confirm against a saved fixture.

**Tests (`test_result_ref_raw.py`, spec §10.3):**
- `test_result_ref_raw_pytxt_ref`: acquire (synthetic) → `save_ref` (PyTxT schema → has waveforms) → `load_ref` → `GET /api/v1/result/ref/raw?bpm=<first prefix>` → 200, `len(x_nm)==100000` (or the synthetic length), `bpm_prefix` matches.
- `test_result_ref_raw_no_ref`: fresh state → 404 "No reference loaded".
- `test_result_ref_raw_missing_bpm_param`: no `bpm` → 400.
- `test_result_ref_raw_unknown_bpm`: loaded ref, `bpm=SR99X:BPM9` → 404.
- `test_result_ref_raw_matlab_only` (also satisfies `test_legacy_mat_file_loads`): load the real `legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat` (MATLAB-only, `raws is None`) → `GET .../ref/raw?bpm=SR01C:BPM1` → 404 with the explanatory detail; assert `detail == _NO_WF_DETAIL`. If the legacy file isn't readable in CI, fall back to a synthetic MATLAB-only `.mat` (save R0+BPMs without the `*_wf` vars) and note it.
- `test_result_ref_raw_promoted`: acquire → `promote_ref` (no file) → 404 explanatory detail.

- [ ] **Step 1:** Add the route to `result.py`.
- [ ] **Step 2:** Write `test_result_ref_raw.py`.
- [ ] **Step 3:** Run + commit.

```
.venv/bin/pytest tests/integration/test_result_ref_raw.py tests/integration/test_acquire_via_rest.py -v
```

Commit: `feat(api): M4 Task 2 — GET /result/ref/raw lazy reference-waveform drill-down`

---

## Task 3: Frontend — 4-panel layout switch + diff render + tooltip/status extension

**Files:** `pytxt/frontend/trajectory.html`, `pytxt/frontend/js/trajectory.js`, `pytxt/frontend/css/theme.css`

**Notes (spec §5.4):**
- **HTML:** add two more `.canvas-wrap` blocks — `#canvasDX` (label "ΔX (mm)") and `#canvasDY` (label "ΔY (mm)") — inside a grid container that the CSS toggles. Wrap the four canvases in a `.panel-grid` whose class flips between `panels-2` and `panels-4`. Add a status-header `<span id="trajectoryDiffRms">` (hidden until ref loaded) for the `Δ rms: X=… · Y=… mm` row (spec §5.4 "Status header gains one row").
- **CSS (`theme.css`):** `.panel-grid.panels-2` → single column, two rows (current look); `.panel-grid.panels-4` → 2×2 grid. Add `--canvas-dx`/`--canvas-dy` custom props (pick distinct hues from `--canvas-x/y`). ΔX/ΔY panels auto-range to `±max(|diff|)` — that's a render concern, below.
- **`trajectory.js`:**
  - Add `state.dx`, `state.dy` (Float arrays) and `state.refLoaded` (bool).
  - **Subscribe** to `RESULT:BPM:X_DIFF_FIRST_TURN` → `state.dx`, `RESULT:BPM:Y_DIFF_FIRST_TURN` → `state.dy`, and `STATE:REF_LOADED` → `state.refLoaded` (mirror the existing `connection.subscribe(prefix + "RESULT:BPM:X_FIRST_TURN", …)` calls at lines 278-309). Each callback ends in `redraw()`.
  - **`redraw()`** (currently lines 252-261): when `state.refLoaded`, set the grid class to `panels-4` and call `render(canvasDX, state.dx, color_dx)` + `render(canvasDY, state.dy, color_dy)`; else `panels-2`. The diff arrays are NaN-filled by the IOC when no ref → guard `render` against all-NaN (draw the empty grid, as it likely already does for empty data).
  - **Auto-range:** the existing `render()` presumably scales to data min/max. The ΔX/ΔY panels should scale to `±max(|diff|)` symmetric about zero — if `render` doesn't already center on zero, add an optional `symmetric` arg or a small wrapper for the diff panels. Inspect `render()`'s scaling (lines ~160-205) before deciding; keep the change minimal.
  - **Tooltip** (`showTooltipAt`, lines 57-70): when `state.refLoaded`, append `ΔX=<dx[i]> ΔY=<dy[i]>` (mm, fixed precision) to the existing `.tt-values` line for BPM index `i`.
  - **Status header** (lines 256-260): when `state.refLoaded` and a diff is present, show `#trajectoryDiffRms` = `Δ rms: X=<x_rms> · Y=<y_rms> mm`. The rms values come from the `/state` snapshot `last_diff` (`DiffSummary.x_rms_mm/y_rms_mm`) — either fetch `/api/v1/state` after each acquire, or compute rms client-side from `state.dx/dy`. Prefer the snapshot value (authoritative; matches the backend summary). Note the choice.
- **Do not** break the 2-panel phase-2 layout when no ref is loaded — `panels-2` must render pixel-identically to today (the phase-2 e2e `trajectory.spec.js` still has to pass).

- [ ] **Step 1:** HTML — add ΔX/ΔY canvases + grid container + diff-rms span.
- [ ] **Step 2:** CSS — `panels-2`/`panels-4` grid + diff canvas colors.
- [ ] **Step 3:** JS — diff/ref subscriptions, 4-panel redraw, symmetric auto-range, tooltip + status extension.
- [ ] **Step 4:** Manual smoke (synthetic reader) + run the existing phase-2 e2e to confirm no 2-panel regression.

```
cd tests/e2e && npx playwright test trajectory.spec.js smoke.spec.js
```

(If Playwright browsers aren't installed: `cd tests/e2e && npx playwright install chromium`.)

- [ ] **Step 5:** Commit.

Commit: `feat(frontend): M4 Task 3 — 4-panel ΔX/ΔY layout switch + diff render + tooltip/status`

---

## Task 4: Frontend — reference sidebar + dialogs (`js/reference.js`)

**Files:** `pytxt/frontend/js/reference.js` (new), `pytxt/frontend/trajectory.html`, `pytxt/frontend/css/theme.css`

**Notes (spec §5.4, §6.11):**
- **HTML:** add a `.reference-sidebar` container to the right of the canvas row, with: a status block (`#refName`, `#refSource`, `#refLoadedAt`, or "No reference loaded"), and five buttons — `#promoteRefBtn` ("Promote current"), `#loadRefBtn` ("Load…"), `#saveRefBtn` ("Save current…"), `#uploadRefBtn` ("Upload .mat"), `#clearRefBtn` ("Clear"). Add lightweight dialog containers (hidden `<div>`s or `<dialog>`): a load-picker (`#loadRefDialog` with a `<ul id="refList">`), a save dialog (`#saveRefDialog` with `<input id="saveRefName">`), and a hidden `<input type="file" id="uploadRefInput" accept=".mat">`.
- **`reference.js`** (new module; load it after `trajectory.js` in `trajectory.html`):
  - **Subscribe** to `STATE:REF_LOADED`, `STATE:REF_NAME`, `STATE:REF_SOURCE`, `STATE:REF_LOADED_AT` via `connection.subscribe`; render the sidebar status block on each update. (`trajectory.js` already owns `STATE:REF_LOADED` for the layout switch — that's fine, multiple subscribers per PV are supported; or expose a tiny shared flag. Keep modules independent: both subscribe.)
  - **Promote:** `#promoteRefBtn` → `connection.command("promote_ref", {})`. Disable when there's no last acquire (track via `STATE:LAST_ACQUIRE_OK_COUNT` or the acquire status the page already has).
  - **Load:** `#loadRefBtn` → `fetch("/api/v1/references")` → populate `#refList` with `name` + `modified_at`; clicking an item → `connection.command("load_ref", {name})` → close dialog.
  - **Save:** `#saveRefBtn` → open `#saveRefDialog` with `#saveRefName` prefilled to the MATLAB timestamp default (`YYYY-MM-DD_HH:MM:SS_reference_trajectory.mat`, local-ish — or leave blank to let the backend default); confirm → `connection.command("save_ref", {name})` (empty → backend timestamp default).
  - **Upload:** `#uploadRefBtn` → click hidden `#uploadRefInput`; on `change`, `POST /api/v1/references` with `FormData` (`fd.append("file", file)`) via `fetch` (NOT `connection.command`, which targets `/cmd/*`). On 201 → refresh the picker list; on 409/422 → surface an inline error.
  - **Clear:** `#clearRefBtn` → `connection.command("clear_ref", {})`.
  - Error handling: each command/fetch wraps in try/catch and shows a small inline message (the sidebar already re-renders from the resulting `STATE:REF_*` PV updates, so success needs no manual state-poke — the PV subscription is the confirmation, per CLAUDE.md §1 observability).
- **CSS:** `.reference-sidebar` styling (compact, right of `.panel-grid`); dialog/overlay styling. Keep it consistent with the existing dark theme custom properties.
- **Parity note:** every button maps to a CMD that already has CA + REST parity from M2/M3 — the UI adds no new command paths (CLAUDE.md §1). Upload is the one REST-only action (a file's bytes can't be a PV — the acknowledged §15 gap).

- [ ] **Step 1:** HTML — sidebar + buttons + dialogs + file input.
- [ ] **Step 2:** `reference.js` — subscriptions + 5 button handlers + load picker + save dialog + multipart upload.
- [ ] **Step 3:** CSS — sidebar + dialog styling.
- [ ] **Step 4:** Manual smoke against the synthetic reader (load/save/upload/promote/clear round-trip in a browser).
- [ ] **Step 5:** Commit.

Commit: `feat(frontend): M4 Task 4 — reference sidebar + load/save/upload/promote/clear dialogs`

---

## Task 5: Playwright e2e — `reference.spec.js`

**Files:** `tests/e2e/reference.spec.js` (new)

**Notes (spec §10.4 — single happy-path scenario, mirrors `trajectory.spec.js`):**
- Reuse the web-server config already in `playwright.config.js` (`PYTXT_USE_SYNTHETIC_READER=1`, baseURL `http://127.0.0.1:8008`). No config change needed — new spec is auto-discovered (`*.spec.js`).
- Steps:
  1. `goto('/trajectory.html')`; wait `#connectionStatus[data-state="connected"]`.
  2. Click `#acquireButton`; wait `#trajectoryStatus` contains "OK". Assert the page is in 2-panel mode (`.panel-grid.panels-2` present, or `#canvasDX` not visible).
  3. Click `#promoteRefBtn`; wait for 4-panel (`.panel-grid.panels-4` / `#canvasDX` visible). Assert ΔX/ΔY render (canvas pixels) — right after promote, diff is ~zero, so assert the **panels exist and are drawn** (grid + zero line) rather than non-zero pixels.
  4. Click `#acquireButton` again; assert ΔX/ΔY now show **non-zero** somewhere (synthetic reader varies per call) — sample `getImageData()` for a colored diff pixel, mirroring `trajectory.spec.js`'s pixel check (decision §7).
  5. Click `#saveRefBtn`, accept the default name, confirm → wait for the save to succeed (sidebar still shows a loaded ref; optionally assert via `GET /api/v1/references` that a new file appears — Playwright can `request.get`).
  6. Click `#clearRefBtn`; wait for 2-panel return (`.panel-grid.panels-2`).
  7. Click `#loadRefBtn`; in `#loadRefDialog` click the just-saved file; wait for 4-panel return; ΔX/ΔY ~zero everywhere (freshly-loaded ref vs the acquire it was saved from → assert panels drawn; exact-zero is acceptable to assert loosely).
- Use generous waits (`{timeout: 10000}`) on acquire/load steps as the existing specs do. Single worker (already configured) avoids the shared-IOC port clash.
- Run the **full** Playwright suite to confirm no regression in the 5 phase-2 specs.

- [ ] **Step 1:** Write `reference.spec.js` (7-step happy path).
- [ ] **Step 2:** Run the new spec, then the whole e2e suite.

```
cd tests/e2e && npx playwright test reference.spec.js
cd tests/e2e && npx playwright test
```

- [ ] **Step 3:** Commit.

Commit: `test(e2e): M4 Task 5 — reference workflow Playwright happy-path spec`

---

## Task 6: Closeout — decision log + roadmap (Phase 3 complete) + final verification

**Files:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-decisions.md`, `PyTxT-roadmap.html`, `docs/PyTxT-overview.md` (public-surface refresh)

**Decision-log entries (dated 2026-06-01, match the file template):**
1. `/result/ref/raw` re-parses the reference from disk lazily (no waveform cache in AppState); promoted + MATLAB-only refs both 404 via the same `_NO_WF_DETAIL` path.
2. Upload validates by parse-then-keep-or-delete; collision checked before write; `max_upload_bytes` Settings field (200 MB default) → 413.
3. `python-multipart` added as a hard dependency (was absent) — required by `UploadFile`.
4. No `DELETE /references/{name}` (deferred per §15).
5. Frontend: 2-panel↔4-panel via a `.panel-grid` class toggle on `STATE:REF_LOADED`; ΔX/ΔY auto-range symmetric ±max|diff|; Δrms row sourced from `/state` `last_diff` (authoritative) vs client recompute — record which was used.
6. Upload is the one REST-only UI action (no CA path to push file bytes — the acknowledged §15 file-vs-PV asymmetry); every other sidebar button hits an existing parity'd CMD.
7. Any surprises (legacy `.mat` readability in CI; canonical-name matching in `ref/raw`; symmetric-range refactor of `render()`; e2e flake notes).

**Roadmap (`PyTxT-roadmap.html`) — flip Phase 3 to complete:**
- Hero: `M1 ✓ · M2 ✓ · M3 ✓ · M4` → `M1 ✓ · M2 ✓ · M3 ✓ · M4 ✓`; `.progress-fill`/`.progress-text` `75%` → `100%`; Phase-3 narrative → "M4 (upload/download + 4-panel frontend + e2e) landed — **Phase 3 complete**"; next = Phase 4 (Threading workflow).
- Phase 3 milestone tracker: M4 card `ms now` → `ms done` / `✓ Done`; Phase 3 `<details>` badge → `… · M4 ✓`, mark the M4 `<li>` done; if there's a Phase-level status chip, flip Phase 3 `phase now` → done and Phase 4 → `phase now`/next.
- Stats: tests count (pytest + Playwright — report exact numbers from the final run); unpushed-commits count (`git rev-list --count origin/main..HEAD` + 1 for this closeout commit).
- Recent activity: prepend a `Phase 3 ✓` entry + the M4 commits.
- Validate: CSS classes exist, `<details>` open/close balance, `html.parser` parses clean — before committing.

**Overview (`docs/PyTxT-overview.md`):** refresh the live REST surface (add `POST/GET /references`, `GET /references/{name}`, `GET /result/ref/raw`) and the status line (Phase 3 complete) per CLAUDE.md "refresh when the public surface changes."

- [ ] **Step 1:** Append decision-log entries.
- [ ] **Step 2:** Update + validate the roadmap; refresh the overview.
- [ ] **Step 3:** Final verification — full pytest + full Playwright.

```
.venv/bin/pytest -q
cd tests/e2e && npx playwright test
.venv/bin/python -c "from pytxt.api.routes import references, result; print('M4 routes import ok')"
git log --oneline -12
git status
```

Report exact pass/fail/skip counts for both suites (account for the known CA flake `test_acquire_partial_fail.py::test_partial_fail_state_pvs_published` — re-run in isolation if it's the only failure; note the M3-hardening fix should have reduced it).

- [ ] **Step 4:** Commit.

Commit: `docs(roadmap+decisions+overview): M4 closeout — Phase 3 reference trajectory complete`

---

## Notes for the implementer

- **Parity is the contract** (CLAUDE.md §1): the sidebar buttons map 1:1 to existing CMDs with CA+REST parity. The *only* REST-only action is multipart upload — a file's bytes can't be a PV (acknowledged §15). Don't invent UI-only command paths.
- **Bulk content stays out of PVs and AppState** (CLAUDE.md §3, decision §1): `ref/raw` re-parses from disk; upload/download are REST. No 100k-sample arrays in process state.
- **Domain stays I/O-free** (CLAUDE.md §5): no new logic in `domain/reference.py`; M4 only *calls* `load_reference_mat` from the adapter layer (wrapped in `asyncio.to_thread`).
- **Don't regress phase-2** : the 2-panel layout and its e2e (`trajectory.spec.js`) must stay green. Run it after every frontend task.
- **Subagent command shape:** `.venv/bin/pytest`, not `source .venv/bin/activate`. Playwright runs from `tests/e2e/` via `npx playwright test`.
- **Known flake:** `test_acquire_partial_fail.py::test_partial_fail_state_pvs_published` (CA loopback / dual-IOC) — the M3-hardening commit `9087972` added a beacon absorber + dedicated-port fix; if it still flakes, re-run in isolation before treating as a regression.
- **Stop at the Phase-3 boundary:** no Phase-4 threading-workflow work (`srinjectoneshot`/`steppv`), no `DELETE /references`, no response-matrix math. If you reach for any of those, stop — they're out of scope.
