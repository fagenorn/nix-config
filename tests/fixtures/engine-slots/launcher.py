"""A stand-in for the account launcher in the engine's agent-slot tests (#1522).

Run as `python launcher.py <log> <mode> <launcher args...>`: it reads stdin, counts the held
slot files under `$HOME/.agents/state/engine/runs/*/slots/slot-*.lock` (a file is held when a
fresh `os.open` plus `flock(LOCK_EX | LOCK_NB)` raises `BlockingIOError`), appends one compact
JSON line `{"held": <n>, "mode": <mode>}` to `<log>`, then acts by `<mode>`:

    reply   prints a successful session result with a structured reply and exits 0
    prose   prints the same result without `structured_output` and exits 0
    kill    sends itself SIGKILL
    orphan  starts a 60 second sleeper in its own session, writes its pid to `<log>.orphan.pid`,
            then behaves as `reply`; it keeps every inheritable descriptor it was
            given open in the sleeper, so a slot the engine leaked would stay held
    pipes   as `orphan`, but the sleeper keeps this process's stdout and stderr open
    killpipes  as `pipes`, but the launcher sends itself SIGKILL instead of replying
"""

import fcntl
import glob
import json
import os
import signal
import subprocess
import sys

RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 10,
          "num_turns": 1, "result": "drafted", "session_id": "x", "total_cost_usd": 0,
          "usage": {}, "permission_denials": []}
REPLY = {"status": "drafted", "summary": "s", "items": []}


def held_slots() -> int:
    pattern = os.path.join(os.environ["HOME"], ".agents/state/engine/runs/*/slots/slot-*.lock")
    held = 0
    for path in glob.glob(pattern):
        descriptor = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held += 1
        finally:
            os.close(descriptor)
    return held


def main(argv: list[str]) -> int:
    log, mode = argv[0], argv[1]
    sys.stdin.read()
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"held": held_slots(), "mode": mode},
                                sort_keys=True, separators=(",", ":")) + "\n")
    if mode == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    if mode in ("orphan", "pipes", "killpipes"):
        output = None if mode != "orphan" else subprocess.DEVNULL
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
            close_fds=False, stdin=subprocess.DEVNULL, stdout=output, stderr=output)
        with open(f"{log}.orphan.pid", "w", encoding="utf-8") as handle:
            handle.write(str(sleeper.pid))
        if mode == "killpipes":
            os.kill(os.getpid(), signal.SIGKILL)
    result = dict(RESULT)
    if mode != "prose":
        result["structured_output"] = REPLY
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
