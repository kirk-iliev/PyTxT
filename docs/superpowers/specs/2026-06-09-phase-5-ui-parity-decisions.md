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
