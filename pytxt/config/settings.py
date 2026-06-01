"""PyTxT runtime settings.

All settings are env-var-driven (prefix `PYTXT_`). Defaults are
*dev-safe*: out of the box, the app uses the OSPREY:TEST:TXT:* PV
namespace and ports 59064/59065 so it cannot collide with real ALS
PVs. Production deployment must explicitly override.
"""
import os
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PYTXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",  # rejects unknown kwargs (env-var typos caught by model_validator below)
    )

    # --- PV namespace ---
    pv_prefix: str = "OSPREY:TEST:TXT:"

    # --- IOC server (caproto) ---
    ioc_host: str = "0.0.0.0"
    ioc_port: int = 59064
    ioc_repeater_port: int = 59065

    # --- FastAPI / uvicorn ---
    api_host: str = "127.0.0.1"
    api_port: int = 8008

    # --- App ---
    log_level: str = "INFO"
    heartbeat_interval_s: float = 1.0

    # --- Phase 2 ---
    bpm_read_timeout_s: float = 2.0
    bpm_prefixes_path: str = "pytxt/config/bpm_prefixes.txt"

    # --- Phase 3 ---
    # Reference-trajectory file library. Declared here so PYTXT_REFERENCE_DIR
    # is env-overridable; the dir is resolved + created in composition.main()
    # (kept side-effect-free here so unit tests don't litter the repo).
    reference_dir: Path = Path("data/references")

    # Max bytes accepted by the multipart upload route (POST /references).
    # Default 200 MB covers the ~144 MB worst-case PyTxT-extended .mat with
    # headroom; overflow → HTTP 413. Env-overridable via PYTXT_MAX_UPLOAD_BYTES.
    max_upload_bytes: int = 200 * 1024 * 1024

    # Version is NOT env-overridable; populated at startup by composition.main()
    # from importlib.metadata.version("pytxt") with fallback to "0.0.0+dev".
    version: str = ""

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_pytxt_env_vars(cls, data: object) -> object:
        """Raise ValidationError for unknown PYTXT_* env vars (catches typos)."""
        # version is set programmatically by composition.main() from package metadata,
        # not from env. Exclude it from the known set so PYTXT_VERSION is rejected.
        known = {f"PYTXT_{k.upper()}" for k in cls.model_fields if k != "version"}
        # Whitelist env vars consumed outside Settings (composition-time switches).
        known |= {"PYTXT_USE_SYNTHETIC_READER"}
        unknown = [k for k in os.environ if k.startswith("PYTXT_") and k not in known]
        if unknown:
            raise ValueError(f"Unknown PYTXT_* env vars: {unknown!r}")
        return data

    @field_validator("pv_prefix")
    @classmethod
    def _prefix_must_end_with_colon(cls, v: str) -> str:
        if not v.endswith(":"):
            raise ValueError(f"pv_prefix must end with ':' (got {v!r})")
        return v
