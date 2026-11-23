"""A stand-in for the account launcher in the engine's stubbed runs.

Run as `python claude_stub.py <scenario.json> <log> <launcher args...>`. It reads stdin (the
prompt) and takes the value after `--json-schema`. The scenario file is one JSON object of
entries keyed by step id. The stub reads the step and the visit from the file name after
`--append-system-prompt-file` (`<step>.<visit>.system.md`) and takes the entry `<step>.<visit>`
when the scenario holds it, else the entry `<step>`. An entry is the structured reply itself, or
`{"reply": {...}, "commit": {"worktree": <abs path>, "path": <relative>, "text": <file text>}}`:
then the stub records `start = git -C <worktree> rev-parse HEAD`, writes the file, adds and
commits it as `stub change`, and answers the reply with `start_head` = start and `commit` = the
new HEAD. It appends `{"argv", "key", "prompt"}` as one JSON line to `<log>`, `key` being the
step id (never the visit), writes `{"account": "stub"}` to the file named by
`CLAUDE_ACCOUNT_ANSWER` when that is set, and prints
`tests/fixtures/engine-session/result-normal.json` with `structured_output` replaced by the
answer and `session_id` by the argv word after `--session-id` (or `--resume`), then exits 0. A
step with no entry prints a result with no `structured_output`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

NORMAL = Path(__file__).resolve().parents[1] / "engine-session" / "result-normal.json"


def word_after(argv: list[str], *flags: str) -> str | None:
    for flag in flags:
        if flag in argv:
            return argv[argv.index(flag) + 1]
    return None


def step_and_visit(words: list[str]) -> tuple[str | None, str | None]:
    path = word_after(words, "--append-system-prompt-file")
    if path is None:
        return None, None
    stem = Path(path).name.removesuffix(".system.md")
    step, _, visit = stem.rpartition(".")
    return step, visit


def commit_effect(effect: dict) -> tuple[str, str]:
    """Make the stub's commit in the effect's worktree; returns the HEAD before and after it."""
    tree = effect["worktree"]

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", tree, *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    start = git("rev-parse", "HEAD")
    target = Path(tree) / effect["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(effect["text"], encoding="utf-8")
    git("add", effect["path"])
    git("-c", "user.name=stub", "-c", "user.email=stub@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "stub change")
    return start, git("rev-parse", "HEAD")


def main(argv: list[str]) -> int:
    scenario = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    log, words = argv[1], argv[2:]
    prompt = sys.stdin.read()
    step, visit = step_and_visit(words)
    name = next((n for n in (f"{step}.{visit}", step) if n in scenario), None)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": words, "key": step, "prompt": prompt}, sort_keys=True) + "\n")
    answer = os.environ.get("CLAUDE_ACCOUNT_ANSWER")
    if answer:
        Path(answer).write_text(json.dumps({"account": "stub"}), encoding="utf-8")
    result = json.loads(NORMAL.read_text(encoding="utf-8"))
    session = word_after(words, "--session-id", "--resume")
    if session is not None:
        result["session_id"] = session
    if name is None:
        result.pop("structured_output", None)
    else:
        entry = scenario[name]
        if "reply" in entry:
            reply = dict(entry["reply"])
            if "commit" in entry:
                reply["start_head"], reply["commit"] = commit_effect(entry["commit"])
            entry = reply
        result["structured_output"] = entry
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
