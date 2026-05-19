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

## 2026-05-19 — numpy added as a core project dependency

**Context:** Implementing `tests/fixtures/fake_bpm_ioc.py` (Task A). The test file imports numpy and the fixture uses it to synthesize waveforms.

**Decision:** Added `numpy>=1.26` to `[project.dependencies]` in `pyproject.toml` rather than `[project.optional-dependencies].dev`.

**Why:** numpy is not just a test utility — it will be the primary computation substrate for the domain layer (trajectory windowing, response-matrix math, reference comparison). Putting it in dev-only would mean production code would lack a declared dependency. Phase 2 domain modules will import numpy unconditionally.

**Spec relationship:** Fills gap (spec listed numpy as part of the stack but didn't specify where in pyproject.toml it should live).

**Forward impact:** All phase-2 domain and test files can `import numpy` without qualification. No spec update needed.
