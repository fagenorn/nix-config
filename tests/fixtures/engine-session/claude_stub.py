"""A stand-in for the account launcher in the engine's agent-step tests.

Run as `python claude_stub.py <log> <canned> <exit> <diagnostic> <launcher args...>`:
it appends one compact JSON line `{"announced", "argv", "cwd", "stdin"}` to
`<log>`, prints the bytes of the `<canned>` file to stdout unchanged, writes the
bytes of the `<diagnostic>` file to stderr unless `<diagnostic>` is `-`, and
exits `<exit>`.

`announced` is true when some `$HOME/.agents/state/engine/runs/*/events.jsonl`
holds a `session_starting` event whose `session` is the argv word after
`--session-id`, or a `session_resuming` event whose `session` is the argv word
after `--resume`: the engine recorded the session before this process read it.

Each log record also holds `answer_file` (true when `CLAUDE_ACCOUNT_ANSWER` is set) and
`account_env` (the `CLAUDE_ACCOUNT` value or null).

When `<canned>` names a file ending in `.answers.json`, it holds a JSON list of entries
`{"stdout": <absolute path>, "exit": <int>, "account": <str|null>, "all_out": <optional
{"resumes_at": str|null}>}`: invocation `n` (the lines already in `<log>`) uses entry
`min(n, len - 1)` and ignores `<exit>`. When `CLAUDE_ACCOUNT_ANSWER` is set, an `all_out`
entry writes `{"all_out":true,"resumes_at":...}` there and prints nothing, and an entry with an
account writes `{"account":<account>}`. In the legacy mode the same variable gets
`{"account":"stub"}`.
"""

import glob
import json
import os
import sys


def announced(argv: list[str]) -> bool:
    if "--session-id" in argv:
        flag, kind = "--session-id", "session_starting"
    elif "--resume" in argv:
        flag, kind = "--resume", "session_resuming"
    else:
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


def invocations(log: str) -> int:
    if not os.path.exists(log):
        return 0
    with open(log, encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def main(argv: list[str]) -> int:
    log, canned, code, diagnostic, words = argv[0], argv[1], int(argv[2]), argv[3], argv[4:]
    answer_path = os.environ.get("CLAUDE_ACCOUNT_ANSWER")
    entry = None
    if canned.endswith(".answers.json"):
        with open(canned, encoding="utf-8") as handle:
            entries = json.load(handle)
        entry = entries[min(invocations(log), len(entries) - 1)]
        canned, code = entry["stdout"], entry["exit"]
    record = {"announced": announced(words), "answer_file": answer_path is not None,
              "account_env": os.environ.get("CLAUDE_ACCOUNT"), "argv": words,
              "cwd": os.getcwd(), "stdin": sys.stdin.read()}
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    answer, all_out = None, entry is not None and "all_out" in entry
    if answer_path is not None:
        if entry is None:
            answer = {"account": "stub"}
        elif all_out:
            answer = {"all_out": True, "resumes_at": entry["all_out"]["resumes_at"]}
        elif entry["account"] is not None:
            answer = {"account": entry["account"]}
    if answer is not None:
        with open(answer_path, "w", encoding="utf-8") as handle:
            json.dump(answer, handle)
    if not all_out:
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
