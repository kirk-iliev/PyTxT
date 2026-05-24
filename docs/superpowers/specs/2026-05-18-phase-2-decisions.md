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

## 2026-05-20 — AppState.update equality check now numpy-tolerant

**Context:** After the two-pass `AppState.update` fix, the first REST-driven ACQUIRE on appsdev2 raised `HTTP 500`. Terminal-1 traceback:
```
File "pytxt/state/app_state.py", line 89, in update
    if old == v:
ValueError: The truth value of an array with more than one element is ambiguous.
```
`last_acquire_raws` is `dict[str, RawBPM]`. RawBPM is a dataclass with numpy-array fields. Dict equality dives into per-key value equality, which invokes RawBPM's auto-generated `__eq__`, which compares numpy arrays element-wise — returning a bool array that fails `if <array>`.

**Decision:** Wrap the no-op equality check in `try/except (ValueError, TypeError)` and treat any uncomparable value as "changed." This is the correct semantic: when we can't tell whether two values are equal, the safe assumption is that they differ; firing listeners on a possibly-unchanged value is fine (they already filter duplicates downstream), but *not* firing on a genuinely-changed value silently desyncs PVs from state. Added a regression unit test (`test_update_handles_numpy_bearing_field_replacement`) that builds two RawBPMs with different numpy arrays and proves the second `update()` doesn't crash and the listener fires.

**Why:** This bug was already latent in the original `update()` code — the equality check existed before today. It just never surfaced because every existing test path either:
- updates a scalar field (no numpy involved), or
- updates `last_acquire_raws` while the prior value was the empty dict `{}` (Python dict-eq short-circuits on length mismatch without touching values), or
- updates with the same reader-mock-returned value (same object, eq trivially true).

The first real second acquire against the ring exposed it.

**Spec relationship:** Fills gap — the spec didn't speak to equality semantics for compound fields.

**Forward impact:**
- Tests: now 73 passing (added one regression test).
- Any new AppState field that holds numpy / arbitrary objects automatically works — the try/except is type-agnostic.
- A possible future refinement: if a field type explicitly opts into a structural equality method, we could prefer that over try/except. Not needed yet.

Tag: `[numpy-eq-tolerant]`.

## 2026-05-21 — Real BPM prefix list dumped from live MML: 107 entries, `getname` returns `:SA:X` form

**Context:** Pre-M2 housekeeping. Spec §6.11 wanted a one-time MATLAB dump of the operational BPM prefix list, committed as `pytxt/config/bpm_prefixes.txt`, to replace M1's hardcoded `["SR01C:BPM1"]`. Done today at an ALS control-room MATLAB session.

**Decision:** Commit a 107-entry `pytxt/config/bpm_prefixes.txt` produced by the following exact sequence, and delete the predecessor `docs/bpm_prefixes.txt` (104 entries, extracted from a legacy reference-trajectory file in commit `117c518`) which is now superseded.

```matlab
setpathals('StorageRing');
b = getbpmlist('nonBergoz');
b([1 2 8 37],:) = [];
n = getname('BPMx', b);
for i=1:size(n,1); s = strtrim(n(i,:)); disp(s(1:end-5)); end
```

**Surprises worth logging:**

1. **Count: 107, not ~120.** The spec, the bpm-tbt-pv-pattern-confirmed memory, and the legacy lattice filename (`alslat_loco_..._124bpms.m`) all suggested ~120. Live MML `getbpmlist('nonBergoz')` returned **111** rows (not 124), so after the 4-index excision the answer is 107. Best hypothesis: more BPM channels have migrated off Bergoz electronics than the 124-BPM lattice file assumes — the lattice is the *modeling* truth, the MML query is the *operational* truth. Operational wins for our use case.

2. **`getname('BPMx', b)` returns SA-PV names, not bare prefixes.** Output rows look like `'SR01C:BPM3:SA:X  '` (slow-acquisition X PV, padded char matrix). The legacy `SCexp_ALS_setupBPMs.m` shape-shifts these by `findstr('X')` + truncate + cell-convert + `end-4` strip — but for our purposes we want the bare prefix `SR01C:BPM3`, so the cleaner transform is `strtrim()` then `s(1:end-5)` (drop the trailing `:SA:X`). The spec's snippet showed `disp(n(i,:))` with no strip; that was based on inference, not a live dump, and would have produced unusable PV-not-prefix output. Updated.

