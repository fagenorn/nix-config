"""A probe of `cut_engine.py`: one thread spawns a long process, then another writes the cut point.

Run as `cut_spawn_probe.py <run_dir>` with `ENGINE_CUT_AT` naming `step_entered` of step `x`, visit 1, first
occurrence, in the run `<procedure>#1` of `<run_dir>`, and `ENGINE_CUT_LOG` set. The spawned process starts in its
own session, as the engine's do, and no ledger event ever records it: the cut kills this process's group while
that process, spawned just before, is still alive. It prints that process's pid before the cut.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cut_engine  # noqa: E402
from agent_tools.delivery import engine_ledger  # noqa: E402

cut_engine.install()
run_dir = Path(sys.argv[1])
spawned = threading.Event()


def spawn() -> None:
    process = subprocess.Popen(["sleep", "600"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    print(process.pid, flush=True)
    spawned.set()


threading.Thread(target=spawn).start()
spawned.wait()
engine_ledger._append_line(run_dir / "events.jsonl", b'{"event":"step_entered","step":"x","visit":1}\n')
