"""Cross-cutting core for the public API: errors, auth, gating, metering,
ratelimit, payload rules and the persistence store. Modules depend on core;
core never depends on modules.
"""
