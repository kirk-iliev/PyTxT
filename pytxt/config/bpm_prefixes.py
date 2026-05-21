"""Loader for the committed BPM-prefix list.

The file is a plain-text catalog of ALS storage-ring BPM PV prefixes,
one per line, with `#` comment lines and blank lines ignored. Sourced
via a one-time MATLAB dump (see the file header for the exact `setpathals`
+ `getbpmlist` + `getname` sequence) and committed to the repo, because
no static catalog exists upstream — every operational path derives
names live from MML.
"""
from __future__ import annotations

from pathlib import Path


def load_bpm_prefixes(path: str | Path) -> list[str]:
    """Read `path` and return the list of BPM prefixes.

    Lines beginning with `#` (after lstrip) and blank lines are skipped.
    Each remaining line is stripped of surrounding whitespace.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if `path` is empty (zero non-comment, non-blank lines).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"BPM prefixes file not found: {p} (configure via PYTXT_BPM_PREFIXES_PATH)"
        )

    prefixes: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        prefixes.append(line)

    if not prefixes:
        raise ValueError(
            f"BPM prefixes file {p} contains no entries (only comments/blank lines)"
        )

    return prefixes
