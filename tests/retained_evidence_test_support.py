"""The committed retained review evidence and the identities its tests trust (issue 235; EV1, EV2).

`BUNDLE` is the committed bundle directory. `ANCHOR_SHA256` is the anchor digest
a reader trusts for it, and `TOOL_COMMIT` the reviewed tool commit it was
derived with. Both are literals fixed by review: nothing computes them from the
bundle, so replacing the bundle cannot move them. This module declares no
TestCase and imports no `agent_tools`, so the launcher module can import it.
"""
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent / "fixtures/retained-review-evidence"
ANCHOR_SHA256 = "sha256:d0968f6a9ca20160bd027bb3ce12b5231efa603057a054a76fe37e5f4870a8a5"
TOOL_COMMIT = "691d8f257615c5698965918b3cca036c2e9ccec9"
