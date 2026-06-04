#!/usr/bin/env python3
"""Generate the ALS storage-ring HCM/VCM corrector setpoint-channel catalog.

Port of the corrector branch of MATLAB `getname_als.m`
(machine/ALS/StorageRing/getname_als.m, lines ~289-640) for the **Setpoint**
channel type (`ChanTypeFlag == 1` -> 'AC'), which is what the threading apply
writes (`steppv('HCM'/'VCM', ...)` -> `setpv` -> the Setpoint AC channel).

Why this exists: no static corrector-name catalog exists upstream — every
operational path derives names live from MML via `getname_als`. This script
reconstructs the naming *formula* from source so PyTxT can produce the catalog
with no MATLAB dependency, mirroring how `config/bpm_prefixes.txt` was produced.

Limits (max |setpoint|, amps) ported from `alsinit.m:5410 local_maxsp`.

NOT fully closed: the exact *device enumeration* (which [sector, dev] pairs are
populated) is built dynamically in `alsinit` and is not a single literal. The
enumeration encoded here (HCM dev 1-8, VCM dev {1,2,4,5,7,8}, sectors 1-12) is
the standard ALS layout and reproduces the known device counts (HCM=96, VCM=72)
from `mml-audit get_family`. The one residual ambiguity — `local_maxsp` errors
on "Sector 1, HCM1 is missing" yet the count is still 96 — should be confirmed
with a one-time read-only dump: `family2dev('HCM')` / `family2dev('VCM')` in MML
(pure in-memory AO read; does not touch the machine).
"""
from __future__ import annotations

SECTORS = range(1, 13)  # SR01..SR12


def hcm_setpoint_channel(sector: int, dev: int) -> str:
    """HCM Setpoint (AC) PV name. Ported from getname_als.m HCM branch."""
    ss = sector
    if dev == 1:
        return f"SR{ss:02d}C___HCM1___AC00"
    if dev == 2:
        return f"SR{ss:02d}C___HCM2___AC01"
    if dev == 3:
        return f"SR{ss:02d}C___HCSD1__AC00"
    if dev == 4:
        return f"SR{ss:02d}C___HCSF1__AC02"
    if dev == 5:
        return f"SR{ss:02d}C___HCSF2__AC03"
    if dev == 6:
        return f"SR{ss:02d}C___HCSD2__AC01"
    if dev == 7:
        return f"SR{ss:02d}C___HCM3___AC02"
    if dev == 8:
        return f"SR{ss:02d}C___HCM4___AC03"
    if dev == 10:  # chicane (sector+1, 'U' subsector)
        return f"SR{ss + 1:02d}U___HCM2___AC00"
    raise ValueError(f"bad HCM device number: {dev}")


def vcm_setpoint_channel(sector: int, dev: int) -> str:
    """VCM Setpoint (AC) PV name. Ported from getname_als.m VCM branch."""
    ss = sector
    if dev == 1:
        return f"SR{ss:02d}C___VCM1___AC00"
    if dev == 2:
        return f"SR{ss:02d}C___VCM2___AC01"
    if dev == 3:
        raise ValueError("No VCSD1 corrector magnet (VCM dev 3).")
    if dev == 4:
        return f"SR{ss:02d}C___VCSF1__AC00"
    if dev == 5:
        return f"SR{ss:02d}C___VCSF2__AC01"
    if dev == 6:
        raise ValueError("No VCSD2 corrector magnet (VCM dev 6).")
    if dev == 7:
        return f"SR{ss:02d}C___VCM3___AC02"
    if dev == 8:
        return f"SR{ss:02d}C___VCM4___AC03"
    if dev == 10:  # chicane (sector+1); sector 5 special-cases to AC00
        return f"SR{ss + 1:02d}U___VCM2___{'AC00' if ss == 5 else 'AC01'}"
    raise ValueError(f"bad VCM device number: {dev}")


def max_amps(family: str, dev: int) -> float:
    """Max |setpoint| in amps. Ported from alsinit.m:5410 local_maxsp."""
    if family == "HCM":
        if dev in (1, 2, 7, 8):
            return 35.0
        if dev in (3, 6, 4, 5):
            return 17.0
        if dev == 10:
            return 20.0
    if family == "VCM":
        if dev in (1, 2, 7, 8):
            return 36.0
        if dev in (4, 5):
            return 14.5
        if dev == 10:
            return 19.98
    raise ValueError(f"no max for {family} dev {dev}")


# Standard ALS device enumeration (reproduces HCM=96, VCM=72).
HCM_DEVS = [1, 2, 3, 4, 5, 6, 7, 8]
VCM_DEVS = [1, 2, 4, 5, 7, 8]  # dev 3 and 6 do not exist


def build(family: str):
    devs = HCM_DEVS if family == "HCM" else VCM_DEVS
    fn = hcm_setpoint_channel if family == "HCM" else vcm_setpoint_channel
    rows = []
    for s in SECTORS:
        for d in devs:
            rows.append((s, d, fn(s, d), max_amps(family, d)))
    return rows


if __name__ == "__main__":
    for fam in ("HCM", "VCM"):
        rows = build(fam)
        print(f"# {fam}: {len(rows)} devices")
        for s, d, name, mx in rows:
            print(f"{name}   # SR{s:02d} dev{d}  |max|={mx}A")
        print()
