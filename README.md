# PyTxT

Turn-by-turn beam analysis service for the ALS injection chain. Python backend + browser frontend + soft EPICS IOC. Port of the MATLAB `TxT_GUI.mlapp`.

## North-star principles, stack, and scope

See [`CLAUDE.md`](CLAUDE.md).

## Current phase

Phase 2 — read path (CA client + soft IOC + WS-to-CA bridge). Phase 1 (skeleton + hello-world IOC) is complete. See [`docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md`](docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md) for the design, [`docs/superpowers/plans/2026-05-19-phase-2-read-path.md`](docs/superpowers/plans/2026-05-19-phase-2-read-path.md) for the implementation plan, and [`docs/superpowers/specs/2026-05-18-phase-2-decisions.md`](docs/superpowers/specs/2026-05-18-phase-2-decisions.md) for the running decisions log.

## Quickstart

The project targets Python 3.10 (the appsdev2 control-room floor). `.python-version` pins this so [`uv`](https://docs.astral.sh/uv/) (or pyenv) auto-selects a matching interpreter regardless of what's on the host.

```bash
uv venv --python 3.10 .venv     # one-time: create the pinned venv
source .venv/bin/activate
make install     # editable install + dev deps
make dev         # run locally on http://localhost:8008/
make test        # unit + integration + e2e
```
