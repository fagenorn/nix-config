"""A stand-in for the account launcher in the engine's agent-step tests.

Run as `python claude_stub.py <log> <canned> <resumed> <exit> <diagnostic> <launcher args...>`:
it appends one compact JSON line
`{"announced", "argv", "config_dir", "cwd", "host_settings", "stdin"}` to `<log>`
(`config_dir` and `host_settings` are the values of `CLAUDE_CONFIG_DIR` and
`CLAUDE_ACCOUNT_HOST_SETTINGS` in the environment, or null when unset), prints the bytes of the `<resumed>` file to stdout unchanged when the
launcher args hold `--resume` and `<resumed>` is not `-`, else those of the
`<canned>` file, writes the bytes of the `<diagnostic>` file to stderr unless
`<diagnostic>` is `-`, and exits `<exit>`.

`announced` is true when some `$HOME/.agents/state/engine/runs/*/events.jsonl`
holds a `session_starting` event whose `session` is the argv word after
`--session-id`, or a `session_resuming` event whose `session` is the argv word
after `--resume`: the engine recorded the session before this process read it.
"""

import glob
import json
import os
import sys


def announced(argv: list[str]) -> bool:
    flag, kind = (("--session-id", "session_starting") if "--session-id" in argv
                  else ("--resume", "session_resuming"))
    if flag not in argv:
        return False
    session = argv[argv.index(flag) + 1]
    pattern = os.path.join(os.environ["HOME"], ".agents/state/engine/runs/*/events.jsonl")
    for path in glob.glob(pattern):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("event") == kind and event.get("session") == session:
                    return True
    return False


def main(argv: list[str]) -> int:
    log, canned, resumed, code, diagnostic, words = (
        argv[0], argv[1], argv[2], int(argv[3]), argv[4], argv[5:])
    record = {"announced": announced(words), "argv": words,
              "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"), "cwd": os.getcwd(),
              "host_settings": os.environ.get("CLAUDE_ACCOUNT_HOST_SETTINGS"),
              "stdin": sys.stdin.read()}
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    chosen = resumed if "--resume" in words and resumed != "-" else canned
    with open(chosen, "rb") as handle:
        sys.stdout.buffer.write(handle.read())
    sys.stdout.buffer.flush()
    if diagnostic != "-":
        with open(diagnostic, "rb") as handle:
            sys.stderr.buffer.write(handle.read())
        sys.stderr.buffer.flush()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
