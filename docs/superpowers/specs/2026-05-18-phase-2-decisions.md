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
