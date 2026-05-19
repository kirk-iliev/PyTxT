"""GET /api/v1/result/* — read-only result endpoints.

Phase 2 M1: stub. Real implementation (raw waveform endpoint) lands in M4.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["result"])
