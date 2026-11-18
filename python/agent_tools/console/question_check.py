"""`question_check`: the verify script that the fixed project questions are each answered from the console's own records (#1271).

`python -m agent_tools.console.question_check --project ID [--run NAME] [--url URL]
[--token-file PATH] [--state-file PATH] [--result-file PATH] [--wait SECONDS]` asks this host's
console three fixed questions of one project and judges the answers it shows. The questions are
`QUESTIONS` (what shipped and what is live in the last 7 days; what costs the most time or tokens
per issue and whether the backlog holds an improvement) and a third about a failed production run:
`NAMED_RUN` with `--run`, else `LAST_FAILED_RUN` (P7). The check asks them through the page's own
write route (`POST /api/project-question` with `Origin` and `X-Console-Token`), so a run that posts
starts at most three read-only `sonnet` sessions, which is why its verify check is `effects: paid`.
The answers, and any refusal text the console returns, go only to the result file, where the owner
reads them; stdout never carries them (P10).

Options. `--url` defaults to `http://127.0.0.1:27184`; only `http` on `127.0.0.1` or `localhost` is
accepted, else exit 2. `--token-file` defaults to `<state dir>/page-token`, `--state-file` to
`<state dir>/checks/question-check.json` and `--result-file` to
`<state dir>/checks/question-check-result.json`, where the state dir is `<state_root()>/console`.
`--wait` defaults to `WAIT_SECONDS` (480, below verify_exec's 600-second limit).

The state file is `{"projects": {ID: {"revision": SHA, "keys": {QUESTION TEXT: REQUEST KEY}}}}`. The
result file is `{"project", "revision", "checked_at", "status", "questions": [{"question",
"request_key", "verdict", "post", "shown"}]}`: `post` is None when this run sent nothing for the
question, `"posted"`, or `"refused: <status>: <text>"` (the console's refusal text included);
`shown` is the view question exactly as `/api/state` gave it, every answer section included, or None
when the view holds no question with its key. Each file is written 0600 in a 0700 directory.

Order of one run:

1. `revision()` is `git rev-parse HEAD` of the current directory (verify-pending runs the script in
   a detached worktree at the block's merge commit, and only once the deployment holds). None is
   status `no_revision`, exit 2, nothing posted.
2. The console's `/api/state` view: None is `not_running`, 75.
3. The project entry whose `project_id` is ID, in `entries` or in a `quiet_group`'s `projects`: none
   is `not_registered`, 75.
4. Saved keys belong to one revision. When the saved entry of ID has another revision it is replaced
   by `{"revision": rev, "keys": {}}`, so answers to an earlier revision's questions are never
   judged. Each question text takes its saved key, else a new `secrets.token_hex(16)` key, and the
   state file is written before any POST (a key kept across a retry of the same revision is the
   only way a retry finds the question it already asked).
5. A question is found by its own key only (P6): the view question of ID whose `request_key` is the
   key saved for its text, judged by that question's `id`; a question of the same text under
   another key or none is never judged. A text whose key no view question carries is posted as
   `{"project_id", "question", "request_key"}`, at most once per run; an unreadable token file is
   `no_token`, 75, nothing posted. A 204 is `posted`; any other status, or none, is `refused` and
   the key stays saved.
6. The run waits within itself (P9): it polls, `sleep(POLL_SECONDS)` and then a new view read (a
   None read keeps polling), until every question is found and not `working`, or until `--wait`
   seconds have passed since the run began. After a post the view is read again before it is trusted.
7. Verdicts: not found or `working` is `pending` (`refused` when its post was refused); `failed` and
   `timed_out` are `failed`; `answered` is `grounded` or `ungrounded`. An answer is grounded iff its
   `answer` is a non-blank string and `cites(read_text, question_id + RECORDS_SUFFIX)` holds (P5).
8. Status, first match wins: any `failed` or `ungrounded` is `not_met`, exit 1; any `pending` or
   `refused` is `waiting`, 75; else `met`, 0. A usage or setup error is 2.
9. The result file is written whenever step 3 found the project. Stdout is exactly one JSON line with
   sorted keys, `{"status", "verdicts", "result_file"}`, holding no question text, no answer text
   and no text the console returned (P10); a refused post shows only as the verdict `refused`. The
   runs that stop before the project is found print `{"status"}` alone. Stderr gets only argparse's
   usage error. The check writes nothing but its two files and never reads the tracker or the forge.

`cites(read_text, name)` is False for None. Otherwise it removes the `ASK_READ_TEXT` prefix and
splits the rest on whitespace and `,;()[]<>` backquote and quote and `*`, strips each token's trailing
`.` and `:` and then a line suffix (`:12`, `:1-40`, `:3,5`), and is True iff some token's text after
its last `/` equals `name` exactly, so a backup, a longer name or another question's file never counts.

The seams of `main` are `state`, `post`, `now`, `sleep`, `new_key` and `revision`.
"""