3. **MML exclusion `[1 2 8 37]` is correct; UI default `[1 2 8 27]` is not.** The audit of `legacy/` flagged that `legacy/TxT_GUI/_unpacked/TxT_GUI.m:928` has `'[1 2 8 27]'` as the GUI field default — likely a typo. The operational truth from `SCexp_ALS_setupBPMs.m:7` (function default) and `load_default_SC.m:17` (SC config default) is `[1 2 8 37]`, and that's what we used. Documenting here so a future reader doesn't try to "reconcile" with the GUI's stray value.

4. **Filename: spec said `bpm_prefixes.txt` but MATLAB session output was named `bpm_prefix_list.txt`.** Renamed to match the spec / settings.py field (`bpm_prefixes_path`). Trivial but worth flagging because the spec and `pytxt/config/settings.py:40` were already coherent; nothing else needed to change.

5. **No static fallback exists in the legacy tree.** Confirmed by exhaustive audit of all 136 `.m`/`.mlapp` files under `legacy/`: there is no checked-in BPM name list anywhere. Every operational path derives names live from MML. The `.mat` files contain calibration/position/trajectory data, never name catalogs. If the lattice or electronics change, this file *must* be re-dumped — there is no other authoritative source.

**Spec relationship:** Updates §6.11 (snippet now reflects the real `setpathals` + `strtrim` + `end-5` shape, count is 107), §11 M2 header ("Scale to all 107 BPMs"), and §12 DoD line 2 ("107 entries as of the 2026-05-21 dump"). All authoritative wording now matches reality.

**Forward impact:**
- M2 implementation can proceed: `composition.py` reads `settings.bpm_prefixes_path` (already populated, value `"pytxt/config/bpm_prefixes.txt"`), parses the file (skip `#` comments and blank lines), populates `app_state.bpm_prefixes`, hands the list to `BpmReader`.
- The IOC's `RESULT:BPM:NAMES` waveform PV is pre-sized for `max_bpms` via `_pad_string_array` — confirm the current `max_bpms` setting accommodates 107 with headroom (current spec discussion expected ~120, so 107 fits trivially).
- `BpmReader.read_all` already uses `asyncio.gather` per M1's commit `d137181` — no code change required to scale from 1 to 107.
- If `getbpmlist` ever returns substantially fewer than 111 (e.g. <100) or substantially more (e.g. >120), that's a signal of upstream MML / electronics change worth investigating before re-committing.

Tag: `[bpm-prefix-list-dumped]`.

## 2026-05-21 — M2-1 composition loader: standalone module + fail-fast error policy

**Context:** M2-1 task per the roadmap: replace M1's `_PHASE_2_M1_BPM_PREFIXES = ["SR01C:BPM1"]` hardcode in `composition.py` with a load from `settings.bpm_prefixes_path`. Spec §6.11 specified the file format (one prefix per line, `#` comments, blank lines OK); spec §6.12 specified that composition wires the loaded list into `AppState.bpm_prefixes` and `BpmReader`. The spec did *not* specify *where* the parsing logic lives or what the error contract is.

**Decisions:**

1. **Loader lives in its own module: `pytxt/config/bpm_prefixes.py`** (data file is `pytxt/config/bpm_prefixes.txt`, side-by-side, distinguished by extension). Composition imports `load_bpm_prefixes` rather than inlining the 10-line parse loop. Rationale: keeps `composition.py` focused on wiring, makes the loader trivially unit-testable without spinning up the IOC/API, and matches the existing convention of small focused modules under `pytxt/config/`.

2. **Fail-fast error contract:**
   - `FileNotFoundError` if `settings.bpm_prefixes_path` doesn't exist — the app exits at startup, before any IOC/API is bound. Hint message points the user at `PYTXT_BPM_PREFIXES_PATH`.
   - `ValueError` if the file parses to zero entries (only comments + blanks). Same effect — startup aborts.
   The roadmap explicitly called for fail-fast on missing/empty, so no surprise here; the only choice was whether to use `FileNotFoundError` (native, semantically correct for the missing case) vs a custom exception. Native wins — no error class to maintain.

3. **`Path | str` signature.** `settings.bpm_prefixes_path` is a `str` (pydantic default), but callers may pass a `Path` (tests). The loader accepts either and normalizes via `Path(path)`. Cheap; avoids forcing every caller to convert.

4. **Whitespace-tolerant parse.** Lines are `.strip()`-ed before the empty-line / `#` check, so trailing `\r\n` (Windows line endings if anyone ever edits the file there), leading/trailing spaces, and `#`-with-leading-spaces all behave as expected. The shipped file is clean LF-only, but the tolerance costs nothing.

