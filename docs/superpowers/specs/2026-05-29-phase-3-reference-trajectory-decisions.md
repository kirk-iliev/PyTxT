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


## 2026-05-29 — M2 is backend-only; all frontend work deferred to M4

**Context:** M2 (reference wiring) scope — spec §11 M2 prose mentions "Frontend hover tooltip extended (no layout switch yet)."

**Decision:** M2 ships zero `pytxt/frontend/` changes. All reference-related frontend work (hover-tooltip extension, the 4-panel ΔX/ΔY layout, reference sidebar) lands atomically in M4 alongside the e2e Playwright spec.

**Why:** The M2 *DoD bullets* require only PV/REST parity plus the parity test — not frontend. Splitting frontend across M2 and M4 would mean a partial hover-tooltip change with no e2e coverage. Keeping M2 backend-only makes it fully unit + integration testable with no Playwright dependency, and lets M4 design the layout switch in one coherent pass.

**Spec relationship:** Deviates from §11 M2 prose; the M2 DoD bullets are unaffected.

**Forward impact:** M4 owns the entire reference frontend surface. No follow-up needed in M2/M3.


## 2026-05-29 — ReferenceSource + DiffResult live in domain/types.py, not api/schemas

**Context:** M2 Task 1 — placing the new `ReferenceSource` enum and `DiffResult` dataclass that `AppState` references.

**Decision:** Both landed in `pytxt/domain/types.py`. The Pydantic `pytxt/api/schemas/reference.py` re-exports/re-uses the domain `ReferenceSource` enum rather than defining its own.

**Why:** `AppState` (in `pytxt/state/`) references both types. Defining them in `api/schemas/` would force a `state → api` import, inverting the layering (adapters depend on state/domain, never the reverse). This mirrors the M1 decision to keep `Reference`/`DiffSummary` in `types.py`.

**Spec relationship:** Deviates from the §5.3 sketch (which placed them in `api/schemas/reference.py`); functional surface identical.

**Forward impact:** M3's file-load path should keep building `ReferenceSource.FILE` from the same domain enum; no schema-side enum definition to drift.


## 2026-05-29 — Two publish triggers: reference_loaded drives status, last_diff drives the diff arrays

**Context:** M2 Task 4 — `server.py` IOC publisher wiring the new `STATE:REF_*` bundle and the `RESULT:BPM:{X,Y}_DIFF_FIRST_TURN` waveforms.

**Decision:** Subscribe two independent listeners. `reference_loaded` change → `_publish_reference_status()` (writes `STATE:REF_LOADED/NAME/LOADED_AT/SOURCE`). `last_diff` change → `_publish_diff_arrays()` (writes the diff waveforms; NaN-fills when `last_diff is None`).

**Why:** On a normal acquire while a ref stays loaded, `reference_loaded` does not change (status listener stays quiet) but `last_diff` does → the diff arrays refresh every acquire in lockstep with the first-turn arrays, while the status bundle only republishes on promote/clear. Driving the diff arrays off `last_diff` (not `reference_loaded`) is exactly the §7.5 semantic.

**Spec relationship:** Implements §6.5/§7.5; the two-trigger split is the implementation choice the spec left open.

**Forward impact:** Known cosmetic edge: a re-promote while already loaded leaves `reference_loaded` True→True, so the status listener does not fire and `STATE:REF_LOADED_AT` stays stale until the next clear/promote cycle. Acceptable for M2 (name/source are unchanged under re-promote). If the timestamp ever needs to refresh on re-promote, switch the status trigger to `reference_loaded_at`.


## 2026-05-29 — Promote recomputes the live first-turn rather than storing it on AppState

**Context:** M2 Task 2 — `handle_promote_ref` needs the live first-turn *arrays* to set as the promoted R0, but `handle_acquire` only persists `last_acquire_raws` (dict) + the `LastAcquireResult` summary, not a `FirstTurnResult`.

**Decision:** Option (A) — recompute inside the handler: `extract_first_turn({p: state.last_acquire_raws.get(p) for p in state.bpm_prefixes})`. No new `last_first_turn` AppState field.

**Why:** The IOC publisher (`server.py:_publish_last_acquire`) already re-derives first-turn arrays from `last_acquire_raws + bpm_prefixes` this exact way, so there is a proven helper pattern to mirror. This keeps AppState from carrying a redundant array copy that would have to be kept in sync on every acquire. Since the recomputed first-turn is already aligned to `bpm_prefixes`, `align_to_current` is a no-op for promote; for symmetry we still set `reference_bpm_names = list(state.bpm_prefixes)`.

**Spec relationship:** Implements §7.3; the recompute-vs-store choice (the spec offered both) is resolved here as (A).

