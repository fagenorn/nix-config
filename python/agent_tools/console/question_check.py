"""`question_check`: the verify script that the fixed project questions are each answered from the console's own records (#1271).

`python -m agent_tools.console.question_check --project ID [--run NAME] [--url URL]
[--token-file PATH] [--state-file PATH] [--result-file PATH] [--wait SECONDS] [--deep [--compare
agree|disagree]]` asks this host's console three fixed questions of one project and judges the answers it shows. The questions are
`QUESTIONS` (what shipped and what is live in the last 7 days; what costs the most time or tokens
per issue and whether the backlog holds an improvement) and a third about a failed production run:
`NAMED_RUN` with `--run`, else `LAST_FAILED_RUN` (P7). The check asks them through the page's own
write route (`POST /api/project-question` with `Origin` and `X-Console-Token`), so a run that posts
starts at most three read-only `sonnet` sessions, which is why its verify check is `effects: paid`.
The answers, and any refusal text the console returns, go only to the result file, where the owner
reads them; stdout never carries them (P10).

The fixed set also holds issue 1274's deeper question, `DEEP_QUESTION` (where agents spend time and tokens on
issues, which parts of an issue take long, and what could be improved). `--deep` asks it alone, with each POST
body `{"project_id", "question", "request_key", "deep": true}`, and judges it by its own rule (Verdicts below)
and by the lead's comparison (below); without `--deep` the three questions and their bodies are unchanged.

Options. `--url` defaults to `http://127.0.0.1:27184`; only `http` on `127.0.0.1` or `localhost` is
accepted, else exit 2. `--token-file` defaults to `<state dir>/page-token`, `--state-file` to
`<state dir>/checks/question-check.json` and `--result-file` to
`<state dir>/checks/question-check-result.json`, where the state dir is `<state_root()>/console`.
`--wait` defaults to `WAIT_SECONDS` (480, below verify_exec's 600-second limit). With `--deep` the state file
defaults to `<state dir>/checks/question-check-deep.json` and the result file to
`<state dir>/checks/question-check-deep-result.json`, so an ordinary check at another revision never replaces the
deep key or the deep result.

`--compare agree|disagree` (only with `--deep`, else status `bad_usage`, exit 2) is the lead's comparison of the
deeper answer with the lead's hand analysis on its main figures. It posts nothing and asks nothing. Under the
state lock it reads the deep state entry of the project: when its revision is the current revision and the deep
result file holds, for that revision and the saved key, a question with verdict `grounded`, it writes
`"comparison": {"question_id", "request_key", "revision", "agrees", "at"}` into that entry and prints
`{"status": "compared", "agrees": BOOL}`, exit 0; otherwise `{"status": "nothing_to_compare"}`, exit 2, nothing
written. A new revision replaces the entry, comparison included (step 4).

The state file is `{"projects": {ID: {"revision": SHA, "keys": {QUESTION TEXT: REQUEST KEY}}}}`; its
`keys` hold (with the entry's optional `comparison`, above) every question text this revision has been asked, not only the current run's three, so
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
   cost question's (`QUESTIONS[1]`) answer is also grounded only when `spend_figure(answer, spend_figures(records
   text))` holds and `cites_part(read_text, question_id + RECORDS_SUFFIX, SPEND_PART)` holds, so a cost answer
   that quotes no figure of its own records' spend section, or does not cite the spend part of its own file, is
   `ungrounded` (ADR-console-089). The deeper question's (`DEEP_QUESTION`) answer is grounded iff it is answered with a non-blank
   answer, `cites(read_text, id + RECORDS_SUFFIX)`, `cites_part(read_text, name, TRANSCRIPTS_PART)` and
   `spend_figure(answer, section_figures(records text, TRANSCRIPTS_PART))` hold, else `ungrounded`. The records
   text is the question's own retained file,
   `<state dir>/project-question-settings/<question id>.records.json` (the console keeps it for an answered
   question, `project_question.RECORDS_KEPT_SECONDS`); a file that cannot be read leaves the answer `ungrounded`.
8. Status, first match wins: any `failed` or `ungrounded` is `not_met`, exit 1; any `pending` or
   `refused` is `waiting`, 75; else `met`, 0. A usage or setup error is 2. The deeper status: `met` only when the
   verdict is `grounded` and the state's `comparison` names the same question id, key and revision with `agrees`
   true; `not_met` when the verdict is `ungrounded` or `failed`, or the comparison says `agrees` false; `waiting`
   when the verdict is `grounded` and no matching comparison exists, or the verdict is pending or refused. The
   deep result file gains `"comparison"`, the matching comparison or None.
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

`section_figures(records, part)` applies `spend_figures`' rule to the top-level member `part`, and for
`TRANSCRIPTS_PART` also takes every int under a `seconds` key as its digits; `spend_figures(records)` is
`section_figures(records, SPEND_PART)`: the set of spend values the records text prints: parsed as JSON, every number under
a `tokens` key (an int) of its `spend` member, at any depth, as its digits, and every number under a `dollars`
key as `$` and two decimals (`$0.42`, `$38.10`); text that is no JSON, or has no `spend` object, gives the empty
set. `spend_figure(text, figures)` is False for None, else whether the text quotes one of them: it finds each
number in the text (digits with commas only between three-digit groups, an optional fraction, not inside a longer
word or number, an optional `$` before it) and holds a token count when a number with no `$` and no fraction,
commas dropped, is in `figures`, and a dollar amount when a number with `$` and a fraction, commas dropped, is.
The shape of the prose around a figure is never judged (ADR-console-089: the session is told to quote each
figure exactly as the records print it). Stated limits, not defects: a number of the answer that is no spend
figure but equals a spend value passes, and a figure the session reformats (rounded, `1.2M`, converted or
reworded) is no figure.

`cites_part(read_text, name, part)`
is True iff `cites(read_text, name)` holds and some occurrence of `name` in the Read text, at the start
of a line or after whitespace, `/`, a backquote, a quote, `(`, `[`, `<` or `*`, is followed by optional
closing backquotes, quotes or asterisks, an optional line range (`:120-400`) and optional whitespace and then a
parenthesized group one of whose words equals `part` (case-insensitively; the group is split at whitespace and
at `,`, `;`, `:`, `/`, `&` and the brackets and marks around a word, and every word must be a section name of
`question_records.DEEP_SECTIONS`, `held`, `checks`, `offset`, `limit`, `part`, `parts`, `section`, `sections`, `only`,
`and`, `line`, `lines` or a number, so `spend offset 3 limit 40` marks the spend part and a group with any
other word, `excluding`, `not`, `skipped`, `but` or `unread`, marks none, as in `deliveries only, spend skipped`), so the part is bound to the citation of the
question's own file: `<path> (deliveries), old-profile.md (spend)` does not cite the spend part.

The seams of `main` are `state`, `post`, `now`, `sleep`, `new_key`, `revision` and `records` (a question id to its
records text, None when unreadable).
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

from agent_tools.console import manager_check, project_question, question_records, service, view

QUESTIONS = (
    "What shipped, and what is live, in the last 7 days?",
    "What costs the most time or tokens per issue, and is anything in the backlog to improve it?",
)
NAMED_RUN = "Why did production run {run} fail?"
LAST_FAILED_RUN = "Why did the most recent failed production run fail?"
DEEP_QUESTION = "Where do agents spend time and tokens on issues, which parts of an issue take long, and what could be improved?"
TRANSCRIPTS_PART = "transcripts"
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
# A figure in an answer: a number (commas only between three-digit groups, an optional fraction), not part of a
# longer word or number, with an optional `$` before it. Judged only by membership in the records' spend values.
_AMOUNT = re.compile(r"(?<![\w.,])(\$\s?)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?!\w)")
# The words a parenthesized group may hold besides the part it marks: the records' section names, the prompt's
# `offset`/`limit` pair and numbers. Any other word (`excluding`, `skipped`, `but`, `unread`) can say the part
# was not read, so a group that holds one marks no part.
_PART_WORDS = frozenset((*question_records.DEEP_SECTIONS, "held", "checks", "offset", "limit", "part", "parts",
                         "section", "sections", "only", "and", "line", "lines"))
_PART_NUMBER = re.compile(r"[\d,.-]+")
_PART_SPLIT = re.compile(r"[\s,;:/&()\[\]<>`'\"*]+")
_EXIT = {"met": 0, "not_met": 1, "waiting": NOT_YET}


def questions(run: str | None, deep: bool = False) -> tuple[str, ...]:
    """The three fixed question texts, the third naming `run` when given; `deep` is #1274's deeper question alone."""
    if deep:
        return (DEEP_QUESTION,)
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


