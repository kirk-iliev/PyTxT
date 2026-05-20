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


## 2026-05-20 — Integration suite hangs at end-of-test on Linux; root cause is leaked caproto `ClientContext`, not the IOC

**Context:** During M1 control-room validation (`docs/phase-2-m1-controlroom-validation.md` §4), `make test-integration` appeared to hang at the end of every test on appsdev2 — Ctrl-C surfaced an already-recorded PASSED. The same symptom reproduced on the dev Fedora box once integration tests were actually exercised on Linux for the first time (earlier local runs only ran unit tests / `--collect-only`). Test bodies completed; teardown spun.

**Decision (three layered changes):**

1. **Root cause fix — disconnect `ClientContext` in every test that creates one.** Each test instantiated `caproto.asyncio.client.Context()` and never called `disconnect()`. `pytest-asyncio` creates a fresh event loop per test, so the leftover client's `_command_queue_loop` background task ended up bound to a dead loop. When the *next* test wrote to a PV, the IOC's circuit response triggered the dead-loop client to queue work via `_get_loop()`, which raised `RuntimeError: <Queue ...> is bound to a different event loop` — *forever*, hot-spinning at 100% CPU because caproto's circuit handler swallows the exception and immediately retries. Added `_disconnect_quietly(client)` helper (2-second `wait_for`) and called it from every `finally` block that owns a `ClientContext`. Files: `tests/integration/test_ioc_lifecycle.py`, `tests/integration/test_parity.py` (in `_do_via_ca`), `tests/integration/test_ping_via_ca.py`.

2. **Defense in depth — bound `await server_task` after `cancel()`.** caproto's own `Context.run()` cancellation handler awaits `tasks.cancel_all()`, which can itself block if any spawned task (e.g. `broadcaster_receive_loop`) is wedged in a UDP recv. Wrapped every test-side `await server_task` with `asyncio.wait_for(..., timeout=2.0)` and broadened the swallow to `(CancelledError, TimeoutError)`. Same pattern applied to the `fake_bpm_ioc` fixture.

3. **Force-close IOC sockets on cancel.** Added a `try: ... except CancelledError: self._force_close_context_sockets(); raise` wrapper around `Context.run()` in `pytxt/ioc/server.py`. Brute-force-closes `tcp_sockets`, `udp_socks`, and `beacon_socks` so any blocked recv unblocks and caproto's internal cleanup can complete. This is the production-relevant fix — operator Ctrl-C of `python -m pytxt` benefits from it too.