**Forward impact:** M3's file-load path supplies `reference_first_turn` from the loaded `.mat` aligned via `align_to_current`, so the field is already the right shape — no AppState migration.


## 2026-05-29 — No-acquire guard uses last_acquire.ok_count == 0; numpy-tolerant update() needed no change

**Context:** M2 Task 2 — confirming the exact `LastAcquireResult` field the promote refusal keys on, plus whether `AppState.update()` needed touching for the new array-bearing fields.

**Decision:** `handle_promote_ref` refuses with `NoLastAcquireError` when `state.last_acquire.ok_count == 0` (no BPM produced a position — covers the initial sentinel and the all-fail case in one check). The numpy-tolerant `AppState.update()` required **no** change: its existing `except (ValueError, TypeError)` equality guard already treats `DiffResult` (holds `dx`/`dy` arrays) and `FirstTurnResult` (holds arrays) as "changed" when an elementwise comparison is ambiguous, so listeners fire correctly for `last_diff` and `reference_first_turn`.

**Why:** `ok_count` is the single field that distinguishes "have a real first-turn to copy" from "nothing acquired yet"; keying on it avoids inspecting raw dicts. Confirming the equality guard already covered the new fields avoided a speculative `update()` change (regression-tested in `test_app_state.py`).

**Spec relationship:** Fills gap — §6.3 said "confirm the exact field name"; this records `ok_count`. §6.2's numpy-tolerance note is confirmed sufficient.

**Forward impact:** None. M3's `LOAD_REF` does not gate on `last_acquire` (it sources from a file), so the `ok_count` guard is promote-specific.


## 2026-05-29 — Integration tests use AsyncMock readers / fake_bpm_ioc, not a SyntheticBpmReader + reference_dir fixture

**Context:** M2 Task 7 — the plan header (and §10.3) referenced reusing "the phase-2 `SyntheticBpmReader` + IOC/REST integration fixtures" and implied a tmp `reference_dir` fixture.

**Decision:** Task 7 followed the *real* phase-2 integration convention instead: `AsyncMock`-based readers and the `fake_bpm_ioc` fixture for CA-loopback acquires. No `reference_dir` fixture was added — M2 is file-free, so there is nothing to back with a directory (file LOAD/SAVE and `reference_dir` are M3).

**Why:** `SyntheticBpmReader` is the e2e/Playwright reader wired via `PYTXT_USE_SYNTHETIC_READER=1` at the composition root; the phase-2 *integration* tests drive acquires through `AsyncMock` readers and `fake_bpm_ioc`, which is the established harness. Adding a `reference_dir` fixture in M2 would be premature scope creep into M3's file backing.

**Spec relationship:** Fills gap / minor deviation from the plan's fixture phrasing; the test coverage (promote/clear via CA + REST, no-acquire refusal, NaN-fill on clear, parity rows) matches §10.3's M2 subset exactly.

**Forward impact:** M3 introduces the tmp `reference_dir` fixture when it adds file LOAD/SAVE; M2's integration tests need no rework.


## 2026-05-29 — `reference_dir` created in composition, not a Settings validator

**Context:** M3 Task 1 — wiring `Settings.reference_dir` (default `Path("data/references")`) through composition into the IOC and REST app.

**Decision:** `Settings` only *declares* the field; the directory is created (`reference_dir.mkdir(parents=True, exist_ok=True)`) in `composition.main()` after `settings.reference_dir.resolve()`, NOT in a `@field_validator` on `Settings`.

**Why:** A mkdir validator fires on *every* `Settings()` instantiation — including the unit-test suite, which constructs `Settings()` repeatedly — and would litter the repo with a stray `data/references/` directory on every test run. Putting the side effect at the composition root keeps `Settings()` pure and side-effect-free; tests inject their own `tmp_path` dirs directly into `create_app`/`PyTxTIOC`.

