# PyTxT Phase 1 — Skeleton + Hello-World IOC

**Status:** Design (approved, ready for implementation planning)
**Date:** 2026-05-06
**Scope:** Phase 1 of 6 (per `PyTxT-project-plan.html`)
**Owner:** Kirk
**Drafted with:** Claude (Opus 4.7)

---

## 1. Purpose

Establish the architectural skeleton for PyTxT — soft IOC + CA client + FastAPI + browser frontend, all coordinated on a single asyncio loop — and validate the round-trip end-to-end with a minimal hello-world feature surface. Every architectural seam that phases 2–5 depend on must be exercised and tested by the end of phase 1.

Phase 1 is the foundation. It does not implement any beam-physics functionality. It does prove that:

- A soft IOC can publish app state as PVs that external CA clients can subscribe to.
- A FastAPI service can serve REST and a WebSocket bridge that exposes those same PVs to a browser.
- A browser can both observe state changes (via WS) and issue commands (via REST POST).
- An external agent can issue the same commands via CA writes, with **bit-identical effect**.
- Every subsystem has a clearly bounded home in the repo such that phases 2–5 add code without restructuring.

---

## 2. North-star principles (binding for this design)

These derive from `CLAUDE.md` and are the constraints every decision below answers to.

### 2.1 Agent-callable first

