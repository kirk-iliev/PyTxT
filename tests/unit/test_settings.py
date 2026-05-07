"""Unit tests for pytxt.config.settings."""
import pytest
from pydantic import ValidationError


def test_default_values():
    """Out-of-the-box settings use safe dev defaults."""
    from pytxt.config.settings import Settings
    s = Settings()
    assert s.pv_prefix == "OSPREY:TEST:TXT:"
    assert s.ioc_port == 59064
    assert s.ioc_repeater_port == 59065
    assert s.api_port == 8008
    assert s.heartbeat_interval_s == 1.0
    assert s.log_level == "INFO"


def test_pv_prefix_must_end_with_colon():
    """The validator catches a missing trailing colon (would produce malformed PV names)."""
    from pytxt.config.settings import Settings
    with pytest.raises(ValidationError) as exc_info:
        Settings(pv_prefix="TxT")
    assert "must end with ':'" in str(exc_info.value)


def test_env_var_override(monkeypatch):
    """PYTXT_* env vars override defaults."""
    monkeypatch.setenv("PYTXT_PV_PREFIX", "TxT:")
    monkeypatch.setenv("PYTXT_IOC_PORT", "5064")
    monkeypatch.setenv("PYTXT_API_PORT", "9000")
    from pytxt.config.settings import Settings
    s = Settings()
    assert s.pv_prefix == "TxT:"
    assert s.ioc_port == 5064
    assert s.api_port == 9000


def test_unknown_env_var_rejected(monkeypatch):
    """model_validator catches typos like PYTXT_PV_PREFEX (extra='forbid' does not apply to env vars)."""
    monkeypatch.setenv("PYTXT_PV_PREFEX", "TxT:")  # typo
    from pytxt.config.settings import Settings
    with pytest.raises(ValidationError):
        Settings()


def test_pytxt_version_env_var_rejected(monkeypatch):
    """version is set programmatically (not from env); PYTXT_VERSION must be treated as a typo."""
    monkeypatch.setenv("PYTXT_VERSION", "1.2.3")
    from pytxt.config.settings import Settings
    with pytest.raises(ValidationError):
        Settings()
