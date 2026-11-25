"""The closed kind list of a review finding (issue 1416, issue 1535).

This module is the home of `KINDS`, the closed list of kinds a reviewer gives
each finding. Every review reply schema under `procedures/` copies the list into
its `kind` enum; no engine module imports this module, so the engine reads the
schema alone. It imports only the standard library.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = (
    "edge-or-failure-path", "weak-test", "missing-test", "contract-mismatch", "stale-docs", "security",
    "concurrency", "plan-step-not-executable", "other")
