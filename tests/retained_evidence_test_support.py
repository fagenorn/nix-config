"""The committed retained review evidence and the identities its tests trust (issue 235; EV1, EV2).

`BUNDLE` is the committed bundle directory. `ANCHOR_SHA256` is the anchor digest
a reader trusts for it, and `TOOL_COMMIT` the reviewed tool commit it was
derived with. Both are literals fixed by review: nothing computes them from the
bundle, so replacing the bundle cannot move them. This module declares no
TestCase and imports no `agent_tools`, so the launcher module can import it.
"""
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent / "fixtures/retained-review-evidence"
ANCHOR_SHA256 = "sha256:3df1e2b9a6a20fcdf98f2cdd30a451aedcea829b6f9fea26cc76be3f0aaca0ce"
TOOL_COMMIT = "7213928f0e3c91de247dc028fe95b95f6a9dcf88"
