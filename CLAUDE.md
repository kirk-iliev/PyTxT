# PyTxT

Turn-by-turn beam analysis app for the ALS injection chain. Python backend +
browser frontend + soft EPICS IOC. Port of MATLAB `TxT_GUI.mlapp`.

## North-star principles

These bias every design decision — refer back when in doubt.

### 1. Agent-callable first, human-callable second

PyTxT is built to operate within **Osprey**, the harnessed-Claude framework
the ALS runs for agentic accelerator operation. Every meaningful capability
this app provides — every command, every readable piece of state, every
analysis result — must be invokable and observable by an agent without
special web-API knowledge. The browser UI is one consumer of these
capabilities, not the privileged one.

Concrete implications:

- **Every CMD has both a PV and a REST endpoint, with identical effect.** An
  agent can choose its preferred transport. The browser uses the same
  surface. No private "UI-only" command paths.
- **Schemas are first-class.** Pydantic models for every request/response,
  OpenAPI auto-generated, every field named for clarity rather than
  brevity. Agents can't read implicit conventions.
- **State is observable.** Every command has a corresponding state PV (or
  state field) that confirms what happened — not just "did the call return
  200." Agents need to verify outcomes.
- **Idempotency where it makes sense.** Agents retry; commands should be
  safe under retry, or fail loudly if they aren't.
- **Discoverability.** OpenAPI + descriptive endpoint names + every PV
  carries a description string. An agent (or human) reading the API
  spec should be able to figure out what's available.
- **Plan for MCP exposure.** The REST API should be shaped such that an
  MCP server wrapping it would be a thin adapter, not a redesign.

### 2. PVs are the primary state interface

Application state — fit results, reference trajectory, tracking on/off,
liveness — is published as **EPICS PVs via a soft IOC**, not held in
process memory behind a private API. This means Phoebus, the archiver,
the alarm system, and Osprey agents can all subscribe to PyTxT the same
way they subscribe to any magnet IOC. The browser is "just another CA
client that happens to render images."

This is the deliberate divergence from PyBeamViewer (which is REST/WS
only, with state in process memory). Don't replicate PyBeamViewer's
state model in PyTxT.

### 3. REST/WS handles what PVs can't

PVs are right for: scalar state, waveforms, commands, liveness, anything
the broader control system might want. REST/WS is right for: bulk
transfers (waveform downloads, reference-file I/O), file uploads, static
asset serving, and the WS-to-CA bridge that lets the browser subscribe
to PVs. Don't put bulk file content in PVs; don't put live state in REST
polling.

### 4. Forward-looking package layout, not a PyBeamViewer clone

PyBeamViewer is single-subsystem (camera frames in, JPEGs out). PyTxT is
multi-subsystem (CA client + soft IOC + analysis + REST/WS + frontend,
all coordinated). Mirror PyBeamViewer's *patterns* (single-process
asyncio, vanilla JS + Canvas, Pydantic schemas, Playwright e2e) but
*not* its directory structure. Each subsystem gets its own clearly
bounded package.

### 5. Domain logic is I/O-free

Pure analysis (trajectory windowing, response-matrix math, reference
comparison) lives in a `domain/` package that has no caproto, no
FastAPI, no asyncio dependencies. Testable in milliseconds with numpy
alone. Adapters above it (CA client, IOC server, REST routes) translate
to and from this pure core.

## Stack

Python 3.10+ (control-room hosts run 3.10), FastAPI + uvicorn, **caproto** (IOC server *and* CA client,
both async on one event loop), **pySC** (port of MATLAB SC toolkit —
lattice modeling, response matrix, SVD pseudo-inverse), numpy/scipy,
Pillow. Frontend: vanilla JS + Canvas + CSS custom properties (no
framework). Tests: pytest + Playwright. Container: python:3.12-slim,
docker-compose. Deploy target: appsdev2, port 8008.

## Where things live

- `docs/PyTxT-overview.md` — **canonical end-to-end overview**: what
  PyTxT is, origin, machine context, architecture, live PV + REST
  surfaces, status, roadmap. Refresh when the public surface or
  architectural picture changes.
- `legacy/TxT_GUI/` — original MATLAB GUI (.mlapp, unpacked .m sources)
- `legacy/automated_startup/` — `SCexp_ALS_*.m` operational glue
  (reference for porting hardware interactions); plus lattice files
- `PyTxT-project-plan.html` — locked scope, phased delivery (owner: PI).
  Read for "what we're building" and "in scope vs. out of scope"
- `PyTxT-roadmap.html` — live status dashboard; refresh after every
  milestone / phase completion or major architectural change
- `orientation.md` — short stub pointing at the overview
- `TxT_GUI_manual.pdf` — the 18-step user workflow that defines feature
  parity
- `docs/superpowers/specs/` — per-phase design specs (created via the
  brainstorming → writing-plans flow). Each spec has a paired
  `<spec-name>-decisions.md` log; see below.

## Implementation decision logs

Every phase spec gets a companion decision log at
`docs/superpowers/specs/<spec-name>-decisions.md`. During any
implementation session executing a spec, append entries to this log
for:

- Choices made because the spec was silent on something (gap-filling).
- Deviations from the spec (with reason).
- Tradeoffs taken where the spec didn't pick.
- Surprises from real code / data / upstream APIs.
- Test infrastructure shortcuts, ergonomic refactors extracted during
  the work, library or dependency choices made mid-implementation.

If a decision invalidates a spec section, also update the spec.
The log is for context and history; the spec stays authoritative.
The decision log file itself documents its own entry format — copy the
template at the top of each log when adding entries.

## Status

Phases 1–3 **complete** (skeleton/IOC → read path → reference trajectory, the
last shipped 2026-06-01). Phase 4 (threading workflow) — next. Live detail:
`PyTxT-roadmap.html`; end-to-end picture: `docs/PyTxT-overview.md`.

## Open architectural questions to resolve as we go

- **Osprey integration shape**: does Osprey prefer to invoke services via
  HTTP/REST, via MCP, via CA directly, or all three? Until known, design
  for all three to be cheap to add.
- **MML-wrapped operations** (`srinjectoneshot`, `steppv`): two external
  MATLAB Middle Layer functions (not in repo) hide the injection-trigger and
  CM-step PVs. **Key finding (see `docs/phase-4-injection-notes.md`):** in the
  legacy GUI, firing injection is an *optional* checkbox step
  (`enable_inject`) — the passive arm+read+analyze path (which PyTxT already
  implements) works without it. So these are optional, safety-gated Phase-4
  conveniences, not blockers. De-box via `type srinjectoneshot` / `camonitor`
  on a control-room host. The BPMs latch on timing **event 48**.
- **Test-IOC port isolation**: dev IOC must use `OSPREY:TEST:TXT:*`
  prefix and ports 59064/59065 per als-profiles safety rules. Production
  uses real `TxT:*`. Make this config-driven from day 1.
