# M4 — Raw REST + UI polish + Playwright e2e

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 2 by (a) filling in the raw-waveform REST stub, (b) polishing the trajectory plot to operator-readable quality (sector ticks, Y-axis numerics, hover tooltip with click-to-pin, compact timestamp), and (c) adding the first browser-level e2e regression guard.

**Architecture:** Backend change is one route filling — `GET /api/v1/result/bpm/raw` reads from `state.last_acquire_raws[prefix]` and emits the existing `BpmRawWaveforms` schema with 400/404 paths. (We explicitly **drop the 409** the spec line mentioned — see §A in `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §11 M4.) Frontend changes are confined to `pytxt/frontend/{trajectory.html, js/trajectory.js, css/theme.css}`: tooltip module-local state, sector-tick math derived from `state.names`, Y-axis numeric ticks, and an ISO-8601 → compact local-time reformat. Playwright e2e drives the existing `/trajectory.html` against a tiny `SyntheticBpmReader` selected by `PYTXT_USE_SYNTHETIC_READER=1`; the spec asserts canvas pixel content + tooltip visibility on hover.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, caproto (no new caproto surface here), pytest + `httpx.ASGITransport`, vanilla JS + Canvas, Playwright (existing `tests/e2e/` setup).

**Spec source of truth:** `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §11 M4 detailed design (locked 2026-05-24 at commit `37436e6`).

**File map:**

- Modify `pytxt/api/routes/result.py` — Task 1
- Create `tests/integration/test_result_raw_endpoint.py` — Task 1
- Modify `pytxt/frontend/js/trajectory.js` — Tasks 2, 3, 4, 5, 6
- Modify `pytxt/frontend/trajectory.html` — Tasks 3, 4 (canvas height + tooltip div)
- Modify `pytxt/frontend/css/theme.css` — Task 4 (tooltip styles)
- Create `pytxt/ca_client/synthetic_reader.py` — Task 7
- Create `tests/unit/test_synthetic_reader.py` — Task 7
- Modify `pytxt/composition.py` — Task 7 (env-var fork to synthetic reader)
- Create `tests/e2e/trajectory.spec.js` — Task 8
- Modify `tests/e2e/playwright.config.js` — Task 8 (webServer block)
- Append to `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — Task 9
- Modify `PyTxT-roadmap.html` — Task 9

---

## Task 1: Backend — `GET /api/v1/result/bpm/raw?bpm=<prefix>`

**Files:**
- Modify: `pytxt/api/routes/result.py` (currently 7-line stub, top of file)
- Create: `tests/integration/test_result_raw_endpoint.py`

**Notes:**
- Source data: `state.last_acquire_raws: dict[str, RawBPM]`. Populated by `handle_acquire` at `pytxt/handlers/acquire.py:94-100` (only successful BPMs are kept; failed prefixes are absent from the dict).
- `RawBPM.x_wf`/`y_wf`/`sum_wf` are `np.ndarray` of `int32` shape `(100000,)`; the schema wants `list[int]` so use `.tolist()`.
- `RawBPM.armed` is already an int; `RawBPM.read_timestamp` is `datetime`. The Pydantic model handles `datetime` → ISO-8601 automatically.
- Status codes: **400** if `bpm` param missing or empty; **404** if `bpm not in state.bpm_prefixes` (unknown for this deploy) OR `bpm not in state.last_acquire_raws` (no data yet / this BPM was in the last failed-set). No 409 — see spec §A.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_result_raw_endpoint.py`:

```python
"""Integration: GET /api/v1/result/bpm/raw?bpm=<prefix>.

Covers 400 (missing/empty param), 404 (unknown prefix OR no data yet), and
200 happy-path with shape/schema verification.
"""
from datetime import datetime, timezone

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


def _fake_raw(prefix: str) -> RawBPM:
    return RawBPM(
        prefix=prefix,
        x_wf=np.arange(100000, dtype=np.int32),
        y_wf=np.full(100000, -42, dtype=np.int32),
        sum_wf=np.full(100000, 1000, dtype=np.int32),
        armed=0,
        read_timestamp=datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_raw_endpoint_returns_waveform_for_known_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1", "SR01C:BPM2"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=SR01C:BPM1")
    assert r.status_code == 200
    body = r.json()
    assert body["bpm_prefix"] == "SR01C:BPM1"
    assert len(body["x_nm"]) == 100000
    assert len(body["y_nm"]) == 100000
    assert len(body["sum_au"]) == 100000
    assert body["x_nm"][0] == 0
    assert body["x_nm"][99999] == 99999
    assert body["y_nm"][0] == -42
    assert body["armed"] == 0
    assert body["read_timestamp"].startswith("2026-05-24T12:00:00")


@pytest.mark.asyncio
async def test_raw_endpoint_400_on_missing_param():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["SR01C:BPM1"])
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_raw_endpoint_400_on_empty_param():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["SR01C:BPM1"])
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_raw_endpoint_404_on_unknown_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=NOT:A:BPM")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_raw_endpoint_404_when_no_data_yet_for_known_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    # SR01C:BPM2 is a known prefix but has no raw data (e.g. never acquired,
    # or it was in failed_bpm_names of the last acquire).
    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1", "SR01C:BPM2"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=SR01C:BPM2")
    assert r.status_code == 404
```

- [ ] **Step 2: Run the new tests, confirm they fail**

Run: `.venv/bin/pytest tests/integration/test_result_raw_endpoint.py -v`

Expected: all 5 fail with 404 (route not registered) — FastAPI returns `Not Found` because the path doesn't exist. The "200 happy path" test also fails with 404. Confirms the stub really is a stub.

- [ ] **Step 3: Implement the route**

Replace the entire contents of `pytxt/api/routes/result.py`:

```python
"""GET /api/v1/result/* — read-only result endpoints."""
from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.result import BpmRawWaveforms

router = APIRouter(prefix="/api/v1", tags=["result"])


@router.get("/result/bpm/raw", response_model=BpmRawWaveforms)
async def get_bpm_raw(request: Request, bpm: str = "") -> BpmRawWaveforms:
    """Return the most-recent raw TBT waveforms for one BPM.

    Query params:
        bpm: BPM prefix (e.g. ``SR01C:BPM1``). Required and non-empty.

    Returns:
        200: ``BpmRawWaveforms`` with three 100 000-sample int lists.
        400: missing or empty ``bpm`` query parameter.
        404: ``bpm`` is not in the configured prefix list OR no raw data
             is stored for it yet (acquire never ran, or this BPM was in
             the last failed-set so no waveform was kept).

    No 409 path: ``state.last_acquire_raws`` is updated atomically at the
    end of ``handle_acquire`` so readers never see half-written data, even
    during a concurrent acquire.
    """
    if not bpm:
        raise HTTPException(400, "Missing required query parameter: bpm")
    state = request.app.state.app_state
    if bpm not in state.bpm_prefixes:
        raise HTTPException(404, f"Unknown BPM prefix: {bpm!r}")
    raw = state.last_acquire_raws.get(bpm)
    if raw is None:
        raise HTTPException(404, f"No raw waveform data for {bpm!r} yet")
    return BpmRawWaveforms(
        bpm_prefix=raw.prefix,
        x_nm=raw.x_wf.tolist(),
        y_nm=raw.y_wf.tolist(),
        sum_au=raw.sum_wf.tolist(),
        armed=raw.armed,
        read_timestamp=raw.read_timestamp,
    )
```

- [ ] **Step 4: Run the tests, confirm all pass**

Run: `.venv/bin/pytest tests/integration/test_result_raw_endpoint.py -v`

Expected: 5 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/unit tests/integration -v`

Expected: 118 passed (113 prior + 5 new).

- [ ] **Step 6: Commit**

```bash
git add pytxt/api/routes/result.py tests/integration/test_result_raw_endpoint.py
git commit -m "feat(api): M4 — implement GET /result/bpm/raw with 400/404 paths"
```

---

## Task 2: Frontend — Y-axis numeric ticks

**Files:**
- Modify: `pytxt/frontend/js/trajectory.js` (the `render()` function, currently lines 40-94)

**Notes:**
- Three ticks on the left edge of each canvas: top = `+maxAbs`, middle = `0`, bottom = `−maxAbs`, with `maxAbs` already computed inside `render()` at line 57-61. The middle tick aligns with the existing dashed zero line.
- Two decimals, leading sign (use `+` and `−` for non-zero values, plain `0.00` for zero). Append `mm` to the top label only so the axis unit is declared once per panel.
- Tick text is drawn inside the plot area near `x = 4` (left padding), with a small filled background swatch (`var(--canvas-bg)`) so it doesn't clash with the polyline. Use `font: 10px var(--monospace)`, fill `#888`.

- [ ] **Step 1: Read the current `render()` to confirm scope**

Run: `sed -n '40,94p' pytxt/frontend/js/trajectory.js`

Expected: see the existing function body — zero line drawn at `cy`, `yScale` computed from `maxAbs`, polyline + dot overlay.

- [ ] **Step 2: Implement the Y-axis ticks**

In `pytxt/frontend/js/trajectory.js`, inside `render()`, **after** the existing dot-overlay loop (i.e. just before the closing `}` of `render` at the line currently reading `}`), append:

```js
    // Y-axis numeric ticks: +maxAbs / 0 / -maxAbs, two decimals, mm on top.
    ctx.fillStyle = '#888';
    ctx.font = '10px ' + (getComputedStyle(canvas).getPropertyValue('--monospace').trim() || 'ui-monospace, Menlo, monospace');
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const fmtTick = (v, withUnit) => {
      const abs = Math.abs(v).toFixed(2);
      if (v === 0) return '0.00';
      const sign = v > 0 ? '+' : '−';  // unicode minus for visual width parity
      return sign + abs + (withUnit ? ' mm' : '');
    };
    const tickValues = [maxAbs, 0, -maxAbs];
    const tickYs = [8, cy, h - 8];
    for (let k = 0; k < 3; k++) {
      const label = fmtTick(tickValues[k], k === 0);
      ctx.fillText(label, 4, tickYs[k]);
    }
```

- [ ] **Step 3: Visual verification**

Start the dev server in one terminal:

```bash
.venv/bin/python -m pytxt
```

In another terminal, trigger an acquire and open the page:

```bash
open http://localhost:8008/trajectory.html
```

Click **Acquire**. Confirm by eye:
- Top-left of each canvas shows e.g. `+0.32 mm`.
- Middle-left shows `0.00` aligned with the dashed zero line.
- Bottom-left shows `−0.32`.
- Polyline still renders correctly.

Stop the server with Ctrl-C in the first terminal.

- [ ] **Step 4: Run the full Python test suite (sanity — no Python touched)**

Run: `.venv/bin/pytest tests/unit tests/integration -v`

Expected: 118 passed.

- [ ] **Step 5: Commit**

```bash
git add pytxt/frontend/js/trajectory.js
git commit -m "feat(frontend): M4 — Y-axis numeric ticks on trajectory canvases"
```

---

## Task 3: Frontend — sector-boundary X-axis ticks + canvas-height bump

**Files:**
- Modify: `pytxt/frontend/trajectory.html` (canvas height attributes, lines 30 and 34)
- Modify: `pytxt/frontend/js/trajectory.js` (`render()` — sector grouping + label drawing)

**Notes:**
- Sector groups computed from `state.names` (length matches the data length). For each entry, regex-extract `SR\d{2}` from the start of the string. Group consecutive same-sector entries into runs of `{sector_label, start_index, end_index}`. Production data has 12 sectors (SR01..SR12).
- **Both canvases** get sector labels so the two stacked plots remain geometrically aligned (per spec §C: keeping label-on-Y-only would create vertical scale mismatch between the two `cy = h / 2` zero-lines).
- Bump canvas height from 160 → 190 to make room for sector labels below the plot area. The label row lives in the bottom ~24 px of the canvas; the polyline still uses the full height minus padding (`yScale` formula stays correct because `cy = h / 2` is recomputed from the new height).
- **Iteration knob:** if labels look cramped at 190 after visual check, bump further (e.g. 200, 210). Spec explicitly allows this.

- [ ] **Step 1: Bump canvas heights in HTML**

In `pytxt/frontend/trajectory.html`, change line 30:

```html
        <canvas id="canvasX" width="800" height="160" aria-label="X position vs BPM index"></canvas>
```

to:

```html
        <canvas id="canvasX" width="800" height="190" aria-label="X position vs BPM index"></canvas>
```

And line 34:

```html
        <canvas id="canvasY" width="800" height="160" aria-label="Y position vs BPM index"></canvas>
```

to:

```html
        <canvas id="canvasY" width="800" height="190" aria-label="Y position vs BPM index"></canvas>
```

- [ ] **Step 2: Adjust `yScale` so labels don't overlap the polyline**

In `pytxt/frontend/js/trajectory.js`, find the line:

```js
    const yScale = (h / 2 - 8) / maxAbs;
```

Replace with:

```js
    // Reserve 24 px at the bottom for sector labels; polyline + Y-ticks
    // share the upper area. cy stays at h/2 so the dashed zero line and
    // both canvases' vertical alignment are unchanged.
    const labelBandH = 24;
    const yScale = (Math.min(cy - 8, h - cy - labelBandH - 4)) / maxAbs;
```

Note: `cy = h / 2 = 95` for h=190, so `h - cy - labelBandH - 4 = 190 - 95 - 24 - 4 = 67`, and `cy - 8 = 87`. The smaller bound (67) governs scaling — polyline never enters the bottom 24 px label band.

- [ ] **Step 3: Add sector-grouping helper at module top**

In `pytxt/frontend/js/trajectory.js`, between the existing `trimTrailingNonFinite` function (ends ~line 38) and `render` (begins ~line 40), insert:

```js
  /**
   * Group consecutive BPM names by ALS sector. Returns an array of
   * { label, start, end } where label is e.g. "SR01" and start/end are
   * inclusive indices into `names`. Names not matching /^SR\d{2}/ are
   * grouped under label "?".
   */
  function sectorGroups(names) {
    const groups = [];
    let current = null;
    for (let i = 0; i < names.length; i++) {
      const m = /^SR\d{2}/.exec(names[i] || '');
      const label = m ? m[0] : '?';
      if (!current || current.label !== label) {
        if (current) groups.push(current);
        current = { label, start: i, end: i };
      } else {
        current.end = i;
      }
    }
    if (current) groups.push(current);
    return groups;
  }
```

- [ ] **Step 4: Draw sector ticks + labels inside `render()`**

In `pytxt/frontend/js/trajectory.js`, **just before** the Y-axis tick block added in Task 2 (i.e. after the dot-overlay loop, before `ctx.fillStyle = '#888'; ctx.font = '10px ...'`), insert:

```js
    // Sector ticks: faint vertical line + label below the plot area.
    const groups = sectorGroups(state.names.slice(0, data.length));
    if (groups.length > 0) {
      ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue('--canvas-grid').trim() || '#2a2a2a';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#888';
      ctx.font = '10px ' + (getComputedStyle(canvas).getPropertyValue('--monospace').trim() || 'ui-monospace, Menlo, monospace');
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const labelY = h - 18;
      const tickTop = h - labelBandH;
      const tickBot = h - labelBandH + 6;
      for (const g of groups) {
        const xStart = xFor(g.start);
        const xEnd = xFor(g.end);
        // Tick at the start boundary
        ctx.beginPath();
        ctx.moveTo(xStart, tickTop);
        ctx.lineTo(xStart, tickBot);
        ctx.stroke();
        // Label centered between start and end
        const xMid = (xStart + xEnd) / 2;
        ctx.fillText(g.label, xMid, labelY);
      }
    }
```

- [ ] **Step 5: Visual verification**

Start dev server, open page, click Acquire:

```bash
.venv/bin/python -m pytxt &
sleep 2
open http://localhost:8008/trajectory.html
```

Confirm by eye:
- Canvases are taller (~190 px).
- Below the polyline, a row of sector labels: `SR01 SR02 SR03 … SR12` (or just `?` if running against the synthetic reader from Task 7 — both behaviors are correct).
- Faint vertical ticks at each sector boundary.
- Polyline doesn't overlap the label row.

Stop the server:

```bash
pkill -f "python -m pytxt" || true
```

**If labels look cramped:** bump canvas heights to `200` or `210` in `trajectory.html`, redo step 5. Log the chosen final height in the decision log at Task 9.

- [ ] **Step 6: Commit**

```bash
git add pytxt/frontend/trajectory.html pytxt/frontend/js/trajectory.js
git commit -m "feat(frontend): M4 — sector-boundary X-axis ticks + canvas height 160 → 190"
```

---

## Task 4: Frontend — hover tooltip (no pin yet)

**Files:**
- Modify: `pytxt/frontend/trajectory.html` (insert tooltip div)
- Modify: `pytxt/frontend/css/theme.css` (tooltip styles)
- Modify: `pytxt/frontend/js/trajectory.js` (tooltip state + mousemove handler)

**Notes:**
- Snap-to-nearest math (per spec §B): `i = round((mx - 10) * (n - 1) / (w - 20))` clamped to `[0, n-1]`, where `n` is the trimmed data length.
- Hover only — click-to-pin is **Task 5**. After this task, every `mouseleave` should hide the tooltip.
- Tooltip content: two lines. Line 1 is the BPM name (bold). Line 2 has `X: ±0.234 mm   Y: ±0.142 mm`, monospace, fixed-width signs so values don't jitter while sweeping.
- Position: tooltip's top-left at `(mouseX + 12, mouseY + 12)` relative to the page (use `event.pageX/pageY`).
- The tooltip needs a single shared instance — both canvasX and canvasY drive it. Sourced from `state.names[i]`, `state.x[i]`, `state.y[i]` always (both canvases show the same BPM index).

- [ ] **Step 1: Add the tooltip div to HTML**

In `pytxt/frontend/trajectory.html`, after the closing `</section>` of `.trajectory-panel` (line ~40) but still inside `<main>`, add:

```html
    <div id="trajectoryTooltip" class="trajectory-tooltip" hidden>
      <div class="tt-name" id="trajectoryTooltipName"></div>
      <div class="tt-values" id="trajectoryTooltipValues"></div>
    </div>
```

- [ ] **Step 2: Add tooltip CSS**

Append to `pytxt/frontend/css/theme.css`:

```css
.trajectory-tooltip {
  position: absolute;
  z-index: 10;
  background: rgba(20, 22, 28, 0.96);
  color: var(--fg);
  border: 1px solid #444;
  border-radius: 4px;
  padding: 0.35rem 0.6rem;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4);
  font-size: 0.82rem;
  pointer-events: none;
  white-space: nowrap;
}
.trajectory-tooltip[hidden] { display: none; }
.trajectory-tooltip .tt-name {
  font-weight: 600;
  font-family: "SF Mono", Menlo, monospace;
}
.trajectory-tooltip .tt-values {
  font-family: "SF Mono", Menlo, monospace;
  color: var(--fg-muted, #9ba0a6);
  margin-top: 0.15rem;
}
```

- [ ] **Step 3: Add tooltip state + helpers in JS**

In `pytxt/frontend/js/trajectory.js`, immediately after the existing `state` declaration (currently lines 22-26), insert:

```js
  const tooltipEl = document.getElementById('trajectoryTooltip');
  const tooltipNameEl = document.getElementById('trajectoryTooltipName');
  const tooltipValuesEl = document.getElementById('trajectoryTooltipValues');

  const tooltip = {
    visible: false,
    pinned: false,    // wired in Task 5
    bpmIndex: -1,
  };

  function fmtMm(v) {
    if (!Number.isFinite(v)) return '   nan';
    const sign = v >= 0 ? '+' : '−';
    return sign + Math.abs(v).toFixed(2);
  }

  function indexForMouseX(canvas, clientX) {
    // Inverse of xFor(i): i = round((mx - 10) * (n - 1) / (w - 20))
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const mx = (clientX - rect.left) * scaleX;
    const data = trimTrailingNonFinite(state.x.length ? state.x : state.y);
    const n = data.length;
    if (n <= 0) return -1;
    if (n === 1) return 0;
    const i = Math.round((mx - 10) * (n - 1) / (canvas.width - 20));
    return Math.max(0, Math.min(n - 1, i));
  }

  function showTooltipAt(pageX, pageY, i) {
    if (i < 0 || i >= state.names.length) { hideTooltip(); return; }
    const name = state.names[i] || `#${i}`;
    const xv = state.x[i];
    const yv = state.y[i];
    if (!Number.isFinite(xv) && !Number.isFinite(yv)) { hideTooltip(); return; }
    tooltipNameEl.textContent = name;
    tooltipValuesEl.textContent = `X: ${fmtMm(xv)} mm   Y: ${fmtMm(yv)} mm`;
    tooltipEl.style.left = (pageX + 12) + 'px';
    tooltipEl.style.top = (pageY + 12) + 'px';
    tooltipEl.hidden = false;
    tooltip.visible = true;
    tooltip.bpmIndex = i;
  }

  function hideTooltip() {
    if (tooltip.pinned) return;  // pin path overrides hide; Task 5
    tooltipEl.hidden = true;
    tooltip.visible = false;
    tooltip.bpmIndex = -1;
  }
