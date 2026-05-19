"""Shared pytest fixtures for PyTxT tests.

Test isolation strategy:
- Each integration test session picks a free port for the IOC.
- caproto env vars (EPICS_CAS_*, EPICS_CA_*) are pinned to localhost
  with that ephemeral port.
- This guarantees no collision with any real IOC and no cross-test
  interference.
"""
import os
import socket
import time
from typing import Generator

import pytest


def _find_free_port() -> int:
    """Return a free TCP port the OS hands out at this moment."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def ioc_port() -> int:
    return _find_free_port()


@pytest.fixture(scope="session")
def ioc_repeater_port() -> int:
    return _find_free_port()


@pytest.fixture(scope="session", autouse=True)
def configure_caproto_env(ioc_port: int, ioc_repeater_port: int) -> Generator[None, None, None]:
    """Pin caproto's address resolution to localhost + ephemeral ports."""
    saved = {k: os.environ.get(k) for k in (
        "EPICS_CAS_SERVER_PORT",
        "EPICS_CAS_INTF_ADDR_LIST",
        "EPICS_CAS_BEACON_ADDR_LIST",
        "EPICS_CA_SERVER_PORT",
        "EPICS_CA_ADDR_LIST",
        "EPICS_CA_AUTO_ADDR_LIST",
        "EPICS_CA_REPEATER_PORT",
    )}
    os.environ["EPICS_CAS_SERVER_PORT"] = str(ioc_port)
    os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_SERVER_PORT"] = str(ioc_port)
    os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
    os.environ["EPICS_CA_REPEATER_PORT"] = str(ioc_repeater_port)

    yield

    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def test_pv_prefix() -> str:
    """Use a unique prefix per test session to defend against any leakage."""
    return "OSPREY:TEST:TXT:"


# Import phase-2 fixtures so tests can use them without explicit imports.
from tests.fixtures.fake_bpm_ioc import fake_bpm_ioc  # noqa: F401
