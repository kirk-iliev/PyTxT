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


@pytest.fixture(scope="session")
def beacon_absorber() -> Generator[int, None, None]:
    """A live UDP socket that absorbs caproto server beacons for the session.

    Without it, the fake-IOC's beacon loop sends to a dead loopback port
    (EPICS_CAS_BEACON_PORT default 5065, where nothing listens) and Linux
    intermittently returns ICMP port-unreachable → ECONNREFUSED on a later
    send. caproto raises that as a fatal CaprotoNetworkError out of
    broadcast_beacon_loop, flaking any test with a running IOC. Binding a
    real socket on the beacon destination keeps the port alive so the send
    always succeeds silently. We never recv — the kernel buffer just drops
    the tiny, infrequent beacons. Returns the bound port for
    EPICS_CAS_BEACON_PORT.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture(scope="session", autouse=True)
def configure_caproto_env(
    ioc_port: int, ioc_repeater_port: int, beacon_absorber: int
) -> Generator[None, None, None]:
    """Pin caproto's address resolution to localhost + ephemeral ports."""
    saved = {k: os.environ.get(k) for k in (
        "EPICS_CAS_SERVER_PORT",
        "EPICS_CAS_INTF_ADDR_LIST",
        "EPICS_CAS_BEACON_ADDR_LIST",
        "EPICS_CAS_AUTO_BEACON_ADDR_LIST",
        "EPICS_CAS_BEACON_PORT",
        "EPICS_CA_SERVER_PORT",
        "EPICS_CA_ADDR_LIST",
        "EPICS_CA_AUTO_ADDR_LIST",
        "EPICS_CA_REPEATER_PORT",
    )}
    os.environ["EPICS_CAS_SERVER_PORT"] = str(ioc_port)
    os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"
    # Beacons go ONLY to the loopback absorber: a fixed address list +
    # AUTO=no suppresses the 255.255.255.255 broadcast, and BEACON_PORT
    # targets the live absorber socket so the send never hits a dead port.
    os.environ["EPICS_CAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_AUTO_BEACON_ADDR_LIST"] = "no"
    os.environ["EPICS_CAS_BEACON_PORT"] = str(beacon_absorber)
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
# Phase-4 injection-trigger fixture.
from tests.fixtures.fake_injection_ioc import fake_injection_ioc  # noqa: F401
