# Phase 4 — Implementation Decisions Log

Companion to: [`2026-06-01-phase-4-threading-design.md`](2026-06-01-phase-4-threading-design.md)

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

## 2026-06-01 — Pre-implementation: open design decisions carried from the spec

**Context:** Spec drafted from the source-traced investigation (`docs/phase-4-injection-notes.md`). These are the design choices the spec §8 flags as needing resolution before/during M1–M4. Logged here so the resolutions land in one place as implementation proceeds.

**Decision:** Recommendations recorded; final calls pending Kirk's review:
- **D1 (M⁺ runtime source):** cache an offline-generated matrix; no pySC at runtime. *Recommended.*
- **D2 (units):** fold amps↔kick into offline M⁺; runtime is hardware-amps. *Recommended.*
- **D3 (firing mode):** *Corrected from an earlier conflation.* `inhibit=1` (bumps on stored beam, no first turn) = commissioning/measurement only; **real first-turn threading needs `inhibit=0`** (gun fires). Rec: command defaults to `inhibit=1`; commission pipeline in `inhibit=1`; real threading uses `inhibit=0` behind operator sign-off + prefix promotion. Spec §5.5/§7/§8 + injection-notes updated 2026-06-01.
- **D4 (loop termination):** `max_steps` + divergence guard + optional RMS-convergence early-exit. *Recommended.*
- **D5 (retry safety):** incremental CM steps are non-idempotent — retry contract TBD (step-id or expected-prior-setpoint guard).
- **D6 (bucket default):** 308 vs 1 — needs operator input.

**Why:** Captured up front because each materially shapes M1–M4 code structure (esp. D1/D2 determine whether pySC is a runtime dependency at all).

**Spec relationship:** Mirrors design §8.

**Forward impact:** Convert each to a dated resolution entry when decided. D5 must be resolved before M2 (STEP_CM). D6 and the §9 operator inputs gate M3 (INJECT_ONESHOT).

---

## 2026-06-01 — Corrector channel-name port (pre-M2)

**Context:** Needed the literal SR HCM/VCM setpoint PV names; `getname_als.m` builds them programmatically (no static catalog upstream).

**Decision:** Ported the corrector branch of `getname_als.m` (Setpoint/'AC' type) to `tools/gen_corrector_channels.py` rather than depend on a MATLAB dump.

**Why:** No-MATLAB, reproducible in-repo, mirrors how `config/bpm_prefixes.txt` was produced. The port self-validates: it emits exactly 96 HCM + 72 VCM, matching `mml-audit get_family` device counts (a wrong formula wouldn't).

**Spec relationship:** Implements design §5.3.

**Forward impact:** One residual — `local_maxsp` errors "Sector 1, HCM1 missing" yet the count is 96 with dev1-8×12. Confirm the SR01 device list via a read-only `family2dev('HCM')` dump before committing `config/hcm_channels.txt`. `[needs operator input]`