def spend_figures(records: str | None) -> frozenset[str]:
    """The spend values the records print: each token count as its digits, each dollar amount as `$` and two places."""
    return section_figures(records, SPEND_PART)


def section_figures(records: str | None, part: str) -> frozenset[str]:
    """The values the top-level member `part` of the records prints: `spend_figures`' rule, and for the transcripts
    part also each int under a `seconds` key as its digits."""
    try:
        spend = json.loads(records)[part] if records is not None else None
    except (ValueError, TypeError, KeyError, RecursionError):
        return frozenset()
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                number = isinstance(value, (int, float)) and not isinstance(value, bool)
                if number and name == "tokens" and isinstance(value, int):
                    found.add(str(value))
                elif number and name == "dollars":
                    found.add(f"${value:.2f}")
                elif number and name == "seconds" and part == TRANSCRIPTS_PART and isinstance(value, int):
                    found.add(str(value))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spend)
    return frozenset(found)


def spend_figure(text: str | None, figures: frozenset[str]) -> bool:
    """Whether `text` quotes a figure of `figures`, a token count or a two-place dollar amount as the records print it."""
    if text is None:
        return False
    for found in _AMOUNT.finditer(text):
        number = found.group(2).replace(",", "")
        if found.group(1) is None and found.group(3) is None and number in figures:
            return True
        if found.group(1) is not None and found.group(3) is not None and f"${number}{found.group(3)}" in figures:
            return True
    return False