```

- [ ] **Step 4: Wire mousemove + mouseleave on both canvases**

In `pytxt/frontend/js/trajectory.js`, inside `bootstrap()`, **after** the existing `acquireButton.addEventListener('click', ...)` block (currently ends around line 165) but **before** the closing `}` of `bootstrap`, append:

```js
    function onCanvasMove(canvas) {
      return (ev) => {
        if (tooltip.pinned) return;  // Task 5 honors pin
        const i = indexForMouseX(canvas, ev.clientX);
        showTooltipAt(ev.pageX, ev.pageY, i);
      };
    }
    function onCanvasLeave() {
      hideTooltip();
    }
    canvasX.addEventListener('mousemove', onCanvasMove(canvasX));
    canvasY.addEventListener('mousemove', onCanvasMove(canvasY));
    canvasX.addEventListener('mouseleave', onCanvasLeave);
    canvasY.addEventListener('mouseleave', onCanvasLeave);
```

- [ ] **Step 5: Visual verification**

```bash
.venv/bin/python -m pytxt &
sleep 2
open http://localhost:8008/trajectory.html
```

Click Acquire. Hover over canvasX:
- Tooltip appears near cursor.
- Line 1 shows the BPM name (e.g. `SR01C:BPM1`).
- Line 2 shows `X: +0.32 mm   Y: −0.04 mm` (values match the data at that BPM index).
- Moving the cursor across the canvas snaps tooltip to nearest BPM.
- Leaving the canvas hides the tooltip.
- Hovering canvasY shows the same BPM-indexed values (one tooltip, shared).

Stop the server:

```bash
pkill -f "python -m pytxt" || true
```

- [ ] **Step 6: Commit**

```bash
git add pytxt/frontend/trajectory.html pytxt/frontend/css/theme.css pytxt/frontend/js/trajectory.js
git commit -m "feat(frontend): M4 — hover tooltip showing BPM name + X/Y values"
```

---

## Task 5: Frontend — click-to-pin + dismiss

**Files:**
- Modify: `pytxt/frontend/js/trajectory.js` (pin state + click handlers + close button)
- Modify: `pytxt/frontend/css/theme.css` (close-button styles)

**Notes:**
- Click on canvasX or canvasY toggles `tooltip.pinned`. When pinning, a `×` close-button is appended to the tooltip. When un-pinning (either by clicking the canvas again or clicking the `×` or clicking outside), the tooltip dismisses.
- Document-level click (capture-phase) dismisses when target is neither the tooltip nor either canvas. This catches "click anywhere else on the page."
- When pinned: `pointer-events: auto` on the tooltip so the `×` is clickable. When unpinned: `pointer-events: none` (existing).
- The `×` button is added/removed dynamically rather than always present in the HTML, so that the hover-only tooltip stays minimal.

- [ ] **Step 1: Add close-button CSS**

Append to `pytxt/frontend/css/theme.css`:

```css
.trajectory-tooltip.pinned {
  pointer-events: auto;
  cursor: default;
}
.trajectory-tooltip .tt-close {
  position: absolute;
  top: 2px;
  right: 4px;
  width: 1rem;
  height: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--fg-muted, #9ba0a6);
  border: 0;
  cursor: pointer;
  font-size: 0.9rem;
  line-height: 1;
  padding: 0;
}
.trajectory-tooltip .tt-close:hover { color: var(--fg); }
.trajectory-tooltip.pinned {
  padding-right: 1.4rem;  /* room for × */
}
```

- [ ] **Step 2: Add pin/unpin helpers in JS**

In `pytxt/frontend/js/trajectory.js`, immediately after `hideTooltip()` defined in Task 4, append:

```js
  function pinTooltipAt(pageX, pageY, i) {
    showTooltipAt(pageX, pageY, i);  // ensure visible with current data
    if (tooltip.bpmIndex < 0) return;  // showTooltipAt rejected (e.g. NaN slot)
    tooltip.pinned = true;
    tooltipEl.classList.add('pinned');
    if (!tooltipEl.querySelector('.tt-close')) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tt-close';
      btn.setAttribute('aria-label', 'Dismiss');
      btn.textContent = '×';  // ×
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        unpinTooltip();
      });
      tooltipEl.appendChild(btn);
    }
  }

  function unpinTooltip() {
    tooltip.pinned = false;
    tooltipEl.classList.remove('pinned');
    const btn = tooltipEl.querySelector('.tt-close');
    if (btn) btn.remove();
    hideTooltip();
  }
