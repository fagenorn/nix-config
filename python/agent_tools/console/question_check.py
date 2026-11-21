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

The state file is `{"projects": {ID: {"revision": SHA, "keys": {QUESTION TEXT: REQUEST KEY}}}}`; its
`keys` hold every question text this revision has been asked, not only the current run's three, so
`--run A`, `--run B` and `--run A` again finds A's question the second time. The
result file is `{"project", "revision", "checked_at", "status", "questions": [{"question",
"request_key", "verdict", "post", "shown"}]}`: `post` is None when this run sent nothing for the
question, `"posted"`, or `"refused: <status>: <text>"` (the console's refusal text included);
`shown` is the view question exactly as `/api/state` gave it, every answer section included, or None
when the view holds no question with its key. Each file is written 0600 in a 0700 directory, through a temporary file of its own that is then renamed over it,
so two checks at once never share a temporary.

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
   only way a retry finds the question it already asked). Reading the state, choosing the keys and
   writing it are one section under an exclusive `flock` on `<state file>.lock`, so two runs at
   once share one set of keys and cannot start six paid sessions. A state file that exists but is
   not the shape above (truncated, not JSON, a wrong type, no `projects` member, a key that is not 32
   lowercase hex digits (`project_question.REQUEST_KEY`, which the console would refuse over HTTP on every
   run), or one key saved for two
   texts of a project, since two lookups of one key would judge one answer for two questions) is status `bad_state`, exit 2, nothing
   posted and the file left as it was: a fresh empty state would generate new keys and could ask
   every paid question again. A missing file is an empty state, `{"projects": {}}`.
5. A question is found by its own key only (P6): the view question of ID whose `request_key` is the
   key saved for its text, judged by that question's `id`; a question of the same text under
   another key or none is never judged. A text whose key no view question carries is posted as
   `{"project_id", "question", "request_key"}`, at most once per run (but see below); an unreadable token file is
   `no_token`, 75, nothing posted. A 204 is `posted`; any other status, or none, is `refused` and
   the key stays saved. The console keeps a receipt of every key it has asked beyond the question's own
   retention and answers 204 to it without starting a session, so a key kept from an earlier run whose
   question the view no longer holds is posted, the view is read at once, and when that key's question
   is still not shown the key was answered by its receipt: under the lock the saved key is replaced
   by a new one (a run that finds another run already replaced it adopts that one and posts nothing)
   and the text is posted once more under it. Only a receipt hit is posted a second time, and it started no session.
6. The run waits within itself (P9): it polls, `sleep(POLL_SECONDS)` and then a new view read (a
   None read keeps polling), until every question is found and not `working`, or until `--wait`
   seconds have passed since the run began. After a post the view is read again before it is trusted.
7. Verdicts: not found or `working` is `pending` (`refused` when its post was refused); `failed` and
   `timed_out` are `failed`; `answered` is `grounded` or `ungrounded`. An answer is grounded iff its
   `answer` is a non-blank string and `cites(read_text, question_id + RECORDS_SUFFIX)` holds (P5); the
   cost question's (`QUESTIONS[1]`) answer is also grounded only when `spend_figure(answer)` holds and
   `cites_part(read_text, question_id + RECORDS_SUFFIX, SPEND_PART)` holds, so a cost answer that names
   no spend figure, or does not cite the spend part of its own file, is `ungrounded` (ADR-console-090).
8. Status, first match wins: any `failed` or `ungrounded` is `not_met`, exit 1; any `pending` or
   `refused` is `waiting`, 75; else `met`, 0. A usage or setup error is 2.
9. The result file is written whenever step 3 found the project. Stdout is exactly one JSON line with
   sorted keys, `{"status", "verdicts", "result_file"}`, holding no question text, no answer text
   and no text the console returned (P10); a refused post shows only as the verdict `refused`. The
   runs that stop before the project is found print `{"status"}` alone. Stderr gets only argparse's
   usage error. The check writes nothing but its two files and the lock file beside its state file, and never
   reads the tracker or the forge.

