# Phase 5 — Implementation Decisions Log

Companion to: [`2026-06-09-phase-5-ui-parity-design.md`](2026-06-09-phase-5-ui-parity-design.md)

Append-only log of implementation-time decisions: choices made during coding that weren't in the spec, deviations from the spec, surprises discovered, and tradeoffs taken. Read this alongside the spec for the full picture of what was actually built and why.

## How to use this log

- **One entry per non-trivial decision.** Skip decisions fully covered by the spec; this log is for the deltas.
- **Add entries chronologically**, newest at the bottom.
- **Each entry uses the template below.** Keep entries terse — the goal is a quick read, not exhaustive prose.
- **If a decision invalidates a spec section, update the spec too** (not just log it here). The log is for context; the spec is authoritative.
- **When in doubt, log it.** Future you (and future agents) will thank present you.

## What counts as a non-trivial decision worth logging

- A choice made because the spec was silent on it (filled a gap).
- A deviation from what the spec said (with reason).
- A tradeoff taken (we chose X over Y because Z, where the spec didn't pick).
- A surprise from real code, real CA traffic, real data shapes, or real upstream APIs.
- A library or dependency choice made during implementation.
- An ergonomic refactor extracted during the work (a helper, a shared utility, a pattern).
- A test infrastructure shortcut or workaround.

## What does NOT need to be logged

- Pure bug fixes inside spec'd code.
- Decisions explicitly documented in the spec.
- Style preferences and formatting.
- One-off renames or trivial code shape changes.

---

## Entry template (copy when adding)

```markdown
## YYYY-MM-DD — <short title>

**Context:** What was being implemented when this came up (file/function/milestone).

**Decision:** The choice made (one or two sentences).

**Why:** Rationale, alternatives considered, tradeoffs.

**Spec relationship:** Extends §X / Deviates from §X / Fills gap (spec was silent on this).

**Forward impact:** Does the spec need updating? Does later code need to know? Any follow-ups? Tag with `[needs-spec-update]` if the spec is now out of sync.
```

---

## 2026-06-09 — Phase framed as the plan's Phase 5, UI as the spine

**Context:** Drafting the spec from a manual ↔ UI ↔ backend triangulation, after Kirk asked when to focus on UI.

**Decision:** Treat the UI overhaul as Phase 5 of the locked plan ("Analysis polish; full GUI feature parity with the 18-step MATLAB manual; tab-structured frontend") rather than a new ad-hoc effort. The frontend overhaul is the spine; analysis-polish math is folded in as the single backend-bearing milestone (U6).

**Why:** The project plan already allocates GUI parity + tab-structured frontend to Phase 5, alongside analysis polish. Inventing a separate "UI phase" would fork the plan. Keeping the analysis-polish thread attached preserves the plan's intent while letting the UI lead (which is what's actionable now, in the pre-shift desk-work window).

**Spec relationship:** Establishes the spec's scope (§1).

**Forward impact:** Roadmap/overview should reflect Phase 5 = UI-led + analysis polish when the phase closes.

## 2026-06-09 — Scorecard, not raw 18-step parity, defines "done"

**Context:** Deciding what "full feature parity" concretely means for Phase 5's definition of done (§4, §11).

**Decision:** Parity is measured against the classified scorecard (§4), not literal 1:1 reproduction of all 18 MATLAB steps. Steps 2–3 (external SR BPM app), 6 (shot recording), and the BBA/RF/Tune-Scan tabs are out of scope; steps 13–14 are deferred-backend with a visible placeholder; steps 13–17's manual response-matrix loop is intentionally collapsed into the single `THREAD_START` closed loop + one manual corrector panel.

**Why:** A literal port would build UI for capabilities PyTxT deliberately doesn't have (and shouldn't — the threading loop *automates away* the manual matrix/pinv/calc/apply sequence). Honest parity is "every operator-meaningful capability is reachable and legible," which the scorecard makes auditable.

**Spec relationship:** Defines §4 and §9; drives §11.

**Forward impact:** When closing the phase, audit against §4's 🔨 rows, not the raw manual TOC.

## 2026-06-09 — U0: multi-page shell via injected header (shell.js), not SPA

**Context:** U0 — building the tab shell across `index.html` / `trajectory.html` / `threading.html`.

**Decision:** Resolved open decision **D1** in favor of multi-page + a shared `js/shell.js` that injects the header (brand + 6-tab nav + connection-status) at the top of `<body>` synchronously on load. No client-side router, no SPA. `shell.js` is markup-only and must be the *first* `<script>` on each page.