```

- [ ] **Step 3: Wire canvas-click toggle + document-level outside-click dismiss**

In `pytxt/frontend/js/trajectory.js`, inside `bootstrap()`, just after the mousemove/mouseleave wiring added in Task 4, append:

```js
    function onCanvasClick(canvas) {
      return (ev) => {
        if (tooltip.pinned) {
          unpinTooltip();
          return;
        }
        const i = indexForMouseX(canvas, ev.clientX);
        pinTooltipAt(ev.pageX, ev.pageY, i);
      };
    }
    canvasX.addEventListener('click', onCanvasClick(canvasX));
    canvasY.addEventListener('click', onCanvasClick(canvasY));

    document.addEventListener('click', (ev) => {
      if (!tooltip.pinned) return;
      const t = ev.target;
      if (t === tooltipEl || tooltipEl.contains(t)) return;
      if (t === canvasX || t === canvasY) return;
      unpinTooltip();
    }, true);  // capture phase so we run before bubbling listeners
```

- [ ] **Step 4: Visual verification**

```bash
.venv/bin/python -m pytxt &
sleep 2
open http://localhost:8008/trajectory.html
```

Click Acquire. Then:
- Hover over a BPM in canvasX → tooltip appears (Task-4 behavior, unchanged).
- Click that BPM → tooltip stays where it is (pinned), `×` button appears in top-right.
- Move the mouse away → tooltip stays visible (because pinned).
- Click the `×` → tooltip dismisses.
- Click another BPM → tooltip pins at that new BPM (canvas click reads new index).
- Click outside both canvases (e.g. on the page background) → tooltip dismisses.
- Click the canvas again while pinned → tooltip dismisses (toggle behavior).

Stop server:

```bash
pkill -f "python -m pytxt" || true
```

- [ ] **Step 5: Commit**

```bash
git add pytxt/frontend/css/theme.css pytxt/frontend/js/trajectory.js
git commit -m "feat(frontend): M4 — click-to-pin tooltip with × dismiss + outside-click handling"
```

---

## Task 6: Frontend — compact local-time timestamp

**Files:**
- Modify: `pytxt/frontend/js/trajectory.js` (the line in `redraw()` that uses `state.timestamp`)

**Notes:**
- Current behavior: `state.timestamp` is set verbatim from `STATE:LAST_ACQUIRE_TIMESTAMP` (ISO-8601 with microseconds + offset, e.g. `2026-05-22T21:48:55.518797+00:00`). It's appended to the counts line as-is.
- New behavior: render as `21:48:55 UTC` (or just `21:48:55` for local). Use `new Date(iso).toLocaleTimeString([], { hour12: false })`. On invalid input, fall back to the raw string so nothing disappears.
- This is a `redraw()`-time format; the underlying `state.timestamp` field stays as the ISO string (so external consumers can still read the original form via /api/v1/state).

- [ ] **Step 1: Add a format helper near the top of trajectory.js**

In `pytxt/frontend/js/trajectory.js`, just above the existing `statusName` function (currently around line 28), insert:

```js
  function formatTimestamp(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;  // fallback: invalid input
    return d.toLocaleTimeString([], { hour12: false });
  }
