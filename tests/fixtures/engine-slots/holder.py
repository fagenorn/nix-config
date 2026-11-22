"""A stand-in for a process that holds every agent slot of an engine run (#1522).

Run as `python holder.py <slots dir> <indices> <ready file>`: it creates the slots directory
(mode 0700), opens `slot-<i>.lock` there for each `i` of the comma-separated `<indices>` and takes
an exclusive non-blocking `flock` on each (exit 1 when one is already taken), writes
`<ready file>`, then sleeps up to 120 seconds and exits 0. The test ends it with SIGKILL, which
frees the locks.
"""

import fcntl
import os
import sys
import time


def main(argv: list[str]) -> int:
    directory, indices, ready = argv[0], [int(i) for i in argv[1].split(",")], argv[2]
    os.makedirs(directory, mode=0o700, exist_ok=True)
    held = []
    for index in indices:
        descriptor = os.open(os.path.join(directory, f"slot-{index}.lock"),
                             os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        held.append(descriptor)
    with open(ready, "w", encoding="utf-8") as handle:
        handle.write("ready")
    time.sleep(120)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
