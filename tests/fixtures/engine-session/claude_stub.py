"""A stand-in for the account launcher in the engine's agent-step tests.

Run as `python claude_stub.py <log> <canned> <resumed> <exit> <diagnostic> <hold> <launcher args...>`:
it appends one compact JSON line
`{"announced", "argv", "config_dir", "cwd", "host_settings", "stdin"}` to `<log>`
(`config_dir` and `host_settings` are the values of `CLAUDE_CONFIG_DIR` and
`CLAUDE_ACCOUNT_HOST_SETTINGS` in the environment, or null when unset), prints the bytes of the `<resumed>` file to stdout unchanged when the
launcher args hold `--resume` and `<resumed>` is not `-` (never in the `.answers.json` mode),
else those of the `<canned>` file, writes the bytes of the `<diagnostic>` file to stderr unless
`<diagnostic>` is `-`, and exits `<exit>`.

`<hold>` is `-` or a path. With a path, the stub first starts a child in its own
process group that ignores SIGTERM and holds none of the stub's pipes, waits up
to 10 s until the child has written `<hold>.ready`, writes `"<own pid> <child
pid>"` to `<hold>` and sleeps 60 s before it behaves as above. The stub keeps
the default SIGTERM action, so it exits on TERM while its child does not.

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
import subprocess
import sys
import time

CHILD = ("import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
         "open(sys.argv[1], 'w').write('ready'); time.sleep(60)")


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
    log, canned, resumed, code, diagnostic, hold, words = (
        argv[0], argv[1], argv[2], int(argv[3]), argv[4], argv[5], argv[6:])
    answer_path = os.environ.get("CLAUDE_ACCOUNT_ANSWER")
    entry = None
    if canned.endswith(".answers.json"):
        with open(canned, encoding="utf-8") as handle:
            entries = json.load(handle)
        entry = entries[min(invocations(log), len(entries) - 1)]
        canned, code = entry["stdout"], entry["exit"]
    record = {"announced": announced(words), "answer_file": answer_path is not None,
              "account_env": os.environ.get("CLAUDE_ACCOUNT"), "argv": words,
              "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"), "cwd": os.getcwd(),
              "host_settings": os.environ.get("CLAUDE_ACCOUNT_HOST_SETTINGS"),
              "stdin": sys.stdin.read()}
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
    if hold != "-":
        hold_with_child(hold)
    if not all_out:
        chosen = resumed if entry is None and "--resume" in words and resumed != "-" else canned
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
