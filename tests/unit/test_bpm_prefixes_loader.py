"""Unit tests for pytxt.config.bpm_prefixes.load_bpm_prefixes."""
from __future__ import annotations

from pathlib import Path

import pytest

from pytxt.config.bpm_prefixes import load_bpm_prefixes


def test_parses_lines_skipping_comments_and_blanks(tmp_path: Path) -> None:
    f = tmp_path / "prefixes.txt"
    f.write_text(
        "# header comment\n"
        "\n"
        "SR01C:BPM3\n"
        "  SR01C:BPM4  \n"  # trailing/leading whitespace gets stripped
        "# inline section comment\n"
        "\n"
        "SR02C:BPM1\n",
        encoding="utf-8",
    )
    assert load_bpm_prefixes(f) == ["SR01C:BPM3", "SR01C:BPM4", "SR02C:BPM1"]


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="BPM prefixes file not found"):
        load_bpm_prefixes(tmp_path / "does-not-exist.txt")


def test_empty_file_raises_value_error(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no entries"):
        load_bpm_prefixes(f)


def test_comments_only_file_raises_value_error(tmp_path: Path) -> None:
    """A file with only comments + blanks is treated the same as empty."""
    f = tmp_path / "comments-only.txt"
    f.write_text("# just a header\n\n# nothing else\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no entries"):
        load_bpm_prefixes(f)


def test_string_path_accepted(tmp_path: Path) -> None:
    """The settings field is a str, not a Path — the loader must accept either."""
    f = tmp_path / "prefixes.txt"
    f.write_text("SR01C:BPM3\n", encoding="utf-8")
    assert load_bpm_prefixes(str(f)) == ["SR01C:BPM3"]


def test_shipped_file_parses_to_107_entries() -> None:
    """The committed pytxt/config/bpm_prefixes.txt is the operational truth — 107 entries."""
    repo_root = Path(__file__).resolve().parents[2]
    shipped = repo_root / "pytxt" / "config" / "bpm_prefixes.txt"
    prefixes = load_bpm_prefixes(shipped)
    assert len(prefixes) == 107
    # Spot-check shape: first entry should be a real ALS storage-ring prefix.
    assert prefixes[0].startswith("SR")
    # All entries should be unique.
    assert len(set(prefixes)) == len(prefixes)
