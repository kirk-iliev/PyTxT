"""Throwaway reachability probe for one ALS storage-ring TBT BPM.

Reads the four turn-by-turn PVs for a single BPM and prints shape, dtype,
timestamp, severity, and basic statistics. Pure read; no arming, no writes.

Usage:
    python scripts/probe_bpm.py                 # defaults to SR01C:BPM1
    python scripts/probe_bpm.py SR02C:BPM3      # any BPM prefix

Run from a host on the ALS control-system subnet (e.g. appsdev2) so the
caproto client can reach the BPM IOC. EPICS_CA_ADDR_LIST must be set in
the environment if broadcast discovery doesn't reach the IOC.
"""

import asyncio
import sys
from datetime import datetime, timezone

import numpy as np
from caproto.asyncio.client import Context

CHANNELS = {
    "c0":    "X waveform (int, nm)",
    "c1":    "Y waveform (int, nm)",
    "c3":    "sum signal (AU)",
    "armed": "ready flag (0 = data available)",
}


async def probe(prefix: str) -> None:
    pv_names = [f"{prefix}:wfr:TBT:{ch}" for ch in CHANNELS]
    print(f"Probing BPM prefix: {prefix}")
    print(f"PV names: {pv_names}\n")

    ctx = Context()
    pvs = await ctx.get_pvs(*pv_names, timeout=5.0)

    for pv, (ch, desc) in zip(pvs, CHANNELS.items()):
        print(f"--- {pv.name}  ({desc})")
        try:
            reading = await pv.read(timeout=5.0)
        except Exception as e:
            print(f"  READ FAILED: {type(e).__name__}: {e}\n")
            continue

        data = np.asarray(reading.data)
        meta = reading.metadata
        ts = getattr(meta, "timestamp", None)
        sev = getattr(meta, "severity", None)
        stat = getattr(meta, "status", None)

        print(f"  dtype:     {data.dtype}")
        print(f"  shape:     {data.shape}")
        if ts is not None:
            print(f"  timestamp: {datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()}")
        print(f"  severity:  {sev}    status: {stat}")

        if data.size == 0:
            print("  (empty)")
        elif data.size == 1:
            print(f"  value:     {data.item()}")
        else:
            print(f"  first 5:   {data[:5].tolist()}")
            print(f"  last 5:    {data[-5:].tolist()}")
            print(f"  min/max:   {data.min()} / {data.max()}")
            print(f"  mean:      {data.mean():.3f}")
            print(f"  nonzero:   {int(np.count_nonzero(data))} / {data.size}")
        print()


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else "SR01C:BPM1"
    # asyncio.run() requires 3.7+; use loop-based form for older Pythons too.
    loop = asyncio.new_event_loop() if hasattr(asyncio, "new_event_loop") else asyncio.get_event_loop()
    try:
        loop.run_until_complete(probe(prefix))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
