# state

The `AppState` dataclass — single in-process source of truth — and its
async change-notification mechanism. IOC, REST routes, and handlers
read/write through this one object.

Does not own: business logic, transport details.