**Why:** The three existing page scripts (`app.js`, `trajectory.js`, `threading.js`) each look up `#connectionStatus`/`#connectionStatusLabel` at IIFE-execution time and wire `connection.onStatusChange` themselves. Injecting the header synchronously before those scripts run preserves that contract with zero changes to page JS. A router would have meant rewriting all three. `shell.js` deliberately does **not** touch `window.connection` (undefined at that point) — it only renders markup; the per-page scripts keep owning status wiring.

**Why disabled tabs:** Correctors/Injection/Diagnostics pages don't exist until later milestones, so they render as `<span class="nav-tab is-disabled">…<span class="nav-soon">soon</span></span>` (non-navigable, `aria-disabled`) so the full IA is visible now without 404s.

**Spec relationship:** Resolves D1 (§10); implements §5 IA + §6 shell.

**Forward impact:** U1 (dashboard) and later page builds just add an HTML file + flip `ready:true` in `shell.js`'s `TABS`. The `Dashboard` tab points at `/` which still serves the reskinned health/ping content transitionally — U1 swaps that content and moves Ping to Diagnostics.

## 2026-06-09 — U0: defer plot-canvas extraction to U2

**Context:** U0 spec (§6, §7) lists extracting the trajectory Canvas renderer into a reusable `plot-canvas` module among the shared components.

**Decision:** Deferred the extraction to **U2** (raw-TBT viewer), the first milestone that needs a *second* canvas consumer. U0 ships the design-system CSS + shell + reskin only; `trajectory.js`'s proven inline canvas code is left untouched.

**Why:** U0's exit bar is "no capability regression," and the trajectory page is the one already-polished surface. Rewiring its renderer in U0 is pure regression risk for zero U0 benefit — you extract a shared renderer when you have ≥2 consumers (U2 raw-TBT + U3 bar chart + U5 RMS history), not before. This also keeps open decision **D2** (hand-rolled canvas vs. lib) live until there's a real second use case to judge it against.

**Why:** Avoids speculative, untested shared code.

**Spec relationship:** Defers part of §6/§7 U0 scope to U2. Spec text still lists `plot-canvas` under U0 components — treat U2 as its delivery point. `[needs-spec-update]` minor: move `plot-canvas` bullet from U0 to U2 if tidying.

**Forward impact:** U2 owns the extraction; it should refactor `trajectory.js` onto the shared module at that point (or consciously keep them separate and log why).

## 2026-06-09 — U1: fully PV-driven dashboard (no REST poll); shell owns connection status

**Context:** U1 — dashboard home (`index.html` + `dashboard.js`) and the new Diagnostics page.