5. **No alternative-format support.** The loader does *not* accept JSON, YAML, or CSV variants — only the plain-text format documented in the file header. If a different format ever becomes needed (e.g. per-BPM metadata: planes, ring index, calibration), introduce a second loader function rather than overloading this one. Keeping the file format dead-simple is the point.

**Forward impact:**
- M2-2 (parametric multi-BPM perf test) can construct test fixtures via `tmp_path` + arbitrary prefix lists, then call `load_bpm_prefixes(tmp_path / "prefixes.txt")` directly — no monkey-patching of composition needed.
- M2-3 (frontend polyline) is independent of this work; the loader change is invisible to the browser.
- If someone later wants `load_bpm_prefixes` to deduplicate or validate the `SR##C:BPM#` shape, add it then — the current loader is intentionally permissive about content (only about presence/format).

Tag: `[m2-1-composition-loader]`.

## 2026-05-22 — M2-2 multi-BPM scale tests: N=107 ACQUIRE under 3 s confirmed

**Context:** M2-2 task per spec §11 / DoD §12 line 2: prove the read path scales from 1 → 107 BPMs in <3 s end-to-end. Spec didn't prescribe exactly *which* tests; it just specified the integration tier needed multi-BPM coverage and the DoD wall-time bound.

**Decisions:**

1. **Two test files, two scopes.** `tests/integration/test_bpm_reader_scale.py` exercises just `BpmReader.read_all` parametrically at N ∈ {10, 50, 107} — isolates the CA-client transport. `tests/integration/test_acquire_scale.py` exercises the full `handle_acquire` pipeline (real reader + real domain + real state) at N=107 — isolates the handler+domain budget. Both pin the <3 s bound. Two files because the failure modes are distinct: a reader-only failure indicates caproto/network, a handler-only failure indicates domain or state-update overhead.

2. **`per_pv_timeout_s=5.0` in tests, not the default 2.0.** Test reads run against an in-process fake IOC where `caproto`'s first-PV resolution can take ~1 s even on localhost; the *aggregate* `<3 s` assertion is what enforces the SLA, while the per-PV timeout just has to be large enough to avoid spurious flakes on a loaded CI host. Production code keeps the 2 s default.

3. **No production code changes.** The fake-IOC fixture was already parametric (M1 work). `BpmReader.read_all` already uses `asyncio.gather` (M1 work). M2-2 is a pure proof-of-scale milestone; the architecture was load-bearing for the spec's N=107 claim from the start, and these tests are the evidence.

4. **Assertion-message diagnostics added in follow-up commit.** Initial Task 2 implementation matched the plan literally; code-quality review caught that `ok_count`, `fail_count`, and `acquire_in_flight` asserts lacked the failure-context messages that the `status` assert already provided. Follow-up commit `7a07474` adds inline diagnostics — counts, first-five failed BPM names, elapsed wall time — so CI failures print useful context without `--tb=long`. Captured for future test-file style reference: every assertion in a multi-step pipeline test should carry the same level of failure context.

**Observed pytest `call` durations (`pytest --durations=0`):**

- `test_read_all_scales_under_3s[10]`: ~0.13 s (start + read_all + stop combined)
- `test_read_all_scales_under_3s[50]`: ~0.58 s
- `test_read_all_scales_under_3s[107]`: ~1.52 s
- `test_handle_acquire_end_to_end_under_3s[107]`: ~2.33 s pytest total (includes fixture caproto-bind startup); the test's internal `elapsed` (handle_acquire alone) measured 1.23 s on the implementer's run