**Why:** The hang looked environmental but wasn't — it was a test-isolation bug we'd never noticed because the dev box happened to be macOS (which we'd been running on) or had only exercised unit tests on Linux. The cross-loop error spam was buried under pytest's output capture, so it presented as "hung." Once one test ran a CA write that triggered the previous test's leaked client, the spam loop began.

Result on dev Fedora: integration suite went from `Ctrl-C required per test`/`4+ minute hang at test 12` to **23 passed in 5.66s**, slowest individual test 2.22s. Unit suite: 49 passed in 0.09s.

**Spec relationship:** Fills gap — spec was silent on caproto client lifecycle in tests. Did not change any production interface; both pytxt/ioc/server.py and the tests still hold the same contract.

**Forward impact:**
- Anyone adding a new integration test that uses `ClientContext` must disconnect it. Consider promoting `_disconnect_quietly` to `tests/conftest.py` (or providing a `ca_client` fixture that auto-disconnects) before the next round of integration tests is written.
- The `_force_close_context_sockets` hatch in `pytxt/ioc/server.py` is best-effort. If caproto upstream improves its cancellation behavior, this can be removed. Not blocking M1.
- Validates the choice to walk through `phase-2-m1-controlroom-validation.md` on real hardware before declaring M1 done — this bug would have shipped silently otherwise.

Tag: `[ca-client-lifecycle-fixed]`.

## 2026-05-20 — IOC.run() must not mutate EPICS_CA_SERVER_PORT (breaks in-process BpmReader)

**Context:** First end-to-end run on appsdev2 against the real ring. `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1` succeeded but the result PVs were `STATUS=FAILED`, `OK_COUNT=0`, `FAIL_COUNT=1`, `X/Y_FIRST_TURN=all NaN`. Network was fine — direct `caget SR01C:BPM1:wfr:TBT:c0` from a clean shell worked. Logs would show BpmReader CA name-resolution timeouts.

**Decision:** Remove the `os.environ["EPICS_CA_SERVER_PORT"] = str(self.port)` line from `PyTxTIOC.run()` (`pytxt/ioc/server.py`). Only the server-side `EPICS_CAS_SERVER_PORT` (with S) is needed for caproto to bind the IOC; `EPICS_CA_SERVER_PORT` (no S) is the *client* search port.

**Why:** Setting `EPICS_CA_SERVER_PORT=59064` in our process env meant the in-process `BpmReader`'s `ClientContext` broadcast CA name-resolution requests to port 59064 (where only our own IOC listens) instead of port 5064 (where the real ring BPM IOC listens). The search never reached `SR01C:BPM1` and BpmReader returned `None` for every BPM. Acquire handler converted that to NaN sentinels and FAILED status. Easy to miss because the IOC itself was healthy and serving its own PVs correctly — the failure was entirely in the embedded CA client.

This was previously latent: in tests, conftest pins `EPICS_CA_SERVER_PORT` to the ephemeral test-IOC port intentionally because the test client *should* talk to our test IOC, not a real ring. In production, the embedded client needs ring access.

**Spec relationship:** Fills gap — spec mentioned both env vars in the same breath without flagging the client-vs-server distinction.

**Forward impact:** None of the other env-var assignments need to change. `EPICS_CAS_SERVER_PORT` (server bind), `EPICS_CAS_INTF_ADDR_LIST` (server interface), `EPICS_CA_REPEATER_PORT` (shared repeater for in-process client) are all correct. The conftest still sets `EPICS_CA_SERVER_PORT` *for tests only* — that's the right place for it because tests genuinely want the client routed at the test IOC. Tag: `[client-vs-server-env-distinguished]`.

## 2026-05-20 — EPICS_CA_SERVER_PORT: set before Context(), restore after (server vs client conflict)

**Context:** Follow-up to the previous entry. Removing the `EPICS_CA_SERVER_PORT` env-var override broke the IOC entirely on appsdev2 — `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1` from terminal 2 returned `Channel connect timed out`. PyTxT process was alive but `ss -ulnp | grep 59064` showed nothing listening.

**Decision:** caproto's server reads `EPICS_CA_SERVER_PORT` (no S) at `Context.__init__`, captures it as `self.ca_server_port`, and uses it to choose both its TCP bind port and its UDP search-listen port. So we *must* set it before constructing the server Context. The fix is to set the env, construct `Context(pvdb)`, then immediately restore the env to its prior value so the in-process `ClientContext` (used by BpmReader) reads the operator's normal ring-reachable value (typically unset → caproto's default 5064). Both Context.__init__'s read env synchronously, so the set→construct→restore sequence is race-free.

**Why:** The earlier entry's premise was wrong: I'd thought `EPICS_CAS_SERVER_PORT` (with S) controlled the server bind, but caproto only reads the no-S variant. The two roles really do collide in one env var; the *only* way to keep both sides working in a single process is to mutate env around the server-Context construction site. Code paths verified:
- Server path: `os.environ["EPICS_CA_SERVER_PORT"] = "59064"` → `Context(pvdb)` → caproto caches `self.ca_server_port = 59064` → binds TCP and listens for UDP searches on 59064.
- Client path: restore env (pop if previously unset) → BpmReader → `ClientContext()` → `SharedBroadcaster.__init__` reads `EPICS_CA_SERVER_PORT` → falls back to caproto default 5064 → searches ring on 5064 → finds `SR01C:BPM1`.

**Spec relationship:** Fills gap — the spec assumed the env vars were cleanly partitioned by role. They are not in caproto.

**Forward impact:**
- Tests are unaffected: conftest sets the env to the ephemeral test-IOC port for the whole session; tests pass `port=0` to `PyTxTIOC`, so the `if self.port:` block in `run()` is skipped, no save-and-restore happens, and the test client correctly reads the ephemeral port from env.
- If anything ever constructs `Context(pvdb)` outside `PyTxTIOC.run()`, the same dance must be repeated.
- Document the env-var-quirk in the validation handbook so the next person who hits "IOC is alive but its PVs are unreachable from a CA tool" can find the explanation quickly. Tag: `[follow-up: handbook-env-var-note]`.

## 2026-05-20 — AppState.update is now two-pass: apply all changes, then fire all listeners

**Context:** During M1 control-room validation, after fixing the IOC env-var bug, `caput CMD:ACQUIRE 1` reported `OK_COUNT=1`, `FAIL_COUNT=0` (acquire succeeded against the real ring), but `RESULT:BPM:X_FIRST_TURN` and `Y_FIRST_TURN` were all-NaN — including element [0], which should have held the real BPM1 value. The handler's local computation was correct; only the IOC-published waveforms were wrong.

**Decision:** Rewrite `AppState.update(**changes)` as two passes:
1. Validate every kwarg, then apply *all* `setattr`s.
2. Then fire all listeners for the fields that actually changed.

Previously it interleaved: apply field → fire listeners → apply next field → fire next listeners. The IOC's `_publish_last_acquire` listener on `last_acquire` reads `self.state.last_acquire_raws` to re-derive the result waveforms. When the handler called `state.update(last_acquire=..., last_acquire_raws=...)`, the listener fired *between* the two assignments, observing `last_acquire_raws` still at its empty initial value → re-derivation found no BPM data → all NaN published.

**Why:** A function called `update` advertises atomicity — listeners should observe the *post-update* state, not a half-applied mid-iteration snapshot. The bug was masked by every existing test happening to update only one field at a time, or to update related fields in an order that didn't surface the cross-field read.

**Spec relationship:** Fills gap — spec was silent on `update`'s ordering semantics.

**Forward impact:**
- Tests pass unchanged (72/72) because no existing test depends on the broken ordering. The previous behavior was a latent invariant violation.
- Any future listener that reads multiple state fields can now safely assume a consistent snapshot.
- The handler's `state.update(last_acquire=..., last_acquire_raws=...)` call is now order-independent.
- A unit test asserting cross-field consistency during a multi-field update would be a good follow-up.

Tag: `[atomic-update-fixed]`.