def cites_part(read_text: str | None, name: str, part: str) -> bool:
    """Whether the Read section cites `name` and marks `part` in the parentheses right after that citation."""
    if not cites(read_text, name):
        return False
    body = read_text.removeprefix(view.ASK_READ_TEXT.format(text=""))
    pattern = re.compile(r"(?:^|(?<=[\s/`'\"(\[<*]))" + re.escape(name)
                         + r"[*`'\"]*(?::[0-9][0-9,-]*)?[*`'\"]*\s*\(([^)]*)\)", re.MULTILINE)
    return any(_marks(found.group(1), part) for found in pattern.finditer(body))


def _marks(group: str, part: str) -> bool:
    words = [word.casefold() for word in _PART_SPLIT.split(group) if word]
    return part.casefold() in words and all(
        word in _PART_WORDS or _PART_NUMBER.fullmatch(word) for word in words)


def _names(clause: str, name: str) -> bool:
    for token in _TOKEN_SPLIT.split(clause):
        token = _LINE_SUFFIX.sub("", token.rstrip(".:"))
        if token.rsplit("/", 1)[-1] == name:
            return True
    return False


def _records_reader(state_dir: Path):
    """The reader of a question's retained records text under the console's settings directory, None when unreadable."""
    def read(question_id: str) -> str | None:
        try:
            return (state_dir / project_question.SETTINGS_DIR / (question_id + project_question.RECORDS_SUFFIX)
                    ).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
    return read


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
    parser.add_argument("--deep", action="store_true", help="ask the deeper question (#1274) alone, and deep")
    parser.add_argument("--compare", choices=("agree", "disagree"), default=None,
                        help="with --deep: record the lead's comparison of the deeper answer, posting nothing")
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


def _verdict(shown: dict | None, refused: bool, records=None, part: str = SPEND_PART) -> str:
    """`records` is the reader of a question's records text for a question that must quote a figure of its `part`
    (None: any answer needs no figure)."""
    state = shown.get("state") if shown else None
    if state in ("failed", "timed_out"):
        return "failed"
    if state == "answered":
        answer = shown.get("answer")
        name = str(shown.get("id")) + project_question.RECORDS_SUFFIX
        if (isinstance(answer, str) and answer.strip() and cites(shown.get("read_text"), name)
                and (records is None or (spend_figure(answer, section_figures(records(str(shown.get("id"))), part))
                                         and cites_part(shown.get("read_text"), name, part)))):
            return "grounded"
        return "ungrounded"
    return "refused" if refused else "pending"


def _status(verdicts: list[str]) -> str:
    if "failed" in verdicts or "ungrounded" in verdicts:
        return "not_met"
    if "pending" in verdicts or "refused" in verdicts:
        return "waiting"
    return "met"


def _deep_status(verdict: str, comparison: dict | None) -> str:
    """The deeper question's status: `met` only for a grounded answer the lead's comparison agrees with."""
    if verdict in ("failed", "ungrounded"):
        return "not_met"
    if verdict != "grounded":
        return "waiting"
    if comparison is None:
        return "waiting"
    return "met" if comparison.get("agrees") is True else "not_met"


def _matching_comparison(state_file: Path, project: str, rev: str, shown: dict | None, key: str) -> dict | None:
    """The saved comparison of `project` when it names this revision, this key and the shown question's id."""
    saved = _read_state(state_file)
    kept = saved["projects"].get(project) if saved is not None else None
    comparison = kept.get("comparison") if kept is not None and kept["revision"] == rev else None
    if (isinstance(comparison, dict) and shown is not None and comparison.get("revision") == rev
            and comparison.get("request_key") == key and comparison.get("question_id") == shown.get("id")):
        return comparison
    return None