The internal `elapsed` measurement (which is what the test's `< 3.0` assertion gates on) is necessarily faster than the pytest `call` figures because the latter include `start()`/`stop()` overhead. Both bounds are well under the 3 s DoD budget.

**Spec relationship:** No spec change. M2-2 closes spec §11 M2 ("Tests: ca_client integration tests with multi-BPM fake IOC fixture") and provides the evidence for DoD §12 line 2 wall-time claim.

**Forward impact:**
- M2-3 (frontend polyline) can be developed without re-litigating backend scale.
- M3 (failure handling) will *reuse* `fake_bpm_ioc`'s `bpm_offline`/`bpm_timeout` hooks (already designed into the fixture per its dataclass docstring) plus these scale tests as a regression base. The 3 s wall-time bound should stay green in M3 (no per-BPM serial fallbacks slipped in).
- Headroom (~1.3 s of the 3 s budget used at N=107) is comfortable but not enormous; if M3's per-PV timeout work adds significant per-read overhead, this test will catch the regression before it ships.

Tag: `[m2-2-scale-tests]`.

## 2026-05-22 — WS bridge couldn't see our own IOC on appsdev2: prepend `127.0.0.1:<ioc_port>` to EPICS_CA_ADDR_LIST in composition

**Context:** First attempt at M2-3 visual validation (deploy current `main` to appsdev2, click ACQUIRE in the browser, expect 107-BPM polyline). REST `POST /api/v1/cmd/acquire` returned `OK · 107 OK · 0 FAIL` correctly, so `BpmReader` against the real ring worked. But every browser WS subscription to our own IOC's PVs (`OSPREY:TEST:TXT:RESULT:BPM:*`, `STATE:LAST_ACQUIRE_*`) timed out with `"initial read timeout"` from `ws_bridge.py:80`. Canvases stayed empty; status header stayed at "No acquisition yet".

**Diagnosis:** On appsdev2 (and any ALS control-room host), the shell environment sets:

```
EPICS_CA_SERVER_PORT=5064
EPICS_CA_ADDR_LIST=131.243.71.255 131.243.84.255 131.243.89.255 131.243.93.255 131.243.95.255 131.243.199.255 131.243.53.255
EPICS_CA_AUTO_ADDR_LIST=NO
```

Our IOC binds at `127.0.0.1:59064` (per als-profiles safety rule). The IOC's startup code (`pytxt/ioc/server.py:202-253`) temporarily sets `EPICS_CA_SERVER_PORT=59064` around `Context()` construction, then restores it to 5064 so `BpmReader` can read real ring BPMs at the ring's standard port. But it never touches `EPICS_CA_ADDR_LIST` — which has zero localhost entries and `EPICS_CA_AUTO_ADDR_LIST=NO` to forbid auto-adding any.

Result: the in-process CA clients (WS bridge per-connection and BpmReader at startup) inherit an address list that **doesn't include our own IOC at all**. Every `get_pvs("OSPREY:TEST:TXT:*")` broadcasts to the seven ring subnets at port 5064; no ring server has those PV names; the search times out. `BpmReader` is unaffected because it searches for real ring PVs (`SR01C:BPM3:wfr:TBT:c0`), which the ring does have.

This bug was present from M1 too — but M1's "browser validation" (per memory note) may have worked locally on Kirk's Mac, where the shell env doesn't pin EPICS_CA_ADDR_LIST to ring-only addresses (caproto defaults to broadcasting on the local subnet, which includes the loopback IOC). Only the appsdev2 deploy with the operator's strict ring-targeting env exposes the bug.

**Decisions:**

1. **Fix lives in `composition.py`, not in `ws_bridge.py` or `bpm_reader.py`.** New helper `_ensure_local_ioc_in_ca_addr_list(host, port)` prepends `"{host}:{port}"` (in `EPICS_CA_ADDR_LIST` `host:port` syntax) to the address list, called once in `main()` *before* `asyncio.gather()` kicks off the IOC, API, and reader subsystems. caproto captures env vars at `Context()` construction; doing the prepend up front ensures every subsequent in-process CA client sees the localhost entry. The IOC startup juggling only touches `EPICS_CA_SERVER_PORT` (not `EPICS_CA_ADDR_LIST`), so the prepend survives.

2. **One address list, not separate ones per subsystem.** A localhost entry doesn't interfere with ring reads: searches for ring PVs match the ring servers and ignore the localhost responder; searches for `OSPREY:TEST:TXT:*` match the local IOC and are ignored by the ring. The "single address list for both clients" approach is simpler than threading separate broadcaster configs through the WS bridge and BpmReader. If a future ALS deployment ever runs a *second* IOC on localhost with overlapping PV names, this assumption breaks — but that's hypothetical.

3. **Idempotent helper.** If the operator (or a future code path) has already added `127.0.0.1:59064` to the list, the helper is a no-op. This keeps the helper safe to call from any startup ordering without double-listing.

4. **Helper respects operator-set `EPICS_CA_AUTO_ADDR_LIST`.** Only `setdefault` to `NO` if the variable is unset. On appsdev2 it's already `NO`; in unit tests it's whatever the test sets via `monkeypatch`. We don't override an explicit operator choice.

5. **Logged the resolved `EPICS_CA_ADDR_LIST` at startup** so future deploys make this observable — if the prepend didn't take effect, the log line shows it immediately rather than waiting for browser-side timeouts.

**Tests:** 5 new unit tests in `tests/unit/test_composition.py` covering empty list / existing entries / idempotent re-call / operator-set AUTO_ADDR_LIST preservation / different host:port. Full suite 88/88 green.

**Spec relationship:** Fills a gap in spec §3 / §6 that quietly assumed in-process CA clients would resolve our IOC's PVs without special configuration. Not strictly a spec change — more a "this is what 'localhost-discoverable' really requires" footnote that the spec didn't anticipate.

**Forward impact:**
- M2-3 visual validation unblocked; redeploy + browser-click ACQUIRE should now render the 107-BPM polyline.
- Removes a latent footgun for any future agent or developer trying to wire a new in-process CA client (e.g. a Phoebus-style scripting endpoint, an MCP wrapper). The address list is now correct from `composition.main()` onward.
- M3 work (per-PV timeout + concurrent-ACQUIRE rejection) is unaffected — those changes live in `BpmReader` and `handle_acquire`, neither of which touches address-list resolution.
- The single integration test `tests/integration/test_ws_bridge.py` already exercises the WS path in the conftest-pinned localhost environment, so it doesn't catch this class of bug (the conftest sets `EPICS_CA_ADDR_LIST=127.0.0.1`). A future test that specifically simulates the appsdev2-style "ring-only addr list" environment would be a useful guard; deferring to M4 polish.

Tag: `[ws-bridge-ca-addr-list]`.

## 2026-05-22 — WS bridge `_coerce_value` couldn't serialize waveform PVs

**Context:** Second iteration of M2-3 visual validation. After fixing the CA address list (entry `[ws-bridge-ca-addr-list]` above), the scalar STATE PVs flowed correctly through the WS bridge and the status header populated (`OK · 107 OK · 0 FAIL · <timestamp>`). The waveform PVs still failed, but now with different errors visible in the browser console:

```
PV error: ...RESULT:BPM:X_FIRST_TURN — read failed: can only convert an array of size 1 to a Python scalar
PV error: ...RESULT:BPM:Y_FIRST_TURN — read failed: can only convert an array of size 1 to a Python scalar
PV error: ...RESULT:BPM:INJECTION_TURN — read failed: can only convert an array of size 1 to a Python scalar
PV error: ...RESULT:BPM:NAMES — read failed: Unable to serialize unknown type: <class 'caproto._dbr.DbrStringArray'>
```

**Diagnosis:** The pre-existing `_coerce_value(raw)` helper in `pytxt/api/ws_bridge.py` was written for phase-1 scalar PVs. Its logic was:

```python
if hasattr(raw, "__len__") and len(raw) == 1: raw = raw[0]
if isinstance(raw, bytes): return raw.decode(...)
if hasattr(raw, "item"): return raw.item()  # numpy scalar
return raw
```

Two failure modes for waveform PVs:

1. Numeric arrays (X/Y/INJECTION_TURN) arrive as numpy ndarrays of size 128. `hasattr(arr, "item")` is True (numpy arrays *do* have `.item()`), but `arr.item()` raises `ValueError: can only convert an array of size 1 to a Python scalar` for multi-element arrays.
2. String arrays (NAMES) arrive as caproto `DbrStringArray` of size 128. `_coerce_value` returns it as-is; pydantic then can't serialize the unknown type when `WSValueUpdate(...).model_dump_json()` runs.

**Decisions:**

1. **Rewrote `_coerce_value` to handle both scalar and waveform shapes explicitly.** New logic dispatches on:
   - `bytes / bytearray` → decode to str (CA string scalar via DbrChar).
   - has `tolist()` (numpy arrays and 0-d numpy scalars) → `.tolist()` unboxes to native Python primitives.
   - has `__len__` and not `str` (caproto `DbrStringArray` and similar) → manual `list(raw)` then per-element decode of any surviving bytes.
   - anything else → passthrough (scrubbing NaN if applicable).
   - Multi-element containers stay as lists; length-1 containers are unwrapped to scalars so scalar PVs flow as plain values.

2. **NaN → None for JSON safety.** JSON has no NaN literal. Forward-looking for M3 (per-PV timeout + NaN propagation) — when failures map to NaN sentinels, the browser must receive a parseable message. Python `float('nan')` and numpy NaN both get mapped to `None`. The frontend's existing `Number.isFinite(v)` and `v >= 0` filters already handle null correctly, so no frontend change needed.

3. **Decode-on-output, not on-input.** Bytes objects appear in two places: scalar PVs (after unwrapping a length-1 container) and string array elements. Both go through `_coerce_element` which handles bytes uniformly. Avoids a single mega-conditional and makes the per-element rule explicit.

4. **Helper split into three small functions** (`_coerce_nan`, `_coerce_element`, `_coerce_value`) rather than one branching block. Each has a single responsibility and is independently testable; the dispatch logic in `_coerce_value` stays under 15 lines.

5. **No frontend change required.** `trajectory.js` already subscribes via `Array.isArray(msg.value) ? msg.value : [msg.value]` and the render function handles N>1 with NaN gaps. The fix is purely server-side serialization.

**Tests:** 15 new unit tests in `tests/unit/test_ws_coerce.py` covering: scalar bytes / 1-element bytes array / numpy scalars / 1-element numpy array / plain Python scalars / NaN scalar (Python and numpy) / numpy int and float arrays / array with NaN / 128-element array length preservation / multi-element bytes-list (DbrStringArray duck type) / empty-string padding pass-through / mixed str+bytes array / JSON round-trip smoke for the typical PV shapes. Full suite 103/103 green.

**Spec relationship:** Fills a gap in spec §6.5 / WS-bridge design that didn't specify the JSON-coercion rules for waveform shapes (the spec assumed pydantic + `Any` would just work, which is true only for scalar shapes).

**Forward impact:**
- M2-3 visual validation should now show 107-BPM polylines in both X and Y canvases after a redeploy + browser refresh.
- M3's NaN propagation already has the JSON-safe path in place — no further bridge changes needed when failure paths come online.
- Any future PV shape that doesn't fit numeric-array or string-array (e.g. a structured PV from a different IOC) will need an extension here. Adding a new branch is straightforward.

Tag: `[ws-coerce-waveform]`.

## 2026-05-22 — Trajectory render polish: trim trailing NaN + per-BPM dot overlay

**Context:** After fixing the WS bridge (`[ws-bridge-ca-addr-list]` + `[ws-coerce-waveform]`), browser rendering finally worked end-to-end against the live 107-BPM ring. First visual review surfaced two cosmetic issues that the spec §5.4 was silent on:

1. The polyline only filled ~83% of the canvas width because the IOC pads `RESULT:BPM:{X,Y}_FIRST_TURN` to length 128 with NaN, and the renderer plotted across all 128 x-slots. With 107 valid + 21 trailing NaN, the polyline ended at `i = 106 → x ≈ 661/800 px` and the right strip was dead space.
2. The 3×3 per-point fillRect markers were invisible at 107-BPM density (~6 px between points), so individual BPMs couldn't be picked out — visually you saw a single oscillating line, not 107 discrete measurements.

**Decisions:**

1. **Trim trailing non-finite entries in the renderer, not in the IOC.** New `trimTrailingNonFinite(data)` helper in `trajectory.js` walks back from the end and slices to the live prefix. Three reasons not to fix this server-side:
   - The IOC's fixed-length pad keeps the PV waveform shape stable (downstream CA monitors don't see length flicker), which is desirable EPICS hygiene.
   - The renderer needs a NaN-aware path anyway for M3 partial-fail (one or more interior BPMs returning NaN), so the trim is the same code path generalized.
   - Trimming server-side would couple the IOC to a "current N" the frontend already knows from its own subscription.

