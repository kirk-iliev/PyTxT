"""Unit tests for pytxt.composition helpers.

Today this covers only _ensure_local_ioc_in_ca_addr_list — the helper
that makes our own soft IOC discoverable to in-process CA clients
(WS bridge, BpmReader) on hosts where EPICS_CA_ADDR_LIST is set to the
ring's broadcast addresses with EPICS_CA_AUTO_ADDR_LIST=NO (i.e.
appsdev2 and any ALS control-room workstation).
"""
import os

import pytest

from pytxt.composition import _ensure_local_ioc_in_ca_addr_list


@pytest.fixture
def isolated_epics_env(monkeypatch):
    """Clear all EPICS_CA_* env vars so each test starts from a known state."""
    for k in (
        "EPICS_CA_ADDR_LIST",
        "EPICS_CA_AUTO_ADDR_LIST",
        "EPICS_CA_SERVER_PORT",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_prepends_when_addr_list_empty(isolated_epics_env):
    _ensure_local_ioc_in_ca_addr_list("127.0.0.1", 59064)
    assert os.environ["EPICS_CA_ADDR_LIST"] == "127.0.0.1:59064"
    assert os.environ["EPICS_CA_AUTO_ADDR_LIST"] == "NO"


def test_prepends_in_front_of_existing_entries(isolated_epics_env, monkeypatch):
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "131.243.71.255 131.243.84.255")
    _ensure_local_ioc_in_ca_addr_list("127.0.0.1", 59064)
    assert os.environ["EPICS_CA_ADDR_LIST"] == (
        "127.0.0.1:59064 131.243.71.255 131.243.84.255"
    )


def test_idempotent_when_entry_already_present(isolated_epics_env, monkeypatch):
    monkeypatch.setenv(
        "EPICS_CA_ADDR_LIST", "127.0.0.1:59064 131.243.71.255"
    )
    _ensure_local_ioc_in_ca_addr_list("127.0.0.1", 59064)
    assert os.environ["EPICS_CA_ADDR_LIST"] == (
        "127.0.0.1:59064 131.243.71.255"
    )


def test_respects_operator_set_auto_addr_list(isolated_epics_env, monkeypatch):
    """If the operator set AUTO_ADDR_LIST explicitly (even to YES), leave it."""
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "YES")
    _ensure_local_ioc_in_ca_addr_list("127.0.0.1", 59064)
    assert os.environ["EPICS_CA_AUTO_ADDR_LIST"] == "YES"


def test_different_host_port_combo(isolated_epics_env, monkeypatch):
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", "10.0.0.5")
    _ensure_local_ioc_in_ca_addr_list("0.0.0.0", 5064)
    assert os.environ["EPICS_CA_ADDR_LIST"] == "0.0.0.0:5064 10.0.0.5"
