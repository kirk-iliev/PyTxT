"""Unit tests for the corrector channel catalog loader + committed catalogs."""
from __future__ import annotations

from pathlib import Path

import pytest

from pytxt.config.corrector_channels import (
    CorrectorChannel,
    load_corrector_channels,
)

_CONFIG = Path(__file__).resolve().parents[2] / "pytxt" / "config"


def test_committed_hcm_catalog_has_96_channels():
    chans = load_corrector_channels(_CONFIG / "hcm_channels.txt", "HCM")
    assert len(chans) == 96
    assert all(c.family == "HCM" for c in chans)
    assert [c.index for c in chans] == list(range(96))


def test_committed_vcm_catalog_has_72_channels():
    chans = load_corrector_channels(_CONFIG / "vcm_channels.txt", "VCM")
    assert len(chans) == 72
    assert all(c.family == "VCM" for c in chans)


def test_catalog_channels_are_unique_and_named():
    chans = load_corrector_channels(_CONFIG / "hcm_channels.txt", "HCM")
    names = [c.name for c in chans]
    assert len(set(names)) == len(names)            # no duplicates
    assert chans[0].name == "SR01C___HCM1___AC00"
    assert chans[0].max_abs_amps == pytest.approx(35.0)


def test_limits_are_positive():
    for fam, fname in [("HCM", "hcm_channels.txt"), ("VCM", "vcm_channels.txt")]:
        for c in load_corrector_channels(_CONFIG / fname, fam):
            assert c.max_abs_amps > 0


def test_loader_parses_inline_comments(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("# header\nFOO___AC00   12.5   # a comment\n\nBAR___AC01 7\n")
    chans = load_corrector_channels(f, "HCM")
    assert [c.name for c in chans] == ["FOO___AC00", "BAR___AC01"]
    assert chans[0].max_abs_amps == 12.5
    assert chans[1].max_abs_amps == 7.0


def test_loader_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_corrector_channels("/nonexistent/hcm.txt", "HCM")


def test_loader_rejects_malformed_line(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("ONLYNAME\n")
    with pytest.raises(ValueError, match="expected"):
        load_corrector_channels(f, "HCM")


def test_loader_rejects_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("# only comments\n\n")
    with pytest.raises(ValueError, match="no entries"):
        load_corrector_channels(f, "HCM")


def test_loader_rejects_non_numeric_limit(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("FOO___AC00  notanumber\n")
    with pytest.raises(ValueError, match="bad max_amps"):
        load_corrector_channels(f, "HCM")


def test_corrector_channel_is_frozen():
    c = CorrectorChannel(name="X", max_abs_amps=1.0, family="HCM", index=0)
    with pytest.raises(Exception):
        c.name = "Y"  # type: ignore[misc]