2. **Per-BPM markers as filled discs (radius 2.5) in a second pass.** Drawing the connecting line and then a separate disc pass guarantees the dot is on top of the line, so individual BPMs are visible against the polyline. Radius 2.5 was picked so that at 107 BPMs across ~660 px (≈6 px spacing) the dots are clearly separable but still touch enough to read as a "beaded line." This matches the spec §5.4 "polyline with broken-line segments" intent while making the underlying data points readable.

3. **Polish only — no spec change.** The visualisation is still the spec's "two stacked panels, X above Y, position vs BPM index" with NaN-gap breaks. Spec §5.4's hover-tooltip is M4 scope and not touched here.

4. **Confirmed the multi-line "Raw BPM Signal" view from the MATLAB manual is a different visualization (one line per BPM over the full turn waveform), not what phase 2 implements.** Phase 2's `RESULT:BPM:{X,Y}_FIRST_TURN` is the first-turn cross-section. The multi-line view is properly scoped to a later phase (likely phase 3 trajectory analysis or phase 4 polish). Documenting here so a future reader doesn't try to "fix" the single-polyline rendering to match the manual screenshot.

**Tests:** No JS test infrastructure exists yet for the frontend (M4 e2e Playwright spec is what closes that gap). Manual visual verification on appsdev2 is the gate. The Python suite (103/103) is unchanged.