```

- [ ] **Step 2: Use it in `redraw()`**

In `pytxt/frontend/js/trajectory.js`, find the line in `redraw()`:

```js
    trajectoryCountsEl.textContent =
      `${state.okCount} OK · ${state.failCount} FAIL${state.timestamp ? ' · ' + state.timestamp : ''}`;
```

Replace with:

```js
    const ts = formatTimestamp(state.timestamp);
    trajectoryCountsEl.textContent =
      `${state.okCount} OK · ${state.failCount} FAIL${ts ? ' · ' + ts : ''}`;
```

- [ ] **Step 3: Visual verification**

```bash
.venv/bin/python -m pytxt &
sleep 2
open http://localhost:8008/trajectory.html
```

Click Acquire. Confirm:
- Status header counts line ends with `… 107 OK · 0 FAIL · HH:MM:SS` (no microseconds, no `T` separator, no `+00:00`).
- Multiple acquires keep updating the timestamp.

Stop server:

```bash
pkill -f "python -m pytxt" || true
```

- [ ] **Step 4: Commit**

```bash
git add pytxt/frontend/js/trajectory.js
git commit -m "feat(frontend): M4 — compact HH:MM:SS local-time timestamp in status header"
```

---

## Task 7: Synthetic BPM reader for e2e

**Files:**
- Create: `pytxt/ca_client/synthetic_reader.py`
- Create: `tests/unit/test_synthetic_reader.py`
- Modify: `pytxt/composition.py` (env-var fork at the reader-construction point)

**Notes:**
- e2e can't talk to real ALS BPMs — needs a deterministic, no-CA reader that satisfies the `read_all` protocol used by `handle_acquire`. Spec §E says implementer chooses (a) full pytxt against synthetic IOC or (b) in-test stub. We pick a third middle path: a tiny `SyntheticBpmReader` class shipped in `pytxt/ca_client/`, selected at composition time by `PYTXT_USE_SYNTHETIC_READER=1`. Playwright launches pytxt with that env set and gets real end-to-end coverage of the FastAPI + WS + AppState + IOC path with zero CA dependency.
- The synthetic data needs to look enough like real BPM TBT data for `extract_first_turn` to find an injection turn. Looking at the existing M1 test fixture (`tests/integration/test_acquire_via_rest.py::_fake_raw`): `sum_wf` is low (1000) up to index 1370, then high (200000). The first-turn detector keys off the sum_wf rising edge. Match that pattern.
- The synthetic prefix list is small (12 entries, one per sector) so that sector labels (`SR01`..`SR12`) appear in the rendered tooltip text — needed for the e2e regex assertion `/SR\d{2}/`. Generate prefixes as `SR01C:BPM1, SR02C:BPM1, …, SR12C:BPM1`.
- The `read_all` interface: `async def read_all(self) -> dict[str, RawBPM | None]`. Synthetic returns all-success.
- Also need a `start()` method that's a no-op, since composition currently calls `reader.start()` inside `start_reader_after_warmup()`.

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_synthetic_reader.py`:

```python
"""Unit: SyntheticBpmReader produces deterministic RawBPMs matching the protocol."""
import numpy as np
import pytest

from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
async def test_synthetic_reader_read_all_returns_one_raw_per_prefix():
    prefixes = ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    reader = SyntheticBpmReader(prefixes=prefixes)
    await reader.start()
    raws = await reader.read_all()
    assert set(raws.keys()) == set(prefixes)
    for p in prefixes:
        r = raws[p]
        assert isinstance(r, RawBPM)
        assert r.prefix == p
        assert r.x_wf.shape == (100000,)
        assert r.x_wf.dtype == np.int32
        assert r.y_wf.shape == (100000,)
        assert r.sum_wf.shape == (100000,)
        assert r.armed == 0


@pytest.mark.asyncio
async def test_synthetic_reader_sum_wf_has_injection_step():
    """The synthetic sum_wf must rise so domain code can detect the injection turn."""
    reader = SyntheticBpmReader(prefixes=["SR01C:BPM1"])
    await reader.start()
    raws = await reader.read_all()
    sum_wf = raws["SR01C:BPM1"].sum_wf
    # Pre-injection samples are low; post-injection samples are high.
    assert sum_wf[:1000].max() < 10_000
    assert sum_wf[5000:].min() > 50_000


@pytest.mark.asyncio
async def test_synthetic_reader_x_varies_across_prefixes():
    """Each synthetic BPM should produce a different x_wf so the rendered
    polyline isn't a horizontal line."""
    reader = SyntheticBpmReader(prefixes=["SR01C:BPM1", "SR02C:BPM1"])
    await reader.start()
    raws = await reader.read_all()
    x0 = raws["SR01C:BPM1"].x_wf
    x1 = raws["SR02C:BPM1"].x_wf
    assert not np.array_equal(x0, x1)
```