**Decision (a) — no polling:** The dashboard derives Δrms and reference coverage **client-side from the diff waveform PVs** (`RESULT:BPM:{X,Y}_DIFF_FIRST_TURN`) + `RESULT:BPM:NAMES`, rather than polling `GET /api/v1/state` for `last_diff`/`reference.n_aligned`. Coverage = count of indices finite on both planes, over `NAMES.length`. So every dashboard tile is live over the WS/PV bridge with zero REST polling (north-star #2/#3).

**Decision (b) — shell owns the connection indicator:** Moved connection-status wiring out of per-page scripts and into `shell.js` (deferred to `DOMContentLoaded` so `window.connection` exists). The indicator is part of the shell chrome, so the shell should own it — otherwise every new page must remember to wire it (which `dashboard.js` initially didn't, breaking the smoke spec). Existing page scripts still wire it too; the writes are idempotent. Cleanup of the now-redundant per-page wiring is deferred (low value, non-zero risk).

**Decision (c) — Ping/health → Diagnostics:** Per spec §5, the old `/` "Ping" content moved to a new `/diagnostics.html` (reusing `app.js` verbatim for ping/health + a `diagnostics.js` raw-`/state` inspector + API-discovery links). `ping.spec.js` repointed from `/` to `/diagnostics.html`.

**Why coverage shows 12/128 in dev:** synthetic reader emits 12 BPMs; the IOC pads waveform PVs to 128. Real machine → ~120. Display artifact, not a bug.

**Spec relationship:** Implements §6.1 dashboard + §5 IA (Diagnostics now `ready:true`). Fills a gap the spec left implicit (where connection-status wiring lives).

**Forward impact:** New pages get the connection indicator for free via the shell. The PV-derived-coverage pattern is reusable; if a future tile needs `n_aligned` semantics that differ from "finite on both planes," revisit.

## 2026-06-09 — U2: shared plot.js built; trajectory.js kept bespoke; min/max decimation

**Context:** U2 — raw TBT viewer (`tbt.js` + the `Raw turn-by-turn signal` panel on the Trajectory page), and the deferred-from-U0 shared plot-canvas extraction.

**Decision (a) — new shared renderer, trajectory.js left as-is:** Built `js/plot.js` as a general DPI-aware line renderer and used it for the new viewer. Did **not** migrate the Phase-2 `trajectory.js` renderer onto it. The two have genuinely different jobs: trajectory is value-vs-BPM-index with sector ticks and is tightly coupled to mouse hit-testing for the pin/hover tooltip; plot.js is value-vs-sample with label gutters and envelope decimation. Forcing one renderer to do both would add conditionals for little gain and real regression risk on the polished trajectory page. So "extract the shared module" (U0 deferral) is satisfied by *building the reusable renderer for new consumers*, not by rewriting the working one. The U0 log predicted this option.

**Decision (b) — DPI-aware sizing + gutters fix the overlap by design:** plot.js sizes the backing store to `clientSize × devicePixelRatio` (crisp on 4K) and reserves a left gutter (Y labels) + bottom strip (X labels) so axis text never overlaps the trace. For the *existing* trajectory canvases (still bespoke), the axis-label overlap was fixed minimally by moving the HTML `.axis-label` from top-left to top-right, away from that renderer's left-aligned Y-ticks.

**Decision (c) — min/max-per-column decimation:** 100k samples are decimated to one vertical {min,max} envelope bar per pixel column (resolves open decision **D3** → client-side decimation, first cut). Preserves spikes/envelope, renders fast, no server change. Sparse arrays (≤ 2×width) fall back to a plain polyline.

**Decision (d) — X axis = sample index:** the waveforms are 100k raw samples, so the X axis is labeled `sample` (0..99999), not "turn" (the MATLAB GUI's "index of turn" is a processed view; raw is per-sample). Synthetic reader emits step functions, so dev screenshots look flat-with-a-step — real beam data oscillates.

**Spec relationship:** Implements §4 row 5 + §6 raw-TBT; resolves D2 (keep hand-rolled canvas — plot.js *is* hand-rolled, no charting lib) and D3 (client-side decimation).

**Forward impact:** U3 (bar chart) + U5 (RMS history) should reuse/extend `plot.js`. If a third consumer needs hover hit-testing, consider unifying with the trajectory renderer then — not before.

## 2026-06-09 — U3: synthetic corrector writer + catalog endpoint (backend added); bar chart → U5

**Context:** U3 — Correctors panel (manual `CMD:STEP_CM` with the D5 compare-and-set guard).

**Decision (a) — U3 DID add backend (spec §1 said U0–U5 wouldn't):** The spec assumed U3 was pure frontend because the STEP_CM *backend* was built+tested in Phase 4. But that was tested against a pytest fake-writer fixture; the **dev server has no corrector writer** in synthetic mode (`corrector_writer=None` → 503), and the real `CorrectorWriter` does live EPICS I/O. So the panel couldn't function in dev or Playwright. Added **`SyntheticCorrectorWriter`** (in-memory setpoints, mirrors the writer interface, seeded to a small per-index pattern), wired in `composition.py` under `PYTXT_USE_SYNTHETIC_READER=1`, alongside a read-only **`GET /api/v1/config/correctors`** catalog endpoint (names + limits; also serves agent discoverability). `[spec §1 amended in spirit]` — U3/U4 need a synthetic active-command backend to be demoable; the "frontend-only" claim held only for U1/U2/U5-display.

**Decision (b) — preview reads current via dry-run with tol=∞:** The handler runs the CAS check even on dry-run, and there's no setpoint-read endpoint. So "Preview" sends `dry_run=true, expected_prior_a=[0], tol_a=1e12` — the inflated tolerance disables the guard so the dry-run returns the live `readback_a` (current setpoint) without writing. Apply then uses that readback as `expected_prior_a` with the real tol (0.05), so a competing writer between preview and apply trips the CAS (409 → "REFUSED"). No new read endpoint needed; the guard is demonstrated, not bypassed.

**Decision (c) — CM-step bar chart deferred to U5:** Manual step 16 ("plot the corrector step") plots the *response-matrix-computed* step vector — which is produced by the threading loop (Mplus·dR), and the matrix is deferred. There's no multi-corrector computed step to plot in U3 (the manual panel applies one device). So the bar chart moves to U5 (threading), where a real step vector exists, and `plot.js` gains a `bars()` mode there. U3 shows the per-channel result as a table instead. `[deviates from §4 row 16 / §7 U3]`

**Spec relationship:** Implements §4 rows 11/12/17 + §6.2 apply panel; defers row 16 to U5; amends §1's no-backend claim.

**Forward impact:** U4 (injection) will need the same treatment — a **synthetic injection trigger** so `INJECT_ONESHOT` is demoable in dev (currently `injection_trigger=None` → 503). Plan for it. The catalog endpoint + synthetic writer are reusable by U5's threading commissioning UI.

## 2026-06-09 — U4: synthetic injection trigger; gun-fire guard is the demoable safety

**Context:** U4 — Injection panel (safety-gated `CMD:INJECT_ONESHOT`).

**Decision (a) — synthetic injection trigger (backend, as predicted in U3 log):** Added `SyntheticInjectionTrigger` (in-memory TimInjReq + fine-delay, mirrors the trigger interface), wired in `composition.py` under `PYTXT_USE_SYNTHETIC_READER=1`. Without it `INJECT_ONESHOT` is 503 in dev. `read_bucket_control()` returns 0 (top-off inactive → shots allowed); `sync_seq_busy()` is instant; seqNum increments across shots.

**Decision (b) — gun-fire guard is the headline demoable safety; precondition 409 isn't:** The `inhibit=0 → allow_gun_fire` guard (403) is enforced in the handler *before* any trigger call, so it's fully demoable and is the UI's central safety story — gun-fire mode turns the whole panel danger, requires an explicit opt-in checkbox, and only then enables a red FIRE GUN button. The top-off precondition refusal (409) needs `bucket:control:cmd=1`, which the synthetic trigger hardcodes to 0; demoing it would need a toggle endpoint, deferred (it's unit-tested in pytest). Force checkbox is wired but moot in dev.

**Decision (c) — all six nav tabs now live:** With Injection shipped, no tabs remain disabled; `shell.spec.js` updated (the "disabled tab" test became "all six live").

**Spec relationship:** Implements §4 "+ Injection firing" row + §6.3. Confirms the U3-logged prediction that U4 needs synthetic backend.

**Forward impact:** U5 (threading commissioning) reuses both synthetic active backends (corrector writer + injection trigger) — the loop fires per-step shots and steps correctors. The 409 precondition + real-hardware paths remain control-room validation (Phase-4 checklist B1).

## 2026-06-09 — U5: threading observability; step exposed in response; in-memory synthetic matrix

**Context:** U5 — threading run observability (RMS history, outcome guidance, corrector-step bars), the last UI-display milestone.

**Decision (a) — surface the corrector step via ThreadStartResponse:** Added `step_hcm_a` / `step_vcm_a` (the last computed `dphi`) to `ThreadStartResponse`. The loop computes the step internally but never exposed it. Safe vs. the keystone parity test because that test compares **state diffs** (`_public_state`), not response bodies. This is the data for the U3-deferred bar chart — `plot.js` gained a `bars()` mode (zero-baseline, symmetric range, DPI-aware). Resolves the U3 deferral.

**Decision (b) — in-memory synthetic matrix, sized to live dims:** THREAD_START needs a response matrix (else 503). `data/` is gitignored, so a generated `.npz` wouldn't reach e2e/CI, and a fixed-dim artifact wouldn't match the 12-BPM synthetic reader. So `build_synthetic_response_matrix()` moved from the tool into `pytxt/domain/response_matrix.py` (shared; the tool re-exports it), and composition builds it **in-memory** in synthetic mode sized to `len(bpm_prefixes)` × catalog counts. No file dependency; dims always match; THREAD_START works in dev/e2e out of the box.

**Decision (c) — dev loop diverges (demonstrates guidance, not convergence):** The synthetic BPM reader is *not* a closed loop — it doesn't respond to corrector writes — so applied steps don't change the next acquire, and the jitter makes RMS grow → DIVERGED at iteration 2. That's fine and arguably better for the demo: it exercises the divergence-guidance UI (the realistic operator scenario). True convergence on beam is control-room validation (Phase-4 checklist B4); making the synthetic reader a real closed loop was out of scope.

**Spec relationship:** Implements §4 rows 15/16/18 + §6 U5; closes the U3-deferred bar chart.

**Forward impact:** Only U6 (analysis polish — Gaussian fits / dispersion / kick / orbit-RMS metrics, the one new-domain-math milestone) remains. All five UI-display milestones (U0–U5) are done; the full agent surface is unchanged. `plot.js` now has line + bars; U6 metrics can reuse it.
