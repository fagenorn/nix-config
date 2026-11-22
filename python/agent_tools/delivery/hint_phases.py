"""The delivery stages that read a hint file, and the one file each reads.

These are the stages whose steps get a brief. Each reads at most the one hint file
named for it, under `HINT_DIR`; nothing else defines the names.
"""

from __future__ import annotations

HINT_DIR = ".agents/knowledge/hints"
HINT_STAGES: tuple[str, ...] = ("planning", "plan review", "building", "final review")


def hint_file(stage: str) -> str:
    return stage.replace(" ", "-") + ".md"


HINT_FILES: tuple[str, ...] = tuple(hint_file(stage) for stage in HINT_STAGES)
