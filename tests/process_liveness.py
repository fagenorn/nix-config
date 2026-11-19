"""One portable answer to "is this process running?" for tests that check a killed process is gone.

`os.kill(pid, 0)` succeeds for a zombie, and `/proc` exists only on Linux, so the state is read
with `ps`, which Linux and macOS both have.
"""
import os
import subprocess


def process_alive(pid: int) -> bool:
    """True when `pid` exists and is not a zombie (state `Z`)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                           check=False).stdout.strip()
    return bool(state) and not state.startswith("Z")