`cites(read_text, name)` is False for None. Otherwise it removes the `ASK_READ_TEXT` prefix and
splits the rest into clauses (at a newline, and at `.`, `;`, `,`, `!` or `?` followed by whitespace).
A clause names `name` when, splitting it on whitespace and `,;()[]<>` backquote and quote and `*`,
stripping each token's trailing `.` and `:` and then a line suffix (`:12`, `:1-40`, `:3,5`), some
token's text after its last `/` equals `name` exactly, so a backup, a longer name or another
question's file never counts. `cites` is True iff at least one clause names `name` and no clause from
the first one that does to the end of the section matches `_FAILED_READ` (could not, cannot, unable,
failed, denied, refused, not found, not readable, missing, error and the like): an answer that says,
in that clause or any later one, that it could not open its records file has not read it. A failure
word in a clause before the first naming one (`flake.nix (could not open), q2.records.json`) does not count.
A failure word that belongs to the run the question asks about (`failed activation`, `build failed`: a
failure or error next to `activation`, `run`, `build`, `deploy`, `production`, `check`, `job`, `workflow`,
`step`, `test`, `switch`, `delivery`, `release`, `commit` or `merge`, unless `to` follows, as in `run failed
to open`) is removed first (`_FAILED_RUN`), so `q.records.json (failed activation)` is a citation.

`spend_figure(text)` is False for None, else whether the text holds a spend figure: a dollar amount
(`$0.42`, `$1,200`, `$3k`, `$12`, `$5 a month`: a complete amount, not followed by a digit, `,` or `.` and a
digit, so `$12,34` is no figure; a lone digit is a figure unless a word character follows it, an argument
word follows it (`$1 is a script argument`) or an article or argument noun leads into it at the end of a
sentence (`the $1.`), since `$1` is also a shell argument), a number followed by `tokens`
(with an optional `k`, `m`, `b`, `thousand`, `million` or `billion`) or a number followed by `dollars` or
`usd`, with the `**bold**` or `inline code` marks the answer rules permit around the number or the unit
(`**4,200** tokens`). A number is digits with commas only between three-digit groups and an optional fraction, and one right after `#`, a word character, `.` or `,` is
not a figure, so `issue #7, tokens` and `issue 7, tokens` hold none. `cites_part(read_text, name, part)`
is True iff `cites(read_text, name)` holds and some occurrence of `name` in the Read text, at the start
of a line or after whitespace, `/`, a backquote, a quote, `(`, `[` or `<`, is followed by an optional
closing backquote, an optional line range (`:120-400`) and optional whitespace and then a parenthesized
group one of whose items equals `part` (case-insensitively; the group is a list of section names split
at `,`, `;`, `/`, `&` and `and`, so `deliveries only, excluding spend` cites no spend part), so the part is bound to the citation of the
question's own file: `<path> (deliveries), old-profile.md (spend)` does not cite the spend part.

