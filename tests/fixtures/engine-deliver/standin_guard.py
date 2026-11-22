"""A stand-in lifecycle guard for the engine's guard tests (issue 1515).

Run as `python standin_guard.py <mode> ...`. It reads all of stdin first. Every
mode except `sleep` appends one compact JSON line
`{"cwd": os.getcwd(), "payload": <stdin parsed as JSON>}` to its `<log>`.

  allow <log>                 exits 0
  refuse <log> <text>         prints <text> to stderr, exits 2
  exit <log> <code> <text>    prints <text> to stderr, exits <code>
  noisy <log>                 prints `noise` to stdout and to stderr, exits 0
  sleep <pidfile>             starts a 120 s grandchild, writes its own pid and the
                              grandchild's pid to <pidfile> (one per line), sleeps
                              120 s, exits 0
  sleep-away <pidfile>        as `sleep`, but the grandchild runs in a session of its own,
                              as the real guard's policy row check does
  tee <log> <guard>           runs <guard> with the same stdin bytes, forwards its
                              stderr, exits with its code
  only <needle> <mode> <mode words...>
                              exits 0 and logs nothing when <needle> is not a
                              substring of the payload's tool_input.command;
                              otherwise behaves as <mode> on the stdin already read
"""

import json
import os
import subprocess
import sys
import time


def log_line(log: str, data: bytes) -> None:
    try:
        payload = json.loads(data)
    except ValueError:
        payload = None
    line = json.dumps({"cwd": os.getcwd(), "payload": payload},
                      sort_keys=True, separators=(",", ":"))
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def behave(mode: str, words: list[str], data: bytes) -> int:
    if mode in ("sleep", "sleep-away"):
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                      start_new_session=mode == "sleep-away")
        with open(words[0], "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n{grandchild.pid}\n")
        time.sleep(120)
        return 0
    if mode == "only":
        needle, inner, rest = words[0], words[1], words[2:]
        try:
            command = json.loads(data)["tool_input"]["command"]
        except (ValueError, KeyError, TypeError):
            command = ""
        if needle not in command:
            return 0
        return behave(inner, rest, data)
    log = words[0]
    log_line(log, data)
    if mode == "allow":
        return 0
    if mode == "refuse":
        print(words[1], file=sys.stderr)
        return 2
    if mode == "exit":
        print(words[2], file=sys.stderr)
        return int(words[1])
    if mode == "noisy":
        print("noise")
        print("noise", file=sys.stderr)
        return 0
    if mode == "tee":
        done = subprocess.run([words[1]], input=data, stderr=subprocess.PIPE, check=False)
        sys.stderr.buffer.write(done.stderr)
        sys.stderr.flush()
        return done.returncode
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    sys.exit(behave(sys.argv[1], sys.argv[2:], sys.stdin.buffer.read()))
