# config

Env-driven settings (Pydantic `BaseSettings`). The single place where
defaults are documented. Owns: PV prefix, IOC ports, FastAPI ports, log
level, heartbeat interval.

Does not own: any subsystem internals.
