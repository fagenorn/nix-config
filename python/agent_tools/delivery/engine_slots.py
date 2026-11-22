"""The engine route's agent slots (#1522): how many live sessions the host admits for `engine deliver`.

The host declaration (`host_admission`) names the engine route and the agent slots it admits, one per live
engine session. `declared_slots()` reads the declaration once, when a deliver starts; a host whose declaration
is missing, invalid, or does not admit the engine route raises `host_admission.DeclarationError`, and the
caller refuses to start a run.
"""

from __future__ import annotations

from agent_tools.delivery import host_admission


def declared_slots() -> int:
    """The agent slots the host declaration admits for the engine route."""
    return host_admission.route_slots(host_admission.load_declaration(),
                                      host_admission.ENGINE_ROUTE)
