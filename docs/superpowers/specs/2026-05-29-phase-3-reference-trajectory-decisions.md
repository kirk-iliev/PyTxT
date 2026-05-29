# Phase 3 — Implementation Decisions Log

Companion to: [`2026-05-29-phase-3-reference-trajectory-design.md`](2026-05-29-phase-3-reference-trajectory-design.md)

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

## Entries

## 2026-05-29 — Reference and DiffSummary dataclasses in types.py, not reference.py

**Context:** M1 Task 1 — implementing the new `Reference` and `DiffSummary` dataclasses.

**Decision:** Both dataclasses landed in `pytxt/domain/types.py` alongside `RawBPM` and `FirstTurnResult`, NOT inside `pytxt/domain/reference.py` as the spec §6.1 sketch implied.

**Why:** The codebase convention since Phase 2 is "all pure domain dataclasses live in `domain/types.py`; topic-specific modules hold the functions." Following that convention keeps imports simple (callers always grab `from pytxt.domain.types import ...`) and avoids a circular-import risk if `reference.py` ever needs to import another dataclass.

**Spec relationship:** Minor deviation from §6.1; functional surface identical.

**Forward impact:** None. `DiffResult` (mentioned in spec §6.2 for AppState) should also land in `types.py` when M2 wires it.


## 2026-05-29 — BPMs struct stub fields on save

**Context:** M1 Task 3 — implementing `save_reference_mat`, deciding what to put in the `BPMs` struct beyond `Names`.

**Decision:** PyTxT-saved files include `BPMs.Names` (canonical pytxt prefixes), `BPMs.ORDs` (sequential 1..n_bpms `uint16`; we don't have lattice ordinals in pytxt), `BPMs.nBuffer` (int32 100000). Other GUI-visible fields are written as empty arrays: `XGolden`, `YGolden`, `current_mode`, `attenuation`.

**Why:** The MATLAB GUI's loader only consumes `BPMs.Names` and (implicitly) the shape of `R0`. Other fields are GUI display metadata. Stubbing keeps interop honest (a downstream MATLAB script reading `BPMs.XGolden` gets an empty array, not bad data) without requiring pytxt to invent or fetch values it doesn't track.

**Spec relationship:** Fills gap (spec §6.1 said "stub the rest" without enumerating).

**Forward impact:** If a real downstream MATLAB script breaks on empty `XGolden`, populate it from a static config file. Watch for this during M2/M3 control-room testing.


## 2026-05-29 — Full suite is 161 tests with one known-flaky CA integration test

**Context:** M1 closeout — running the full project pytest suite to confirm no Phase-2 regressions from the new pure-domain `reference.py` module.

**Decision:** The full project suite is 161 tests, not the plan's ~151 estimate (121 Phase-2 + 40 new M1 unit tests, since the M1 task breakdown landed 40 reference tests rather than the ~30 estimated). Of these, 160 are deterministic and 1 is KNOWN-FLAKY: `tests/integration/test_acquire_partial_fail.py::test_partial_fail_state_pvs_published`. That CA integration test intermittently times out on the CA loopback transport and passes on retry. It is unrelated to the pure-domain M1 work (M1 touches no caproto / asyncio / PV code).

**Why:** Documenting the real suite size corrects the plan's estimate for future sessions. Flagging the flaky test prevents a future implementer from treating an intermittent CA-loopback timeout as a real regression. The flake's root cause (CA loopback timing / port isolation) is an M3 concern — it should be addressed when M3 does the port-isolation / retry work, not in the pure-domain M1.

**Spec relationship:** Fills gap (the plan's ~151 count was an estimate; this records the measured reality and the flaky test).

**Forward impact:** M3 should add port-isolation / retry hardening to `tests/integration/test_acquire_partial_fail.py` so the CA loopback test is deterministic. Until then, treat a lone `test_partial_fail_state_pvs_published` timeout as the known flake (re-run to confirm), not a regression. `[needs-spec-update]` not required — this is a test-infra note, not a design change.
