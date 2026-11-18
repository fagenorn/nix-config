"""A repeatable screenshot set of the console's sprint states (#1086).

Run: just console-screenshots [out]   (Playwright and its Chromium come from nixpkgs)

Contract:
- `STATES` names the thirty-two screens the sprint block, the finished list, the message life, the
  Spend page, the notices fold, the desk's spend figures and the controls must read well on (`tell-box-open` is
  the sprint block with its Tell box opened; `owner-check` is the sprint block with a held
  issue's owner check beside it; `spend-page` is the `/spend` page over seeded transcripts: a
  running sprint's manager session, an outside-sprint session and one workflow run, with spend on
  at least four of the last seven days; `notices-fold` is `owner/web`'s open Notices fold;
  `notice-post-open` is that fold with the owner's post control opened, and shot against a page
  that has no such control it is the same fold, which is how the before pictures are made;
  `waiting-its-turn` is a sprint whose only movement is a pull request of its holding the land
  lock, served through a stand-in forge reader, with a live delivery run of issue 12 in its `pr`
  step (a run that is not live is no holder of the sprint's), whose run line reads
  "waiting its turn to merge", not quiet;
  `manager-cannot-hear` is a running sprint whose manager session (listed, named for the sprint)
  has a transcript whose last peer-message record is one the client held and did not deliver
  (#1229), read once through the movement poll, so its line reads that the manager cannot hear
  the console; `desk-spend` is the desk page over seeded transcripts: a running sprint and a finished,
  landed one, each with a manager session on two or more days, and an outside-sprint session
  with one batch delivery run, with the sprint block, the finished line and the run line open
  so the spend figures show; `failed-start` is a sprint whose first launch was refused, with its
  card carrying the reason and the Retry and Drop the sprint buttons; `goal-open` is the sprint block of `tell-box-open` with the top
  bar's goal field focused so its box is open; `goal-near` is `goal-open` with 1900
  characters typed, so the count reads near the limit; `goal-over` is it with 2100 characters
  typed, so the count reads over the limit, Send is unavailable and the hint beside it says how much to cut (#1214);
  `inbox-card` is `owner/web`'s question card with
  two options and an owner check beside it; `question-words` and `question-refused` are
  `owner/web`'s look-check question card (Approve, Approve with one fix, Ask for changes, the last
  two marked as needing words) with Ask for changes picked: `question-words` with the words
  `LOOK_WORDS` typed in the card's words box (`WORDS_CARD`: the picked option, the words, the one
  send enabled, no refusal), `question-refused` with the one send clicked and no words
  (`REFUSED_CARD`: the picked option, an empty box, and the card's own "Say what to change."); on a
  page without the words box (`WORDS_BOX`) but with the question's options nothing is picked, typed or
  sent, which is the before picture (the question is seeded without `needs_words` where the service
  does not keep it, `NEEDS_WORDS_KEPT`), while a page with neither shows no question card at all, which
  fails; `accounts-panel` is the accounts panel opened over
  two signed-in profiles, `work-main` and `work-spare`, each with one capacity reading;
  `ask-box` is `owner/web`'s Ask box opened over one answered question (its answer, Read and Ran
  lines) and one question still working, each its own thread, the Questions fold and both
  threads opened when the page has them; a page with no `ASK_OPEN` button is the desk without
  the control, which is the before picture; `questions-closed` is the desk with `owner/web`'s
  Questions fold left closed over two threads, an older one-question thread and a newer thread
  of a question and its answered follow-up, no sprint running so the three projects are quiet
  lines; `questions-open` is that desk with the fold and the newest thread opened when the page
  has the fold, and on a page without it nothing is clicked, which is the before picture;
  `ask-goal` is the `ask-box` fixture with the Questions fold and `owner/web`'s answered
  question's thread opened and that question's Make it a goal clicked, so the goal box shows
  filled from it with `owner/web` chosen, and shot against a page without that control it is
  unclicked, which is the before picture;
  `question-read` is the desk with one answered `owner/web` question (asked 6 minutes ago,
  answered at 4; no sprint) whose stored answer is long and real-shaped: the five headings, an
  Answer of at least 1200 characters with bold, a list, inline code and two fenced blocks (the
  second quotes how a stored answer ends, its heading-like lines inside fenced code), and a
  question back with three choices; on a page with the reading panel (`READING_PANEL`) the
  Questions fold and the thread's line are clicked, so the answer reads in the main column, and
  on a page without it the fold and the thread's summary are clicked, which is the before
  picture, its reading None). On a page with the reading panel the other ask states click
  through it: `ask-box` the fold and `owner/web`'s answered thread's line (its reading is then
  `HEAD_ASK`: the field shown, the working question's line, the panel's Read line), `ask-goal`
  the fold, that line and the panel's Make it a goal, `questions-open` the fold and the newest
  thread's line; on a page without it each clicks what it always did.
  `sharing-panel` is the owner's Sharing panel opened over one invented colleague of `owner/web`
  after one admitted guest request; `guest-page` is that colleague's read-only page through a
  stand-in Serve that adds the tailnet Host and login header, refused when a page with a door
  meta (`#console-door`) is not the guest page. On the base commit's page, which has neither
  the Sharing button nor a door meta, `sharing-panel` is the desk with no panel opened and
  `guest-page` is the page the guest port served then, so a base run still writes every file.
  `WIDTHS` are the two viewport widths each is shot at. `capture`
  writes `<state>-<width>.png` for every pair, so a full run writes 64 files.
- Each state is a fresh fixture console: a registry of three projects (`owner/web`,
  `owner/api`, `owner/docs`) and an event log seeded for that state with event times relative
  to one clock reading, served by the real `ConsoleService` on a loopback port. Nothing is
  written through the service, nothing is mocked in the page, and the launcher is an inert
  stand-in that records what it is given and starts nothing (without one the view would say
  managers are not available on this host).
- The sandbox rule: every path the fixture touches lies under one temporary root, and
  `main` points `HOME`, `CLAUDE_ACCOUNTS_DIR`, `CLAUDE_CONFIG_DIR`, `XDG_STATE_HOME` and
  `XDG_CONFIG_HOME` under another for the run, so the owner's real accounts directory and real
  registry are never read or written. The temporary roots are removed after each state.
- `main(["--out", dir])` prints each written path. It returns 1 (and says so) when any shot's
  `document.documentElement.scrollWidth` exceeds its width; when any sprint's "what it is
  doing now" sentence is squeezed (it starts above its title's bottom, is narrower than the
  head's line or than the title, is taller than two lines, or is clipped); when a shot shows a
  jargon label (a "Detail" or "More" fold, an "Approved version" message row that is not
  sent or not picked up, or one of the review's phrases in the rendered text: "on track",
  "stated" before an age, "withdraw", "nudge", "stop or", "would do differently"); or when a
  `tell-box-open` shot does not show the open Tell box (the textarea, the Send button and the
  pick-up hint, with the label, the field and the hint not overlapping and the field as wide as
  the sprint block's content, `OPEN_TELL`); or when an `ask-box` shot of a page that has the `ASK_OPEN`
  button does not show `owner/web`'s open field, its working question and its answered question's
  Read line (`OPEN_ASK`, or `HEAD_ASK` on a page with the reading panel); or when a
  `question-read` shot on a page with the panel does not read `READ_SHOWN` (`READ_READING`: the
  panel in the main column at the column's full width, the question once (counted from the question the shot was seeded with, an argument of
  the script), the answer holding bold,
  a list, inline code and a block of code, the call-out last in its row after the answer, three
  choices visible); or when a `questions-open` shot reads neither `OPEN_THREAD` (the fold
  opened, the follow-up's Read line shown, a follow-up button visible) nor `BASE_THREAD` (a page
  without the fold that still lists the follow-up and its answer, the before picture), or when a `question-words` or `question-refused` shot's reading is not its `WORDS_CARD` or
  `REFUSED_CARD`; or when an `ask-goal` shot's reading is not `FILLED_GOAL` (the box
  closed, the wrong text or project, or the field clipping the filled text); or when any
  shot has a visible project line whose Ask a question button sits on another row than its Give it
  a goal button (their vertical centres differ by more than 4 px, `ACTS_ROW`); or when any shot is not taken from the top of the
  page (`window.scrollY` is not 0 right before its full-page capture); or when any shot has a
  rendered, visible button, input, textarea, select, `btn-` link or `btn-` summary under 32 px
  tall (`SHORT_CONTROLS`, read after the state is drawn). It returns 2 with a one-line
  reason when Playwright or Chromium is missing, else 0.
- Real-answer mode: `main(["--out", dir, "--question", TEXT, "--answer-file", PATH])` (both or
  neither; one alone exits 2) shoots only `question-read`, seeded with that question and the
  file's UTF-8 text as the stored answer, so it writes exactly `question-read-1440.png` and
  `question-read-480.png`. A real answer need not hold every formatting kind or three choices, so
  its shot passes when its reading is None or its first two members are `(True, 1)` (in the main
  column, the question once); any other reading fails with the same line. The jargon count is not
  checked (the text is the session's, not the page's labels); every other check still applies. Playwright is imported inside `capture` only,
  so the fixture half of this module needs nothing beyond the standard library.
- The before pictures are the base commit's service, view and page together: this module imports
  nothing from `agent_tools` that the base commit lacks, so running it with `PYTHONPATH` at an
  archive of the base commit's `python/` (`git archive <base> python`) serves the base page over the
  same fixtures; swapping in only the base `page.html` is not a before picture, since the head view's
  `questions` object draws nothing on it. The after pictures run with `PYTHONPATH` at the branch.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_tools.console import capacity, event_log, manager, sessions, signin
from agent_tools.console.event_log import SHARING_COLLEAGUE, SHARING_TAILNET, EventLog
from agent_tools.console.movement import LocalReading, PullRequest
from agent_tools.console.service import ConsoleService
from agent_tools.console.sprints import TELL_MINUTE_TEXT, Question

from .console_test_support import hook_body, write_registry

STATES = ("live-several", "waiting-on-you", "stuck", "tell-box-open", "message-sent",
          "message-picked-up", "message-replied", "message-not-picked-up", "finished-list",
          "nothing-running", "waiting-its-turn", "manager-cannot-hear", "owner-check", "spend-page", "notices-fold",
          "notice-post-open", "desk-spend", "failed-start", "goal-open", "goal-near", "goal-over",
          "inbox-card", "question-words", "question-refused", "accounts-panel", "ask-box",
          "questions-closed", "questions-open", "ask-goal", "question-read", "sharing-panel",
          "guest-page")
WIDTHS = (1440, 480)
HEIGHT = 900
GOAL_NEAR_CHARS = 1900
GOAL_OVER_CHARS = 2100
MINUTE = 60.0
PROJECTS = ("owner/web", "owner/api", "owner/docs")
TRACKER_URL = "https://github.com/owner/web/issues"
TAILNET = "desk.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SHARING_STATES = ("sharing-panel", "guest-page")
TELL_TEXT = "leave the importer's schema alone"
REPLY_TEXT = "kept the schema; moved the change to the reader"
MILESTONES = {"Add resumable uploads": "the upload form",
              "Fix the settings page": "the settings form",
              "Keep the importer fast": "the batch reader",
              "Retire the old exporter": "the last export path",
              "Try a new cache": "the cache layer"}
OPEN_TELL = (True, "Send", TELL_MINUTE_TEXT, True)
ASK_ANSWERED_QUESTION = "What does the build check?"
ASK_WORKING_QUESTION = "Is the importer deployed on this host?"
ASK_READ_LINE = "Read: flake.nix, lib/helpers.nix"
# Short on purpose: the open goal field shows three 22 px lines, so the filled question, a blank
# line and this summary must each fit one line of its ~380 px width.
ASK_ANSWER_SUMMARY = "It builds the three hosts and their checks."
ASK_OPEN = 'li[data-project="owner/web"] button.ask-open'
ASK_FOLD = 'details[data-key="questions:owner/web"] > summary'
ASK_THREADS = tuple(f'details[data-key="thread:owner/web:{qid}"] > summary'
                    for qid in ("1177a2", "1177a1"))
OPEN_ASK = (True, "Working on it", ASK_READ_LINE)
ASK_GOAL = 'details[data-key="thread:owner/web:1177a1"] button.ask-goal'
FILLED_GOAL = (True, ASK_ANSWERED_QUESTION + "\n\n" + ASK_ANSWER_SUMMARY, "owner/web", True)
THREAD_QUESTION = "What does the build check?"
FOLLOW_QUESTION = "Does it build the darwin hosts too?"
FOLLOW_READ_LINE = "Read: .github/workflows/ci.yaml"
NEWEST_THREAD = 'details[data-key="thread:owner/web:1178a2"] > summary'
# (the Questions fold is open, the follow-up's Read line, a follow-up button shows); the base
# page has no fold and lists the follow-up as a question of its own.
OPEN_THREAD = (True, FOLLOW_READ_LINE, True)
BASE_THREAD = (False, FOLLOW_READ_LINE, False)
DESK_OUTSIDE = "outside-1136"
DEAF_MANAGER = "manager-1229"
READING_PANEL = "section#reading"
HEAD_ASK = (True, ASK_WORKING_QUESTION, ASK_READ_LINE)
READ_QUESTION = "What was done in the last 7 days, and what is in production?"
READ_FENCED_LINE = "Read: git log --since=7.days"
READ_CHOICES = ("Check the deployed version on the host", "Open the release notes",
                "Leave production as it is")
# The answer of the owner's own question, as a session writes it: the five headings, a long Answer
# part with bold, a list, inline code and two fenced blocks (the second quotes how a stored answer
# ends, so its heading-like lines sit inside fenced code), and a question back with three choices.
READ_ANSWER = "\n".join((
    "Answer: **Seven days of work reached the main branch, and production runs the newest release "
    "of it.** The work is mostly in the console and the delivery workflow, and nothing in these "
    "seven days is waiting on a deploy.",
    "",
    "What changed in the last 7 days, newest first:",
    "",
    "- **Answers read in the main column.** An answered question opens beside the sprint block "
    "instead of folded under the project line, with its question once at the top.",
    "- **Choices under a question back.** A question for you now carries its choices as buttons "
    "under the answer, and the answer's own bold, lists and `code` render as text styles.",
    "- **A question session reads the project.** It runs its declared reads inside `devenv` and "
    "answers in plain words.",
    "- **Spend on the desk.** The desk shows each project's spend for the week next to its line.",
    "- **Fewer stuck sprints.** A sprint whose manager went quiet is named on the desk with the "
    "step it last reached.",
    "",
    "The commits behind that list, from `git log --oneline` on the main branch:",
    "",
    "```",
    "614aa661 Render an answer's bold, lists and code as text styles",
    "6155d362 Open an answered question in the main column with its choices last",
    "8d9f9a34 Count a code fence that opens on a heading line when splitting an answer",
    "6d39af9f Carry a question back's choices and name the answer's formatting in the prompt",
    "1cca6b21 Merge the question session that reads the project",
    "```",
    "",
    "Production is the release the host last switched to, which is the newest tag on the main "
    "branch. The release before it is two weeks old, so every change above reached production in "
    "one step when that tag was cut.",
    "",
    "A stored answer now ends like this, so a reader can tell the parts apart:",
    "",
    "```",
    READ_FENCED_LINE,
    "Question for you: none",
    "```",
    "Read: flake.nix, python/agent_tools/console/page.html, the project's release tags",
    "Ran: git log --oneline",
    "Could not find out: none",
    "Question for you: Which step should I take next?",
    *(f"- {choice}" for choice in READ_CHOICES)))
READ_READING = """((needle) => {
  const panel = document.querySelector('#reading');
  const main = document.querySelector('main');
  if (!panel || !main) return [false, 0, false, false, 0];
  const style = getComputedStyle(main);
  const content = main.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const inMain = panel.getClientRects().length > 0 && main.contains(panel)
    && panel.getBoundingClientRect().width >= content - 1;
  const text = panel.innerText;
  let count = 0;
  for (let at = text.indexOf(needle); at >= 0; at = text.indexOf(needle, at + needle.length)) count++;
  const answer = panel.querySelector('.ask-answer');
  const formatted = Boolean(answer && answer.querySelector('strong') && answer.querySelector('li')
    && answer.querySelector('code.md-code') && answer.querySelector('pre'));
  const callout = panel.querySelector('.ask-callout');
  const calloutLast = Boolean(callout && answer && callout.parentElement.lastElementChild === callout
    && (answer.compareDocumentPosition(callout) & Node.DOCUMENT_POSITION_FOLLOWING));
  const choices = Array.from(panel.querySelectorAll('.ask-callout button.ask-choice')).filter(
    (button) => button.getClientRects().length > 0).length;
  return [inMain, count, formatted, calloutLast, choices];
})"""
READ_SHOWN = (True, 1, True, True, 3)
READING_GOAL = "#reading button.ask-goal"
READ_BASE_THREAD = 'details[data-key="thread:owner/web:1226a1"] > summary'
LOOK_QUESTION = "Does the new line read right?"
LOOK_OPTIONS = ["Approve", "Approve with one fix", "Ask for changes"]
LOOK_WORDS = "Make the first line shorter and keep the second one as it is."
WORDS_BOX = "textarea.words-text"
LOOK_OPTION = ".lead ul.opts li:nth-child(3) button.opt"
CARD_SEND = ".lead button.send"
# The raised card's picked option, the words box's text, whether its one send is enabled and the
# refusal line beside the send (None when the card shows none).
CARD_READING = """(() => {
  const card = document.querySelector('.lead');
  if (!card) return [null, null, null, null];
  const pick = card.querySelector('button.opt[aria-pressed="true"] .ot');
  const words = card.querySelector('textarea.words-text');
  const send = card.querySelector('button.send');
  const notice = Array.from(card.querySelectorAll('.act span')).map(
    (span) => span.textContent.trim()).filter((text) => text.startsWith('Say what'));
  return [pick ? pick.textContent.trim() : null, words ? words.value : null,
          Boolean(send && !send.disabled), notice.length ? notice[0] : null];
})()"""
WORDS_CARD = ("Ask for changes", LOOK_WORDS, True, None)
REFUSED_CARD = ("Ask for changes", "", True, "Say what to change.")
# A service whose questions have no `needs_words` rejects the key and discards the question, so the
# look-check question is seeded with it only where the service keeps it (the base commit's is not).
NEEDS_WORDS_KEPT = "needs_words" in {field.name for field in fields(Question)}
READ_SESSION = "7c2f9d4e-1a8b-4e63-b5d0-9f3a6c1e8b27"


def thread_line(qid: str) -> str:
    return f'button.thread-open[data-key="thread:owner/web:{qid}"]'


class Unavailable(Exception):
    """Playwright or its Chromium is not here; the message is the one-line reason."""


@dataclass(frozen=True)
class Fixture:
    root: Path
    store: Path
    registry: Path
    token: Path
    secrets: Path
    home: Path
    accounts: Path
    config: Path
    state: Path
    projects: tuple[Path, ...]
    holding: tuple[int, ...] = ()
    deaf: bool = False


@dataclass(frozen=True)
class Shot:
    state: str
    width: int
    path: Path
    scroll_width: int
    squeezed: int = 0
    jargon: int = 0
    tell: tuple[bool, str | None, str | None, bool] | None = None
    scroll_y: float = 0.0
    short: tuple[str, ...] = ()
    ask: tuple[bool, str | None, str | None] | None = None
    goal: tuple[bool, str | None, str | None, bool | None] | None = None
    acts: tuple[str, ...] = ()
    thread: tuple[bool, str | None, bool] | None = None
    reading: tuple[bool, int, bool, bool, int] | None = None
    card: tuple[str | None, str | None, bool | None, str | None] | None = None


def sandbox_environ(root: Path) -> dict[str, str]:
    root = Path(root)
    return {"HOME": str(root / "home"),
            "CLAUDE_ACCOUNTS_DIR": str(root / "accounts"),
            "CLAUDE_CONFIG_DIR": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "xdg-config")}


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds")


class _Seed:
    """One event log whose every row carries the time its writer chose, `ago` seconds before now."""

    def __init__(self, log: EventLog, at: list[str], now_s: float):
        self.log = log
        self._at = at
        self.now_s = now_s
        self.count = 0

    def put(self, ago: float, kind: str, project: str, payload: Mapping):
        self._at[0] = _iso(self.now_s - ago)
        return self.log.append([(kind, project, payload)])[0]

    def sprint(self, project: str, title: str, *, started: float, report: float | None = None,
               landed: bool = False, asks: bool = False, close: float | None = None,
               stop: float | None = None, held: bool = False,
               look: bool = False) -> tuple[str, str]:
        """One approved sprint with a started manager; returns `(sprint_id, goal)`."""
        self.count += 1
        sid = f"{self.count:016x}"
        goal = f"{title}."
        base = {"sprint_id": sid, "goal": goal}
        self.put(started, "goal.stated", project, base)
        self.put(started - 10, "manager.started", project, {
            "sprint_id": sid, "profile": "work-main",
            "session_name": manager.session_name(project, sid)})
        self.put(started - 40, "brief.sent", project, {**base, "version": 1, "brief": {
            "title": title, "done": f"{title}, merged and checked.",
            "slices": ["the first slice", "the second slice"], "excluded": [],
            "risks": ["a partial write"], "asks": []}})
        approved = self.put(started - 60, "brief.approved", project, {**base, "version": 1})
        self.put(started - 70, "sprint.read", project, {"sprint_id": sid, "through": approved.seq})
        issues = ([{"issue": 12, "stage": "landed"}, {"issue": 13, "stage": "landed"}] if landed
                  else [{"issue": 11, "stage": "held"}, {"issue": 12, "stage": "building"},
                        {"issue": 13, "stage": "queued"}] if held
                  else [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "queued"}])
        if report is not None:
            self.put(report, "sprint.reported", project, {**base, "report": {
                "status": "the first slice is in review", "phase": "running",
                "milestone": MILESTONES[title], "tracker_url": TRACKER_URL, "issues": issues,
                "inbox": [], "next": "merge the first slice"}})
        if asks:
            self.put(MINUTE * 4, "questions.asked", project, {**base, "blocker": False, "questions": [{
                "question": "Which store should the checkpoint use?",
                "blocks": "the first slice",
                "options": ["the existing database", "a new file"],
                "recommended": "the existing database"}]})
        if look:
            self.put(MINUTE * 4, "questions.asked", project, {**base, "blocker": False, "questions": [{
                "question": LOOK_QUESTION, "blocks": "the first slice",
                "options": LOOK_OPTIONS, "recommended": LOOK_OPTIONS[0],
                **({"needs_words": LOOK_OPTIONS[1:]} if NEEDS_WORDS_KEPT else {})}]})
        if close is not None:
            self.put(close, "sprint.closed", project, {**base, "closing": {
                "summary": f"{title} landed.\nBoth slices merged and the checks are green.",
                "issues": [{"issue": 12, "stage": "landed"}, {"issue": 13, "stage": "landed"},
                           {"issue": 14, "stage": "dropped"}],
                "differently": "Would split the second slice sooner."}})
        if stop is not None:
            self.put(stop, "sprint.stop_requested", project, base)
            self.put(stop - 20, "manager.stopped", project, {"sprint_id": sid})
        return sid, goal

    def failed_start(self, project: str, title: str, ago: float) -> tuple[str, str]:
        """One sprint whose first launch was refused: a stated goal and a `manager.failed`."""
        self.count += 1
        sid = f"{self.count:016x}"
        goal = f"{title}."
        self.put(ago, "goal.stated", project, {"sprint_id": sid, "goal": goal})
        self.put(ago - 10, "manager.failed", project, {"sprint_id": sid, "reason": (
            "Workspace not trusted. Run `claude` in /home/owner/Projects/web once and accept "
            "the trust prompt, then retry.")})
        return sid, goal

    def check(self, project: str, issue: int, ago: float) -> None:
        """One open `verify-ask` inbox item on `issue`, which blocks none of the manager's work."""
        self.put(ago, "inbox.seen", project, {
            "key": f"{project}#{issue}/9001", "project_id": project, "repo": project,
            "issue": issue, "comment_id": 9001,
            "url": f"https://github.com/{project}/issues/{issue}#issuecomment-9001",
            "reason": "verify-ask", "kind": "manual-check",
            "question": "Do the before and after pictures read well?", "detail": "",
            "check_id": "", "questions": [], "items": [],
            "answers": ["passed", "failed", "note"], "paid": False, "confirm": "",
            "answered": False, "held_work": 1, "blocking": [], "version": "v1"})

    def account(self, name: str, week: float) -> None:
        """A signed-in profile with one capacity reading whose week window is `week` used."""
        self._at[0] = _iso(self.now_s)
        reading = capacity.parse_report({
            "http_status": 200, "status": "allowed", "reset": int(self.now_s) + 86400, "binding": None,
            "claim": None, "account": None, "session_id": None,
            "windows": {"7d": {"status": "allowed", "utilization": week,
                               "reset": int(self.now_s) + 86400}}})
        self.log.append(capacity.report_entries(reading, name))
        self.log.append([signin.entry(name, signin.Status("signed_in", None))])

    def message(self, project: str, sid: str, goal: str, *, sent: float, read: float | None = None,
                replied: float | None = None) -> None:
        base = {"sprint_id": sid}
        said = self.put(sent, "sprint.messaged", project, {**base, "goal": goal, "text": TELL_TEXT})
        if read is not None:
            self.put(read, "sprint.read", project, {**base, "through": said.seq})
        if replied is not None:
            self.put(replied, "sprint.answered", project,
                     {**base, "message": said.seq, "reply": REPLY_TEXT})