import argparse
import json
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console import manager_check, project_question, service, view

QUESTIONS = (
    "What shipped, and what is live, in the last 7 days?",
    "What costs the most time or tokens per issue, and is anything in the backlog to improve it?",
)
NAMED_RUN = "Why did production run {run} fail?"
LAST_FAILED_RUN = "Why did the most recent failed production run fail?"
WAIT_SECONDS = 480
POLL_SECONDS = 5
NOT_YET = manager_check.NOT_YET
REVISION_TIMEOUT = 10
_REVISION = re.compile(r"[0-9a-f]{40}")
_TOKEN_SPLIT = re.compile(r"[\s,;()\[\]<>`'\"*]+")
_LINE_SUFFIX = re.compile(r":[0-9][0-9,-]*$")
_EXIT = {"met": 0, "not_met": 1, "waiting": NOT_YET}


def questions(run: str | None) -> tuple[str, str, str]:
    """The three fixed question texts, the third naming `run` when given."""
    third = LAST_FAILED_RUN if run is None else NAMED_RUN.format(run=run)
    return (*QUESTIONS, third)


def cites(read_text: str | None, name: str) -> bool:
    """Whether the Read section names the file `name` as a complete name."""
    if read_text is None:
        return False
    for token in _TOKEN_SPLIT.split(read_text.removeprefix(view.ASK_READ_TEXT.format(text=""))):
        token = _LINE_SUFFIX.sub("", token.rstrip(".:"))
        if token.rsplit("/", 1)[-1] == name:
            return True
    return False


def _git_revision() -> str | None:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=REVISION_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    return text if _REVISION.fullmatch(text) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="question_check", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project id to ask the questions of")
    parser.add_argument("--run", default=None, help="the production run the third question names")
    parser.add_argument("--url", type=manager_check._loopback_url, default=manager_check.DEFAULT_URL)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--result-file", type=Path, default=None)
    parser.add_argument("--wait", type=manager_check._positive, default=WAIT_SECONDS,
                        help="seconds one run waits (default: %(default)s)")
    return parser


def _project_entry(view_: dict, project: str) -> dict | None:
    for entry in view_.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for candidate in [entry, *(entry.get("projects") or [] if entry.get("type") == "quiet_group" else [])]:
            if isinstance(candidate, dict) and candidate.get("project_id") == project:
                return candidate
    return None


def _shown(entry: dict, key: str) -> dict | None:
    group = entry.get("questions")
    for thread in (group.get("threads") if isinstance(group, dict) else None) or []:
        for question in (thread.get("questions") if isinstance(thread, dict) else None) or []:
            if isinstance(question, dict) and question.get("request_key") == key:
                return question
    return None