The seams of `main` are `state`, `post`, `now`, `sleep`, `new_key` and `revision`.
"""

import argparse
import contextlib
import fcntl
import json
import os
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
_CLAUSE_SPLIT = re.compile(r"\n|(?<=[.;,!?])\s+")
_FAILED_READ = re.compile(
    r"\b(?:could\s*n[o']t|can\s*n[o']t|can't|unable|fail(?:ed|s|ure)?|den(?:y|ied|ies)|refus(?:e|ed|al)"
    r"|did\s*n[o']t|didn't|not\s+(?:found|readable|permitted|allowed|available|opened?|read)"
    r"|no\s+such|unreadable|missing|errors?)\b", re.IGNORECASE)
_FAILED_RUN = re.compile(
    r"\b(?:(?:activation|run|build|deploy\w*|production|check|job|workflow|step|test|switch|delivery|release"
    r"|commit|merge)s?\s+(?:fail(?:ed|s|ure)?|errors?)(?!\s+to\b)"
    r"|(?:fail(?:ed|s|ure)?|errors?)\s+(?:activation|run|build|deploy\w*|production|check|job|workflow|step"
    r"|test|switch|delivery|release|commit|merge)s?)\b", re.IGNORECASE)
_LINE_SUFFIX = re.compile(r":[0-9][0-9,-]*$")
SPEND_PART = "spend"
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MAGNITUDE = r"(?:[kmb]|thousand|million|billion)"
_MARK = r"[*`]{0,2}\s?[*`]{0,2}"
_END = r"(?![\d]|[.,]\d)"
# A lone digit after `$` is also a shell positional argument ($1): it is a dollar amount unless a word follows it,
# a word that names an argument follows it, or an article or argument noun leads into it at the end of a sentence.
_SHELL_WORD = r"(?:is|as|are|argument|arguments|arg|args|parameter|param|variable|var|holds|expands|refers|means|set|passed)"
_SHELL_LEAD = "".join(r"(?<!\b" + word + r"\s\$)(?<!\b" + word + r"\s\$\s)"
                      for word in ("the", "with", "using", "use", "argument", "parameter", "arg", "variable", "var"))
_LONE_DIGIT = (r"(?:" + _SHELL_LEAD + r"|(?=\d(?!\.?\s*\Z|\.(?!\d))))\d(?!\w)(?!\s+" + _SHELL_WORD + r"\b)")
_SPEND_FIGURE = re.compile(
    r"\$\s?(?:(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+|\d{1,3}(?:,\d{3})+|\d+\s?" + _MAGNITUDE + r"\b|\d{2,}"
    + r"|" + _LONE_DIGIT + r")" + _END
    + r"|(?<![#\w.,])" + _NUMBER + _MARK + r"(?:" + _MAGNITUDE + _MARK + r")?tokens?\b"
    + r"|(?<![#\w.,])" + _NUMBER + _MARK + r"(?:dollars|usd)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not?|non|excl(?:uding|udes?|uded)?|without|except(?:ing)?)\b", re.IGNORECASE)
_PART_SPLIT = re.compile(r"\s*(?:[,;/&]|\band\b)\s*", re.IGNORECASE)
_EXIT = {"met": 0, "not_met": 1, "waiting": NOT_YET}


def questions(run: str | None) -> tuple[str, str, str]:
    """The three fixed question texts, the third naming `run` when given."""
    third = LAST_FAILED_RUN if run is None else NAMED_RUN.format(run=run)
    return (*QUESTIONS, third)


def cites(read_text: str | None, name: str) -> bool:
    """Whether the Read section names the file `name` as a complete name."""
    if read_text is None:
        return False
    clauses = _CLAUSE_SPLIT.split(read_text.removeprefix(view.ASK_READ_TEXT.format(text="")))
    named = [i for i, clause in enumerate(clauses) if _names(clause, name)]
    return bool(named) and not any(
        _FAILED_READ.search(_FAILED_RUN.sub(" ", clause)) for clause in clauses[named[0]:])


def spend_figure(text: str | None) -> bool:
    """Whether `text` holds a spend figure: a dollar amount or a number of tokens or dollars."""
    return text is not None and _SPEND_FIGURE.search(text) is not None


def cites_part(read_text: str | None, name: str, part: str) -> bool:
    """Whether the Read section cites `name` and marks `part` in the parentheses right after that citation."""
    if not cites(read_text, name):
        return False
    body = read_text.removeprefix(view.ASK_READ_TEXT.format(text=""))
    pattern = re.compile(r"(?:^|(?<=[\s/`'\"(\[<]))" + re.escape(name)
                         + r"`?(?::[0-9][0-9,-]*)?`?\s*\(([^)]*)\)", re.MULTILINE)
    return any(part.casefold() == item.strip(" *`'\"").casefold()
               for found in pattern.finditer(body) if not _NEGATION.search(found.group(1))
               for item in _PART_SPLIT.split(found.group(1)))


def _names(clause: str, name: str) -> bool:
    for token in _TOKEN_SPLIT.split(clause):
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


def _valid_state(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    projects = document.get("projects")
    return isinstance(projects, dict) and all(
        isinstance(kept, dict) and isinstance(kept.get("revision"), str)
        and isinstance(kept.get("keys"), dict)
        and all(isinstance(text, str) and isinstance(key, str)
                and project_question.REQUEST_KEY.fullmatch(key)
                for text, key in kept["keys"].items())
        and len(set(kept["keys"].values())) == len(kept["keys"])
        for kept in projects.values())


def _read_state(path: Path) -> dict | None:
    """The saved state; an empty one when there is no file, None when the file is not a valid state."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"projects": {}}
    except (OSError, ValueError):
        return None
    return document if _valid_state(document) else None


