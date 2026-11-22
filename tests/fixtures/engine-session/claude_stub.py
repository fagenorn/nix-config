"""A stand-in for the account launcher in the engine's agent-step tests.

Run as `python claude_stub.py <log> <canned> <exit> <diagnostic> <hold> <launcher args...>`:
it appends one compact JSON line `{"announced", "argv", "cwd", "stdin"}` to
`<log>`, prints the bytes of the `<canned>` file to stdout unchanged, writes the
bytes of the `<diagnostic>` file to stderr unless `<diagnostic>` is `-`, and
exits `<exit>`.

`<hold>` is `-` or a path. With a path, the stub first starts a child in its own
process group that ignores SIGTERM and holds none of the stub's pipes, waits up
to 10 s until the child has written `<hold>.ready`, writes `"<own pid> <child
pid>"` to `<hold>` and sleeps 60 s before it behaves as above. The stub keeps
the default SIGTERM action, so it exits on TERM while its child does not.

`announced` is true when some `$HOME/.agents/state/engine/runs/*/events.jsonl`
holds a `session_starting` event whose `session` is the argv word after
`--session-id`: the engine recorded the session before this process read it.
"""

import glob
import json
import os
import subprocess
import sys
import time

CHILD = ("import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
         "open(sys.argv[1], 'w').write('ready'); time.sleep(60)")


def announced(argv: list[str]) -> bool:
    if "--session-id" not in argv:
        return False
    session = argv[argv.index("--session-id") + 1]
    pattern = os.path.join(os.environ["HOME"], ".agents/state/engine/runs/*/events.jsonl")
    for path in glob.glob(pattern):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("event") == "session_starting" and event.get("session") == session:
                    return True
    return False


def hold_with_child(hold: str) -> None:
    ready = hold + ".ready"
    child = subprocess.Popen([sys.executable, "-c", CHILD, ready], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 10
    while not os.path.exists(ready) and time.monotonic() < deadline:
        time.sleep(0.02)
    with open(hold, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {child.pid}")
        handle.flush()
    time.sleep(60)


def main(argv: list[str]) -> int:
    log, canned, code, diagnostic, hold, words = (
        argv[0], argv[1], int(argv[2]), argv[3], argv[4], argv[5:])
    record = {"announced": announced(words), "argv": words, "cwd": os.getcwd(),
              "stdin": sys.stdin.read()}
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    if hold != "-":
        hold_with_child(hold)
    with open(canned, "rb") as handle:
        sys.stdout.buffer.write(handle.read())
    sys.stdout.buffer.flush()
    if diagnostic != "-":
        with open(diagnostic, "rb") as handle:
            sys.stderr.buffer.write(handle.read())
        sys.stderr.buffer.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