def _read_state(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _verdict(shown: dict | None, refused: bool) -> str:
    state = shown.get("state") if shown else None
    if state in ("failed", "timed_out"):
        return "failed"
    if state == "answered":
        answer = shown.get("answer")
        if (isinstance(answer, str) and answer.strip()
                and cites(shown.get("read_text"), str(shown.get("id")) + project_question.RECORDS_SUFFIX)):
            return "grounded"
        return "ungrounded"
    return "refused" if refused else "pending"


def _status(verdicts: list[str]) -> str:
    if "failed" in verdicts or "ungrounded" in verdicts:
        return "not_met"
    if "pending" in verdicts or "refused" in verdicts:
        return "waiting"
    return "met"


def main(argv: list[str] | None = None, *, state=None, post=None, now=None, sleep=None,
         new_key=None, revision=None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = manager_check._state_dir()
    token_file = args.token_file or state_dir / "page-token"
    state_file = args.state_file or state_dir / "checks" / "question-check.json"
    result_file = args.result_file or state_dir / "checks" / "question-check-result.json"
    state = state or (lambda url: manager_check.Console(url).state())
    post = post or (lambda url, token, document: manager_check.Console(url, token).post(
        service.PROJECT_QUESTION_PATH, document))
    now = now or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    new_key = new_key or (lambda: secrets.token_hex(16))
    revision = revision or _git_revision
    started = now()

    def finish(status: str, code: int | None = None, **more) -> int:
        print(json.dumps({"status": status, **more}, sort_keys=True))
        return _EXIT.get(status, NOT_YET) if code is None else code

    rev = revision()
    if rev is None:
        return finish("no_revision", 2)
    current = state(args.url)
    if current is None:
        return finish("not_running")
    if _project_entry(current, args.project) is None:
        return finish("not_registered")

    texts = questions(args.run)
    saved = _read_state(state_file)
    projects = saved.get("projects") if isinstance(saved.get("projects"), dict) else {}
    kept = projects.get(args.project)
    if not isinstance(kept, dict) or kept.get("revision") != rev or not isinstance(kept.get("keys"), dict):
        kept = {"revision": rev, "keys": {}}
    keys = {text: kept["keys"].get(text) if isinstance(kept["keys"].get(text), str) else new_key()
            for text in texts}
    manager_check._write_json(state_file, {**saved, "projects": {
        **projects, args.project: {"revision": rev, "keys": keys}}})

    entry = _project_entry(current, args.project)
    posts: dict[str, str] = {}
    stale = False
    for text in texts:
        if _shown(entry, keys[text]) is not None:
            continue
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return _finish_result(finish, result_file, args.project, rev, now, "no_token", texts,
                                  keys, ["pending"] * len(texts), posts, entry)
        status, detail = post(args.url, token, {
            "project_id": args.project, "question": text, "request_key": keys[text]})
        posts[text] = "posted" if status == 204 else f"refused: {status}: {detail}"
        stale = True

    def settled() -> bool:
        return not stale and all(
            (shown := _shown(entry, keys[text])) is not None and shown.get("state") != "working"
            for text in texts)

    while not settled() and now() - started < timedelta(seconds=args.wait):
        sleep(POLL_SECONDS)
        fresh = state(args.url)
        if fresh is not None and _project_entry(fresh, args.project) is not None:
            current, entry, stale = fresh, _project_entry(fresh, args.project), False

    verdicts = [_verdict(_shown(entry, keys[text]), posts.get(text, "").startswith("refused"))
                for text in texts]
    return _finish_result(finish, result_file, args.project, rev, now, _status(verdicts), texts, keys,
                          verdicts, posts, entry)


def _finish_result(finish, result_file, project, rev, now, status, texts, keys, verdicts, posts,
                   entry) -> int:
    manager_check._write_json(result_file, {
        "project": project, "revision": rev, "checked_at": now().isoformat(), "status": status,
        "questions": [{"question": text, "request_key": keys[text], "verdict": verdict,
                       "post": posts.get(text), "shown": _shown(entry, keys[text])}
                      for text, verdict in zip(texts, verdicts)]})
    return finish(status, verdicts=verdicts, result_file=str(result_file))


if __name__ == "__main__":
    sys.exit(main())
