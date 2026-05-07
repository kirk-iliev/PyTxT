# handlers

Pure async functions invoked by both the IOC's CMD-PV dispatcher and
the REST POST routes. **The shared import is the structural enforcement
of agentic parity.** A `handle_<cmd>(state, **args)` function does not
know whether it was called from CA or HTTP.

Does not own: I/O, transport details.