**Forward impact:**
- M2-3 closes after Kirk visually confirms the polyline now spans the full canvas with visible per-BPM dots.
- M3 (partial-fail rendering) will reuse `trimTrailingNonFinite` and benefit from the dot overlay: a single NaN BPM in the middle of the ring will now be visually obvious as a missing dot, not a barely-visible line break.
- M4 (Playwright e2e + hover tooltip) builds on these helpers — `xFor(i)` is now a named inner function ready to be reused for hit-testing.

Tag: `[m2-3-render-polish]`.

## 2026-05-24 — M3 failure handling closed: fixture fault injection + CA putter symmetry + classify-path coverage

**Context:** M3 per spec §11 M3 ("M3 detailed design (locked 2026-05-22)"). The actual failure-handling code shipped in M1: per-PV `asyncio.wait_for` in `BpmReader._read_one`, `handle_acquire._classify` for OK/PARTIAL/FAILED, `try/finally` clearing `acquire_in_flight`, and `LAST_ACQUIRE_*` PVs all wired. M3's job was (a) test coverage and (b) closing the one outlier where the CA putter didn't surface the in-flight error.

**Implementation summary:**

1. `tests/fixtures/fake_bpm_ioc.py` gained an `"offline"` dict-key form (commit `4ea4454`): prefixes listed under that key appear in `fixture.prefixes` (so `BpmReader` is configured to look for them) but are not built into the IOC's `pvdb`. `BpmReader._read_one` returns `None` for them via the "channels is None" early return.
2. Same fixture gained a `"slow"` dict-key form (commit `b4ea2e1` + getter-syntax doc `132349d`): prefixes listed under that key get a custom PVGroup whose `c0/c1/c3/armed` getters `await asyncio.sleep(_SLOW_DELAY_S_DEFAULT=3.0)`. Reader resolves the PVs normally; the per-read `wait_for(timeout=2.0)` times out. Different `BpmReader._read_one` code branch from offline; same observable outcome.
3. `pytxt/ioc/pvs.py::cmd_acquire` putter was reduced from "catch + swallow AcquisitionInFlightError" to "re-raise" (commit `55201f6` + no-reader-test follow-up `8ece629`). caproto encodes the failure as a CA write error, symmetric to REST's 409. `STATE:ACQUIRE_IN_FLIGHT` continues to publish 1 for observers.
4. 6 integration tests + 2 unit tests pinned all the failure paths (commits `2250d6e`, `10681c2`, `28b159d`, `69ffd13`, `603e140`, `e63f943`): partial-fail via offline, partial-fail via timeout, state-PV publication on partial fail, all-fail via emergency catch-all path, all-fail via `_classify(ok=0, fail=N)` path, concurrent CA acquire raises, putter re-raise unit, putter no-reader-noop unit.

