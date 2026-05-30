"""Integration: M3 — REST path-safety for /cmd/load_ref and /cmd/save_ref.

Every unsafe name vector (spec §10.3 `test_path_safety`) must be rejected with
HTTP 422 on BOTH the LOAD and SAVE routes, through the real app stack.

Note on the empty string ``''``: ``LoadRefRequest.name`` carries
``min_length=1``, so an empty LOAD name is rejected by pydantic validation
(422) *before* the handler runs. ``SaveRefRequest.name`` is optional, so an
empty save name reaches ``_resolve_in_library`` and is rejected there
(``InvalidReferenceNameError`` → 422). Either way the contract is the same
422, which is what these tests assert.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.state.app_state import AppState


_UNSAFE_NAMES = [
    "",                 # empty (pydantic min_length for LOAD; handler for SAVE)
    "foo",              # no .mat extension
    "a/b.mat",          # path separator
    "../etc/passwd",    # parent escape
    "/etc/passwd",      # absolute path
]


def _make_app(tmp_path):
    from pytxt.api.server import create_app

    state = AppState(version="m3-test", bpm_prefixes=["A"])
    return create_app(state=state, reference_dir=tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _UNSAFE_NAMES)
async def test_load_ref_rejects_unsafe_name(tmp_path, name):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/load_ref", json={"name": name})
    assert r.status_code == 422, f"load_ref {name!r} → {r.status_code} {r.text}"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _UNSAFE_NAMES)
async def test_save_ref_rejects_unsafe_name(tmp_path, name):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/save_ref", json={"name": name})
    assert r.status_code == 422, f"save_ref {name!r} → {r.status_code} {r.text}"