**Spec relationship:** Deviates from spec §6.12 (which floated a field-validator that mkdir's the path); implements §6.13 (composition-root creation).

**Forward impact:** Any future code that needs the library directory to exist must go through composition or create it itself — never assume `Settings()` made it. No spec update needed beyond noting §6.12's validator was rejected.


## 2026-05-29 — M3 ships only `GET /references`; upload/download/`/result/ref/raw` deferred to M4

**Context:** M3 Task 5 — creating `pytxt/api/routes/references.py`.

**Decision:** M3's `references.py` exposes only `GET /api/v1/references` (the library listing). Multipart `POST /references` (upload), `GET /references/{name}` (download-by-name), and the lazy `GET /result/ref/raw` are explicitly out of scope and land in M4.

**Why:** M3's goal is the CA-reachable half of the reference workflow (LOAD/SAVE via `.mat` files already in the library, plus discovery via listing). Upload/download are bulk-transfer REST concerns tied to the M4 frontend (drag-in a file, download a saved ref); building them now would mean shipping endpoints with no UI consumer and no e2e coverage. `references.py` is structured so M4 extends it rather than rewrites it.

**Spec relationship:** Implements spec §6.8 (GET-only in M3); §11 M4 owns the rest.

**Forward impact:** M4 adds the upload/download routes to the same router. No state model or schema rework needed — `ReferenceLibraryEntry`/`ReferenceLibraryList` already exist.


## 2026-05-29 — SAVE does not mutate AppState; parity SAVE-row asserts identical (none) state effect

**Context:** M3 Tasks 3 & 6 — `handle_save_ref` and its parity-table row.

**Decision:** `handle_save_ref` writes the `.mat` file and returns a `SaveRefResponse` but performs **no** `state.update()` — saving does not auto-load. The parity SAVE row therefore asserts that the CA and REST arms produce *identical* (post-acquire, unchanged-by-save) `_public_state`; the file-write effect is covered separately by the dedicated `test_save_ref_*` integration tests. Each parity arm uses its own `tmp_path` reference_dir so the two saves don't collide on a 409.

**Why:** SAVE's observable confirmation is the file appearing in the library (+ `GET /references` listing it), not a state PV — by design (CLAUDE.md observability: not every command needs a state PV when a more natural artifact exists). Asserting "no state delta" across arms is the correct parity contract for a state-free command. Per-arm dirs avoid one arm's save tripping the other arm's overwrite guard.

**Spec relationship:** Implements spec §7.2; resolves the parity-harness ambiguity the spec left open.

**Forward impact:** If M4 ever makes SAVE auto-load, the parity row must switch from "identical state" to "loaded state matches"; flagged here so that change is deliberate.


## 2026-05-29 — Path-safety via `is_relative_to` (3.9+) after explicit basename rejection

**Context:** M3 Task 2 — `_resolve_in_library(reference_dir, name)` in `pytxt/handlers/reference.py`.

**Decision:** The helper rejects in a fixed order — empty name; any `/`/`\\` separator or `.`/`..`; missing `.mat` suffix — then resolves the candidate and confirms `resolved.is_relative_to(reference_dir.resolve())`, raising `InvalidReferenceNameError` on any failure. Concrete reject vectors covered by `test_reference_path_safety.py`: `''`, `'foo'` (no ext), `'a/b.mat'`, `'../etc/passwd'`, `'/etc/passwd'`, `'..'`, `'foo.mat/../bar.mat'`. Positive: `'good.mat'`, `'2025-03-23_12:43:16_reference_trajectory.mat'`.

**Why:** `Path.is_relative_to` (Python 3.9+, available on the 3.10 control-room hosts) is the cleanest defense against both `../` traversal and symlink escapes after `.resolve()`, and is preferred over manual string-prefix comparison which is fragile across separators. The explicit basename checks run *first* so common bad input fails with a precise message before touching the filesystem. The helper raises only `InvalidReferenceNameError`; "not found" (LOAD) and "exists" (SAVE) checks live in the handlers since they're operation-specific.

**Spec relationship:** Implements spec §6.3 verbatim.

**Forward impact:** M4's download-by-name route reuses `_resolve_in_library` for the same guarantees — no second path-safety implementation.


## 2026-05-29 — Blocking scipy load/save run via `asyncio.to_thread`

**Context:** M3 Task 3 — `handle_load_ref`/`handle_save_ref` calling the M1 domain `load_reference_mat`/`save_reference_mat`.

**Decision:** Both handlers invoke the M1 scipy I/O through `await asyncio.to_thread(load_reference_mat, path)` / `await asyncio.to_thread(save_reference_mat, path, ...)` rather than calling them inline.

**Why:** `scipy.io.loadmat`/`savemat` are synchronous, disk-bound calls that would block the single shared asyncio event loop — stalling the IOC's CA responsiveness and every other in-flight REST request for the duration of a `.mat` read/write. `asyncio.to_thread` offloads them to the default executor, keeping the loop responsive. This honors CLAUDE.md §5 (domain stays I/O-free and synchronous; the adapter layer owns the threading) — no async leaks into `domain/reference.py`.

**Spec relationship:** Implements spec §7.1/§7.2.

**Forward impact:** Any future bulk file op (M4 upload parse, download read) should follow the same `to_thread` pattern at the adapter boundary.


## 2026-05-29 — Reference exception taxonomy + HTTP/CA mappings

**Context:** M3 Tasks 2/3/5 — defining the error model shared by the CA putters and REST routes.

**Decision:** Three new handler exceptions live beside the M2 `NoLastAcquireError` in `pytxt/handlers/reference.py`: `InvalidReferenceNameError` (→ HTTP 422 / CA alarm), `ReferenceNotFoundError` (→ 404 / alarm), `ReferenceExistsError` (→ 409 / alarm). The domain `ReferenceLoadError` (corrupt/wrong-schema `.mat`) is *imported* from `pytxt.domain.reference` and reused (→ 422 / alarm), not redefined. `NoLastAcquireError` (existing, M2) maps SAVE-with-no-acquire → 422 / alarm. The REST routes do the typed-exception → `HTTPException` mapping; the CA putters re-raise the typed exceptions so caproto surfaces them as PV alarms — parity by construction since both call the same handlers.

**Why:** A flat, operation-agnostic taxonomy keeps the CA and REST surfaces in lockstep (CLAUDE.md §1 — parity is the contract): the handler decides *what* went wrong, each adapter decides *how to report it* in its native idiom. Reusing the domain `ReferenceLoadError` avoids a duplicate type and keeps the corrupt-`.mat` path mapping consistent with M1.

**Spec relationship:** Implements spec §8 (error table).

**Forward impact:** M4's upload route reuses `InvalidReferenceNameError`/`ReferenceExistsError`; download reuses `ReferenceNotFoundError`. No new error types anticipated.


## 2026-05-29 — Env-var whitelist is automatic; empty name is caught by pydantic before the handler

**Context:** M3 Tasks 1 & 6 — verifying the new `reference_dir` field against the unknown-`PYTXT_*` rejector, and pinning down where an empty LOAD name fails.

**Decision:** Recorded two confirmed behaviors. (1) The `@model_validator(mode="before")` that rejects unknown `PYTXT_*` env vars iterates `cls.model_fields`, so simply declaring `reference_dir` auto-whitelisted `PYTXT_REFERENCE_DIR` — **no** edit to any hardcoded allowlist was needed (the M2 plan note flagged this as "verify"; verified true, tested in `test_settings.py`). (2) For the REST LOAD route, `LoadRefRequest.name` carries `Field(min_length=1)`, so an empty `""` name is rejected by **pydantic** as a 422 *before* reaching `handle_load_ref`/`_resolve_in_library` — the handler's own empty-name guard never fires on that path. Both produce 422, so the path-safety integration test treats empty-name as a valid 422 vector regardless of which layer rejects it; this is noted inline in `test_reference_path_safety_rest.py`.

**Why:** The env-var behavior confirms the M2-established "add a field, it's auto-accepted" ergonomic — future settings fields need no allowlist bookkeeping. The empty-name finding documents a benign double-guard (pydantic + handler) so a future reader doesn't mistake the handler's empty check for dead code; it's the CA-side defense, since CA string PVs bypass pydantic.

**Spec relationship:** Fills gap (spec §6.12 said "verify" the env-var acceptance; §8/§10.3 didn't pin the empty-name layer).

**Forward impact:** None. The handler's empty-name guard stays as the CA-path defense even though the REST path never reaches it.


## 2026-05-29 — SURPRISE: single-BPM references don't survive a save→load round-trip (latent M1 edge)

**Context:** M3 Task 6 — building the load/save integration + parity fixtures, which `save_reference_mat` a synthetic reference and then `load_reference_mat` it back.

**Decision:** Discovered that a reference with exactly **one** BPM cannot round-trip through save→load. `scipy.io.savemat` squeezes a `(2, 1)` `R0` array down to `(2,)`, and `load_reference_mat` (which uses `squeeze_me=True`) then rejects the loaded `R0` as not matching the expected `(2, n_bpms)` shape. Worked around it in Task 6 by using **2 BPMs** in every save→load fixture (the parity LOAD/SAVE rows and the integration round-trips), which round-trips cleanly. Logged as a known latent M1-domain edge rather than fixed in M3.

**Why:** It's latent-only in production: the real ring has N=107 BPMs and a saved reference is never N=1, so the live path never hits it. Fixing it touches M1 pure-domain code (`load_reference_mat`/`save_reference_mat`) outside M3's adapter scope, so the disciplined call was to document + work around in tests, not widen M3. The clean fix is a one-liner in the loader — `np.atleast_2d(R0)` (and re-check the `(2, n)` orientation) after `loadmat` — deferred to a future hardening milestone.

**Spec relationship:** Surprise from real upstream API (`scipy.io.savemat` squeeze behavior); not contemplated by spec §6 (M1 load/save).

**Forward impact:** `[needs-spec-update]` not required, but a future M1-hardening pass should add `np.atleast_2d` on `R0` in `load_reference_mat` and an explicit N=1 round-trip test. Until then, never assume an N=1 reference round-trips; the production N=107 path is unaffected.