@contextlib.contextmanager
def _locked(state_file: Path):
    """An exclusive lock on `<state file>.lock` for the body, so two runs never both read an empty state."""
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(state_file.with_name(state_file.name + ".lock"),
                         os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _verdict(shown: dict | None, refused: bool, cost: bool = False) -> str:
    state = shown.get("state") if shown else None
    if state in ("failed", "timed_out"):
        return "failed"
    if state == "answered":
        answer = shown.get("answer")
        name = str(shown.get("id")) + project_question.RECORDS_SUFFIX
        if (isinstance(answer, str) and answer.strip() and cites(shown.get("read_text"), name)
                and (not cost or (spend_figure(answer)
                                  and cites_part(shown.get("read_text"), name, SPEND_PART)))):
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
    with _locked(state_file):
        saved = _read_state(state_file)
        if saved is None:
            return finish("bad_state", 2)
        projects = saved.get("projects", {})
        kept = projects.get(args.project)
        if kept is None or kept["revision"] != rev:
            kept = {"revision": rev, "keys": {}}
        keys = {text: kept["keys"][text] if text in kept["keys"] else new_key() for text in texts}
        manager_check._write_json(state_file, {**saved, "projects": {
            **projects, args.project: {"revision": rev, "keys": {**kept["keys"], **keys}}}})

    entry = _project_entry(current, args.project)
    posts: dict[str, str] = {}
    stale = False
    retried = [text for text in texts if text in kept["keys"]]

    def ask(text: str) -> bool:
        """Post `text` under its key; False when there is no token to post with."""
        nonlocal stale
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return False
        status, detail = post(args.url, token, {
            "project_id": args.project, "question": text, "request_key": keys[text]})
        posts[text] = "posted" if status == 204 else f"refused: {status}: {detail}"
        stale = True
        return True

    for text in texts:
        if _shown(entry, keys[text]) is None and not ask(text):
            return _finish_result(finish, result_file, args.project, rev, now, "no_token", texts,
                                  keys, ["pending"] * len(texts), posts, entry)
    posted = [text for text in retried if posts.get(text) == "posted"]
    fresh = state(args.url) if posted else None
    if fresh is not None and _project_entry(fresh, args.project) is not None:
        current, entry, stale = fresh, _project_entry(fresh, args.project), False
        # A kept key the console accepted but that shows no question was answered by its permanent receipt
        # after the answer's retention expired: it starts nothing and never appears, so ask again under a new key.
        expired = [text for text in posted if _shown(entry, keys[text]) is None]
        if expired:
            with _locked(state_file):
                saved = _read_state(state_file)
                if saved is None:
                    return finish("bad_state", 2)
                held = saved["projects"].get(args.project, {"revision": rev, "keys": {}})
                rotate = [text for text in expired if held["keys"].get(text) == keys[text]]
                for text in expired:
                    keys[text] = new_key() if text in rotate else held["keys"].get(text, keys[text])
                manager_check._write_json(state_file, {**saved, "projects": {
                    **saved["projects"], args.project: {
                        "revision": rev, "keys": {**held["keys"], **{t: keys[t] for t in expired}}}}})
            for text in rotate:
                if not ask(text):
                    return _finish_result(finish, result_file, args.project, rev, now, "no_token",
                                          texts, keys, ["pending"] * len(texts), posts, entry)

    def settled() -> bool:
        return not stale and all(
            (shown := _shown(entry, keys[text])) is not None and shown.get("state") != "working"
            for text in texts)

    while not settled() and now() - started < timedelta(seconds=args.wait):
        sleep(POLL_SECONDS)
        fresh = state(args.url)
        if fresh is not None and _project_entry(fresh, args.project) is not None:
            current, entry, stale = fresh, _project_entry(fresh, args.project), False

    verdicts = [_verdict(_shown(entry, keys[text]), posts.get(text, "").startswith("refused"),
                         cost=(text == QUESTIONS[1]))
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