PyTxT is built to operate within **Osprey** (the ALS's harnessed-Claude framework for agentic accelerator operation). Every meaningful capability is invokable and observable by an agent without special web-API knowledge. The browser UI is one consumer; agents are first-class peers.

Concretely:

- Every CMD has both a PV and a REST endpoint with **identical effect**.
- Schemas are first-class (Pydantic for everything; OpenAPI auto-generated; descriptive field names).
- Every command has a corresponding state PV / state field that confirms the outcome — not just an HTTP 200.
- Discoverability is intrinsic: every PV carries a `.DESC` description; every endpoint is in OpenAPI.
- The REST API is shaped such that an MCP server wrapping it would be a thin adapter, not a redesign.

### 2.2 PVs are the canonical state interface

Application state lives in EPICS PVs published by an embedded soft IOC (caproto). The canonical external interface is CA. Anyone (Phoebus, archiver, alarm system, Osprey agent, browser via the WS bridge) reads state by subscribing to PVs. **Nothing important lives only in process memory.**

This is the deliberate divergence from PyBeamViewer (which is REST/WS-only with state in process memory). PyTxT must not repeat that.

### 2.3 REST/WS handles only what PVs can't

PVs are right for: scalar state, waveforms, commands, liveness. REST/WS is right for: bulk transfers (waveform downloads, file I/O), static asset serving, the WS-to-CA bridge that lets the browser subscribe to PVs, OpenAPI discoverability, transport-level health probes.

Nothing in REST/WS adds state that isn't already a PV.

### 2.4 Forward-looking package layout

PyTxT is multi-subsystem (CA client + soft IOC + analysis + REST/WS + frontend). Each subsystem gets its own clearly bounded package. Mirror PyBeamViewer's *patterns* (single-process asyncio, vanilla JS + Canvas, Pydantic schemas, Playwright e2e), not its directory structure.

### 2.5 Domain logic is I/O-free

Pure analysis and data shapes live in a `domain/` package with no caproto, no FastAPI, no asyncio dependencies. Testable in milliseconds with numpy alone.

---

## 3. Architectural pattern: AppState-centered with shared handlers

```
                    ┌─────────────────────────────────┐
upstream PVs ──CA──▶│                                 │── IOC ──▶ CA subscribers
(phase 2+)          │           AppState              │           (Phoebus, Osprey,
                    │  (dataclass, single source of   │            archiver)
operator command ──▶│   truth, change-notification)   │
   • CMD PV write   │                                 │── REST GET /state
   • POST /cmd/...  │  ▲                              │── WS broadcast (via
                    │  │                              │    in-process CA bridge)
                    └──┴──── domain (pure, no I/O) ───┘
                         (called by handlers below)

           handlers/  (pure functions; called by BOTH the IOC CMD-PV
                       dispatcher and the REST POST routes — identical
                       effect by construction)
```

**The structural claim:** agentic parity (CA write ≡ REST POST) is enforced by the type system and import graph, not by review discipline. The same Python function is invoked whether the trigger arrived via CA or HTTP. There is no path by which the two surfaces can drift.

This pattern is chosen over a controller-centered alternative (PyBeamViewer-style) because that pattern degenerates a controller class into a god-object as subsystem count grows, and reduces parity to "remember to call the same method." Event-bus alternatives are rejected as overkill — PyTxT has 4–5 fixed long-lived subsystems, not a dynamic plugin ecosystem.

---

## 4. Package layout

```
PyTxT/
├── pytxt/                          # the application package
│   ├── __init__.py
│   ├── __main__.py                 # `python -m pytxt` entry point
│   ├── composition.py              # wires subsystems onto one asyncio loop
│   │
│   ├── domain/                     # PURE — no caproto, no FastAPI, no asyncio
│   │   ├── __init__.py
│   │   └── README.md               # "this package has zero I/O dependencies"
│   │   # phase 2+: trajectory.py, reference.py
│   │   # phase 4+: response_matrix.py
│   │
│   ├── state/                      # AppState — single source of truth
│   │   ├── __init__.py
│   │   ├── app_state.py            # dataclass + change-notification
│   │   └── README.md
│   │
│   ├── handlers/                   # command handlers (pure async functions)
│   │   ├── __init__.py             # called by IOC dispatcher AND REST routes
│   │   ├── ping.py                 # phase 1's canonical handler
│   │   └── README.md
│   │
│   ├── ca_client/                  # CA *consumer* (reads upstream BPM/CM PVs)
│   │   ├── __init__.py
│   │   └── README.md               # phase 2+: client.py, pv_map.py, readout.py
│   │
│   ├── ioc/                        # caproto soft IOC — publishes app state as PVs
│   │   ├── __init__.py
│   │   ├── server.py               # IOC server lifecycle + state binding
│   │   ├── pvs.py                  # PVGroup with per-PV definitions; CMD putters
│   │   │                           #   call handlers/ inline in phase 1
│   │   └── README.md
│   │                               # phase 2+: dispatcher.py (extracted when 5+ CMDs exist)
│   │
│   ├── api/                        # FastAPI HTTP + WS
│   │   ├── __init__.py
│   │   ├── server.py               # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py           # GET /health
│   │   │   ├── state.py            # GET /api/v1/state
│   │   │   └── cmd.py              # POST /api/v1/cmd/* → same handlers as IOC
│   │   ├── ws_bridge.py            # WS /api/v1/pvs — in-process CA → browser bridge
│   │   ├── schemas/                # Pydantic models (request/response/PV)
│   │   │   ├── __init__.py
│   │   │   ├── state.py            # StateSnapshot
│   │   │   ├── cmd.py              # PingResponse
│   │   │   └── ws.py               # WSMessage shapes
│   │   └── README.md
│   │
│   ├── frontend/                   # static assets served by FastAPI
│   │   ├── index.html
│   │   ├── css/theme.css
│   │   ├── js/app.js
│   │   ├── js/connection.js        # WS subscription helper, reconnect logic
│   │   └── README.md
│   │
│   └── config/                     # env-driven settings
│       ├── __init__.py
│       ├── settings.py             # PV prefix, ports, dev vs. prod
│       └── README.md
│
├── tests/
│   ├── conftest.py                 # shared pytest fixtures
│   ├── unit/                       # domain + handlers + state, no I/O
│   │   ├── test_app_state.py
│   │   ├── test_handlers_ping.py
│   │   ├── test_settings.py
│   │   └── test_schemas.py
│   ├── integration/                # IOC + REST + WS end-to-end (real caproto)
│   │   ├── test_ioc_lifecycle.py
│   │   ├── test_ping_via_ca.py
│   │   ├── test_ping_via_rest.py
│   │   ├── test_parity.py          # THE keystone test (load-bearing)
│   │   ├── test_ws_bridge.py
│   │   ├── test_state_endpoint.py
│   │   └── test_health_endpoint.py
│   └── e2e/
│       ├── playwright.config.js
│       ├── package.json
│       ├── smoke.spec.js
│       └── ping.spec.js
│
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml          # base, bridge networking
│   └── docker-compose.host.yml     # overlay for host networking (prod)
│
├── docs/
│   └── superpowers/specs/          # this file lives here
│
├── legacy/                         # MATLAB reference (already exists)
├── data/                           # reference trajectories (.mat files, phase 3+)
│
├── pyproject.toml
├── README.md
├── CLAUDE.md                       # north-star principles
├── orientation.md                  # first-time orientation
├── PyTxT-project-plan.html         # locked scope, phased delivery (PI-owned)
├── TxT_GUI_manual.pdf              # 18-step user workflow
├── .env.example                    # documented setting reference
└── Makefile                        # test/dev convenience targets
```

### 4.1 Package responsibilities (what each owns / doesn't own)

| Package | Owns | Does not own |
|---|---|---|
| `domain/` | Pure analysis math, data shapes, trajectory algebra (phase 2+) | Any I/O, any networking, any state mutation |
| `state/` | The `AppState` dataclass, change-notification fan-out | Business logic, transport details |
| `handlers/` | Command handlers as pure async functions `(state, args) → effect` | Knowing whether the caller is CA or REST |
| `ca_client/` | Async CA reads from upstream PVs; turning waveforms into domain types; writing upstream commands (phase 2+) | App's own published state |
| `ioc/` | Soft IOC server; PV definitions; reflecting `AppState` changes outward; dispatching CMD-PV writes to handlers | Business logic; HTTP/WS |
| `api/` | FastAPI app, REST routes, WS bridge, Pydantic schemas | PV semantics (delegates to `ioc/handlers/`) |
| `frontend/` | Browser UI, WS subscription, Canvas rendering (phase 2+) | Anything Python-side |
| `config/` | Settings (env-driven; supports dev `OSPREY:TEST:TXT:*` ↔ prod `TxT:*`) | Subsystem internals |
| `composition.py` | Constructing every subsystem and starting the asyncio loop | Any subsystem's logic |

### 4.2 Why these boundaries

- **`handlers/` is its own package, not under `ioc/` or `api/`.** That's the structural enforcement of agentic parity. Both transports import from `handlers/`. There is no "REST handler" or "PV handler"; there is *the* handler.
- **`state/` is separate from `domain/`.** `domain/` is timeless functions; `state/` is "what's true right now." Mixing them means importing the math drags in the state object.
- **`ca_client/` and `ioc/` are siblings, not nested under an `epics/` package.** They have opposite responsibilities (consume upstream / publish own). Conflating them obscures that.
- **`composition.py` is at the top level.** Wiring is its own concern, not buried inside any subsystem. New subsystems are added by editing this one file.

### 4.3 What phase 1 actually populates

**Real code:** `composition.py`, `__main__.py`, `state/app_state.py`, `handlers/ping.py`, `ioc/{server,pvs}.py`, `api/{server,ws_bridge}.py`, `api/routes/{health,state,cmd}.py`, `api/schemas/{state,cmd,ws}.py`, `frontend/{index.html,css/theme.css,js/{app,connection}.js}`, `config/settings.py`, `pyproject.toml`, `docker/{Dockerfile,docker-compose.yml,docker-compose.host.yml}`, all test files listed above.

**Empty (with placeholder README):** `domain/`, `ca_client/`. These are real packages with `__init__.py` and a README explaining what'll go there. Phase 2 fills them without restructuring.

---

## 5. Phase 1 feature surface

### 5.1 PVs published by the IOC

Prefix is config-driven: `OSPREY:TEST:TXT:` in dev, `TxT:` in prod.

| PV | Type | Dir | Description (becomes `.DESC`) |
|---|---|---|---|
| `<prefix>HEALTH:HEARTBEAT` | int | RO | Liveness counter; increments every 1 second |
| `<prefix>HEALTH:UPTIME_S` | float | RO | Seconds since process start |
| `<prefix>STATE:VERSION` | string | RO | Semver of running app, from package metadata |
| `<prefix>STATE:LAST_PING_AT` | string | RO | ISO-8601 timestamp of most recent ping; empty until first ping |
| `<prefix>STATE:PING_COUNT` | int | RO | Pings received since startup |
| `<prefix>CMD:PING` | int | WO | Writing any value triggers the ping handler; value ignored |

### 5.2 REST endpoints (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Standard health probe. Returns `{"status": "ok", "uptime_s": float}`. Always HTTP 200. |
| `GET` | `/api/v1/state` | Full `AppState` snapshot. Returns `{version, heartbeat, uptime_s, last_ping_at, ping_count}`. Pure projection of state PVs. |
| `POST` | `/api/v1/cmd/ping` | Issue a ping. Body: `{}`. Response: `{"acknowledged_at": ISO8601}`. Calls `handlers.ping.handle_ping`. |
| `GET` | `/openapi.json` | Auto-generated OpenAPI spec. **The agent-facing API contract.** |
| `GET` | `/docs` | Swagger UI for humans. |
| `WS` | `/api/v1/pvs` | WebSocket. Generic "subscribe to PV by name." See §5.4 for protocol. |
| `GET` | `/` and `/static/*` | Frontend serving (`index.html`, CSS, JS). |

### 5.3 Browser page (single panel)

- **Connection status indicator** (top-right) — green dot when WS connected, red when not. Reused as affordance pattern in phases 2–5 for upstream-CA connection state.
- **Heartbeat: `142`** — live from `HEALTH:HEARTBEAT`.
- **Uptime: `0:02:23`** — derived from `HEALTH:UPTIME_S`.
- **Version: `0.1.0`** — from `STATE:VERSION`.
- **Last ping: `2026-05-06 14:32:01`** (or `—`) — from `STATE:LAST_PING_AT`.
- **Ping count: `3`** — from `STATE:PING_COUNT`.
- **`[ Ping ]`** button — `POST /api/v1/cmd/ping`.
- **Event log** (last ~10 entries) — every WS message rendered with timestamp.

No tabs. No Canvas. No multi-page UI. CSS is structured for theme reuse (custom properties for `--bg`, `--fg`, `--accent`, `--green`, `--red`, `--monospace`, dark default).

### 5.4 WS protocol

```
client → server:  {"action": "subscribe",   "pvs": ["<prefix>STATE:HEARTBEAT", ...]}
client → server:  {"action": "unsubscribe", "pvs": [...]}
server → client:  {"pv": "<prefix>STATE:HEARTBEAT", "value": 142, "ts": "2026-05-06T14:32:01Z"}
server → client:  {"pv": "...", "error": "PV not found"}
```

**On subscribe:** the bridge immediately sends the current value, so the browser doesn't sit blank. All values come from caproto reads, not Python-internal short-circuits.

---

## 6. Component design

### 6.1 `state/app_state.py` — the keystone

```python
@dataclass
class AppState:
    heartbeat: int = 0
    last_ping_at: Optional[str] = None       # ISO-8601 string
    ping_count: int = 0
    version: str = ""
    started_at: float = 0.0

    _listeners: dict[str, list[Callable[[Any], Awaitable[None]]]] = field(default_factory=dict, init=False)

    @property
    def uptime_s(self) -> float:
        return time.time() - self.started_at

    def subscribe(self, field: str, callback: Callable[[Any], Awaitable[None]]) -> None:
        self._listeners.setdefault(field, []).append(callback)

    async def update(self, **changes) -> None:
        for k, v in changes.items():
            old = getattr(self, k)
            if old != v:
                setattr(self, k, v)
                for cb in self._listeners.get(k, []):
                    try:
                        await cb(v)
                    except Exception:
                        logger.exception(f"AppState listener for {k!r} failed")
                        # other listeners still fire
```

Properties:

- Strongly typed.
- `update()` is the single mutation entry point. Multi-field updates are atomic.
- Equality check suppresses spurious notifications.
- Listeners are async (because IOC PV writes are async in caproto).
- Per-listener exception isolation: a failing listener logs and is skipped; others fire.

### 6.2 `handlers/ping.py` — the parity unit

```python
async def handle_ping(state: AppState) -> None:
    """Record that a ping was received. Side effects: increments ping_count, sets last_ping_at."""
    await state.update(
        last_ping_at=datetime.now(timezone.utc).isoformat(),
        ping_count=state.ping_count + 1,
    )
```

Both the IOC's `CMD:PING` putter and the REST `POST /api/v1/cmd/ping` route call this exact function. The shared import is the structural enforcement of agentic parity.

Future handlers follow the same shape: `async def handle_<name>(state, **args) -> Optional[Result]`. Args come from JSON body (REST) or auxiliary STATE PVs (CA).

### 6.3 `ioc/`

**`pvs.py`** — caproto `PVGroup` with one `pvproperty` per PV. Each carries `dtype`, `read_only`, `name=...`, and a `doc=` string (becomes the PV's `.DESC` field).

```python
class PyTxTPVGroup(PVGroup):
    heartbeat = pvproperty(value=0, dtype=int, read_only=True,
                           name="HEALTH:HEARTBEAT",
                           doc="Liveness counter; increments every 1 second")
    cmd_ping = pvproperty(value=0, dtype=int, name="CMD:PING",
                          doc="Write any value to issue a ping")

    @cmd_ping.putter
    async def cmd_ping(self, instance, value):
        await handle_ping(self.parent.state)
        return value  # value itself is ignored
```

**`server.py`** — wraps `PVGroup` with state binding:

1. Constructs the `PVGroup` with the configured prefix.
2. Subscribes itself to every relevant `AppState` field via an explicit `field → pvproperty` map.
3. Each subscription writes the new value to the corresponding caproto PV.
4. Exposes `run()` to start the IOC server on the asyncio loop.

The `field → PV` map is one explicit dict in `server.py`. Adding a published field = add to dict + add `pvproperty` definition.

**`dispatcher.py`** — phase 1 inlines dispatch in PV putters (one CMD, no abstraction needed). Phase 2+ extracts a generic dispatcher when there are 5+ commands.

### 6.4 `api/`

**`server.py`** — FastAPI app factory. Receives `app_state` and `ioc` references, mounts routers, mounts the static frontend at `/`. App metadata generates a clean OpenAPI doc. CORS is permissive for control-room network (per plan).

**`routes/`** — three small modules:

- `health.py` — `GET /health` → `{"status": "ok", "uptime_s": app_state.uptime_s}`
- `state.py` — `GET /api/v1/state` → `StateSnapshot` Pydantic model
- `cmd.py` — `POST /api/v1/cmd/ping` → `await handle_ping(app_state)` → `{"acknowledged_at": ISO8601}`

**`schemas/`** — Pydantic models. `StateSnapshot`, `PingResponse`, `WSMessage` shapes.

### 6.5 `api/ws_bridge.py` — the in-process CA bridge (chosen design)

The WS bridge runs an **in-process caproto async client** that subscribes to the IOC's PVs by name and forwards CA updates to WS clients.

**Why this over an AppState-direct bridge:**

1. **Plan parity** — "the browser becomes just another CA client" is true: the browser's WS payloads are produced by a CA subscription, not a Python-internal sidestep. Type coercion goes through the same path external CA clients see.
2. **Phase 2 reuse** — phase 2 forwards upstream BPM PVs to the browser; those aren't in `AppState`, they're external. The CA-client-bridge mechanism handles app-published and upstream PVs uniformly. An AppState-direct bridge would need a second mechanism for phase 2.

Cost: in-process CA round-trip (microseconds on localhost) — negligible.

Per-WS-client lifecycle:

1. Client connects, sends `{"action": "subscribe", "pvs": [...]}`.
2. Bridge starts caproto subscriptions for each PV.
3. Send current value immediately on subscribe.
4. On each CA update, forward `{pv, value, ts}` JSON to the WS client.
5. On `unsubscribe`, drop the caproto subscriptions.
6. On disconnect, clean up all subscriptions for that client.

### 6.6 `frontend/`

- **`index.html`** — semantic structure. Section IDs match what `app.js` reads. No inline JS.
- **`css/theme.css`** — CSS custom properties (dark default). Forward-looking: future tabs, canvas plots reuse these.
- **`js/connection.js`** — WS connection encapsulation:
  ```js
  connection.subscribe(pvName, callback);   // get value updates
  connection.command(name, body);           // POST to /api/v1/cmd/<name>
  connection.status;                        // "connecting" | "connected" | "disconnected"
  connection.onStatusChange(callback);
  ```
  Auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s). On reconnect, re-subscribes to all previously-subscribed PVs.
- **`js/app.js`** — page logic. Subscribes to phase-1 PVs on load, updates DOM on changes, wires Ping button to `connection.command`, appends to event log.

### 6.7 `composition.py` — the wiring

```python
async def main():
    settings = Settings()
    settings.version = _resolve_version()   # importlib.metadata.version("pytxt")
                                             # with fallback to "0.0.0+dev"
    logging.basicConfig(level=settings.log_level)
    logger.info(f"PyTxT {settings.version} starting | prefix={settings.pv_prefix} | "
                f"ioc_port={settings.ioc_port} | api_port={settings.api_port}")

    state = AppState(version=settings.version, started_at=time.time())

    ioc = PyTxTIOC(
        prefix=settings.pv_prefix,
        host=settings.ioc_host,
        port=settings.ioc_port,
        state=state,
    )
    ioc.bind_state_changes(state)

    api_app = create_app(state, ioc, settings)
    server = uvicorn.Server(uvicorn.Config(api_app, host=settings.api_host, port=settings.api_port, log_config=None))

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(settings.heartbeat_interval_s)
            await state.update(heartbeat=state.heartbeat + 1)

    await asyncio.gather(
        ioc.run(),
        server.serve(),
        heartbeat_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())
```

The single place that knows about all subsystems. Adding a subsystem is one new `await` arg in `gather()`.

---

## 7. Data flow

### 7.1 Trace 1 — Browser issues a ping

```
Browser                                                      PyTxT process

Operator clicks [Ping]
    │
js/app.js: connection.command("ping", {})
    │
js/connection.js: POST /api/v1/cmd/ping  ───HTTP──▶  uvicorn → FastAPI
                                                          │
                                                   routes/cmd.py:ping
                                                          │
                                                   await handle_ping(state)   ◀── handlers/ping.py
                                                          │
                                                   state.update(last_ping_at=now_iso, ping_count=n+1)
                                                          │
                                                   AppState fires listeners for the two fields
                                                          │
                                                          ▼
                                                   ioc/server.py listener:
                                                     await pvgroup.last_ping_at.write(...)
                                                     await pvgroup.ping_count.write(...)
                                                          │
                                                   caproto broadcasts CA monitor
                                                          │
                                        ┌─────────────────┼─────────────────┐
                                        ▼                                   ▼
                              External CA subscribers              In-process CA client
                              (Phoebus, Osprey agent,              (api/ws_bridge.py)
                               archiver) see the change                    │
                                                                            ▼
                                                              WS broadcast to subscribed
                                                              browser clients:
                                                              {"pv": "...PING_COUNT",
                                                               "value": N+1, "ts": "..."}
    ◀───────────────────────WS──────────────────────────────────────────────┘
    │
js/connection.js fires the subscribe callback registered by app.js
    │
js/app.js: updates DOM "Ping count: N+1", appends to event log

(meanwhile, the original POST response returns
 {"acknowledged_at": "..."} — UI ignores it, since
 WS has already updated the page)
```

Every architectural seam is exercised. A failure of this trace localizes immediately to the broken link.

### 7.2 Trace 2 — External CA agent issues a ping

```
Osprey CA agent / Phoebus                                    PyTxT process

caput("TxT:CMD:PING", 1)  ─────CA write────▶  caproto IOC receives PUT
                                                       │
                                              PVGroup.cmd_ping.putter:
                                              await handle_ping(state)   ◀── handlers/ping.py (SAME)
                                                       │
                                              ... identical from this point to Trace 1 ...
```

The bottom half is **byte-for-byte identical** to Trace 1. Parity is structural.

### 7.3 Trace 3 — HTTP read of state

```
Osprey HTTP agent / curl                                     PyTxT process

GET /api/v1/state  ──HTTP──▶  routes/state.py
                                     │
                              StateSnapshot.from_app_state(state)
                                     │
                              Pydantic JSON serialization
                                     │
                              ◀── 200 {version, heartbeat, uptime_s, last_ping_at, ping_count}
```

Pure projection. No mutation. Equivalent to monitoring all state PVs at once.

### 7.4 Trace 4 — Heartbeat (autonomous read path)

```
composition.py:heartbeat_loop wakes every 1s
    │
await state.update(heartbeat=state.heartbeat + 1)
    │
AppState fires "heartbeat" listener
    │
IOC writes new value to TxT:HEALTH:HEARTBEAT
    │
┌───────────────────┴───────────────────┐
▼                                       ▼
External CA subscribers       WS bridge → all subscribed browsers
                              "Heartbeat: 142" updates in DOM
```

Same downstream pipeline as Trace 1. Validates that mutations from any source flow outward identically.

### 7.5 Error-handling disposition

- **Listener exceptions are isolated.** Per-listener try/except in `AppState.update()`. A faulty listener logs and is skipped; others fire.
- **Caproto write failures retry once.** Single retry with 50 ms backoff; failures beyond that log and proceed. The next heartbeat tick (or next state mutation) catches up.
- **WS client errors disconnect just that client.** Broken pipe, dead browser tab, malformed JSON → close that one connection. Other clients and the bridge's CA subscriptions are unaffected.
- **CA client disconnect from local IOC** (the WS bridge's connection): only happens on shutdown; bridge logs and exits its forwarding loop.
- **IOC bind failure on startup** (port already in use): hard fail, process exits with a clear message. The supervisor (Docker, systemd) restarts.
- **Frontend on disconnect:** `connection.js` auto-reconnects with exponential backoff. On reconnect, re-subscribes to all previously-subscribed PVs. Status indicator turns red while disconnected, green on reconnect.

---

## 8. Configuration

### 8.1 Settings model (`config/settings.py`)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PYTXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",          # unknown PYTXT_* env vars fail loud
    )

    # PV namespace
    pv_prefix: str = "OSPREY:TEST:TXT:"        # dev default; PROD MUST override
    # IOC server
    ioc_host: str = "0.0.0.0"
    ioc_port: int = 59064                       # dev default; PROD = 5064
    ioc_repeater_port: int = 59065              # dev; PROD = 5065
    # FastAPI / uvicorn
    api_host: str = "127.0.0.1"
    api_port: int = 8008                        # plan-allocated for PyTxT
    # App
    log_level: str = "INFO"
    heartbeat_interval_s: float = 1.0
    # Version is NOT a settings field — populated separately at startup from
    # importlib.metadata.version("pytxt"), with fallback to "0.0.0+dev" when
    # running from a non-installed checkout. Lives on Settings for ergonomic
    # access but is not env-overridable.
    version: str = ""  # set by composition.main() before AppState is constructed

    @field_validator("pv_prefix")
    @classmethod
    def _prefix_must_end_with_colon(cls, v: str) -> str:
        if not v.endswith(":"):
            raise ValueError(f"pv_prefix must end with ':' (got {v!r})")
        return v
```

### 8.2 Belt-and-suspenders test-IOC isolation

| Layer | Dev | Prod | What collision it prevents |
|---|---|---|---|
| **PV name prefix** | `OSPREY:TEST:TXT:` | `TxT:` | A dev IOC on the right port can't shadow real PVs because its names differ. |
| **CA server port** | `59064 / 59065` | `5064 / 5065` | A dev IOC with the wrong prefix can't be reached by clients pointing at the standard EPICS port. |

Both must be wrong simultaneously to cause a real-PV collision.

### 8.3 Environment files

```
.env.example              # checked in — documents every setting
.env                      # gitignored — local dev overrides (usually empty)
.env.test                 # checked in — used by integration tests
docker/.env.prod.example  # checked in — production reference values
```

`.env.example` is canonical documentation. Out of the box (no env file, no env vars), the app uses dev defaults. There is no path by which forgetting to set env vars accidentally publishes real `TxT:*` PVs.

### 8.4 Three operational modes (no MODE flag — env vars only)

| Scenario | Env you set | Result |
|---|---|---|
| Local dev (laptop) | nothing | dev defaults |
| Integration tests (local or future CI) | `PYTXT_IOC_PORT=0`, ephemeral | OS-assigned ports per test, no collision risk |
| Production (appsdev2) | `PYTXT_PV_PREFIX=TxT:`, `PYTXT_IOC_PORT=5064`, `PYTXT_IOC_REPEATER_PORT=5065`, `PYTXT_API_HOST=0.0.0.0` | real namespace, standard EPICS ports |

A startup-time log line surfaces the actual prefix and ports so operators see immediately whether they're in dev or prod mode.

### 8.5 Deliberate non-settings (for phase 1)

- API path prefix `/api/v1` — hardcoded. No v2 yet.
- Database / persistence — phase 1 has no persistence.
- Auth secrets — no auth in v1 per plan.
- Reconnect intervals, retry counts — sensible hardcoded defaults; promote to settings if/when a deployment needs to tune them.

---

## 9. Testing strategy

### 9.1 Three tiers

**Tier 1 — Unit (`tests/unit/`).** Pure logic, no I/O, no caproto, no FastAPI. Sub-millisecond per test; full suite under 1 second.

| File | Covers |
|---|---|
| `test_app_state.py` | `update()` fires registered listeners; equality suppresses no-op updates; `uptime_s` property; multi-field updates fire all listeners; per-listener exception isolation |
| `test_handlers_ping.py` | `handle_ping` increments `ping_count`, sets `last_ping_at` |
| `test_settings.py` | `pv_prefix` validator rejects no-trailing-colon; unknown env vars rejected; env-var override works |
| `test_schemas.py` | Pydantic models round-trip; required fields validated |

**Tier 2 — Integration (`tests/integration/`).** Real caproto IOC + real FastAPI + real WS bridge, all on ephemeral ports per test. ~30 seconds for full suite.

| File | Covers |
|---|---|
| `test_ioc_lifecycle.py` | IOC starts, publishes initial PV values, shuts down cleanly; `.DESC` fields populated |
| `test_ping_via_ca.py` | `caput` to `CMD:PING` triggers handler; `STATE:PING_COUNT` and `STATE:LAST_PING_AT` update via CA monitor |
| `test_ping_via_rest.py` | `POST /api/v1/cmd/ping` triggers handler; same state changes observed via CA |
| **`test_parity.py`** | **Keystone.** Pings via CA and REST produce bit-identical effects on AppState and PVs. **This test must remain green forever.** |
| `test_ws_bridge.py` | Subscribe → CA write → WS broadcast received with correct shape; current-value-on-subscribe; unsubscribe stops broadcasts; bad PV name returns clean error |
| `test_state_endpoint.py` | `GET /api/v1/state` projects current AppState; matches CA monitor values |
| `test_health_endpoint.py` | `GET /health` returns 200 with `{status, uptime_s}` immediately after startup |

**Tier 3 — End-to-end (`tests/e2e/`).** Playwright + Chromium against a running PyTxT process.

| File | Covers |
|---|---|
| `smoke.spec.js` | Page loads at `http://localhost:8008/`; `#heartbeat` shows a number > 0 within 3 seconds |
| `ping.spec.js` | Click `#ping-button`; `#ping-count` increments by 1 within 2 seconds |

### 9.2 The parity test (keystone)

```python
async def test_ping_parity_ca_vs_rest(running_app):
    state_before = await snapshot_full_state(running_app)

    await ca_caput(running_app.pv("CMD:PING"), 1)
    state_after_ca = await snapshot_full_state(running_app)
    diff_ca = diff_states(state_before, state_after_ca)

    await reset_to(running_app, state_before)

    await http_post(running_app, "/api/v1/cmd/ping", json={})
    state_after_rest = await snapshot_full_state(running_app)
    diff_rest = diff_states(state_before, state_after_rest)

    assert diff_ca == diff_rest, (
        "REST and CA paths produced different effects — "
        "agentic parity invariant violated"
    )
```

Every future command (`CMD:LOAD_REF`, `CMD:CALC_RM`, `CMD:APPLY_STEP`, …) is added as a parametrize argument to this test. The test grows by parameters, not by file count.

### 9.3 Test infrastructure

- **`tests/conftest.py`** — shared fixtures: `settings_fixture` (ephemeral ports), `app_state_fixture` (fresh AppState), `ioc_fixture` (running IOC), `running_app_fixture` (full composition).
- **`tests/e2e/playwright.config.js`** — Chromium only, base URL configurable, screenshots on failure.
- **`Makefile`** convenience targets: `make test`, `make test-unit`, `make test-integration`, `make test-e2e` (requires `make dev-up` for the server first).

### 9.4 Mocking philosophy

- **No mocking of caproto.** It's fast (microseconds in-process). Mocking would only validate the mock.
- **No mocking of FastAPI.** Use `httpx.AsyncClient` against the real ASGI app.
- **Phase 1 needs no test fixture data.** Synthetic states only. Phase 2+ adds `tests/fixtures/` with sample BPM data drawn from `legacy/automated_startup/2024-06-*_records_trajectory.mat`.

### 9.5 Coverage philosophy

No coverage-percentage target. The bar is:

1. The parity invariant has a dedicated test.
2. Every architectural seam (handlers, AppState listeners, IOC publishing, WS bridge, REST routes, frontend) has at least one test that exercises it.
3. Every error-handling branch has at least one test.

### 9.6 CI

**Not in phase 1.** Phase 1 sets up the test infrastructure such that running `make test` works locally. Wiring CI (GitHub Actions / GitLab) is part of phase 6 (hardening + deploy).

---

## 10. Docker & deployment

### 10.1 `docker/Dockerfile`

Single-stage, mirrors PyBeamViewer:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY pytxt/ pytxt/

EXPOSE 8008
EXPOSE 5064/tcp 5064/udp 5065/tcp 5065/udp

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8008/health || exit 1

ENTRYPOINT ["python", "-m", "pytxt"]
```

### 10.2 Compose files

Two files, following PyBeamViewer's pattern:

- **`docker-compose.yml`** — base service, bridge networking. Useful where host networking works oddly (macOS dev). EPICS broadcast doesn't traverse Docker bridge, so this is dev-only.
- **`docker-compose.host.yml`** — overlay that switches to `network_mode: host`. **Required for production** because EPICS Channel Access uses UDP broadcast for PV name resolution.

```yaml
# docker-compose.yml (excerpt)
services:
  pytxt:
    build: { context: .., dockerfile: docker/Dockerfile }
    env_file: .env
    ports: ["8008:8008"]
    restart: unless-stopped
    volumes:
      - ../data:/app/data:ro    # reference trajectories (phase 3+)
```

Production deploy:
```bash
docker compose -f docker-compose.yml -f docker-compose.host.yml up -d
```
with `.env.prod` injected by ALS deploy tooling (the `als-build-deploy` skill referenced in the plan).

### 10.3 Local dev flow

Both paths supported equally:

```bash
# Native (preferred on macOS)
pip install -e .
python -m pytxt
# → http://localhost:8008/

# Docker (preferred on Linux for parity with prod)
docker compose up --build
# → http://localhost:8008/
```

Both produce identical behavior given the same env vars.

---

## 11. Definition of done

Phase 1 is shippable when **all** of the following pass:

1. `python -m pytxt` runs locally with no env vars; uses dev defaults (`OSPREY:TEST:TXT:*`, ports `59064/59065`, `8008`).
2. Browser at `http://localhost:8008/` shows live-updating heartbeat, version, uptime, ping count, last-ping; connection-status indicator green.
3. Clicking the **Ping** button increments `ping count` in the browser within 2 seconds.
4. `caput OSPREY:TEST:TXT:CMD:PING 1` from a separate terminal increments `ping count` in the browser within 2 seconds.
5. `caget OSPREY:TEST:TXT:STATE:HEARTBEAT` returns the current counter value.
6. `curl http://localhost:8008/api/v1/state` returns JSON containing every state field.
7. `curl -X POST http://localhost:8008/api/v1/cmd/ping -d '{}' -H 'Content-Type: application/json'` increments `STATE:PING_COUNT` (verifiable via either CA or another `/state` call).
8. `curl http://localhost:8008/openapi.json` returns a valid OpenAPI spec listing every endpoint with descriptions.
9. `make test` passes — all three tiers, including the parity test.
10. `docker compose up --build` produces the same observable behavior as native run.

When all 10 are true, phase 1 is complete and phase 2 may begin.

---

## 12. Explicit non-scope

These belong to later phases. If they show up in implementation, push back — they have homes already.

| Deferred to | What |
|---|---|
| Phase 2 | Upstream BPM CA reads, waveform Canvas plotting, the read-path handler, BPM/CM enumeration |
| Phase 3 | `.mat` reference file load/save, REST file upload/download, the active-reference state |
| Phase 4 | Lattice loading, `SCgetModelRM` / `SCgetPinv` (via pySC), CM step calc and apply, MML resolution for `srinjectoneshot` and `steppv`, `FirstTurnThreading.m` port |
| Phase 5 | Gaussian fits, dispersion calcs, RMS metrics, full UI parity with the MATLAB GUI's tab structure |
| Phase 6 | CI pipeline, log shipping, monitoring/alerting wiring, production hardening, Phoebus screen examples |
| Out of scope per plan | Auth, BBA, septum scan, LEDA, full automated_startup chain |

---

## 13. Forward compatibility — what phase 2 looks like on this foundation

Concrete additions to validate the layout pays off:

- New code in **previously empty** packages: `ca_client/{client,pv_map,readout}.py`, `domain/trajectory.py`.
- New handler: `handlers/readout.py` (calls `ca_client.readout()`, mutates `AppState.current_trajectory`).
- New `AppState` fields: `current_trajectory`, `current_sum`, `bpm_names`, `bpm_golden_x`, `bpm_golden_y`.
- New PVs in `ioc/pvs.py`: `STATE:CURRENT_TRAJ_X`, `STATE:CURRENT_TRAJ_Y`, `STATE:BEAM_LOST_AT_BPM`, `CMD:READOUT`.
- New REST routes: `POST /api/v1/cmd/readout` (parity), `GET /api/v1/waveforms/current` (bulk).
- New frontend module: `js/canvas.js` for waveform plotting; `index.html` gains a Canvas element.
- New composition entry: `ca_client.start()` in `composition.main()`'s `gather()`.
- New tests in all three tiers, including a parametrize argument added to the existing parity test.

**Zero structural changes.** Every addition lands in a home that already exists. The composition root grows by one line. The parity test grows by one parameter. Phase 1's investment in the layout is what makes this possible.

---

## 14. Open architectural questions to resolve later (not blocking phase 1)

- **Osprey integration shape** — does Osprey prefer to invoke PyTxT via HTTP/REST, via MCP, via CA directly, or all three? Until known, design for all three to be cheap to add; this is satisfied by phase 1's surface.
- **MML-wrapped operations** — `srinjectoneshot` (injection trigger) and `steppv` (CM step) hide PVs we'll need for phase 4. Resolution: read the MATLAB sources from your PI, or get the underlying PV writes directly. Does not block phases 1–3.

---

*End of design spec. Implementation plan to follow via `superpowers:writing-plans`.*
