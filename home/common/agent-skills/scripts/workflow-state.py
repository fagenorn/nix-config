#!/usr/bin/env python3
"""`workflow-state`: the entry point of `workflow_state.py` (issue 612).

The command is imported through the import system, so its bytecode is cached rather
than compiled on every start: the `scripts` sibling in the source layout, else
`~/.agents/lib/python/workflow_state.py`, whose cache every Home Manager activation
clears (issue 567; the agent-skills README, § Installed module library). Each start
executes a fresh module, registered nowhere in `sys.modules`.
"""

import importlib.util
from pathlib import Path


def load():
    here = Path(__file__).parent
    entry = (here / "workflow_state.py" if here.name == "scripts"
             else Path.home() / ".agents/lib/python/workflow_state.py")
    spec = importlib.util.spec_from_file_location("workflow_state", entry)
    if spec is None or spec.loader is None:
        raise SystemExit(f"workflow-state: cannot load {entry}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(load().main())
