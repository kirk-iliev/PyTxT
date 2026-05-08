# PyTxT — Project Overview

## What we're building

A port of the MATLAB turn-by-turn beam analysis GUI (`TxT_GUI.mlapp`, used at
the ALS during injection startup) to a Python backend with a browser frontend.

The MATLAB original and its user manual describe the functional target: arm
BPMs, inject, read turn-by-turn waveforms, visualize trajectories, set/load
reference trajectories, and run trajectory correction via response-matrix
inversion.

## Architecture

The pattern follows PyBeamViewer (an existing app at the ALS) with one
deliberate change: PyTxT publishes its operationally meaningful state and
commands as **EPICS PVs via a soft IOC**, rather than keeping them in process
memory behind a REST API.

The split:

- **EPICS PVs** — commands, app state, analysis results, liveness. Anything
  Phoebus, the archiver, alarm system, or other agents might subscribe to.
- **REST/WS** — bulk transfers (waveform downloads, reference-file I/O),
  static assets, and a WebSocket↔CA bridge so the browser can subscribe to
  PVs.
- **Browser-local** — UI ephemera (zoom, hover, modal state).

A single Python process runs the soft IOC server, a CA client (for upstream
BPM/CM PVs), and the FastAPI web app on one asyncio loop.

## Stack

Python 3.11+, FastAPI, uvicorn, caproto (IOC + CA client), pySC, numpy/scipy,
vanilla JS + Canvas frontend, pytest + Playwright, Docker.

## Files you'll be given

- `PyTxT-project-plan.html` — the project plan with PV namespace sketch, repo
  layout, phased delivery, and reference-material pointers.
- `TxT_GUI_manual.pdf` — the user manual for the MATLAB original. Walks
  through the 18-step workflow that defines feature parity.
- `~/path/to/PyBeamViewer/` — the architectural template (read-only). Mirror
  its repo layout, FastAPI patterns, frontend approach, and Docker setup.

Read these before making structural decisions.

## Status

Scoping → scaffolding. Implementer: Kirk. Project owner: T. Hellert.
