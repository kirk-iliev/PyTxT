# PyTxT Phase 5 — Operator-Grade UI + 18-Step Feature Parity (+ Analysis Polish)

**Status:** Design (drafted from manual ↔ UI ↔ backend triangulation; awaiting Kirk's review)
**Date:** 2026-06-09
**Scope:** Phase 5 of 6 (per `PyTxT-project-plan.html` — "Analysis polish; full GUI feature parity with the 18-step MATLAB manual; tab-structured frontend")
**Owner:** Kirk
**Drafted with:** Claude (Opus 4.8)
**Builds on:** [Phase 4 spec](2026-06-01-phase-4-threading-design.md) (the command/state surface this UI renders)
**Source investigation:** `docs/TxT_GUI_manual.pdf` (the 18-step workflow that defines parity); current `pytxt/frontend/`; the Phase 1–4 command + state surface.

---

## 1. Purpose

Phases 1–4 built a complete **agent-callable** machine: 8 commands with PV+REST parity,
a full readable state surface, a stable domain core. The browser UI, by contrast, was
grown bottom-up — one panel per milestone, just enough to demonstrate each phase worked.
The result is functional scaffolding with a developer-grade landing page (a "Ping"
diagnostic), three flat pages, and **roughly a third of the backend's capability
unsurfaced** (corrector apply, injection firing, raw TBT signal, threading history).

Phase 5 closes that gap. It delivers the **human-callable** half of the north-star
("agent-callable first, human-callable second" — the second still has to be *good*),
measured against the 18-step `TxT_GUI` manual, plus the analysis-polish math the plan
bundles into this phase.

This phase is **almost entirely desk work over an already-stable command surface** —
it does not touch the IOC, the CA client, or the safety-gated write paths except to
*render* them. That makes it the right work for the calendar gap before the Phase-4
control-room validation shift (which is blocked on beam time, not code).

Two threads, deliberately separable:

1. **Frontend overhaul + parity** (the bulk) — a design system, real information
   architecture, a dashboard home, and panels for every shipped-but-unsurfaced
   capability. No new backend.
2. **Analysis polish** (one milestone) — new I/O-free `domain/` math (Gaussian fits on
   first-turn data, dispersion, kick angle, orbit-RMS metrics) published as new
   `RESULT:*`/`STATE:*` PVs, then surfaced. This is the only thread that adds backend.

Phase 5 does **not** add closed-orbit correction, LOCO, BBA, tune-scan, or RF-correction
workflows — those MATLAB tabs are out of PyTxT scope (§9).

---

## 2. North-star principles binding this design

The five north-star principles (`CLAUDE.md`) continue to apply. Phase 5's concrete
obligations:

- **Agent-callable first, human second** — Phase 5 adds **no UI-only command paths.**
  Every action a panel triggers goes through an existing (or, for analysis polish, a
  new) PV+REST command. New analysis results are published as PVs *first*, then
  rendered. The browser stays "just another CA client that happens to render images."
- **PVs are the canonical state interface** — New analysis outputs (Gaussian fit
  params, dispersion, kick angle, orbit RMS) are `RESULT:*`/`STATE:*` PVs with
  description strings, subscribable by Phoebus and Osprey identically to the browser.
- **REST/WS handles only what PVs can't** — Bulk raw-waveform fetch for the TBT viewer
  uses the existing `GET /result/bpm/raw` (not PVs); live scalars stay on PVs/WS.
- **Forward-looking layout** — Frontend grows a real module structure (shared
  components, per-panel modules) rather than more flat files. New analysis math lands
  in `domain/` (numpy-only), confined behind adapters.
- **Domain logic is I/O-free** — Gaussian/dispersion/kick/RMS math is pure numpy in
  `domain/`, testable in milliseconds, no FastAPI/caproto.

---

## 3. What already exists (verified 2026-06-09)

**Frontend (`pytxt/frontend/`, ~1,650 lines):**

| Page | Quality | Covers |
|---|---|---|
| `index.html` | diagnostic | Ping: version/heartbeat/uptime/ping count + event log |
| `trajectory.html` | **polished** | first-turn X/Y + ΔX/ΔY canvases, interactive tooltip, acquire button, full reference sidebar (promote/load/save/upload/clear) |
| `threading.html` | functional-plain | thread params form, start/stop, live status grid (status/running/iteration/RMS) |

Shared: `css/theme.css` (431 lines, dark theme, CSS custom props), `connection.js`
(WS auto-reconnect CA bridge), per-page JS modules.

**Backend surface available to render (all Phase 1–4, tested):**

- **8 commands** (PV+REST parity): `ping`, `acquire`, `promote_ref`, `clear_ref`,
  `load_ref`, `save_ref`, `step_cm`, `inject_oneshot`, `thread_start`, `thread_stop`.
- **State PVs**: health/liveness, acquire status + failure detail (`STATE:LAST_ACQUIRE_*`
  incl. `FAILED_BPM_NAMES`, `FAIL_REASON`), reference state, corrector step state
  (`STATE:CM_LAST_*`), injection state (`STATE:INJ_LAST_*`), threading loop state
  (`STATE:THREAD_*`, `RESULT:THREAD_RMS`).
- **Result PVs**: `RESULT:BPM:{X,Y,SUM}_FIRST_TURN`, `{X,Y}_DIFF_FIRST_TURN`,
  `INJECTION_TURN`, `NAMES`.
- **Bulk REST**: `GET /result/bpm/raw` (100k-sample TBT x/y/sum), `GET /result/ref/raw`,
  `GET /references` (+ POST upload, GET `{name}` download), `GET /state`, `GET /config`.

**Greenfield for this phase:** Gaussian-fit / dispersion / kick-angle / orbit-RMS
domain math (none exists); a design system; a dashboard; corrector, injection, raw-TBT,
and threading-history UI.

---

## 4. Parity scorecard — 18-step manual vs. PyTxT

The authoritative gap map. Each step is classed: ✅ done · 🔨 UI gap (backend ready) ·
🧮 needs analysis backend · ⏸ deferred-backend · 🚫 out of scope.

| # | Manual step | Backend | UI today | Class | Phase-5 milestone |
|---|---|---|---|---|---|
| 1 | Set Up BPMs | config/startup | implicit | ✅/minor | U1 (surface in dashboard) |
| 2–3 | Open/configure SR BPM Control Panel | external app | n/a | 🚫 | — (operator uses SR BPM app) |
| 4 | Select injection-chain steps | `ACQUIRE` bundles arm+readout | acquire button | 🔨 minor | U1/U2 (chain status display) |
| 5 | Run + observe **raw** Sum/H/V (~250 turns) | `GET /result/bpm/raw` | **none** | 🔨 **major** | **U2 (raw TBT viewer)** |
| 6 | Record / flush injection shots | none | save_ref only | 🚫 | — (references cover persistent save) |
| 7 | Continuous-mode injection | threading loop | none | ✅ folded | U5 (threading is the loop) |
| 8 | One-turn trajectory | `RESULT:*_FIRST_TURN` | trajectory.html | ✅ done | — (polish in U0) |
| 9 | Set reference trajectory | promote/save/load/clear | trajectory.html | ✅ done | — |
| 10 | Shot-to-shot variation | re-acquire + diff | trajectory.html diff | ✅ done | — |
| 11 | Correction demo (excite corrector) | `STEP_CM` | **none** | 🔨 **major** | **U3 (corrector panel)** |
| 12 | Set Up Corrector Magnets | catalog (config) | **none** | 🔨 minor | U3 (catalog browse) |
| 13 | Calculate Response Matrix | ⏸ deferred (cached, no pySC runtime) | none | ⏸ | U3 (show cached-matrix metadata only) |
| 14 | Pseudo-inverse + Tikhonov/gain + **SV spectrum** | ⏸ partly deferred | none | ⏸ | U3 (SV-spectrum panel, gated on deferred work) |
| 15 | Calculate CM step | folded into threading (M⁺·dR) | none | ✅ folded | U5 |
| 16 | **Plot CM step** (HCM/VCM bars) | `step_cm` computes deltas | **none** | 🔨 | **U3 (bar chart)** |
| 17 | Apply CM step | `STEP_CM` | **none** | 🔨 **major** | **U3 (apply w/ CAS guard)** |
| 18 | Trajectory-correction result (iterate) | threading loop | threading.html (plain) | 🔨 | **U5 (loop visualization)** |
| + | Injection firing | `INJECT_ONESHOT` | **none** | 🔨 **major** | **U4 (injection control)** |
| + | Analysis: RMS / dispersion / kick / Gaussian fits (manual §8 note + plan) | none | none | 🧮 | **U6 (analysis polish)** |

**Reading the scorecard:** of 18 steps, 4 are done-and-good (8–10 + folded 7), 5 are
out-of-scope or deferred-backend, and the actionable UI work is ~6 focused builds. The
MATLAB "calculate response matrix → pseudo-inverse → calc CM step → plot → apply" manual
loop (13–17) is *deliberately automated* into one `THREAD_START` closed loop — so we
surface it as **one threading panel + one manual corrector panel**, not five buttons.

---

## 5. Information architecture & navigation

Replace the three flat links with a tab-structured shell (the plan's explicit ask):

```
┌─ PyTxT ─────────────────────────────────────────────  ● connected ─┐
│  Dashboard │ Trajectory │ Correctors │ Injection │ Threading │ Diagnostics │
└─────────────────────────────────────────────────────────────────────┘
```

- **Dashboard** (U1) — new home; at-a-glance state + nav. Replaces the Ping page.
- **Trajectory** (existing, polished in U0) — first-turn + reference + diff. Gains a
  **Raw TBT** sub-view (U2) and an **Analysis** readout strip (U6).
- **Correctors** (U3) — catalog, CM-step bar chart, manual `STEP_CM` apply, SV-spectrum
  placeholder.
- **Injection** (U4) — safety-gated `INJECT_ONESHOT` fire control + last-shot echo.
- **Threading** (U5) — existing controls + RMS-history plot + convergence guidance.
- **Diagnostics** — Ping/health, raw `GET /state` inspector, acquire-failure detail,
  links to OpenAPI. (Demotes the old index content here, where it belongs.)

The Ping page doesn't disappear — it *moves* to Diagnostics, freeing `/` for a real home.

---

## 6. Visual design direction

Keep the existing dark theme as the base (it already reads as professional); formalize
it into a small **design system** so every panel looks intentional and identical in
construction. No CSS framework (north-star #4) — vanilla CSS custom properties +
component classes.

**Tokens (extend `theme.css`):** the existing `--bg/--fg/--accent/--green/--red/--border`
palette, plus a spacing scale, a type scale, elevation/border tokens, and **semantic
state colors** (idle/active/ok/warn/danger) so a "running" loop, a "clamped" corrector,
and a "gun-armed" injection all read consistently.

**Shared components (the consistency lever):**

- `panel` — titled card with optional toolbar (every page is panels on a grid).
- `state-pill` — colored status chip (RUNNING/CONVERGED/REFUSED/FIRED…) used everywhere.
- `readout` — label + monospace value + unit, NaN/never-aware.
- `action-button` — primary/secondary/**danger** variants; danger carries a built-in
  confirm affordance (used by Apply CM Step and Fire).
- `plot-canvas` — the Phase-3 auto-scaled polyline canvas, extracted from `trajectory.js`
  into a reusable module (multi-series, NaN-gap aware, sector ticks, hover tooltip).
- `bar-chart-canvas` — new, for the HCM/VCM step bars (manual step 16).

**Safety as a visual language.** Phase 4 is the first phase that commands the
accelerator. The UI must make that *unmissable*: `inhibit`/`allow_gun_fire` state, the
top-off precondition, and corrector limits get dedicated danger-styled banners — not
buried form fields. A fire button when the gun is live looks different from one in
`inhibit=1`.

### 6.1 Dashboard mockup (U1)

```
┌─ PyTxT ──────────────────────────────────  ● connected · v0.x · up 4:12:07 ─┐
│  [Dashboard] Trajectory  Correctors  Injection  Threading  Diagnostics       │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌─ Machine / Liveness ───────┐  ┌─ Last Acquisition ────────────────────┐    │
│  │ Heartbeat   ▲ 14728         │  │ Status      ● OK                       │    │
│  │ Uptime      4:12:07         │  │ BPMs        118 ok · 2 fail            │    │
│  │ Version     0.x             │  │ Inj turn    median 37                  │    │
│  │ IOC prefix  OSPREY:TEST:..  │  │ When        12:41:08                   │    │
│  └─────────────────────────────┘  │ Failed      SR05C:BPM2, SR11C:BPM1 ⚠  │    │
│                                    └────────────────────────────────────────┘  │
│  ┌─ Reference ────────────────┐  ┌─ Threading Loop ──────────────────────┐    │
│  │ ● Loaded  2026-06-01_ref    │  │ Status      ○ IDLE (last: CONVERGED)   │    │
│  │ Source    file              │  │ Iteration   6 / 6                      │    │
│  │ Δ rms     X 0.42 · Y 0.31mm │  │ Orbit RMS   0.18 mm                    │    │
│  │ Coverage  118 / 120 BPMs    │  │ [ Open Threading → ]                   │    │
│  └─────────────────────────────┘  └────────────────────────────────────────┘  │
│                                                                                │
│  Quick actions:  [ ▶ Acquire ]   [ Open Trajectory → ]   [ Correctors → ]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

Every tile is read-only state pulled from PVs the dashboard subscribes to; "Quick
actions" reuse existing commands. The failed-BPM list (currently published but never
shown) surfaces here and on Diagnostics.

### 6.2 Corrector panel mockup (U3)

```
┌─ Correctors ──────────────────────────────────────────────────────────────────┐
│  Family: ( HCM ▾ )   Catalog: 96 devices · source family2dev (✓ confirmed A2)   │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌─ Last CM-step result ──────────────────────────────────────────────────┐    │
│  │  ● APPLIED   family HCM · 11 applied · 1 clamped · 12:43:55             │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─ CM step (computed Δ, A) ──────── manual step 16 ──────────────────────┐    │
│  │   +6e-4┤                          ██                                    │    │
│  │        │        ██      ██  ██    ██  ██                                 │    │
│  │      0 ┼──██────██──██──██──██────██──██──────────────────  HCM index    │    │
│  │        │  ██                                      ██                     │    │
│  │   -6e-4┤                                          ██                     │    │
│  │          1   2   3   4   5   6   7   8   9   10   11                     │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─ Apply step (manual STEP_CM) ──────────────────────────────────────────┐    │
│  │  Device   [ SR01C:HCM1 ▾ ]    Δ (A) [ +0.0010 ]                         │    │
│  │  Expected prior (A): 0.042  (read ← )   Tol: 0.05   Limit: ±0.5 A       │    │
│  │  ☐ Dry run                                                              │    │
│  │  ⚠ Writes a live corrector. Compare-and-set guarded.                    │    │
│  │                                              [ Dry-run ]  [ ‼ Apply ]   │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─ SV spectrum ──────────────────────────────────────────────────────────┐    │
│  │  (gated on deferred response-matrix generation — placeholder until then) │    │
│  └────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

The Apply panel is a thin, guarded UI over `CMD:STEP_CM`: it surfaces the D5
compare-and-set guard (`expected_prior_a`, with a "read current" button), the per-device
limit clamp, and dry-run — exactly the safety contract the spec defined, made visible.

### 6.3 Injection control (U4) — sketch

A single Fire panel over `CMD:INJECT_ONESHOT`: `bucket` (default 308), `gun_bunches`,
`mode`, and the safety triad rendered as a prominent state block — `inhibit` (default 1 =
gun blocked), `allow_gun_fire` (must be explicitly toggled for `inhibit=0`), and the
top-off precondition indicator. Last-shot echo (`STATE:INJ_LAST_*`). When `inhibit=0` +
`allow_gun_fire`, the whole panel goes danger-styled with a typed confirm.

---

## 7. Milestones

Ordered for incremental value; each is independently shippable and verified by
Playwright. U0–U5 add **no backend**; U6 is the only one that does.

- **U0 — Design system + shell.** Extend `theme.css` tokens; build shared components
  (`panel`, `state-pill`, `readout`, `action-button`, extracted `plot-canvas`); build
  the tab shell + routing across pages; re-skin existing trajectory/threading pages onto
  the system. *Exit:* all current pages render on the new shell with no capability
  regression; Playwright nav test green.
- **U1 — Dashboard home.** New `/` per §6.1, subscribing to existing state PVs; move
  Ping content to Diagnostics. *Exit:* dashboard reflects live state; failed-BPM detail
  visible.
- **U2 — Raw TBT viewer.** Sum/H/V multi-turn plot (manual step 5) over
  `GET /result/bpm/raw`, per-BPM selectable, on the Trajectory tab. *Exit:* selecting a
  BPM renders its 3 traces; handles missing/failed BPMs.
- **U3 — Corrector panel** (§6.2): catalog browse, CM-step bar chart, guarded manual
  `STEP_CM` apply, SV-spectrum placeholder. *Exit:* dry-run + apply paths exercised
  against fake IOC; CAS-refusal and clamp feedback rendered.
- **U4 — Injection control** (§6.3): safety-gated `INJECT_ONESHOT` panel + last-shot
  echo. *Exit:* fire (inhibit=1) path exercised; gun-live danger state + confirm verified.
- **U5 — Threading observability:** RMS-history plot across iterations
  (`rms_history_mm` from the response / `RESULT:THREAD_RMS` stream), convergence/
  divergence status with next-action guidance, per-iteration corrector-move display.
  *Exit:* a dry-run loop renders its RMS curve and terminal status with guidance text.
- **U6 — Analysis polish (backend + UI):** new I/O-free `domain/` math — orbit-RMS
  metrics, Gaussian fits on first-turn data, dispersion, kick angle (plan §"12–14");
  publish as new `RESULT:*`/`STATE:*` PVs with descriptions + REST parity; surface as an
  Analysis readout strip on Trajectory. *Exit:* domain unit tests (numpy, ms-fast); new
  PVs published + parity-tested; UI strip renders fits.

**Sequencing note:** U0 first (everything depends on the shell). U1–U5 are independent
after U0 and can be reordered by priority — U2/U3/U4 close the biggest parity gaps; U6 is
separable and can trail (it's the one with backend risk and is least tied to the manual's
core threading workflow).

---

## 8. Testing strategy

- **Playwright e2e** per milestone, extending the existing suite (10 specs today),
  driven against the fake BPM IOC (`tests/fixtures/fake_bpm_ioc.py`) — same harness Phase
  4 used. Each panel gets: renders-state, command-round-trips, error/refusal-path tests.
- **Domain unit tests** for U6 math (pytest, numpy-only, no IOC).
- **Visual consistency** is enforced by the shared components, not snapshot tests
  (avoid brittle pixel diffs); a single "every page mounts on the shell" smoke test
  guards the IA.
- **No new parity surface** for U0–U5 (they call existing commands), so the Phase-4
  REST↔CA keystone parity test is unchanged; U6 adds its new commands/PVs to it.

---

## 9. Out of scope (explicit)

Carried from the project plan and manual; **do not build UI for these:**

- **SR BPM Control Panel** (manual steps 2–3) — a separate MATLAB app; the operator sets
  pilot-tone/beam-current there. PyTxT only *assumes* it's configured.
- **Shot recording / flush** (manual step 6) — no backend; the reference library covers
  the persistent-save need.
- **BBA, RF Correction, Tune Scan tabs** (MATLAB center tabs) — out of PyTxT scope.
- **Closed-orbit / multi-turn correction, LOCO** — not in any PyTxT phase.
- **Response-matrix generation + live SV spectrum** (manual steps 13–14) — backend is
  *deferred* (runtime uses a cached M⁺, no pySC). U3 ships a labeled placeholder; the
  live SV-spectrum panel lands when that deferred work does. **Not a Phase-5 blocker.**

---

## 10. Open decisions (resolve during implementation)

- **D1 — Tab shell mechanism:** multi-page (separate HTML per tab, current pattern) vs.
  single-page with client routing. *Lean:* keep multi-page + a shared header component
  (simplest, matches current vanilla-JS approach, no router dependency) unless shared
  live state across tabs argues otherwise.
- **D2 — Plot library:** keep hand-rolled Canvas (Phase-3 `plot-canvas`) vs. adopt a
  lightweight charting lib for the bar chart / RMS history / SV spectrum. *Lean:* extend
  the hand-rolled canvas (north-star #4 "no framework"; the trajectory canvas already
  proves it's enough) unless a panel needs interaction the canvas can't cheaply give.
- **D3 — Raw-TBT decimation:** 100k samples/BPM is heavy for the browser. Decimate
  client-side, server-side (new query param), or render windowed? *Lean:* client-side
  decimation for first cut; revisit if sluggish.
- **D4 — U6 analysis math source:** port from which legacy `.m`? Confirm the fit/
  dispersion/kick definitions against `legacy/` before implementing.
- **D5 — Dashboard ↔ live state:** if D1 stays multi-page, each tab subscribes
  independently; confirm the WS bridge handles N concurrent page subscriptions cleanly
  (it should — it's per-connection).

Decisions land in the companion log:
`2026-06-09-phase-5-ui-parity-decisions.md`.

---

## 11. Definition of done

Phase 5 closes when:

- The tab shell + dashboard + Correctors + Injection + Threading-observability + Raw-TBT
  panels ship on the design system, each Playwright-verified against the fake IOC.
- The parity scorecard (§4) shows every 🔨 row resolved (or explicitly deferred with a
  visible placeholder for the ⏸ rows).
- U6 analysis math is published as parity-tested PVs and surfaced.
- `docs/PyTxT-roadmap.html`, `docs/PyTxT-overview.md`, and `CLAUDE.md` status updated.
- No regression in the agent-callable surface (the point of the phase is the human
  surface; the agent surface must remain identical).
