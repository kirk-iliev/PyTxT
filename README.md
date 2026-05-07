# PyTxT

Turn-by-turn beam analysis service for the ALS injection chain. Python backend + browser frontend + soft EPICS IOC. Port of the MATLAB `TxT_GUI.mlapp`.

## North-star principles, stack, and scope

See [`CLAUDE.md`](CLAUDE.md).

## Current phase

Phase 1 — skeleton + hello-world IOC. See [`docs/superpowers/specs/2026-05-06-phase-1-skeleton-design.md`](docs/superpowers/specs/2026-05-06-phase-1-skeleton-design.md) for the design and [`docs/superpowers/plans/2026-05-07-phase-1-skeleton.md`](docs/superpowers/plans/2026-05-07-phase-1-skeleton.md) for the implementation plan.

## Quickstart

```bash
make install     # editable install + dev deps
make dev         # run locally on http://localhost:8008/
make test        # unit + integration + e2e
```