**Decisions worth recording:**

1. **Construct-time-only fault injection.** Rejected runtime mutation (`fake_ioc.bpm_offline(name)` mid-test). Caproto doesn't gracefully handle a connected channel suddenly disappearing, and explicit setup-time topology is easier to reason about than mid-test state changes. If a future M-something needs to model "BPM goes offline during a session," it'll be its own milestone.

2. **`"slow"` default delay = 3.0 s, not configurable per-prefix.** Single global delay above the production `per_pv_timeout_s=2.0` covers every test scenario currently anticipated. If a future test needs per-prefix delays (e.g. timeout-boundary testing), extend the parameter to a `dict[str, float]` then. YAGNI for now.

3. **Caproto pvproperty getter syntax: positional `get` argument** (tag `[m3-task2-getter-syntax]`). The plan suggested two patterns: `@c0.getter` decorator first, `read=` keyword second. Neither worked in the installed caproto (the decorator shadows the descriptor; `read=` is rejected by `ChannelData.__init__`). The third pattern — passing the getter as the first positional argument to `pvproperty(...)` — is the documented primary API per `pvproperty.__init__(get: Optional[Getter] = None, ...)`. The fixture's `_make_slow_bpm_group` docstring documents this so a future maintainer doesn't refactor it back to the decorator form. caproto version at time of choice: 0.8.x.

