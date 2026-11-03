"""Load an installed agent module so its bytecode cannot outlive its source.

Home-manager links installed modules into the Nix store, where every file has
mtime 1. Python's default bytecode check compares source mtime and size only, so
a same-size edit would keep running the old compiled code (issue 567). The
loader here reports a source "mtime" derived from the file's content, so the
ordinary timestamp pyc is reused exactly when the content is unchanged and the
bytecode cache keeps working (issue 499).
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Sequence


class _ContentKeyedLoader(importlib.machinery.SourceFileLoader):
    def path_stats(self, path: str) -> dict[str, float | int]:
        stats = super().path_stats(path)
        digest = hashlib.sha256(Path(path).read_bytes()).digest()
        stats["mtime"] = int.from_bytes(digest[:4], "big")
        return stats


def module_spec(name: str, entry: Path | str,
                submodule_search_locations: Sequence[str] | None = None):
    """A spec for `entry` whose bytecode is keyed by the file's content."""
    path = str(entry)
    return importlib.util.spec_from_file_location(
        name, path, loader=_ContentKeyedLoader(name, path),
        submodule_search_locations=submodule_search_locations)


def load_module(name: str, entry: Path | str) -> ModuleType:
    """Execute `entry` as a fresh module, registered nowhere in `sys.modules`."""
    spec = module_spec(name, entry)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {entry}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