def _seed_state(seed: _Seed, state: str, web_root: str = "",
                read: tuple[str, str] = (READ_QUESTION, READ_ANSWER)) -> tuple[str, ...]:
    """Seed the events of `state`; returns the sprint ids whose transcripts the state writes."""
    web, api = PROJECTS[0], PROJECTS[1]
    if state == "live-several":
        seed.sprint(api, "Keep the importer fast", started=60 * MINUTE, report=45 * MINUTE)
        seed.sprint(api, "Retire the old exporter", started=5 * 60 * MINUTE,
                    report=3 * 60 * MINUTE, landed=True, close=2 * 60 * MINUTE)
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE,
                    asks=True)
        seed.sprint(web, "Fix the settings page", started=20 * MINUTE, report=2 * MINUTE)
    elif state == "waiting-on-you":
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE,
                    asks=True)
    elif state == "stuck":
        seed.sprint(web, "Add resumable uploads", started=60 * MINUTE, report=45 * MINUTE)
    elif state == "manager-cannot-hear":
        sid, _ = seed.sprint(web, "Add resumable uploads", started=60 * MINUTE,
                             report=45 * MINUTE)
        seed.put(MINUTE, sessions.SEEN, web, {
            "session_id": DEAF_MANAGER, "cwd": web_root, "repo": web_root, "state": "working",
            "name": manager.session_name(web, sid)})
    elif state == "failed-start":
        seed.failed_start(web, "Add resumable uploads", 3 * MINUTE)
    elif state in SHARING_STATES:
        seed.put(3 * MINUTE, SHARING_TAILNET, None, {"tailnet": TAILNET})
        seed.put(2 * MINUTE, SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": [web]})
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE)
        seed.sprint(api, "Keep the importer fast", started=60 * MINUTE, report=45 * MINUTE)
    elif state == "waiting-its-turn":
        seed.sprint(web, "Add resumable uploads", started=60 * MINUTE, report=45 * MINUTE)
    elif state in ("tell-box-open", "goal-open", "goal-near", "goal-over"):
        seed.sprint(web, "Add resumable uploads", started=20 * MINUTE, report=2 * MINUTE)
    elif state.startswith("message-"):
        sid, goal = seed.sprint(web, "Add resumable uploads", started=20 * MINUTE,
                                report=2 * MINUTE)
        if state == "message-sent":
            seed.message(web, sid, goal, sent=30)
        elif state == "message-picked-up":
            seed.message(web, sid, goal, sent=90, read=40)
        elif state == "message-replied":
            seed.message(web, sid, goal, sent=3 * MINUTE, read=2.5 * MINUTE, replied=MINUTE)
        else:
            seed.message(web, sid, goal, sent=6 * MINUTE)
    elif state == "finished-list":
        seed.sprint(web, "Add resumable uploads", started=40 * MINUTE, report=2 * MINUTE)
        seed.sprint(api, "Retire the old exporter", started=5 * 60 * MINUTE,
                    report=3 * 60 * MINUTE, landed=True, close=2 * 60 * MINUTE)
        seed.sprint(web, "Try a new cache", started=4 * 60 * MINUTE, report=3.5 * 60 * MINUTE,
                    stop=3 * 60 * MINUTE)
    elif state == "owner-check":
        seed.sprint(web, "Add resumable uploads", started=20 * MINUTE, report=2 * MINUTE,
                    held=True)
        seed.check(web, 11, 3 * MINUTE)
    elif state == "inbox-card":
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE,
                    asks=True)
        seed.check(web, 11, 3 * MINUTE)
    elif state in ("question-words", "question-refused"):
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE,
                    look=True)
    elif state == "accounts-panel":
        seed.account("work-main", 0.4)
        seed.account("work-spare", 0.9)
    elif state in ("notices-fold", "notice-post-open"):
        seed.sprint(web, "Add resumable uploads", started=20 * MINUTE, report=2 * MINUTE)
        sid, goal = seed.sprint(web, "Fix the settings page", started=20 * MINUTE,
                                report=2 * MINUTE)
        seed.put(90, "notice.posted", web, {"sprint_id": sid, "goal": goal, "notice": {
            "kind": "claim", "text": "reworking the settings form",
            "what": "python/agent_tools/console/page.html", "until": "the form lands"}})
        seed.put(30, "notice.posted", web, {"poster": "owner", "notice": {
            "kind": "heads-up", "text": "routes are frozen until Friday"}})
    elif state in ("ask-box", "ask-goal"):
        seed.put(3 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1177a1", "question": ASK_ANSWERED_QUESTION,
            "profile": "work-main", "session_id": "5b1f0c2e-7a4d-4e8b-9c3a-1d2e3f4a5b6c"})
        seed.put(2 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1177a1", "outcome": "answered",
            "answer": f"Answer: {ASK_ANSWER_SUMMARY}\n{ASK_READ_LINE}\nRan: just build\n"
                      "Could not find out: none\nQuestion for you: none"})
        seed.put(20, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1177a2", "question": ASK_WORKING_QUESTION,
            "profile": "work-main", "session_id": "8d3e9a40-2c6b-4f17-a5d8-0e9f8a7b6c5d"})
    elif state in ("questions-closed", "questions-open"):
        session = {"older": "3c7a1e90-5d2b-4f68-8a14-b7e0c9d2f6a1",
                   "first": "a91d4f27-6b3e-4c85-9e02-d5f1a8b3c764",
                   "follow": "e2b86c13-0f9a-4d57-b3a8-61c4d7e9f052"}
        answer = ("Answer: {text}\n{read}\nRan: none\nCould not find out: none\n"
                  "Question for you: none")
        seed.put(30 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1178a1", "question": "Which hosts does the flake define?",
            "profile": "work-main", "session_id": session["older"]})
        seed.put(29 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1178a1", "outcome": "answered",
            "answer": answer.format(text="Three: two Macs and one WSL box.",
                                    read="Read: flake.nix")})
        seed.put(10 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1178a2", "question": THREAD_QUESTION,
            "profile": "work-main", "session_id": session["first"]})
        seed.put(9 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1178a2", "outcome": "answered",
            "answer": answer.format(text="It evaluates the Linux host and the agent tests.",
                                    read=ASK_READ_LINE)})
        seed.put(4 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1178a3", "question": FOLLOW_QUESTION, "thread_id": "1178a2",
            "profile": "work-main", "session_id": session["follow"]})
        seed.put(3 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1178a3", "outcome": "answered",
            "answer": answer.format(text="No; CI evaluates the Linux host and does not build the Macs.",
                                    read=FOLLOW_READ_LINE)})
    elif state == "question-read":
        seed.put(6 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1226a1", "question": read[0],
            "profile": "work-main", "session_id": READ_SESSION})
        seed.put(4 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1226a1", "outcome": "answered", "answer": read[1]})
    elif state == "spend-page":
        return (seed.sprint(web, "Add resumable uploads", started=20 * MINUTE,
                            report=2 * MINUTE)[0],)
    elif state == "desk-spend":
        running = seed.sprint(web, "Add resumable uploads", started=20 * MINUTE,
                              report=2 * MINUTE)[0]
        ended = seed.sprint(api, "Retire the old exporter", started=5 * 60 * MINUTE,
                            report=3 * 60 * MINUTE, landed=True, close=2 * 60 * MINUTE)[0]
        seed.put(MINUTE, sessions.SEEN, web, {
            "session_id": DESK_OUTSIDE, "cwd": web_root, "repo": web_root,
            "state": "working", "name": "importer run"})
        return running, ended
    elif state != "nothing-running":
        raise ValueError(f"unknown state {state!r}")
    return ()


def _transcript(lines: Sequence[Mapping]) -> bytes:
    return b"".join((json.dumps(line) + "\n").encode() for line in lines)


class _Assistant:
    """Assistant transcript lines, each with its own message id, `days_ago` whole days before now."""

    def __init__(self, now_s: float):
        self.now_s = now_s
        self.count = 0

    def __call__(self, sid: str, cwd: str, days_ago: int, input: int, output: int) -> dict:
        self.count += 1
        when = datetime.fromtimestamp(self.now_s, timezone.utc) - timedelta(days=days_ago)
        return {"type": "assistant", "sessionId": sid, "cwd": cwd,
                "timestamp": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "message": {"id": f"msg-{self.count:04d}", "model": "claude-sonnet-4-6",
                            "usage": {"input_tokens": input, "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": input * 8,
                                      "output_tokens": output}}}


def _write_spend(fixture: Fixture, now_s: float, sprint_id: str) -> None:
    """Transcripts for the Spend page: a sprint's manager, an outside-sprint session, a run.

    Every assistant line has its own message id, the registered root as its `cwd`, and a time
    0 to 6 whole UTC days before `now_s`, so at least four of the last seven days have spend.
    """
    web, api = (str(path) for path in fixture.projects[:2])
    assistant = _Assistant(now_s)

    msid, osid = "manager-1135", "outside-1135"
    slug = fixture.config / "projects" / "-web"
    run = slug / msid / "subagents" / "workflows" / "wf_1"
    run.mkdir(parents=True, exist_ok=True)
    title = {"type": "custom-title", "customTitle": manager.session_name("owner/web", sprint_id),
             "sessionId": msid}
    (slug / f"{msid}.jsonl").write_bytes(_transcript([title] + [
        assistant(msid, web, ago, 40_000 + 9_000 * ago, 3_000 + 400 * ago) for ago in range(7)]))
    other = fixture.config / "projects" / "-api"
    other.mkdir(parents=True, exist_ok=True)
    (other / f"{osid}.jsonl").write_bytes(_transcript([
        assistant(osid, api, ago, 25_000 + 5_000 * ago, 2_000) for ago in (0, 2, 3, 5)]))
    (run / "journal.jsonl").write_bytes(_transcript([
        {"type": "started", "agentId": "a1", "label": "plan", "phase": "Plan"},
        {"type": "started", "agentId": "a2", "label": "impl-1", "phase": "Tasks"}]))
    (run / "agent-a1.jsonl").write_bytes(_transcript([
        assistant(msid, web, ago, 60_000, 5_000) for ago in (1, 4)]))
    (run / "agent-a2.jsonl").write_bytes(_transcript([
        assistant(msid, web, ago, 90_000, 8_000) for ago in (0, 1, 2, 5)]))


def _write_desk_spend(fixture: Fixture, now_s: float, running: str, ended: str) -> None:
    """Transcripts for the desk page: both sprints' managers and an outside session's batch run.

    The run `wf_9` sits under the outside-sprint session `outside-1136`; its journal opens a
    `facts-901` agent and an `acquire-901` agent, so the delivery reads as issue 901 planning.
    """
    web, api = (str(path) for path in fixture.projects[:2])
    assistant = _Assistant(now_s)
    projects = fixture.config / "projects"
    for slug, root, project, sprint_id, msid, days in (
            ("-web", web, "owner/web", running, "manager-1136-web", range(5)),
            ("-api", api, "owner/api", ended, "manager-1136-api", (1, 2, 4))):
        (projects / slug).mkdir(parents=True, exist_ok=True)
        title = {"type": "custom-title", "sessionId": msid,
                 "customTitle": manager.session_name(project, sprint_id)}
        (projects / slug / f"{msid}.jsonl").write_bytes(_transcript([title] + [
            assistant(msid, root, ago, 30_000 + 7_000 * ago, 2_500 + 300 * ago)
            for ago in days]))
    run = projects / "-web" / DESK_OUTSIDE / "subagents" / "workflows" / "wf_9"
    run.mkdir(parents=True, exist_ok=True)
    (run / "journal.jsonl").write_bytes(_transcript([
        {"type": "started", "agentId": "f1", "label": "facts-901", "phase": "Intake"},
        {"type": "started", "agentId": "q1", "label": "acquire-901", "phase": "Deliver"}]))
    (run / "agent-f1.jsonl").write_bytes(_transcript([
        assistant(DESK_OUTSIDE, web, ago, 50_000, 4_000) for ago in (0, 2)]))
    (run / "agent-q1.jsonl").write_bytes(_transcript([
        assistant(DESK_OUTSIDE, web, ago, 80_000, 6_000) for ago in (0, 1, 3)]))


def _write_held_manager(fixture: Fixture, now_s: float) -> None:
    """The deaf manager's transcript: a delivered peer message, then the one the client held."""
    slug = fixture.config / "projects" / "-web"
    slug.mkdir(parents=True, exist_ok=True)
    (slug / f"{DEAF_MANAGER}.jsonl").write_bytes(_transcript([
        {"type": "user", "origin": {"kind": "peer"}, "message": {"content": "carry on"}},
        {"type": "system", "content": "Held peer message from the console, not delivered until "
                                      "you approve it at this terminal"}]))


def build_fixture(root: Path, state: str, now_s: float, *,
                  read: tuple[str, str] = (READ_QUESTION, READ_ANSWER)) -> Fixture:
    root = Path(root)
    environ = sandbox_environ(root)
    home, accounts, config, state_dir = (
        Path(environ[name]) for name in ("HOME", "CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR",
                                         "XDG_STATE_HOME"))
    projects = tuple(root / "projects" / name.split("/")[1] for name in PROJECTS)
    for directory in (home, accounts, config, state_dir, config / "sessions", *projects):
        directory.mkdir(parents=True, exist_ok=True)
    console = state_dir / "console"
    fixture = Fixture(
        root=root, store=console / "events.sqlite3", registry=state_dir / "fleet" / "registry.json",
        token=console / "token", secrets=console / "sprint-secrets", home=home,
        accounts=accounts, config=config, state=state_dir, projects=projects,
        holding=(12,) if state == "waiting-its-turn" else (), deaf=state == "manager-cannot-hear")
    write_registry(fixture.registry, [
        {"project_id": name, "root": str(path)} for name, path in zip(PROJECTS, projects)])
    at = [_iso(now_s)]
    log = EventLog(fixture.store, clock=lambda: at[0])
    try:
        sprint_ids = _seed_state(_Seed(log, at, now_s), state, str(projects[0]), read=read)
    finally:
        log.close()
    if state == "accounts-panel":
        for name in ("work-main", "work-spare"):
            (accounts / "profiles" / name).mkdir(parents=True, exist_ok=True)
    if state == "manager-cannot-hear":
        _write_held_manager(fixture, now_s)
    if state == "spend-page":
        _write_spend(fixture, now_s, sprint_ids[0])
    elif state == "desk-spend":
        _write_desk_spend(fixture, now_s, *sprint_ids)
    return fixture


def _seed_lock_run(service: ConsoleService, fixture: Fixture, now_s: float) -> None:
    """A live delivery run whose issue 12 sits in the `pr` (lock) step, so the holder's issue is live.
    The journal last moved with the sprint's report, so only the held lock moves the sprint."""
    root = str(fixture.projects[0])
    body = hook_body("session start", cwd=root)
    service.ingest_hook(body)
    sid = json.loads(body)["session_id"]
    run = fixture.config / "projects" / "-web" / sid / "subagents" / "workflows" / "wf_l1"
    run.mkdir(parents=True, exist_ok=True)
    (run / "journal.jsonl").write_bytes(_transcript([
        {"type": "started", "agentId": "a1", "label": "setup", "phase": "Setup"},
        {"type": "result", "agentId": "a1", "result": {"branch": "issue-12-upload-form"}},
        {"type": "started", "agentId": "a2", "label": "pr", "phase": "Ship"}]))
    moved = now_s - 45 * MINUTE
    os.utime(run / "journal.jsonl", (moved, moved))
    service.poll_deliveries()


def start_service(fixture: Fixture, now_s: float, launches: list | None = None, *,
                  guest: bool = False) -> ConsoleService:
    def launcher(launch: manager.Launch) -> None:
        if launches is not None:
            launches.append(launch)

    forge: dict = {}
    if fixture.holding or fixture.deaf:
        forge = {"local_reader": lambda root, pattern: LocalReading((), False)}
    if fixture.holding:
        forge["pull_reader"] = lambda slug, pattern, *, cancelled: (
            PullRequest(7, frozenset(fixture.holding), False, None, True),)
    service = ConsoleService(
        fixture.store, fixture.registry, port=0, session_dirs=lambda: [fixture.config / "sessions"],
        profile_dirs=lambda: sorted((fixture.accounts / "profiles").glob("*")), token_path=fixture.token, sprint_secrets=fixture.secrets,
        session_poll_seconds=3600, nudger=lambda nudge: None, launcher=launcher,
        activity=lambda root: None,
        slug_of=(lambda root: "owner/web") if fixture.holding else (lambda root: None),
        branch_pattern_of=lambda repo: "issue-<num>-<slug>" if fixture.holding else None,
        dispatch=lambda job: job(), guest_port=0 if guest else None,
        repo_of=lambda cwd: cwd, ping_log=lambda: None, **forge)
    service.start()
    service.poll_spend()
    if fixture.holding:
        _seed_lock_run(service, fixture, now_s)
        service.poll_movement()
    elif fixture.deaf:
        service.poll_movement()
    return service


def _guest_get(address: tuple[str, int], path: str = "/", *, host: str | None = TAILNET,
               login: str | None = COLLEAGUE) -> http.client.HTTPResponse:
    """One GET to `address` carrying the tailnet Host and the colleague's login header."""
    headers = {}
    if host is not None:
        headers["Host"] = host
    if login is not None:
        headers["Tailscale-User-Login"] = login
    connection = http.client.HTTPConnection(*address, timeout=10)
    connection.request("GET", path, headers=headers)
    return connection.getresponse()


class _Serve:
    """A loopback stand-in for Tailscale Serve in front of the guest port.

    Each GET is forwarded to `guest_address` with `Host: TAILNET` and `Tailscale-User-Login:
    COLLEAGUE`, any incoming `Tailscale-*`, `X-Forwarded-For` and `Host` dropped; the status and
    headers are copied and the body is streamed until EOF, each chunk flushed (the view stream
    is event-stream). `.address` is where a browser reads it; `.close()` stops it.
    """

    def __init__(self, guest_address: tuple[str, int]):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                kept = {name: value for name, value in self.headers.items()
                        if not name.lower().startswith("tailscale-")
                        and name.lower() not in ("x-forwarded-for", "host")}
                connection = http.client.HTTPConnection(*guest_address, timeout=3600)
                try:
                    connection.request("GET", self.path, headers={
                        **kept, "Host": TAILNET, "Tailscale-User-Login": COLLEAGUE})
                    response = connection.getresponse()
                    self.send_response_only(response.status)
                    for name, value in response.getheaders():
                        self.send_header(name, value)
                    self.end_headers()
                    while chunk := response.read1(65536):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    connection.close()
                    self.close_connection = True

            def log_message(self, format: str, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.address: tuple[str, int] = self._server.server_address[:2]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def capture(out: Path, states: Sequence[str] = STATES, widths: Sequence[int] = WIDTHS, *,
            read: tuple[str, str] = (READ_QUESTION, READ_ANSWER)) -> list[Shot]:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as error:
        raise Unavailable("playwright is not installed") from error
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    taken: list[Shot] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Error as error:
            raise Unavailable(f"no Chromium to launch: {' '.join(str(error).split())[:120]}") from error
        try:
            for state in states:
                with tempfile.TemporaryDirectory(prefix="console-shots-") as tmp:
                    now_s = datetime.now(timezone.utc).timestamp()
                    service = start_service(
                        build_fixture(Path(tmp).resolve(), state, now_s, read=read), now_s,
                        guest=state in SHARING_STATES)
                    serve = None
                    try:
                        host, port = service.address
                        if state == "sharing-panel":
                            _guest_get(service.guest_address).read()
                        elif state == "guest-page":
                            serve = _Serve(service.guest_address)
                            host, port = serve.address
                        for width in widths:
                            path = "spend" if state == "spend-page" else ""
                            taken.append(
                                _shoot(browser, f"http://{host}:{port}/{path}", state, width, out,
                                      question=read[0]))
                    finally:
                        if serve is not None:
                            serve.close()
                        service.close()
        finally:
            browser.close()
    return taken


TELL_READING = """(() => {
  const box = document.querySelector('textarea.tell');
  const rect = box ? box.getBoundingClientRect() : null;
  const text = (selector) => {
    const node = document.querySelector(selector);
    return node ? node.textContent.trim() : null;
  };
  const span = document.querySelector('label.tell-label > span');
  const hint = document.querySelector('p.tell-hint');
  const sprint = document.querySelector('li.sprint');
  let laidOut = false;
  if (rect && span && hint && sprint) {
    const s = span.getBoundingClientRect();
    const h = hint.getBoundingClientRect();
    const style = getComputedStyle(sprint);
    const content = sprint.clientWidth - parseFloat(style.paddingLeft)
      - parseFloat(style.paddingRight);
    laidOut = s.bottom <= rect.top + 1 && rect.bottom <= h.top + 1 && rect.width >= content - 1;
  }
  return [Boolean(rect && rect.width > 0 && rect.height > 0),
          text('button.tell-send'), text('p.tell-hint'), laidOut];
})()"""

ASK_READING = f"""(() => {{
  const mine = document.querySelector('li.asks[data-project="owner/web"]');
  if (!mine) return [false, null, null];
  const homes = Array.from(document.querySelectorAll(
    'li[data-project="owner/web"], details[data-key="questions:owner/web"]'));
  const field = mine.querySelector('textarea.ask-text');
  let shown = false;
  if (field) {{
    const rect = field.getBoundingClientRect();
    shown = field.getClientRects().length > 0 && rect.width > 0 && rect.height > 0
      && getComputedStyle(field).visibility !== 'hidden';
  }}
  const visible = (node) => node.getClientRects().length > 0;
  const panel = document.querySelector({json.dumps(READING_PANEL)});
  if (panel) {{
    const line = Array.from(document.querySelectorAll(
      'button.thread-open[data-key="thread:owner/web:1177a2"] .thread-first')).find(visible);
    const answered = panel.querySelector('p.ask-read');
    return [shown, line ? line.textContent.trim() : null,
            answered ? answered.textContent.trim() : null];
  }}
  const read = (start, selector) => {{
    const rows = homes.flatMap((home) => Array.from(home.querySelectorAll('li.ask')));
    const row = rows.find((item) => {{
      const question = item.querySelector('p.ask-question');
      return visible(item) && question && question.textContent.trim().startsWith(start);
    }});
    const node = row ? row.querySelector(selector) : null;
    return node ? node.textContent.trim() : null;
  }};
  return [shown, read({json.dumps(ASK_WORKING_QUESTION)}, 'p.ask-state'),
          read({json.dumps(ASK_ANSWERED_QUESTION)}, 'p.ask-read')];
}})()"""

GOAL_READING = """(() => {
  const box = document.querySelector('#goal .goal-box');
  const field = document.querySelector('#goal textarea.goal-text');
  const pressed = document.querySelector('#goal .goal-project[aria-pressed="true"]');
  const shown = field ? field.getClientRects().length > 0 : false;
  return [Boolean(box && box.getClientRects().length > 0),
          field ? field.value : null,
          pressed ? pressed.textContent.trim() : null,
          field ? shown && field.scrollHeight <= field.clientHeight + 1 : null];
})()"""

ACTS_ROW = """Array.from(document.querySelectorAll('li[data-project]')).filter((line) => {
  const give = line.querySelector('button.give-goal');
  const ask = line.querySelector('button.ask-open');
  if (!give || !ask || line.getClientRects().length === 0) return false;
  const centre = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.top + rect.height / 2;
  };
  return Math.abs(centre(give) - centre(ask)) > 4;
}).map((line) => line.dataset.project)"""

THREAD_READING = f"""(() => {{
  const fold = document.querySelector('details[data-key="questions:owner/web"]');
  const homes = Array.from(document.querySelectorAll(
    'li[data-project="owner/web"], details[data-key="questions:owner/web"], #reading'));
  const visible = (node) => node.getClientRects().length > 0 && !node.closest('details:not([open])');
  const rows = homes.flatMap((home) => Array.from(home.querySelectorAll('li.ask')));
  const row = rows.find((item) => {{
    const question = item.querySelector('p.ask-question');
    return visible(item) && question
      && question.textContent.trim().startsWith({json.dumps(FOLLOW_QUESTION)});
  }});
  const read = row ? row.querySelector('p.ask-read') : null;
  const follow = Array.from(document.querySelectorAll('button.follow-open')).some(visible);
  return [Boolean(fold && fold.open), read ? read.textContent.trim() : null, follow];
}})()"""

SQUEEZED_COUNT = """Array.from(document.querySelectorAll('li.sprint')).filter((sprint) => {
  const now = sprint.querySelector('.sp-now');
  if (!now) return false;
  const n = now.getBoundingClientRect();
  const title = sprint.querySelector('.title-line').getBoundingClientRect();
  const head = sprint.querySelector('.sp-head').getBoundingClientRect();
  const lineHeight = parseFloat(getComputedStyle(now).lineHeight);
  return n.top < title.bottom - 1 || n.width < head.right - title.left - 1
    || n.width < title.width - 1 || n.height > 2 * lineHeight + 1
    || now.scrollHeight > now.clientHeight + 1;
}).length"""

JARGON_COUNT = r"""(() => {
  const folds = Array.from(document.querySelectorAll('#projects summary')).filter(
    (summary) => ['Detail', 'More'].includes(summary.textContent.trim())).length;
  const rows = Array.from(document.querySelectorAll('#projects li.message')).filter((row) => {
    const text = row.querySelector('.message-text');
    const state = row.querySelector('.message-state');
    const said = state ? state.textContent.trim() : '';
    return text && text.textContent.trim().startsWith('You: Approved version')
      && !said.startsWith('sent') && !said.startsWith('not picked up');
  }).length;
  const phrases = document.body.innerText.match(
    /\bon track\b|\bstated (just now|\d)|\bwithdraw|\bnudge|\bstop or\b|would do differently/gi);
  const owners = Array.from(document.querySelectorAll('#projects button.notice-withdraw')).filter(
    (button) => button.innerText.trim() === 'Withdraw').length;
  return folds + rows + Math.max(0, (phrases ? phrases.length : 0) - owners);
})()"""


CONTROL_SELECTOR = 'button, input, textarea, select, a[class*="btn-"], summary[class*="btn-"]'
SHORT_CONTROLS = f"""Array.from(document.querySelectorAll({json.dumps(CONTROL_SELECTOR)})).filter(
  (n) => n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden").map(
  (n) => [n, n.getBoundingClientRect().height]).filter(([n, h]) => h < 32).map(
  ([n, h]) => n.tagName.toLowerCase() + "." + (n.getAttribute("class") || "").split(/\\s+/)[0]
    + " " + Math.round(h * 100) / 100 + "px")"""
SCROLL_TOP = "window.scrollTo(0, 0)"
SCROLL_Y = "window.scrollY"


def _shoot(browser, url: str, state: str, width: int, out: Path, *,
           question: str = READ_QUESTION) -> Shot:
    page = browser.new_page(viewport={"width": width, "height": HEIGHT})
    try:
        page.goto(url)
        page.wait_for_selector("#breakdowns h2" if state == "spend-page" else "#projects h2")
        if state == "guest-page" and page.query_selector("#console-door") is not None:
            page.wait_for_selector("#top-who:not([hidden])")
            if page.query_selector("#capacity") is not None:
                raise RuntimeError("the guest shot is not the guest page")
        if state in ("finished-list", "desk-spend"):
            if state == "desk-spend":
                page.click('details[data-key="line:owner/web"] > summary')
            page.click('details[data-key="finished"] > summary')
            page.click('details[data-key^="ended:"] > summary')
        if state in ("notices-fold", "notice-post-open"):
            page.click('details[data-key^="notices:"] > summary')
            if state == "notice-post-open" and page.query_selector("button.notice-open"):
                page.click("button.notice-open")
        if state in ("goal-open", "goal-near", "goal-over"):
            page.focus("textarea.goal-text")
            page.wait_for_selector(".goal-box")
            if state == "goal-near":
                page.fill("textarea.goal-text", "x" * GOAL_NEAR_CHARS)
            if state == "goal-over":
                page.fill("textarea.goal-text", "x" * GOAL_OVER_CHARS)
                page.wait_for_selector(".goal-hint:not(:empty)")
        if state == "accounts-panel":
            page.click("#capacity")
            page.wait_for_selector("#accounts:not([hidden])")
        if state == "sharing-panel" and page.query_selector("#sharing-open") is not None:
            page.click("#sharing-open")
            page.wait_for_selector("#sharing:not([hidden])")
        tell = None
        if state == "tell-box-open":
            page.click("button.tell-open")
            page.wait_for_selector(".tell-hint")
            tell = tuple(page.evaluate(TELL_READING))
        paneled = (state in ("ask-box", "ask-goal", "questions-open", "question-read")
                   and page.query_selector(READING_PANEL) is not None)
        ask = None
        if state == "ask-box" and page.query_selector(ASK_OPEN):
            page.click(ASK_OPEN)
            page.wait_for_selector('li.asks[data-project="owner/web"] textarea.ask-text')
            if page.query_selector(ASK_FOLD):
                for selector in ((ASK_FOLD, thread_line("1177a1")) if paneled
                                 else (ASK_FOLD, *ASK_THREADS)):
                    page.click(selector)
            ask = tuple(page.evaluate(ASK_READING))
        goal = None
        if state == "ask-goal":
            if page.query_selector(ASK_FOLD):
                for selector in ((ASK_FOLD, thread_line("1177a1")) if paneled
                                 else (ASK_FOLD, ASK_THREADS[1])):
                    page.click(selector)
            goal_button = READING_GOAL if paneled else ASK_GOAL
            if page.query_selector(goal_button):
                page.click(goal_button)
                page.wait_for_selector("#goal .goal-box")
                goal = tuple(page.evaluate(GOAL_READING))
        thread = None
        if state == "questions-open":
            if page.query_selector(ASK_FOLD):
                for selector in ((ASK_FOLD, thread_line("1178a2")) if paneled
                                 else (ASK_FOLD, NEWEST_THREAD)):
                    page.click(selector)
            thread = tuple(page.evaluate(THREAD_READING))
        card = None
        if state in ("question-words", "question-refused"):
            if page.query_selector(WORDS_BOX):
                page.click(LOOK_OPTION)
                if state == "question-words":
                    page.fill(WORDS_BOX, LOOK_WORDS)
                else:
                    page.click(CARD_SEND)
                card = tuple(page.evaluate(CARD_READING))
            elif not page.query_selector(LOOK_OPTION):
                card = (None, None, None, None)
        reading = None
        if state == "question-read":
            if paneled:
                for selector in (ASK_FOLD, thread_line("1226a1")):
                    page.click(selector)
                reading = tuple(page.evaluate(READ_READING, question))
            elif page.query_selector(ASK_FOLD):
                for selector in (ASK_FOLD, READ_BASE_THREAD):
                    page.click(selector)
        page.evaluate(SCROLL_TOP)
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        squeezed = page.evaluate(SQUEEZED_COUNT)
        jargon = page.evaluate(JARGON_COUNT)
        scroll_y = page.evaluate(SCROLL_Y)
        short = tuple(page.evaluate(SHORT_CONTROLS))
        acts = tuple(page.evaluate(ACTS_ROW))
        path = out / f"{state}-{width}.png"
        page.screenshot(path=str(path), full_page=True)
    finally:
        page.close()
    return Shot(state, width, path, scroll_width, squeezed, jargon, tell, scroll_y=scroll_y,
                short=short, ask=ask, goal=goal, acts=acts, thread=thread, reading=reading,
                card=card)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="console-screenshots",
        description="Shoot the console's sprint states against a fixture console.")
    parser.add_argument("--out", required=True, help="the directory the PNG files go to")
    parser.add_argument("--question", help="the owner's question, shot with --answer-file")
    parser.add_argument("--answer-file", help="the stored answer's text (UTF-8), shot with --question")
    args = parser.parse_args(argv)
    if (args.question is None) != (args.answer_file is None):
        parser.error("--question and --answer-file go together")
    real = args.question is not None
    if real:
        text = Path(args.answer_file).read_text(encoding="utf-8")
    saved = {name: os.environ.get(name) for name in sandbox_environ(Path("."))}
    with tempfile.TemporaryDirectory(prefix="console-shots-env-") as tmp:
        os.environ.update(sandbox_environ(Path(tmp).resolve()))
        try:
            taken = (capture(Path(args.out), states=("question-read",), read=(args.question, text))
                     if real else capture(Path(args.out)))
        except Unavailable as error:
            print(f"console-screenshots: {error}", file=sys.stderr)
            return 2
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    for shot in taken:
        print(shot.path)
    wide = [shot for shot in taken if shot.scroll_width > shot.width]
    for shot in wide:
        print(f"console-screenshots: {shot.path.name} scrolls sideways "
              f"({shot.scroll_width} > {shot.width})")
    squeezed = [shot for shot in taken if shot.squeezed > 0]
    for shot in squeezed:
        print(f"console-screenshots: {shot.path.name} squeezes the now sentence "
              f"({shot.squeezed} above, narrower than its line, over two lines or clipped)")
    jargon = [] if real else [shot for shot in taken if shot.jargon > 0]
    for shot in jargon:
        print(f"console-screenshots: {shot.path.name} shows a jargon label ({shot.jargon})")
    closed = [shot for shot in taken if shot.state == "tell-box-open" and shot.tell != OPEN_TELL]
    for shot in closed:
        print(f"console-screenshots: {shot.path.name} does not show the open Tell box")
    unasked = [shot for shot in taken
               if shot.state == "ask-box" and shot.ask not in (None, OPEN_ASK, HEAD_ASK)]
    for shot in unasked:
        print(f"console-screenshots: {shot.path.name} does not show the open Ask box")
    unfilled = [shot for shot in taken
                if shot.state == "ask-goal" and shot.goal not in (None, FILLED_GOAL)]
    for shot in unfilled:
        print(f"console-screenshots: {shot.path.name} does not show the goal box filled from "
              "the answer")
    unthreaded = [shot for shot in taken
                  if shot.state == "questions-open"
                  and shot.thread not in (None, OPEN_THREAD, BASE_THREAD)]
    for shot in unthreaded:
        print(f"console-screenshots: {shot.path.name} does not show the opened thread")
    shown = (None, READ_SHOWN)
    unread = [shot for shot in taken if shot.state == "question-read"
              and (shot.reading is not None and shot.reading[:2] != (True, 1) if real
                   else shot.reading not in shown)]
    for shot in unread:
        print(f"console-screenshots: {shot.path.name} does not show the answer in the main column")
    expected = {"question-words": WORDS_CARD, "question-refused": REFUSED_CARD}
    uncarded = [shot for shot in taken
                if shot.state in expected and shot.card not in (None, expected[shot.state])]
    for shot in uncarded:
        print(f"console-screenshots: {shot.path.name} does not show the question card "
              f"{'with its words typed' if shot.state == 'question-words' else 'refused without words'}")
    offrow = [shot for shot in taken if shot.acts]
    for shot in offrow:
        print(f"console-screenshots: {shot.path.name} puts Ask a question on another row than "
              f"Give it a goal ({', '.join(shot.acts)})")
    scrolled = [shot for shot in taken if shot.scroll_y != 0]
    for shot in scrolled:
        print(f"console-screenshots: {shot.path.name} is not taken from the top of the page "
              f"(scrolled {shot.scroll_y:g} px)")
    short = [shot for shot in taken if shot.short]
    for shot in short:
        print(f"console-screenshots: {shot.path.name} has a control under 32 px "
              f"({', '.join(shot.short)})")
    return 1 if (wide or squeezed or jargon or closed or unasked or unfilled or unthreaded or unread
                 or uncarded or offrow or scrolled or short) else 0


if __name__ == "__main__":
    sys.exit(main())