- [ ] **Step 2: Run the test, confirm it fails (module doesn't exist)**

Run: `.venv/bin/pytest tests/unit/test_synthetic_reader.py -v`

Expected: ImportError on `pytxt.ca_client.synthetic_reader`.

- [ ] **Step 3: Implement the synthetic reader**

Create `pytxt/ca_client/synthetic_reader.py`:

```python
"""Deterministic BPM reader for e2e and demo use.

Returns synthetic `RawBPM` waveforms that match the shape and dtype of
real CA reads, with a sum-waveform rising edge at sample 1370 so the
domain's first-turn extraction finds a real injection turn.

Selected at composition time by setting ``PYTXT_USE_SYNTHETIC_READER=1``.
Never used in production — production wires the real ``BpmReader``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from pytxt.domain.types import RawBPM

_N_SAMPLES = 100_000
_INJECTION_INDEX = 1370


class SyntheticBpmReader:
    """No-CA reader returning deterministic per-prefix waveforms.

    The injection-step pattern matches the production sum-waveform shape
    closely enough that `pytxt.domain.first_turn_extract.extract_first_turn`
    detects a sensible per-BPM injection turn.
    """

    def __init__(self, prefixes: list[str]) -> None:
        self.prefixes = list(prefixes)

    async def start(self) -> None:  # noqa: D401 - protocol no-op
        """Match the BpmReader protocol; nothing to connect to."""
        return None

    async def read_all(self) -> dict[str, RawBPM | None]:
        now = datetime.now(timezone.utc)
        out: dict[str, RawBPM | None] = {}
        sum_wf = np.full(_N_SAMPLES, 1000, dtype=np.int32)
        sum_wf[_INJECTION_INDEX:] = 200_000
        for i, prefix in enumerate(self.prefixes):
            # Vary x/y per BPM so the rendered polyline shows a non-flat
            # pattern. Amplitude in nm; rendered as mm after /1e6.
            x_amp = 80_000 + 5_000 * i
            y_amp = 40_000 - 3_000 * i
            x_wf = np.full(_N_SAMPLES, x_amp, dtype=np.int32)
            y_wf = np.full(_N_SAMPLES, y_amp, dtype=np.int32)
            out[prefix] = RawBPM(
                prefix=prefix,
                x_wf=x_wf,
                y_wf=y_wf,
                sum_wf=sum_wf,
                armed=0,
                read_timestamp=now,
            )
        return out
```

- [ ] **Step 4: Run the unit tests, confirm pass**

Run: `.venv/bin/pytest tests/unit/test_synthetic_reader.py -v`

Expected: 3 passed.

- [ ] **Step 5: Wire it into composition**

In `pytxt/composition.py`, find the block:

```python
    bpm_prefixes = load_bpm_prefixes(settings.bpm_prefixes_path)
```

and the later:

```python
    reader = BpmReader(
        prefixes=bpm_prefixes,
        per_pv_timeout_s=settings.bpm_read_timeout_s,
    )
```

Replace the `reader = BpmReader(...)` block (around lines 89-92) with:

```python
    if os.environ.get("PYTXT_USE_SYNTHETIC_READER") == "1":
        # e2e / demo mode: 12 sectors × 1 BPM each, deterministic data, no CA.
        from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
        bpm_prefixes = [f"SR{s:02d}C:BPM1" for s in range(1, 13)]
        reader = SyntheticBpmReader(prefixes=bpm_prefixes)
        logger.info("PYTXT_USE_SYNTHETIC_READER=1 — using SyntheticBpmReader with 12 fake BPMs")
    else:
        reader = BpmReader(
            prefixes=bpm_prefixes,
            per_pv_timeout_s=settings.bpm_read_timeout_s,
        )
```

Note: when the env var is set, we override `bpm_prefixes` *after* the original `load_bpm_prefixes` call. The `state = AppState(... bpm_prefixes=bpm_prefixes)` constructor a few lines below will then see the synthetic 12-entry list. This is intentional so `RESULT:BPM:NAMES` publishes the synthetic prefixes, the WS bridge subscribes to them, and the frontend renders 12-BPM data correctly.

But wait — the AppState construction at line 83 happens **before** the reader construction. Reorder so the env-var check runs first.

Concretely: move the AppState construction so it comes **after** the `if PYTXT_USE_SYNTHETIC_READER` block. The new ordering should be:

```python
    bpm_prefixes = load_bpm_prefixes(settings.bpm_prefixes_path)

    _ensure_local_ioc_in_ca_addr_list(settings.ioc_host, settings.ioc_port)

    if os.environ.get("PYTXT_USE_SYNTHETIC_READER") == "1":
        from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
        bpm_prefixes = [f"SR{s:02d}C:BPM1" for s in range(1, 13)]
        reader = SyntheticBpmReader(prefixes=bpm_prefixes)
        logger.info("PYTXT_USE_SYNTHETIC_READER=1 — using SyntheticBpmReader with 12 fake BPMs")
    else:
        reader = BpmReader(
            prefixes=bpm_prefixes,
            per_pv_timeout_s=settings.bpm_read_timeout_s,
        )

    logger.info(
        "PyTxT %s starting | prefix=%s | ioc=%s:%d | api=%s:%d | bpms=%d (%s) | "
        "EPICS_CA_ADDR_LIST=%r",
        settings.version, settings.pv_prefix,
        settings.ioc_host, settings.ioc_port,
        settings.api_host, settings.api_port,
        len(bpm_prefixes), settings.bpm_prefixes_path,
        os.environ.get("EPICS_CA_ADDR_LIST", ""),
    )

    state = AppState(
        version=settings.version,
        started_at=time.time(),
        bpm_prefixes=bpm_prefixes,
    )
```

Read the current `pytxt/composition.py` lines 67-92 first, then apply the reordering with a single Edit (preserving the surrounding code exactly — only moving the `state = AppState(...)` block after the synthetic-reader branch and inserting the if/else).

- [ ] **Step 6: Smoke-test composition with the env var**

Run:

```bash
PYTXT_USE_SYNTHETIC_READER=1 .venv/bin/python -m pytxt &
sleep 3
curl -s http://localhost:8008/api/v1/state | python -m json.tool | grep -E '"bpm_prefixes"|SR' | head -5
pkill -f "python -m pytxt" || true
```

Expected: 12 `SR0[1-9]C:BPM1` / `SR1[0-2]C:BPM1` entries visible.

Then run an acquire end-to-end:

```bash
PYTXT_USE_SYNTHETIC_READER=1 .venv/bin/python -m pytxt &
sleep 3
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire -H 'Content-Type: application/json' -d '{}' | python -m json.tool
pkill -f "python -m pytxt" || true
```

Expected: `status: "OK"`, `ok_count: 12`, `fail_count: 0`, plus a sensible `injection_turn_median`.

- [ ] **Step 7: Run the full test suite to confirm nothing else regressed**

Run: `.venv/bin/pytest tests/unit tests/integration -v`

Expected: 121 passed (118 prior + 3 new).

- [ ] **Step 8: Commit**

```bash
git add pytxt/ca_client/synthetic_reader.py tests/unit/test_synthetic_reader.py pytxt/composition.py
git commit -m "feat(composition): M4 — SyntheticBpmReader for e2e via PYTXT_USE_SYNTHETIC_READER=1"
```

---

## Task 8: Playwright e2e — trajectory smoke + hover

**Files:**
- Modify: `tests/e2e/playwright.config.js` (add `webServer` block to auto-launch pytxt with synthetic reader)
- Create: `tests/e2e/trajectory.spec.js`

**Notes:**
- Playwright's `webServer` config block starts a command before tests run and tears it down after. Set it to launch pytxt with `PYTXT_USE_SYNTHETIC_READER=1`, wait for `http://127.0.0.1:8008` to respond, then run.
- The existing ping.spec.js and smoke.spec.js currently assume a pre-started server. The new `webServer` block will let them also work without manual setup — but to keep backward-compat for the existing tests (which previously ran against a real-data server), use `reuseExistingServer: true` so a manually-started server still wins.
- Spec asserts (per spec §E):
  1. Navigate to `/trajectory.html`.
  2. Wait for `#connectionStatus` to read `connected` (data-state attribute).
  3. Click `#acquireButton`.
  4. Wait for `#trajectoryStatus` text to contain `OK`.
  5. Assert canvas pixel content via `getImageData(0, 0, w, h).data.some(b => b !== 0)`.
  6. `page.mouse.move(...)` to centre of canvasX.
  7. Assert `#trajectoryTooltip` visible with `textContent` matching `/SR\d{2}/`.

- [ ] **Step 1: Add `webServer` block to playwright.config.js**

Replace `tests/e2e/playwright.config.js` with:

```js
const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const repoRoot = path.resolve(__dirname, '..', '..');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  timeout: 30000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  webServer: {
    command: `${repoRoot}/.venv/bin/python -m pytxt`,
    url: 'http://127.0.0.1:8008',
    reuseExistingServer: true,
    timeout: 15000,
    env: {
      PYTXT_USE_SYNTHETIC_READER: '1',
    },
    cwd: repoRoot,
  },
  use: {
    baseURL: 'http://127.0.0.1:8008',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
```

- [ ] **Step 2: Write the e2e spec**

Create `tests/e2e/trajectory.spec.js`:

```js
const { test, expect } = require('@playwright/test');

test.describe('PyTxT trajectory page', () => {
  test('acquire → render → hover tooltip flow', async ({ page }) => {
    await page.goto('/trajectory.html');

    // Step 1: page loaded and WS connected
    const connStatus = page.locator('#connectionStatus');
    await expect(connStatus).toHaveAttribute('data-state', 'connected', { timeout: 5000 });

    // Step 2: click Acquire, wait for OK status
    await page.locator('#acquireButton').click();
    await expect(page.locator('#trajectoryStatus')).toContainText('OK', { timeout: 10000 });

    // Step 3: confirm both canvases drew something (non-zero pixel content)
    for (const id of ['canvasX', 'canvasY']) {
      const hasContent = await page.evaluate((canvasId) => {
        const c = document.getElementById(canvasId);
        const ctx = c.getContext('2d');
        const data = ctx.getImageData(0, 0, c.width, c.height).data;
        // Skip the dark background (RGB ~10/10/13 ≈ 0a0a0a). Look for any
        // pixel whose green channel is > 50 (polyline is bright green
        // #4ade80) or whose blue channel is > 100 (polyline is bright blue
        // #60a5fa). Tick labels at #888 also count.
        for (let i = 0; i < data.length; i += 4) {
          if (data[i + 1] > 50 || data[i + 2] > 100) return true;
        }
        return false;
      }, id);
      expect(hasContent, `${id} should have rendered pixel content`).toBe(true);
    }

    // Step 4: hover over canvasX centre, expect tooltip to show "SRxx"
    const canvasX = page.locator('#canvasX');
    const box = await canvasX.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

    const tooltip = page.locator('#trajectoryTooltip');
    await expect(tooltip).toBeVisible({ timeout: 2000 });
    const txt = await tooltip.textContent();
    expect(txt).toMatch(/SR\d{2}/);
  });
});
```

- [ ] **Step 3: Run the e2e suite**

Run: `cd tests/e2e && npx playwright test --reporter=list`

Expected: 3 specs pass total (smoke, ping, trajectory). The Playwright `webServer` block will launch pytxt with the synthetic reader, run the tests, then tear it down. If pytxt is already running locally with the synthetic reader, `reuseExistingServer: true` makes Playwright skip the launch step.

If the run hangs at `webServer` startup: the most likely cause is port 8008 being already occupied by a real-reader pytxt — kill it with `pkill -f "python -m pytxt"` and retry. Document this in the decision log at Task 9 if it surfaces.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/playwright.config.js tests/e2e/trajectory.spec.js
git commit -m "test(e2e): M4 — Playwright trajectory spec covering acquire → render → hover"
```

---

## Task 9: Close-out — decision log, roadmap, memory update

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` (append M4 entries)
- Modify: `PyTxT-roadmap.html` (close M4 milestone, mark Phase 2 done)
- Modify: `/Users/kirkiliev/.claude/projects/-Users-kirkiliev-Documents-coding-PyTxT/memory/phase_2_progress.md` (replace M3-done memory with phase-2-complete memory)

**Notes:**
- The decision log format is documented at the top of `2026-05-18-phase-2-decisions.md`. Match that format exactly. Use the entry tag `[m4-raw-rest-and-polish]` as the top-level rollup, plus sub-tags `[m4-raw-rest-no-409]`, `[m4-pin-tooltip]`, `[m4-sector-ticks]`, `[m4-synthetic-reader]` for the individually-locked design choices.
- Roadmap update: hero stat → total test count (should be ~125 — confirm with `pytest --collect-only -q | tail -5`); milestone card for M4 → ✅ closed; "What's next" → Phase 3 (or "Phase 2 complete, awaiting Phase 3 brainstorming"); Recent activity → top 3 M4 commits.
- Memory update (per the auto-memory `feedback_roadmap_freshness` rule, also do this proactively): rewrite `phase_2_progress.md` so its summary reflects "Phase 2 closed; M4 done"; preserve the workflow notes that are still load-bearing.

- [ ] **Step 1: Confirm full test suite + e2e are green before close-out**

Run:

```bash
.venv/bin/pytest tests/unit tests/integration -v
cd tests/e2e && npx playwright test --reporter=list && cd ../..
```

Expected: pytest ~121 passed, Playwright 3 passed. If anything is red, fix before proceeding.

- [ ] **Step 2: Live ring smoke-test (optional but encouraged — Kirk's call)**

Per phase-2 DoD §12.2: deploy to appsdev2, click Acquire against the real ALS BPM list, confirm trajectory renders. Note any deltas in the decision log. Skip this step only if Kirk says so or the ring is in shutdown.

- [ ] **Step 3: Append decision-log entries**

Open `docs/superpowers/specs/2026-05-18-phase-2-decisions.md`, scroll to the end, and append entries following the template at the top of that file. The entries to add:

- `[m4-raw-rest-no-409]` — Dropping the 409 from `GET /result/bpm/raw`. State updates atomically; no half-written reads possible. Symmetric reads are agent-friendlier than blocking-during-acquire. Decision is reversible if Phase 3 surfaces a real concurrency hazard.
- `[m4-pin-tooltip]` — Click-to-pin extends the spec's plain hover. Implementation: dynamic `×` button, document-capture outside-click dismiss, `pointer-events: auto` only when pinned. Open question: keyboard accessibility (Tab-focus the close button) is deferred until we add a broader keyboard story.
- `[m4-sector-ticks]` — Labels on **both** canvases (not just bottom). Reason: keep stacked plots geometrically aligned. Cost: one extra label row; benefit: consistent geometry.
- `[m4-synthetic-reader]` — Composition forks on `PYTXT_USE_SYNTHETIC_READER=1` to a `SyntheticBpmReader` that produces 12 deterministic SRxxC:BPM1 waveforms. Chosen over (a) "spawn fake IOC in pytest" — too heavy for e2e — and (b) "in-Playwright stub" — would leave handler/state path uncovered. Trades a few lines of production code for full FastAPI + IOC + AppState coverage in e2e.
- `[m4-canvas-height]` — Canvas heights bumped from 160 → 190 to fit sector labels. Note the final height actually used (if implementer needed to bump further per Task 3 Step 5 — record whatever value shipped).
- `[m4-playwright-webserver]` — Added `webServer` block to playwright.config.js with `reuseExistingServer: true` so the existing ping/smoke specs still work against a manually-started server. Document any port-8008 collision issues found during Task 8 Step 3.

Each entry uses the timestamp `2026-05-24` (or the actual close-out date). If the on-real-ring validation at Step 2 surfaced surprises, add one more entry `[m4-live-ring-validation]` capturing the findings.

- [ ] **Step 4: Update roadmap**

In `PyTxT-roadmap.html`:
- Hero stats: update test count to actual current count (run `.venv/bin/pytest --collect-only -q tests/unit tests/integration | tail -3` to get the number).
- M4 milestone card: state ✅ closed with completion date.
- "What's next" panel: phase 2 done; phase 3 brainstorming pending.
- Recent activity: top ~4 M4 commits.

- [ ] **Step 5: Update memory**

Rewrite `/Users/kirkiliev/.claude/projects/-Users-kirkiliev-Documents-coding-PyTxT/memory/phase_2_progress.md` so the summary reads "Phase 2 complete (M1+M2+M3+M4); M4 added raw REST endpoint + sector ticks + tooltip + Playwright e2e + SyntheticBpmReader". Preserve the still-useful subagent-workflow notes from the existing version. Update `MEMORY.md` description line to match.

If `PyTxT-roadmap.html` is the canonical status board (per `feedback_roadmap_freshness`), make sure the memory description points to it as the up-to-date dashboard.

- [ ] **Step 6: Commit close-out artifacts**

```bash
git add docs/superpowers/specs/2026-05-18-phase-2-decisions.md PyTxT-roadmap.html
git commit -m "docs(roadmap+log): M4 ✓ closed — Phase 2 done"
```

(Memory commits separately — memory lives in `~/.claude/...`, not the repo.)

- [ ] **Step 7: Final sanity sweep**

Run:

```bash
.venv/bin/pytest tests/unit tests/integration -v
cd tests/e2e && npx playwright test --reporter=list && cd ../..
git log --oneline -10
git status
```

Expected: all green, ~9 M4 commits on `main`, working tree clean (or only the orientation/CLAUDE/README/etc. unstaged changes that were pre-existing).

---

## Notes for the implementer

- **Per CLAUDE.md §1 (Agent-callable first):** the raw REST endpoint must round-trip cleanly via `curl` and via OpenAPI — verify both at least once during Task 1.
- **Per CLAUDE.md §5 (Domain logic is I/O-free):** no domain-package edits in M4. If you find yourself reaching into `pytxt/domain/`, stop and re-read the spec.
- **Subagent commands shape:** if subagent-driven dev is in use, use `.venv/bin/pytest` not `source .venv/bin/activate && pytest` — see memory entry [feedback_subagent_command_shape].
- **Playwright on this machine:** memory entry [feedback_playwright_verification] notes Playwright MCP doesn't render on Kirk's machine; use `open <path>` for visual checks. The `npx playwright test` CLI works fine for the automated spec — that's what Task 8 uses.
- **No mocks of state or app in tests** unless explicitly motivated — the existing integration tests use real `AppState` and `create_app`; follow that pattern.
- **Frontend tasks have no automated unit tests by design** (spec §F: "no JS unit test infrastructure for M4"). The e2e spec is the regression guard; the per-task visual-verification steps are how we validate during implementation.
