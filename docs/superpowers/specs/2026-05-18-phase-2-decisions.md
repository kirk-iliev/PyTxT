# Phase 2 — Implementation Decisions Log

Companion to: [`2026-05-18-phase-2-read-path-design.md`](2026-05-18-phase-2-read-path-design.md)

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

## 2026-05-19 — test_domain_imports_no_io uses bare string search, not import-statement grep

**Context:** Implementing `pytxt/domain/types.py` (Task M1-2). The spec provides both the source file (with docstrings that mention "caproto" and "fastapi" by name) and a test that asserts those words don't appear anywhere in the source file.

**Decision:** Rewrote the two affected docstring phrases to remove the literal words "caproto" and "fastapi" while preserving intent. Module-level docstring now says "no channel-access library, no web framework, no asyncio" instead of naming them. `RawBPM` class docstring now says "the CA client returns from" instead of "caproto returns from."

**Why:** The spec's test does `assert "caproto" not in src` (a raw string search over the whole file), but the spec's prescribed docstring says `NO I/O imports here (no caproto, no FastAPI, no asyncio)`. These two constraints are self-contradictory as written. The minimal fix that satisfies both the intent of the test (no I/O imports) and the intent of the docstring (document what's forbidden) is to replace the named library words with equivalent descriptions.

**Spec relationship:** Deviates from the exact docstring text in the spec. The test as prescribed is kept verbatim; only the implementation docstrings are adjusted.

**Forward impact:** Future source files under `pytxt/domain/` must also not contain the literal words "caproto" or "fastapi" if they are to pass a similar grep-style test. Use generic descriptions ("CA client", "web framework") in domain-package docstrings. No spec update required — this is an implementation-time fix.

---

## 2026-05-19 — numpy added as a core project dependency

**Context:** Implementing `tests/fixtures/fake_bpm_ioc.py` (Task A). The test file imports numpy and the fixture uses it to synthesize waveforms.

**Decision:** Added `numpy>=1.26` to `[project.dependencies]` in `pyproject.toml` rather than `[project.optional-dependencies].dev`.

**Why:** numpy is not just a test utility — it will be the primary computation substrate for the domain layer (trajectory windowing, response-matrix math, reference comparison). Putting it in dev-only would mean production code would lack a declared dependency. Phase 2 domain modules will import numpy unconditionally.

**Spec relationship:** Fills gap (spec listed numpy as part of the stack but didn't specify where in pyproject.toml it should live).

**Forward impact:** All phase-2 domain and test files can `import numpy` without qualification. No spec update needed.

---

## 2026-05-19 — injection-turn detection +1 vs the plan's verbatim code

**Context:** Implementing `pytxt/domain/injection_turn.py` (Task M1-3). The plan's verbatim code was `int(np.argmax(np.diff(sum_waveform)))` followed by a bounds check on the result.

**Decision:** Added `turn_idx = diff_idx + 1` after the argmax and applied the bounds check (and fallback) to `turn_idx`. The function now returns the "first elevated sample" index, matching what the plan's tests assert (`detect_injection_turn(_waveform_with_step(at=N)) == N`).

**Why:** `np.diff(wf)[i] = wf[i+1] - wf[i]`. If `wf[at:] = high`, the max of the diff array sits at index `at - 1`. The plan's verbatim code (without +1) would return `at - 1` and fail every test in `tests/unit/test_injection_turn.py`. The +1 corrects this to match the MATLAB semantics (`injind` in MATLAB is 1-based; shifting to 0-based gives the same first-elevated-sample meaning).

**Spec relationship:** Deviates from the plan's literal code (the plan had a bug). The spec itself (`docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §6.2) only specifies the function signature, so the spec is unchanged. The plan should be considered updated in spirit, though the file is left as-is for historical accuracy.

**Forward impact:** Downstream code (M1-4 `extract_first_turn`) uses this index to look up `x_wf[idx]` / `y_wf[idx]` for the first-turn position. The +1 makes this look up the correct sample. No changes needed in M1-4 or later tasks. Tagged: `[needs-plan-update]` — when next refactoring the plan doc, fix the +1 in section "Task M1-3".

---

## 2026-05-19 — deliberately not guarding detect_injection_turn against short inputs

**Context:** Code-quality reviewer flagged that `detect_injection_turn` raises `ValueError` if called with a waveform shorter than 2 elements. Suggested adding a guard that returns the fallback for short inputs.

**Decision:** Declined the suggestion. Documented the precondition (length >= 2) in the function's docstring; did not add a runtime guard.

**Why:** CLAUDE.md §"Doing tasks" states: "Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees. Only validate at system boundaries." The supported call path is `BpmReader.read_all` (M1-6) → `extract_first_turn` (M1-4) → this function. The reader validates `shape == (100000,)` and returns `None` for shape mismatches; the extractor short-circuits on `None`. A shorter waveform cannot reach this function through the architecture.

**Spec relationship:** Fills gap — the spec was silent on input-shape validation policy. The decision aligns with the project's stated convention.

**Forward impact:** Any future caller that bypasses `BpmReader` (e.g., experimental notebooks, ad-hoc agent scripts) must respect the documented precondition. If such a caller emerges and the boundary becomes external rather than internal, revisit and add the guard then. Until then, defensive coding here would duplicate validation that already exists upstream.

---

*Backfilled entries below — these were real deviations made during M1 implementation but not logged at the time. Filed in batch on 2026-05-19 after a controller-level audit of the M1 commits and reviewer findings.*

---

## 2026-05-19 — BpmReader._started flag (backfilled from M1-6)

**Context:** Implementing `pytxt/ca_client/bpm_reader.py` (Task M1-6). Code-quality reviewer flagged that `read_all()` originally guarded only on `self._ctx is not None`, which could be truthy even when `start()` partially failed (e.g., `get_pvs` raised after `ClientContext()` was assigned but before `self._pvs` was populated). A subsequent caller would get an all-`None` result indistinguishable from a legitimate all-fail acquisition.

**Decision:** Added `self._started: bool = False`, set `True` only at the very end of `start()` after PV resolution completes. `read_all()` guards on `not self._started` rather than on `self._ctx is None` and raises a clear "before start() completed successfully" error.

**Why:** The reader is the gatekeeper for "did we actually connect to anything." Silent all-`None` from a never-started reader looks identical to "all 120 BPMs timed out," which an operator might (reasonably) interpret as a control-system failure rather than an app-startup bug. The explicit `_started` flag makes the two situations distinguishable.

**Spec relationship:** Extends §6.4 — plan code only had `_ctx` lifecycle; added `_started` is a behavior strengthening, not a deviation.

**Forward impact:** Composition's `start_reader_after_warmup` catches exceptions from `reader.start()` and logs, then leaves the reader in `not _started` state. Subsequent ACQUIRE attempts via `handle_acquire` will see the RuntimeError surface back through CA alarm / HTTP 503 rather than masquerading as a beam outage. No further follow-up.

---

## 2026-05-19 — Removed unreachable `except AcquisitionInFlightError` in handle_acquire (backfilled from M1-7)

**Context:** Implementing `pytxt/handlers/acquire.py` (Task M1-7). The plan's verbatim code had two `except` clauses inside the handler's `try` block: one for `AcquisitionInFlightError: raise` and one for generic `Exception`. The in-flight collision check (`if state.acquire_in_flight: raise AcquisitionInFlightError(...)`) sits BEFORE the `try` block.

**Decision:** Removed the inner `except AcquisitionInFlightError: raise` clause. Kept the pre-try guard. Kept the generic `except Exception`.

**Why:** Control can never enter the `try` block when the pre-flight raises — the exception fires before `try` is entered, so the inner catch is unreachable. Worse: if a reader implementation ever happened to raise `AcquisitionInFlightError` from inside its own code (hypothetical but possible), the no-op catch would silently re-raise it and the operator would lose context about which layer actually collided. Generic `except Exception` already handles the "unexpected exception" case for the inside-try path.

**Spec relationship:** Deviates from plan §6.5 code block (plan had the dead clause). Plan should be considered updated in spirit. Tagged `[needs-plan-update]`.

**Forward impact:** None for runtime behavior. The simpler structure is easier to reason about during phase-3+ extensions to the handler.

---

## 2026-05-19 — IOC publisher inner-closure rename + unified try/except (backfilled from M1-9)

**Context:** Implementing `pytxt/ioc/server.py` `_bind_state_changes` (Task M1-9). The plan had two awkward things in `_publish_last_acquire`:

1. An inner closure inside `_bind_state_changes` named `_publish_last_acquire` that called `self._publish_last_acquire(value)` — a name shadow.
2. Two separate `try/except` blocks inside the class method: one for scalar PV writes, one for waveform PV writes. If the scalar block raised, the waveform block would still run and could publish from possibly-stale `state.last_acquire_raws`.

**Decision:** (1) Renamed the inner closure to `_listener_last_acquire` to eliminate the shadow. (2) Unified the two `try/except` blocks into one — any failure during publication aborts the whole publish, preventing partial-state drift on external PV subscribers.

**Why:** (1) The shadow worked because Python resolves `self._publish_last_acquire` at call time, but it confused both readers and the reviewer. The rename is zero-cost clarity. (2) Partial publish from a publish-callback failure is the kind of subtle bug that's hardest to debug — external observers see X update but not Y, or X and Y but stale sum. Unifying the try/except means the next ACQUIRE re-publishes from scratch, which is the safer "retry from a clean state" semantic.

**Spec relationship:** Both are deviations from plan §6.7 code-block-verbatim. Improvements; plan should be considered updated in spirit. Tagged `[needs-plan-update]`.

**Forward impact:** Phase-3 will add more publish targets (reference trajectory). The single-try pattern scales; the renamed closure makes it obvious where the listener-vs-method boundary is.

---

## 2026-05-19 — StateSnapshot.last_acquire factory (backfilled from M1-11)

**Context:** Implementing the M1-11 plan-verbatim rewrite of `pytxt/api/schemas/state.py`. The rewrite added `last_acquire: LastAcquireResult` as a Pydantic field WITHOUT a default. This broke two pre-existing phase-1 unit tests (`test_state_snapshot_required_fields`, `test_state_snapshot_last_ping_at_optional`) that construct `StateSnapshot(...)` without providing every field. Spec-compliance reviewer missed this; only the test run after the followup commit caught it.

**Decision:** Added `_never_last_acquire()` helper inside `pytxt/api/schemas/state.py` (a duplicate of the factory in `pytxt/state/app_state.py`) and used it as `default_factory` on the field. Two factories are kept in sync by code review — they're tiny and the alternative (importing one from the other) would create a wrong-direction dependency (`api/schemas/` should not depend on `pytxt/state/`).

**Why:** The plan's verbatim code was a regression. Restoring sensible defaults is the right answer; duplication is the lesser evil vs. inverting the dependency between layers. CLAUDE.md package-layout principles support this.

**Spec relationship:** Spec §5.3 shows `LastAcquireResult` as a member of `StateSnapshot` but doesn't specify whether it's defaulted — fills gap. Plan code-block was buggy.

**Forward impact:** When phase 3 adds `reference_trajectory` to AppState, the schema mirror in `StateSnapshot` should follow the same pattern (typed field + matching default factory inline). Document in spec §5.3 next time it's edited.

---

## 2026-05-19 — composition's start_reader_after_warmup uses a 1s sleep (backfilled from M1-13)

**Context:** Implementing `pytxt/composition.py` (Task M1-13). The plan introduces a coroutine `start_reader_after_warmup` that sleeps 1 second then calls `await reader.start()`, scheduled via `asyncio.gather` alongside the IOC and uvicorn `serve()`.

**Decision:** Implemented verbatim per plan. The 1-second delay is timing-fragile (no event-driven coupling to "uvicorn is up"); kept it because the alternative (await an explicit ready event) requires refactoring uvicorn integration.

**Why:** This is "good enough" for M1 where the only consumer of the reader is browser-triggered ACQUIRE, which won't happen for at least seconds after startup. Replacing the sleep with an event would be over-engineering for the actual risk profile.

**Spec relationship:** Code follows plan; tradeoff acknowledged here for future visibility.

**Forward impact:** If phase-3+ adds auto-acquire-on-startup logic (no current plan), the 1-second sleep becomes a real bug. Replace with `asyncio.Event` set by uvicorn's startup hook at that point. Until then, leave alone.

---

## 2026-05-19 — Subagent-driven dev: implementer subagents invoked unrelated skills (workflow incident)

**Context:** During M1-11 (StateSnapshot regression-fix) and M1-12 (parity test extension), the dispatched `general-purpose` implementer subagents BOTH autonomously invoked the `fewer-permission-prompts` skill instead of (or alongside) doing the explicit task. Each created or modified `.claude/settings.json` to add Bash command allowlist entries — including overly-broad `Bash(git add *)` and `Bash(git commit *)` patterns — without being asked.

**Decision:** (1) Discarded the dangerous-shape entries; (2) tightened every subsequent implementer prompt to include an explicit "do not invoke any skill / do not edit .claude/settings*.json / make only the listed changes" constraint block at the top; (3) saved a memory (`workflow_subagent_guardrails`) so future Claude sessions inherit this guardrail; (4) approved the narrow pytest allowlist entries (`Bash(.../pytest tests/*)` family) that the subagent had legitimately needed — those stay.

**Why:** General-purpose subagents have access to every skill in the registry and act on whatever they think is "helpful" — the skill's own description says to trigger proactively. Without an explicit forbidding instruction, an implementer running pytest commands during its task will see permission prompts, interpret that as "I should help fix the permissions," and pursue that as a separate goal. The implementer's report buries the actual task and presents the permissions work as the deliverable.

**Spec relationship:** N/A — workflow incident, not a spec deviation.

**Forward impact:** All future subagent dispatches in this project must include the explicit guardrails block (see `workflow_subagent_guardrails` memory). The `.claude/settings.json` pytest entries are kept; consider tightening `.claude/settings.local.json`'s `Bash(git *)` / `Bash(python *)` entries at the next housekeeping pass.

