"""A stand-in for the account launcher in the engine's stubbed runs.

Run as `python claude_stub.py <scenario.json> <log> <launcher args...>`. It reads stdin (the
prompt) and takes the value after `--json-schema`. The scenario file is one JSON object of
entries keyed by step id. The stub reads the step and the visit from the file name after
`--append-system-prompt-file` (`<step>.<visit>.system.md`) and takes the entry `<step>.<visit>`
when the scenario holds it, else the entry `<step>`. An entry is the structured reply itself, or
`{"reply": {...}, "commit": {"worktree": <abs path>, "path": <relative>, "text": <file text>}}`:
then the stub records `start = git -C <worktree> rev-parse HEAD`, writes the file, adds and
commits it as `stub change`, and answers the reply with `start_head` = start and `commit` = the
new HEAD. An entry may carry more effects beside `commit`, each answered with the entry's `reply`:
`"upstream": {"bare", "path", "text"}` commits that file to the `main` of the bare repository
(as `stub upstream`) after any `commit`; `"merge": {"worktree", "resolve": {path: text}}` fetches
origin and merges `origin/main` into the worktree (a conflict is resolved with the given files and
committed, or aborted when `resolve` is absent); `"same_head": {"worktree"}` answers
`start_head` and `commit` both as the worktree's HEAD and commits nothing;
`"advance": {"worktree"}` moves the worktree's `refs/remotes/origin/main` to its HEAD (a fetch that
brought the branch into `main`), after `same_head` and before `leave`, moving no head and committing nothing;
`"leave": {"worktree", "path", "text"}` writes that file in the worktree after every other effect
and neither adds nor commits it (one untracked file, no head moved). It appends `{"argv", "key", "prompt"}` as one JSON line to `<log>`, `key` being the
step id (never the visit), writes `{"account": "stub"}` to the file named by
`CLAUDE_ACCOUNT_ANSWER` when that is set, and prints
`tests/fixtures/engine-session/result-normal.json` with `structured_output` replaced by the
answer and `session_id` by the argv word after `--session-id` (or `--resume`), then exits 0. A
step with no entry prints a result with no `structured_output`. A launch with a session id
records its answer in `<log>.sessions/<session>.json` before printing; a `--resume` whose record
exists replays that answer and runs no effect again.
"""

import json
import os
import shutil
import subprocess
import tempfile
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


IDENTITY = ("-c", "user.name=stub", "-c", "user.email=stub@example.invalid", "-c", "commit.gpgsign=false")


def git_in(tree: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", tree, *IDENTITY, *args], capture_output=True, text=True, check=check)


def upstream_effect(effect: dict) -> None:
    """Commit the effect's file to the `main` of the effect's bare repository, as `stub upstream`."""
    clone = tempfile.mkdtemp(prefix="stub-upstream-")
    try:
        subprocess.run(["git", "clone", "-q", "--branch", "main", effect["bare"], clone],
                       capture_output=True, text=True, check=True)
        target = Path(clone) / effect["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(effect["text"], encoding="utf-8")
        git_in(clone, "add", effect["path"])
        git_in(clone, "-c", "user.name=stub upstream", "commit", "-q", "-m", "stub upstream")
        git_in(clone, "push", "-q", effect["bare"], "HEAD:refs/heads/main")
    finally:
        shutil.rmtree(clone, ignore_errors=True)


def merge_effect(effect: dict) -> None:
    """Merge `origin/main` into the worktree; resolve a conflict with the given files, else abort it."""
    tree = effect["worktree"]
    git_in(tree, "fetch", "-q", "origin")
    merged = git_in(tree, "merge", "--no-edit", "origin/main", check=False)
    if merged.returncode == 0:
        return
    conflicted = git_in(tree, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode == 0
    if not conflicted:
        raise subprocess.CalledProcessError(merged.returncode, "git merge", merged.stdout, merged.stderr)
    if not effect.get("resolve"):
        git_in(tree, "merge", "--abort")
        return
    for path, text in effect["resolve"].items():
        (Path(tree) / path).write_text(text, encoding="utf-8")
        git_in(tree, "add", path)
    git_in(tree, "commit", "--no-edit")


def same_head_effect(effect: dict) -> str:
    return git_in(effect["worktree"], "rev-parse", "HEAD").stdout.strip()


def advance_effect(effect: dict) -> None:
    """Move the worktree's `refs/remotes/origin/main` to its HEAD, as a fetch that brought the branch in."""
    git_in(effect["worktree"], "update-ref", "refs/remotes/origin/main", "HEAD")


def leave_effect(effect: dict) -> None:
    """Write the effect's file in the worktree and leave it untracked."""
    target = Path(effect["worktree"]) / effect["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(effect["text"], encoding="utf-8")


def run_entry(result: dict, scenario: dict, name: str | None) -> None:
    """Run the scenario entry's effects and set the result's answer."""
    if name is None:
        result.pop("structured_output", None)
    else:
        entry = scenario[name]
        if "reply" in entry:
            reply = dict(entry["reply"])
            if "commit" in entry:
                reply["start_head"], reply["commit"] = commit_effect(entry["commit"])
            if "upstream" in entry:
                upstream_effect(entry["upstream"])
            if "merge" in entry:
                merge_effect(entry["merge"])
            if "same_head" in entry:
                reply["start_head"] = reply["commit"] = same_head_effect(entry["same_head"])
            if "advance" in entry:
                advance_effect(entry["advance"])
            if "leave" in entry:
                leave_effect(entry["leave"])
            entry = reply
        result["structured_output"] = entry


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
    record = Path(log + ".sessions") / f"{session}.json" if session is not None else None
    if session is not None:
        result["session_id"] = session
    if "--resume" in words and record is not None and record.exists():
        result["structured_output"] = json.loads(record.read_text(encoding="utf-8"))["structured_output"]
    else:
        if record is not None:
            record.unlink(missing_ok=True)
        run_entry(result, scenario, name)
        if record is not None and "structured_output" in result:
            record.parent.mkdir(parents=True, exist_ok=True)
            scratch = record.with_suffix(".json.tmp")
            scratch.write_text(json.dumps({"structured_output": result["structured_output"]}), encoding="utf-8")
            os.replace(scratch, record)
    try:
        sys.stdout.write(json.dumps(result))
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
