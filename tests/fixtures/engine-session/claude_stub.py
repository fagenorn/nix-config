"""A stand-in for the account launcher in the engine's agent-step tests.

Run as `python claude_stub.py <log> <canned> <exit> <diagnostic> <launcher args...>`:
it appends one compact JSON line `{"announced", "argv", "cwd", "stdin"}` to
`<log>`, prints the bytes of the `<canned>` file to stdout unchanged, writes the
bytes of the `<diagnostic>` file to stderr unless `<diagnostic>` is `-`, and
exits `<exit>`.

`announced` is true when some `$HOME/.agents/state/engine/runs/*/events.jsonl`
holds a `session_starting` event whose `session` is the argv word after
`--session-id`: the engine recorded the session before this process read it.
"""

import glob
import json
import os
import sys


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


def main(argv: list[str]) -> int:
    log, canned, code, diagnostic, words = argv[0], argv[1], int(argv[2]), argv[3], argv[4:]
    record = {"announced": announced(words), "argv": words, "cwd": os.getcwd(),
              "stdin": sys.stdin.read()}
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
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