4. **Re-raise rather than alarm on STATE:ACQUIRE_IN_FLIGHT for concurrent CA acquire.** Symmetry with REST 409 is more important than EPICS-native alarm aesthetics: any client that wrote to `CMD:ACQUIRE` cares whether their write took effect. Alarms are for observers; this is a writer concern.

5. **Concurrent CA test observes `CaprotoTimeoutError`, not an explicit error response.** When the putter re-raises, caproto 0.8.x's server logs the exception but doesn't send a write-NAK packet. The client times out waiting for the ACK. The test pins to `caproto.CaprotoTimeoutError` with an inline `ON CAPROTO UPGRADE` comment pointing at `ErrorResponseReceived` as the likely replacement if a future caproto version adds explicit write-error encoding. Pinned narrow rather than broadened to a tuple because importing a not-yet-existing class would itself break under the current version.

6. **Concurrent test uses `state.acquire_in_flight=True` at entry rather than overlapping two real acquires.** Same idiom as the REST test (`test_post_acquire_concurrent_returns_409`). The behavior under test is "putter raises when in-flight is set," not "two concurrent puts race." Avoids timing flakiness.

7. **Slow-prefix must be last in the prefix list** (test 2 of `test_acquire_partial_fail.py`). The in-process caproto fake IOC and the CA client share an asyncio event loop. When a slow getter calls `asyncio.sleep(3.0)`, it stalls the server's dispatch loop — reads queued AFTER the sleep don't get served until it completes, causing those clients to time out too. Placing the slow BPM last in the prefix list lets the four fast BPMs get fully served before the slow getter blocks. This is a test-fixture-only artefact, not a production behavior difference: real Libera BPMs are on separate networked IOCs. Machine-enforced by `assert fake_bpm_ioc.prefixes[-1] == "FAKE:BPM5"` at test entry so a future parametrize change can't silently break the timing guarantee.

8. **All-fail has TWO valid paths and we test both.** The plan's original test only hit the handler's emergency catch-all (when `reader.start()` raises on get_pvs timeout, then `read_all` raises because `_started=False`). Code-quality review caught that this never exercised `_classify(ok=0, fail=N) → FAILED`. Added a second test using `all-slow` so `start()` succeeds, `read_all` returns `{prefix: None for all}`, and the handler reaches `_classify` normally. Both end states are identical from an observer's perspective; both internal paths deserve coverage.

9. **Concurrent CA test's `pytest.raises` was pinned post-pass.** The plan started with `pytest.raises(Exception)` as a diagnostic shape, with explicit instructions to narrow after the first run revealed the actual class. Followed that process: ran with a diagnostic try/except print, observed `CaprotoTimeoutError`, narrowed and committed.

**Tests:** 10 new tests (2 fixture-verification in `test_fake_bpm_ioc.py` + 3 partial-fail + 2 all-fail + 1 concurrent-CA = 8 integration, plus 2 unit). Full suite is now 113/113 (up from 103 at end of M2). The slow-prefix tests add ~3 s wall time each (intentional — exercising the real `wait_for` timeout), so M3 added ~10 s to the full-suite total. Acceptable.

**Spec relationship:** M3 closes spec §11 M3 and its DoD lines ("simulated timeout produces NaN gap in plot + correct fail count in state PV; concurrent ACQUIRE returns 409 cleanly").

**Forward impact:**

- Phase 2 has just one milestone left: M4 (Raw REST `/result/bpm/raw`, UI polish, Playwright e2e).
- The fault-injection fixture is now reusable for any future "what if a BPM is unreachable?" test in any later phase.
- The `cmd_acquire` putter is now in symmetric error-surfacing parity with REST. Future commands (if added) should follow the same pattern: handler raises → putter re-raises → CA client sees a failed write.
- The slow-prefix-must-be-last constraint is a real limitation worth knowing about: any future test that wants more than one slow BPM, or a slow BPM in the middle, will hit the same shared-event-loop ordering issue. Two ways to address if it comes up: (a) split the fake IOC into a separate process, (b) construct a separate caproto `Context` per BPM. Both are bigger investments; defer until needed.
- The caproto-version dependence of `CaprotoTimeoutError` in the concurrent-CA test will likely break on a future upgrade. The inline upgrade-hint comment points at the remediation path.

Tag: `[m3-failure-handling]`.
