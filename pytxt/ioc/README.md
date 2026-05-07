# ioc

caproto soft IOC server. Publishes `AppState` outward as PVs and
dispatches CMD-PV writes to handlers. The canonical external interface
to PyTxT — what Phoebus, the archiver, and Osprey CA agents subscribe
to.

Does not own: business logic, HTTP/WS.