def _grounded_deep_question(result_file: Path, project: str, rev: str, key: str | None) -> str | None:
    """The id of the deeper question the result file judged `grounded` for this revision and key, else None."""
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(result, dict) or result.get("project") != project or result.get("revision") != rev:
        return None
    for judged in result.get("questions") or []:
        shown = judged.get("shown") if isinstance(judged, dict) else None
        if (isinstance(judged, dict) and key is not None and judged.get("request_key") == key
                and judged.get("verdict") == "grounded" and isinstance(shown, dict)
                and isinstance(shown.get("id"), str)):
            return shown["id"]
    return None


def _compare(finish, project: str, agrees: bool, state_file: Path, result_file: Path, rev: str, now) -> int:
    """Record the lead's comparison against the grounded deeper answer of this revision; post and ask nothing."""
    with _locked(state_file):
        saved = _read_state(state_file)
        if saved is None:
            return finish("bad_state", 2)
        kept = saved["projects"].get(project)
        key = kept["keys"].get(DEEP_QUESTION) if kept is not None and kept["revision"] == rev else None
        question_id = _grounded_deep_question(result_file, project, rev, key)
        if question_id is None:
            return finish("nothing_to_compare", 2)
        manager_check._write_json(state_file, {**saved, "projects": {**saved["projects"], project: {
            **kept, "comparison": {"question_id": question_id, "request_key": key, "revision": rev,
                                   "agrees": agrees, "at": now().isoformat()}}}})
    return finish("compared", 0, agrees=agrees)


def main(argv: list[str] | None = None, *, state=None, post=None, now=None, sleep=None,
         new_key=None, revision=None, records=None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = manager_check._state_dir()
    token_file = args.token_file or state_dir / "page-token"
    suffix = "-deep" if args.deep else ""
    state_file = args.state_file or state_dir / "checks" / f"question-check{suffix}.json"
    result_file = args.result_file or state_dir / "checks" / f"question-check{suffix}-result.json"
    state = state or (lambda url: manager_check.Console(url).state())
    post = post or (lambda url, token, document: manager_check.Console(url, token).post(
        service.PROJECT_QUESTION_PATH, document))
    now = now or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    new_key = new_key or (lambda: secrets.token_hex(16))
    revision = revision or _git_revision
    records = records or _records_reader(state_dir)
    started = now()

    def finish(status: str, code: int | None = None, **more) -> int:
        print(json.dumps({"status": status, **more}, sort_keys=True))
        return _EXIT.get(status, NOT_YET) if code is None else code

    if args.compare is not None and not args.deep:
        return finish("bad_usage", 2)
    rev = revision()
    if rev is None:
        return finish("no_revision", 2)
    if args.compare is not None:
        return _compare(finish, args.project, args.compare == "agree", state_file, result_file, rev, now)
    current = state(args.url)
    if current is None:
        return finish("not_running")
    if _project_entry(current, args.project) is None:
        return finish("not_registered")

    texts = questions(args.run, args.deep)
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
            **projects, args.project: {**kept, "revision": rev, "keys": {**kept["keys"], **keys}}}})

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
            "project_id": args.project, "question": text, "request_key": keys[text],
            **({"deep": True} if args.deep else {})})
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
                        **held, "revision": rev, "keys": {**held["keys"], **{t: keys[t] for t in expired}}}}})
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

    part = TRANSCRIPTS_PART if args.deep else SPEND_PART
    verdicts = [_verdict(_shown(entry, keys[text]), posts.get(text, "").startswith("refused"),
                         records=records if args.deep or text == QUESTIONS[1] else None, part=part)
                for text in texts]
    if not args.deep:
        return _finish_result(finish, result_file, args.project, rev, now, _status(verdicts), texts, keys,
                              verdicts, posts, entry)
    comparison = _matching_comparison(state_file, args.project, rev, _shown(entry, keys[texts[0]]), keys[texts[0]])
    return _finish_result(finish, result_file, args.project, rev, now, _deep_status(verdicts[0], comparison),
                          texts, keys, verdicts, posts, entry, {"comparison": comparison})


def _finish_result(finish, result_file, project, rev, now, status, texts, keys, verdicts, posts,
                   entry, more=None) -> int:
    manager_check._write_json(result_file, {
        "project": project, "revision": rev, "checked_at": now().isoformat(), "status": status,
        "questions": [{"question": text, "request_key": keys[text], "verdict": verdict,
                       "post": posts.get(text), "shown": _shown(entry, keys[text])}
                      for text, verdict in zip(texts, verdicts)], **(more or {})})
    return finish(status, verdicts=verdicts, result_file=str(result_file))


if __name__ == "__main__":
    sys.exit(main())
