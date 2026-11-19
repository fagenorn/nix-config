"""A repeatable screenshot set of the console's sprint states (#1086).

Run: just console-screenshots [out]   (Playwright and its Chromium come from nixpkgs)

Contract:
- `STATES` names the forty screens the sprint block, the finished list, the message life, the
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
  fails; `look-card` is a look card on an approved `owner/web`
  sprint, open, with its three options and the before and after pictures every look card carries (#1260); `look-moved` is that card after an approval found
  the pull request at another head, so its line says nothing was recorded and that the manager will send the new
  pictures,
  the options still there; `look-failed` is that card answered with the approval and its
  tracker post failed, so the card holds the headline, the reason and a Retry button and no
  options; `accounts-panel` is the accounts panel opened over
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
  picture, its reading None). `activation-tooling` and `activation-host` are the desk with no sprint and an
  activation reading of merged changes this host is built from, none a console file: the first
  changes only agent tooling (a `python/` file and a skill), so its one line reads the
  agent-tooling wording; the second also changes the host configuration, so its line reads the
  host-configuration wording (the page draws one activation line, so each picture shows one
  wording, and `ACTIVATION_SHOWN` holds the line and the one Activate button each reads); each is
  shot with a stand-in reading, no run and no activator. Only a page whose `Activation` cannot
  read `other` (`reads_other()` is False) holds no change, so its line is absent and its reading is
  `ACTIVATION_BASE`, which is the before picture; a page that reads `other` must show `ACTIVATION_SHOWN`. On a page with the reading panel the other ask states click
  through it: `ask-box` the fold and `owner/web`'s answered thread's line (its reading is then
  `HEAD_ASK`: the field shown, the working question's line, the panel's Read line), `ask-goal`
  the fold, that line and the panel's Make it a goal, `questions-open` the fold and the newest
  thread's line; on a page without it each clicks what it always did.
  `sharing-panel` is the owner's Sharing panel, with Serve on, opened over one invented colleague
  of `owner/web` after one admitted request from this host itself, so it shows the no-other-device
  line; `sharing-reached` is that panel after a further request from another device;
  `sharing-off` is that panel with sharing switched off and
  the read name shown, and `sharing-unreadable` is it with sharing on and no readable name, so
  it shows its line; neither makes a guest request; `guest-page` is that colleague's read-only page through a
  stand-in Serve that adds the tailnet Host and login header, refused when a page with a door
  meta (`#console-door`) is not the guest page. On the base commit's page, which has neither
  the Sharing button nor a door meta, `sharing-panel` is the desk with no panel opened and
  `guest-page` is the page the guest port served then, so a base run still writes every file.
  `WIDTHS` are the two viewport widths each is shot at. `capture`
  writes `<state>-<width>.png` for every pair, so a full run writes 80 files.
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
  `activation-tooling` or `activation-host` shot does not read its `ACTIVATION_SHOWN` entry (nor, on a page that
  cannot read `other`, `ACTIVATION_BASE`); or when a
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
  tall (`SHORT_CONTROLS`, read after the state is drawn). When any shot misses a `STYLE_CHECKS`
  row, the line names each miss: the row's computed style is read after the capture, with probes
  and steps as `StyleCheck` and `STYLE_STEPS` say. The style reading and its steps run only when
  `style_applies()` (the page served is the page beside this module), so a base run's pictures and
  result are as before. In real-answer mode, `fixture` rows are skipped. `capture(...,
  mutate=True)` records in `Shot.broke` each row whose `broken` rule made it miss. It returns 2
  with a one-line reason when Playwright or Chromium is missing, else 0.
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
  `questions` object draws nothing on it. The after pictures run with `PYTHONPATH` at the branch. `guest_door_kwargs` and `guest_door` pick the
base commit's guest port or the branch's guest socket, so a base run still serves the guest states.
"""
from __future__ import annotations

import argparse
import http.client
import inspect
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_tools.console import capacity, event_log, manager, pictures, sessions, signin
from agent_tools.console.activation import Activation
from agent_tools.console.answer import FORGE_DOWN
from agent_tools.console.event_log import SHARING_COLLEAGUE, SHARING_TAILNET, EventLog
from agent_tools.console.movement import LocalReading, PullRequest
from agent_tools.console.service import ConsoleService
from agent_tools.console.sprints import TELL_MINUTE_TEXT, Question

from .console_test_support import hook_body, write_registry

STATES = ("live-several", "waiting-on-you", "stuck", "tell-box-open", "message-sent",
          "message-picked-up", "message-replied", "message-not-picked-up", "finished-list",
          "nothing-running", "waiting-its-turn", "manager-cannot-hear", "owner-check", "spend-page", "notices-fold",
          "notice-post-open", "desk-spend", "failed-start", "goal-open", "goal-near", "goal-over",
          "inbox-card", "question-words", "question-refused", "look-card", "look-moved",
          "look-failed", "accounts-panel", "ask-box", "questions-closed", "questions-open",
          "ask-goal", "question-read", "activation-tooling", "activation-host", "sharing-panel",
          "sharing-off", "sharing-unreadable", "sharing-reached", "guest-page")
WIDTHS = (1440, 480)
HEIGHT = 900
GOAL_NEAR_CHARS = 1900
GOAL_OVER_CHARS = 2100
MINUTE = 60.0
PROJECTS = ("owner/web", "owner/api", "owner/docs")
TRACKER_URL = "https://github.com/owner/web/issues"
LOOK_APPROVE = "Approve this head"
LOOK_HEAD = "3f9c1d27a05be84c61d9f0273b8e5a14c7d0962e"
LOOK_FOUND = "8e41b0a6d2c7f35918ae04b7c6d1259f3e0a7b84"
TAILNET = "desk.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
SELF_ADDRESS = "100.64.0.10"
OTHER_DEVICE_ADDRESS = "100.64.0.20"
SHARING_STATES = ("sharing-panel", "sharing-off", "sharing-unreadable", "sharing-reached",
                  "guest-page")
SHARING_PANELS = ("sharing-panel", "sharing-off", "sharing-unreadable", "sharing-reached")
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
ACTIVATION_COMMIT = "1258" * 10
ACTIVATION_PATHS = {
    "activation-tooling": ("python/agent_tools/system/util.py",
                           "home/common/agent-skills/skills/deliver-standard/SKILL.md"),
    "activation-host": ("python/agent_tools/system/util.py", "hosts/common/common-packages.nix")}
ACTIVATION_SHOWN = {
    "activation-tooling": ("A change to the agent tooling merged at 125812581258 and is not active "
                           "on this host.", 1),
    "activation-host": ("A change to the host configuration merged at 125812581258 and is not "
                        "active on this host.", 1)}
ACTIVATION_BASE = (None, 0)
ACTIVATION_READING = """(() => {
  const line = document.querySelector('#projects p.activation');
  if (!line || line.getClientRects().length === 0) return [null, 0];
  const text = line.querySelector('span');
  const buttons = Array.from(line.querySelectorAll('button.activate')).filter(
    (button) => button.getClientRects().length > 0);
  return [text ? text.textContent.trim() : null, buttons.length];
})()"""
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
    activating: tuple[str, ...] = ()


@dataclass(frozen=True)
class StyleCheck:
    """One computed-style check of the page, read after the picture of each state it names.

    `selector` names the element (the first match, or every rendered match with `every`), `prop`
    its computed property (of `pseudo` when set) and `want` how `value` is compared (`WANTS`).
    A row with a `probe` reads the matches of `selector` in the probe's markup, placed last in
    `host` and marked with `data-style-probe`; `compare_probe` places the element `same_as` and
    `gt` compare with. `forced` pseudo-classes are forced on the matches over CDP, and
    `reduced_motion` reads under `prefers-reduced-motion: reduce`. `broken` is a rule that must
    make this row miss, which `capture(mutate=True)` proves. A `fixture` row reads the canonical
    fixture answer, so a real-answer run skips it. The whole-page kinds (`none_peach`, `palette`,
    `tokens`, `distinct`, `sizes_shared`) read the elements under `selector` (the probe's, for a
    probe row) and the painted colours of each, normalised, or the CSSOM `:root` token list;
    `fills` reads each match against its parent's content width.
    """
    name: str
    states: tuple[str, ...]
    widths: tuple[int, ...]
    selector: str
    prop: str
    want: str
    value: str
    broken: str
    probe: str = ""
    host: str = "body"
    compare_probe: str = ""
    compare_host: str = "body"
    pseudo: str = ""
    forced: tuple[str, ...] = ()
    every: bool = False
    reduced_motion: bool = False
    fixture: bool = False


# The selectors clicked, in order, after a state's picture and before its style reading.
STYLE_STEPS: dict[str, tuple[str, ...]] = {}
WANTS = frozenset({"equals", "in", "not", "starts", "min", "max", "same_as", "gt",
                   "none_peach", "palette", "tokens", "distinct", "sizes_shared", "fills"})
PALETTE = {
    "--base": "rgb(36, 39, 58)", "--mantle": "rgb(30, 32, 48)", "--s0": "rgb(54, 58, 79)",
    "--s1": "rgb(73, 77, 100)", "--s2": "rgb(91, 96, 120)", "--text": "rgb(202, 211, 245)",
    "--sub1": "rgb(184, 192, 224)", "--sub0": "rgb(165, 173, 203)", "--ov2": "rgb(147, 154, 183)",
    "--crust": "rgb(24, 25, 38)", "--peach": "rgb(245, 169, 127)", "--lav": "rgb(183, 189, 248)",
    "--green": "rgb(166, 218, 149)", "--yellow": "rgb(238, 212, 159)", "--red": "rgb(237, 135, 150)",
}
_HAIR = "rgba(202, 211, 245, 0.09)"
_HOVER = "rgba(202, 211, 245, 0.05)"
_CLEAR = "rgba(0, 0, 0, 0)"
_NO_STATE_COLOURS = ("--peach", "--green", "--yellow", "--red")
_DESK_TOKENS = ("--base", "--crust", "--display", "--green", "--hair", "--hover", "--lav", "--mantle",
                "--ov2", "--peach", "--red", "--s0", "--s1", "--s2", "--sub0", "--sub1", "--text",
                "--ui", "--yellow")
_SPEND_PALETTE = {k: v for k, v in PALETTE.items() if k not in _NO_STATE_COLOURS}
# The lists the whole-page want kinds compare with, named by a row's `value`. The desk literals
# are the only colour literals of the desk page's style block besides its tokens.
STYLE_LISTS = {
    "peach": PALETTE["--peach"],
    "palette": {
        "desk": [*PALETTE.values(), "rgb(248, 187, 152)", "rgba(183, 189, 248, 0.1)", _HOVER, _HAIR,
                 "rgba(24, 25, 38, 0.22)", "rgba(24, 25, 38, 0.28)", "rgba(8, 9, 16, 0.45)",
                 "rgba(8, 9, 16, 0.9)", _CLEAR],
        "spend": [*_SPEND_PALETTE.values(), _HOVER, _HAIR, _CLEAR],
        "notices": [PALETTE[k] for k in ("--text", "--sub1", "--sub0", "--ov2", "--s0", "--s1",
                                         "--s2", "--base", "--mantle")] + [_HAIR, _HOVER, _CLEAR],
    },
    "tokens": {
        "desk": {"names": list(_DESK_TOKENS),
                 "colours": {**PALETTE, "--hair": _HAIR, "--hover": _HOVER}},
        "spend": {"names": [n for n in _DESK_TOKENS if n not in _NO_STATE_COLOURS],
                  "colours": {**_SPEND_PALETTE, "--hair": _HAIR, "--hover": _HOVER}},
    },
}
_EVERY_STATE = tuple(state for state in STATES if state != "guest-page")
_BOTH = (1440, 480)
_NEEDS = ".needs, .needs *, .btn-primary, .btn-primary *"
_RED_ON = "{ color: rgb(1, 2, 3) !important }"


def _colour(name, state, selector, token, probe="", host="body", widths=(1440,), **kw):
    """A row that wants `selector`'s `color` to be `token`'s colour, broken by a rule setting it to
    rgb(1, 2, 3)."""
    return StyleCheck(name, (state,), widths, selector, kw.pop("prop", "color"), "equals",
                      PALETTE[token], f"{selector} {_RED_ON}", probe=probe, host=host, **kw)


STYLE_CHECKS: tuple[StyleCheck, ...] = (
    StyleCheck("peach-only-needs", _EVERY_STATE, _BOTH, "body", "color", "none_peach", _NEEDS,
               ".top-in { border-top: 2px solid rgb(245, 169, 127) !important }"),
    StyleCheck("runs-not-red", ("live-several", "waiting-its-turn"), (1440,),
               ".run, .runs, .moved, .quiet", "color", "not", PALETTE["--red"],
               ".run, .runs, .moved, .quiet { color: rgb(237, 135, 150) !important }", every=True),
    StyleCheck("palette-notices", ("notices-fold",), _BOTH, ".line.notices", "color", "palette",
               "notices", ".notice-label { color: rgb(183, 189, 248) !important }"),
    StyleCheck("palette-accounts", ("accounts-panel",), _BOTH, "#accounts", "color", "palette",
               "desk", "#accounts { background-color: rgb(1, 2, 3) !important }"),
    StyleCheck("sizes-accounts", ("accounts-panel",), (1440,), "#accounts", "font-size",
               "sizes_shared", "", "#accounts * { font-size: 13.37px !important }"),
    StyleCheck("accounts-hidden", ("accounts-panel",), (1440,), ".acct-panel[hidden]", "display",
               "equals", "none", ".acct-panel[hidden] { display: block !important }",
               probe='<div class="acct-panel" hidden data-style-probe></div>'),
    StyleCheck("palette-spend", ("spend-page",), _BOTH, "body", "color", "palette", "spend",
               ".brand { color: rgb(237, 135, 150) !important }"),
    StyleCheck("tokens-desk", ("nothing-running",), (1440,), ":root", "--*", "tokens", "desk",
               ":root { --green: #00ff00 !important }"),
    StyleCheck("tokens-spend", ("spend-page",), (1440,), ":root", "--*", "tokens", "spend",
               ":root { --peach: #f5a97f }"),
    _colour("state-working", "nothing-running", ".s-working", "--green",
            probe='<span class="s-working" data-style-probe>x</span>'),
    _colour("state-waiting-answer", "nothing-running", ".s-waiting_answer", "--yellow",
            probe='<span class="s-waiting_answer" data-style-probe>x</span>'),
    _colour("state-waiting-permission", "nothing-running", ".s-waiting_permission", "--yellow",
            probe='<span class="s-waiting_permission" data-style-probe>x</span>'),
    _colour("state-limit", "nothing-running", ".s-limit", "--red",
            probe='<span class="s-limit" data-style-probe>x</span>'),
    _colour("cap-out-red", "nothing-running", ".cap-out", "--red", host="#capacity",
            probe='<span class="cap-out" data-style-probe>x</span>'),
    _colour("message-you-lav", "message-sent", ".message-text", "--lav", widths=_BOTH),
    _colour("reason-quiet", "nothing-running", ".card .reason", "--ov2",
            probe='<div class="card" data-style-probe><span class="reason">x</span></div>'),
    _colour("ball-needs", "nothing-running", ".sprint-ball.needs", "--peach",
            probe='<span class="sprint-ball needs" data-style-probe>x</span>'),
    _colour("tone-go", "nothing-running", ".st-go", "--green",
            probe='<span class="st-go" data-style-probe>x</span>'),
    _colour("tone-wait", "nothing-running", ".st-wait", "--yellow",
            probe='<span class="st-wait" data-style-probe>x</span>'),
    _colour("tone-dim", "nothing-running", ".st-dim", "--ov2",
            probe='<span class="st-dim" data-style-probe>x</span>'),
    StyleCheck("pips-differ", ("nothing-running",), (1440,),
               ".pip.pip-landed | .pip.pip-delivery | .pip.pip-held | .pip.pip-queued",
               "border-top-style", "distinct", "",
               ".pip.pip-queued { border: 0 !important; background: var(--sub0) !important }",
               probe='<span data-style-probe><span class="pip pip-landed"></span>'
                     '<span class="pip pip-delivery"></span><span class="pip pip-held"></span>'
                     '<span class="pip pip-queued"></span></span>'),
    _colour("spend-quiet", "desk-spend", ".spend", "--ov2", widths=_BOTH),
    _colour("sp-spend-quiet", "desk-spend", ".sp-spend", "--ov2", widths=_BOTH),
    StyleCheck("option-fills", ("inbox-card",), _BOTH, ".btn-option", "width", "fills", "",
               ".btn-option { width: 50% !important }", every=True),
    StyleCheck("option-pick-key", ("question-words",), _BOTH, '.btn-option[aria-pressed="true"] kbd',
               "background-color", "equals", PALETTE["--lav"],
               '.btn-option[aria-pressed="true"] kbd { background: none !important }'),
    _colour("nav-quiet", "nothing-running", ".nav", "--sub0", widths=_BOTH),
    StyleCheck("nav-nowrap", ("nothing-running",), _BOTH, ".nav", "white-space", "equals", "nowrap",
               ".nav { white-space: normal !important }"),
    StyleCheck("nav-width", ("nothing-running",), _BOTH, ".nav", "width", "max", "60",
               ".nav { width: 200px !important }"),
    StyleCheck("nav-min-width", ("nothing-running",), _BOTH, ".nav", "min-width", "equals", "auto",
               ".nav { min-width: 0 !important }"),
)
STYLE_PLACE = r"""((rows) => {
  let placed = 0;
  const put = (html, host, name) => {
    if (!html) return;
    const where = document.querySelector(host);
    if (!where) return;
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    const probe = template.content.firstElementChild;
    if (!probe) return;
    probe.setAttribute('data-style-probe', name);
    where.appendChild(probe);
    placed++;
  };
  for (const row of rows) {
    put(row.probe, row.host, row.name);
    put(row.compare_probe, row.compare_host, row.name + ':compare');
  }
  return placed;
})"""
STYLE_MUTATE = r"""((css) => {
  const style = document.createElement('style');
  style.id = 'style-mutation';
  style.textContent = css;
  document.head.appendChild(style);
})"""
STYLE_SETTLE = r"""(() => {
  for (const animation of document.getAnimations()) {
    try { animation.finish(); } catch (error) { /* an infinite animation has no end */ }
  }
})"""
STYLE_CLEAR = r"""(() => {
  for (const node of document.querySelectorAll('[data-style-probe], #style-mutation')) node.remove();
})"""
STYLE_READING = r"""((rows) => {
  const parse = (text) => {
    const found = /^(?:rgba?\(|(color)\(srgb\s+)([^)]*)\)$/.exec(String(text).trim());
    if (!found) return null;
    const parts = found[2].split(/[\s,\/]+/).filter(Boolean).map(Number);
    if (parts.length < 3 || parts.length > 4 || parts.some((n) => Number.isNaN(n))) return null;
    const scale = found[1] ? 255 : 1;
    const channel = (n) => Math.round(Math.min(255, Math.max(0, n * scale)));
    const alpha = parts.length === 4 ? parts[3] : 1;
    return [channel(parts[0]), channel(parts[1]), channel(parts[2]),
            Math.round(alpha * 100) / 100].join(',');
  };
  const same = (a, b) => {
    const pa = parse(a), pb = parse(b);
    return pa !== null || pb !== null ? pa === pb : a === b;
  };
  const probes = (name) => Array.from(document.querySelectorAll('[data-style-probe]')).filter(
    (node) => node.getAttribute('data-style-probe') === name);
  const within = (roots, selector) => roots.flatMap((root) => [
    ...(root.matches(selector) ? [root] : []), ...root.querySelectorAll(selector)]);
  const onPage = (selector) => Array.from(document.querySelectorAll(selector)).filter(
    (node) => !node.closest('[data-style-probe]'));
  const label = (node) => node.tagName.toLowerCase() + '.'
    + (node.getAttribute('class') || '').split(/\s+/)[0];
  const LISTS = __LISTS__;
  const SHAPES = new Set(['path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse', 'text']);
  const COLOURS = /(?:rgba?|color)\([^)]*\)/g;
  const painted = (node) => {
    const s = getComputedStyle(node);
    const out = [['color', s.color], ['background-color', s.backgroundColor]];
    for (const side of ['top', 'right', 'bottom', 'left']) {
      if (parseFloat(s.getPropertyValue('border-' + side + '-width')) > 0) {
        out.push(['border-' + side + '-color', s.getPropertyValue('border-' + side + '-color')]);
      }
    }
    if (s.outlineStyle !== 'none') out.push(['outline-color', s.outlineColor]);
    out.push(['text-decoration-color', s.textDecorationColor]);
    if (s.getPropertyValue('column-rule-style') !== 'none') {
      out.push(['column-rule-color', s.getPropertyValue('column-rule-color')]);
    }
    for (const prop of ['caret-color', 'accent-color']) {
      const value = s.getPropertyValue(prop);
      if (value !== 'auto') out.push([prop, value]);
    }
    for (const prop of ['box-shadow', 'text-shadow']) {
      const value = s.getPropertyValue(prop);
      if (value !== 'none') for (const colour of value.match(COLOURS) || []) out.push([prop, colour]);
    }
    if (SHAPES.has(node.tagName.toLowerCase())) {
      for (const prop of ['fill', 'stroke']) {
        const value = s.getPropertyValue(prop);
        if (value !== 'none' && !value.startsWith('url(')) out.push([prop, value]);
      }
    }
    return out;
  };
  const rendered = (node) => node.getClientRects().length > 0;
  const scopeOf = (row) => {
    const roots = row.probe ? probes(row.name) : onPage(row.selector);
    const found = new Set();
    for (const root of roots) for (const node of [root, ...root.querySelectorAll('*')]) found.add(node);
    return {
      roots,
      nodes: Array.from(found).filter((node) => rendered(node)
        && (row.probe || !node.closest('[data-style-probe]'))),
    };
  };
  const wholePage = (row) => {
    const found = [];
    const { roots, nodes } = scopeOf(row);
    if (!roots.length) return [`${row.name}: ${row.selector} is absent`];
    if (row.want === 'none_peach') {
      const peach = parse(LISTS.peach);
      for (const node of nodes) {
        if (node.matches(row.value)) continue;
        for (const [prop, colour] of painted(node)) {
          if (parse(colour) === peach) found.push(`${row.name}: ${label(node)} ${prop} is ${colour}`);
        }
      }
    } else if (row.want === 'palette') {
      const allowed = new Set(LISTS.palette[row.value].map(parse));
      for (const node of nodes) {
        for (const [prop, colour] of painted(node)) {
          if (!allowed.has(parse(colour))) found.push(`${row.name}: ${label(node)} ${prop} is ${colour}`);
        }
      }
    } else if (row.want === 'sizes_shared') {
      const inside = new Set(nodes);
      const sizes = new Set(Array.from(document.querySelectorAll('body *')).filter(
        (node) => rendered(node) && !inside.has(node) && !node.closest('[data-style-probe]'))
        .map((node) => getComputedStyle(node).fontSize));
      for (const node of nodes) {
        const size = getComputedStyle(node).fontSize;
        if (!sizes.has(size)) found.push(`${row.name}: ${label(node)} font-size is ${size}`);
      }
    }
    return found;
  };
  const tokens = (row) => {
    const list = LISTS.tokens[row.value];
    const declared = new Set();
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.selectorText === ':root') {
          for (const name of Array.from(rule.style)) if (name.startsWith('--')) declared.add(name);
        } else if (rule.cssRules) {
          walk(rule.cssRules);
        }
      }
    };
    for (const sheet of document.styleSheets) walk(sheet.cssRules);
    const found = [];
    for (const name of Array.from(declared).sort()) {
      if (!list.names.includes(name)) found.push(`${row.name}: :root declares ${name}`);
    }
    for (const name of list.names) {
      if (!declared.has(name)) found.push(`${row.name}: :root lacks ${name}`);
    }
    for (const [name, colour] of Object.entries(list.colours)) {
      if (!declared.has(name)) continue;
      const scratch = document.createElement('span');
      scratch.style.color = `var(${name})`;
      document.body.appendChild(scratch);
      const got = getComputedStyle(scratch).color;
      scratch.remove();
      if (!same(got, colour)) found.push(`${row.name}: ${name} is ${got}`);
    }
    return found;
  };
  const distinct = (row) => {
    const names = row.selector.split('|').map((part) => part.trim());
    const roots = row.probe ? probes(row.name) : [];
    const seen = [];
    for (const name of names) {
      const [node] = row.probe ? within(roots, name) : onPage(name);
      if (!node) return [`${row.name}: ${name} is absent`];
      const s = getComputedStyle(node);
      const tuple = ['background-image', 'border-top-style', 'border-top-width',
        'border-top-left-radius', 'box-shadow', 'width']
        .map((prop) => s.getPropertyValue(prop).replace(COLOURS, 'C')).join('|');
      seen.push([name, tuple]);
    }
    const found = [];
    for (let i = 0; i < seen.length; i++) {
      for (let j = i + 1; j < seen.length; j++) {
        if (seen[i][1] === seen[j][1]) {
          found.push(`${row.name}: ${seen[i][0]} and ${seen[j][0]} differ only in colour`);
        }
      }
    }
    return found;
  };
  const misses = [];
  for (const row of rows) {
    if (row.want === 'none_peach' || row.want === 'palette' || row.want === 'sizes_shared') {
      misses.push(...wholePage(row));
      continue;
    }
    if (row.want === 'tokens') { misses.push(...tokens(row)); continue; }
    if (row.want === 'distinct') { misses.push(...distinct(row)); continue; }
    const matches = row.probe ? within(probes(row.name), row.selector) : onPage(row.selector);
    const subjects = row.every ? matches.filter((node) => node.getClientRects().length > 0)
                               : matches.slice(0, 1);
    if (!subjects.length) {
      misses.push(`${row.name}: ${row.selector} is absent`);
      continue;
    }
    const pseudo = row.pseudo || null;
    for (const node of subjects) {
      let got = getComputedStyle(node, pseudo).getPropertyValue(row.prop);
      let other = null;
      if (row.want === 'same_as' || row.want === 'gt') {
        const [rival] = [...within(probes(row.name + ':compare'), row.value), ...onPage(row.value)];
        if (!rival) {
          misses.push(`${row.name}: ${row.value} is absent`);
          continue;
        }
        other = getComputedStyle(rival, pseudo).getPropertyValue(row.prop);
      }
      let ok = false;
      if (row.want === 'fills') {
        const parent = node.parentElement;
        const cs = getComputedStyle(parent);
        const width = node.getBoundingClientRect().width;
        got = Math.round(width * 100) / 100 + 'px';
        ok = width >= parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 1;
      } else if (row.want === 'equals') ok = same(got, row.value);
      else if (row.want === 'in') ok = row.value.split('|').some((member) => same(got, member));
      else if (row.want === 'not') ok = !same(got, row.value);
      else if (row.want === 'starts') ok = got.startsWith(row.value);
      else if (row.want === 'min') ok = parseFloat(got) >= parseFloat(row.value);
      else if (row.want === 'max') ok = parseFloat(got) <= parseFloat(row.value);
      else if (row.want === 'same_as') ok = same(got, other);
      else if (row.want === 'gt') ok = parseFloat(got) > parseFloat(other);
      if (!ok) {
        misses.push(`${row.name}: ${row.every ? label(node) : row.selector + row.pseudo} `
                    + `${row.prop} is ${got}`);
      }
    }
  }
  return misses;
})""".replace("__LISTS__", json.dumps(STYLE_LISTS))


def style_applies(served: Path | None = None) -> bool:
    """Whether the page served is the page beside this module (a base run serves the base's)."""
    if served is None:
        import agent_tools.console
        served = Path(next(iter(agent_tools.console.__path__)))
    here = Path(__file__).resolve().parents[1] / "python/agent_tools/console"
    for name in ("page.html", "spend.html"):
        try:
            if (Path(served) / name).read_bytes() != (here / name).read_bytes():
                return False
        except OSError:
            return False
    return True


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
    activation: tuple[str | None, int] | None = None
    card: tuple[str | None, str | None, bool | None, str | None] | None = None
    style: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    broke: tuple[str, ...] = ()


def sandbox_environ(root: Path) -> dict[str, str]:
    root = Path(root)
    return {"HOME": str(root / "home"),
            "CLAUDE_ACCOUNTS_DIR": str(root / "accounts"),
            "CLAUDE_CONFIG_DIR": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "xdg-config")}


def _solid_png(colour: tuple[int, int, int], width: int = 96, height: int = 60) -> bytes:
    """A small RGB PNG of one colour, so a picture gallery has something to draw."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(colour) * width
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds")


class _Seed:
    """One event log whose every row carries the time its writer chose, `ago` seconds before now."""

    def __init__(self, log: EventLog, at: list[str], now_s: float, pictures_dir: Path | None = None):
        self.log = log
        self.pictures_dir = pictures_dir
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

    def look_pictures(self, project: str, sid: str) -> list[dict]:
        """The before and after pictures of a look question: two stored PNGs of one size, in two colours."""
        stored = []
        for pair, line, colour in (("before", "Before, 1440 px", (222, 226, 232)),
                                   ("after", "After, 1440 px", (196, 224, 205))):
            picture, _ = pictures.store(self.pictures_dir, _solid_png(colour))
            self.put(MINUTE * 5, *pictures.entry(project, sid, picture))
            stored.append({"picture": picture, "line": line, "pair": pair})
        return stored

    def look(self, project: str, sid: str, goal: str, *, moved: bool = False,
             failed: bool = False) -> None:
        """One look question on `sid`: open, found moved to another head, or approved with the post failed.
        It carries the two pictures a real look card always has, marked before and after."""
        base = {"sprint_id": sid, "goal": goal}
        shown = self.look_pictures(project, sid)
        question = {
            "question": "Does the settings page look right?",
            "blocks": "the merge of issue 12",
            "context": "The before and after of the settings page, from the same pull request.",
            "options": [LOOK_APPROVE, "Approve with one fix", "Ask for changes"],
            "recommended": LOOK_APPROVE, "pictures": shown,
            **({"needs_words": ["Approve with one fix", "Ask for changes"]} if NEEDS_WORDS_KEPT else {}),
            "look": {"issue": 12, "pr": 34, "head": LOOK_HEAD, "approve": LOOK_APPROVE}}
        asked = self.put(MINUTE * 4, "questions.asked", project, {
            **base, "blocker": False, "look_repo": "owner/web", "questions": [question]})
        where = {"round": asked.seq, "index": 0}
        if moved:
            self.put(MINUTE * 2, "look.recorded", project, {
                **base, **where, "outcome": "moved", "found": LOOK_FOUND, "state": "open"})
        if failed:
            answered = self.put(MINUTE * 3, "question.answered", project, {
                **base, **where, "question": "Does the settings page look right?",
                "answer": LOOK_APPROVE, "chosen": LOOK_APPROVE, "recommended": LOOK_APPROVE,
                "differs": False,
                "look": {"issue": 12, "pr": 34, "head": LOOK_HEAD, "repo": "owner/web"}})
            self.put(MINUTE * 2, "look.recorded", project, {
                **base, **where, "outcome": "failed", "message": answered.seq,
                "reason": FORGE_DOWN})

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
        if state == "sharing-off":
            seed.put(MINUTE, SHARING_TAILNET, None, {"shared": False})
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
    elif state in ("look-card", "look-moved", "look-failed"):
        sid, goal = seed.sprint(web, "Fix the settings page", started=30 * MINUTE, report=6 * MINUTE)
        seed.look(web, sid, goal, moved=state == "look-moved", failed=state == "look-failed")
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
    elif state not in ("nothing-running", *ACTIVATION_PATHS):
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
        holding=(12,) if state == "waiting-its-turn" else (), deaf=state == "manager-cannot-hear",
        activating=ACTIVATION_PATHS.get(state, ()))
    write_registry(fixture.registry, [
        {"project_id": name, "root": str(path)} for name, path in zip(PROJECTS, projects)])
    at = [_iso(now_s)]
    log = EventLog(fixture.store, clock=lambda: at[0])
    try:
        sprint_ids = _seed_state(_Seed(log, at, now_s, console / "pictures"), state, str(projects[0]), read=read)
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


def reads_other() -> bool:
    """Whether this page's `Activation` can hold merged changes outside the console (it has `other`)."""
    return "other" in Activation.__dataclass_fields__


def _activation_reader(paths: tuple[str, ...]):
    """A stand-in reading of merged changes outside the console; a base commit's `Activation` has no `other`."""
    def read(roots):
        other = {"other": paths} if reads_other() else {}
        return Activation(sorted(roots)[0], (), ACTIVATION_COMMIT, **other)
    return read


class _UnixHTTPConnection(http.client.HTTPConnection):
    """An HTTP client of a guest door that is a Unix socket at `path`."""

    def __init__(self, path: str, timeout: float = 5):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def guest_door_kwargs(constructor, folder: Path) -> dict:
    """The constructor arguments that open the guest door: the branch's socket, else the base's port."""
    if "guest_socket" in inspect.signature(constructor).parameters:
        return {"guest_socket": folder / "guest" / "guest.sock"}
    return {"guest_port": 0}


def guest_door(service) -> str | tuple[str, int]:
    """Where `service` listens for guests: its socket path, else (the base commit) its address."""
    return service.guest_socket if hasattr(service, "guest_socket") else service.guest_address


def _door_connection(door: str | tuple[str, int], timeout: float) -> http.client.HTTPConnection:
    if isinstance(door, str):
        return _UnixHTTPConnection(door, timeout)
    return http.client.HTTPConnection(*door, timeout=timeout)


def _tailnet_kwargs(guest_dir: Path | None, readable: bool, service: list) -> dict:
    """The readers of this host's tailnet name and of Serve for a guest door; a base constructor takes none (#1305).

    A readable name carries this host's own address, and Serve proxies the tailnet name to the
    service's own guest socket; `service` is filled with that service as it is built, so the proxy
    names the path the service keeps.
    """
    parameters = inspect.signature(ConsoleService).parameters
    if guest_dir is None or "status_reader" not in parameters:
        return {}
    kwargs: dict = {"status_reader": (lambda: {"Self": {"DNSName": TAILNET + ".",
                                                        "TailscaleIPs": [SELF_ADDRESS]}})
                    if readable else (lambda: None), "serve_seconds": 3600}
    if readable and "serve_reader" in parameters:
        kwargs["serve_reader"] = lambda: {"Web": {f"{TAILNET}:443": {"Handlers": {
            "/": {"Proxy": "unix:" + service[0].guest_socket}}}}}
    return kwargs


def start_service(fixture: Fixture, now_s: float, launches: list | None = None, *,
                  guest_dir: Path | None = None, tailnet_readable: bool = True) -> ConsoleService:
    def launcher(launch: manager.Launch) -> None:
        if launches is not None:
            launches.append(launch)

    forge: dict = {}
    if fixture.holding or fixture.deaf:
        forge = {"local_reader": lambda root, pattern: LocalReading((), False)}
    if fixture.holding:
        forge["pull_reader"] = lambda slug, pattern, *, cancelled: (
            PullRequest(7, frozenset(fixture.holding), False, None, True),)
    if fixture.activating:
        forge["activation_reader"] = _activation_reader(fixture.activating)
    bound: list = []
    service = ConsoleService(
        fixture.store, fixture.registry, port=0, session_dirs=lambda: [fixture.config / "sessions"],
        profile_dirs=lambda: sorted((fixture.accounts / "profiles").glob("*")), token_path=fixture.token, sprint_secrets=fixture.secrets,
        session_poll_seconds=3600, nudger=lambda nudge: None, launcher=launcher,
        activity=lambda root: None,
        slug_of=(lambda root: "owner/web") if fixture.holding else (lambda root: None),
        branch_pattern_of=lambda repo: "issue-<num>-<slug>" if fixture.holding else None,
        dispatch=lambda job: job(),
        repo_of=lambda cwd: cwd, ping_log=lambda: None,
        **({} if guest_dir is None else guest_door_kwargs(ConsoleService, guest_dir)),
        **_tailnet_kwargs(guest_dir, tailnet_readable, bound), **forge)
    bound.append(service)
    service.start()
    if guest_dir is not None and "status_reader" in inspect.signature(ConsoleService).parameters:
        service.poll_serve()
    service.poll_spend()
    if fixture.activating:
        service.poll_activation()
    if fixture.holding:
        _seed_lock_run(service, fixture, now_s)
        service.poll_movement()
    elif fixture.deaf:
        service.poll_movement()
    return service


def _guest_headers(door: str | tuple[str, int]) -> dict:
    """The headers Serve sends to `door`: a port door (the base commit) reads the tailnet name as its
    `Host`; a socket door reads `Host: localhost` and the name as its one `X-Forwarded-Host`."""
    if isinstance(door, str):
        return {"Host": "localhost", "X-Forwarded-Host": TAILNET}
    return {"Host": TAILNET}


def _guest_get(door: str | tuple[str, int], path: str = "/", *,
               login: str | None = COLLEAGUE,
               forwarded_for: str | None = None) -> http.client.HTTPResponse:
    """One GET to `door` carrying the door's host headers, the colleague's login header and, when given, `X-Forwarded-For`."""
    headers = _guest_headers(door)
    if login is not None:
        headers["Tailscale-User-Login"] = login
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    connection = _door_connection(door, 10)
    connection.request("GET", path, headers=headers)
    return connection.getresponse()


def guest_requests(state: str, door: str | tuple[str, int]) -> None:
    """The guest-door requests a sharing `state` makes before it is shot: `sharing-panel` one from
    this host itself, `sharing-reached` that and then one from another device, any other none."""
    if state in ("sharing-panel", "sharing-reached"):
        _guest_get(door, forwarded_for=SELF_ADDRESS).read()
    if state == "sharing-reached":
        _guest_get(door, forwarded_for=OTHER_DEVICE_ADDRESS).read()


class _Serve:
    """A loopback stand-in for Tailscale Serve in front of the guest port.

    Each GET is forwarded to the guest door `door` with the door's host headers (`_guest_headers`:
    `Host: TAILNET` for a port door, `Host: localhost` and `X-Forwarded-Host: TAILNET` for a socket
    door) and `Tailscale-User-Login: COLLEAGUE`, any incoming `Tailscale-*`, `X-Forwarded-For`,
    `X-Forwarded-Host` and `Host` dropped; the status and
    headers are copied and the body is streamed until EOF, each chunk flushed (the view stream
    is event-stream). `.address` is where a browser reads it; `.close()` stops it.
    """

    def __init__(self, door: str | tuple[str, int]):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                kept = {name: value for name, value in self.headers.items()
                        if not name.lower().startswith("tailscale-")
                        and name.lower() not in ("x-forwarded-for", "x-forwarded-host", "host")}
                connection = _door_connection(door, 3600)
                try:
                    connection.request("GET", self.path, headers={
                        **kept, **_guest_headers(door), "Tailscale-User-Login": COLLEAGUE})
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
            read: tuple[str, str] = (READ_QUESTION, READ_ANSWER),
            mutate: bool = False) -> list[Shot]:
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
                with tempfile.TemporaryDirectory(prefix="console-shots-") as tmp, \
                        tempfile.TemporaryDirectory(prefix="cg-", dir="/tmp") as door:
                    now_s = datetime.now(timezone.utc).timestamp()
                    service = start_service(
                        build_fixture(Path(tmp).resolve(), state, now_s, read=read), now_s,
                        guest_dir=Path(door) if state in SHARING_STATES else None,
                        tailnet_readable=state != "sharing-unreadable")
                    serve = None
                    try:
                        host, port = service.address
                        if state in SHARING_PANELS:
                            guest_requests(state, guest_door(service))
                        elif state == "guest-page":
                            serve = _Serve(guest_door(service))
                            host, port = serve.address
                        for width in widths:
                            path = "spend" if state == "spend-page" else ""
                            taken.append(
                                _shoot(browser, f"http://{host}:{port}/{path}", state, width, out,
                                       question=read[0],
                                       canonical=read == (READ_QUESTION, READ_ANSWER),
                                       mutate=mutate))
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


def read_style(page, rows: Sequence[StyleCheck], *, mutation: str | None = None,
               only: str | None = None) -> tuple[str, ...]:
    """Read each row's computed style on `page`, leaving no probe and no mutation behind."""
    page.evaluate(STYLE_CLEAR)
    if mutation is not None:
        page.evaluate(STYLE_MUTATE, mutation)
    page.evaluate(STYLE_PLACE, [asdict(row) for row in rows])
    page.evaluate(STYLE_SETTLE)
    read = [row for row in rows if only is None or row.name == only]
    found: list[str] = []
    plain = [row for row in read if not row.forced and not row.reduced_motion]
    if plain:
        found += page.evaluate(STYLE_READING, [asdict(row) for row in plain])
    for row in (row for row in read if row.forced):
        session = page.context.new_cdp_session(page)
        for method in ("DOM.enable", "CSS.enable"):
            session.send(method)
        root = session.send("DOM.getDocument")["root"]["nodeId"]
        if row.probe:
            mark = f'[data-style-probe="{row.name}"]'
            selector = f":is({mark}, {mark} *):is({row.selector})"
        else:
            selector = f":is({row.selector}):not([data-style-probe], [data-style-probe] *)"
        nodes = session.send("DOM.querySelectorAll", {"nodeId": root, "selector": selector})
        nodes = nodes["nodeIds"] if row.every else nodes["nodeIds"][:1]
        for node in nodes:
            session.send("CSS.forcePseudoState",
                         {"nodeId": node, "forcedPseudoClasses": list(row.forced)})
        page.evaluate(STYLE_SETTLE)
        found += page.evaluate(STYLE_READING, [asdict(row)])
        for node in nodes:
            session.send("CSS.forcePseudoState", {"nodeId": node, "forcedPseudoClasses": []})
    moving = [row for row in read if row.reduced_motion]
    if moving:
        page.emulate_media(reduced_motion="reduce")
        page.evaluate(STYLE_SETTLE)
        found += page.evaluate(STYLE_READING, [asdict(row) for row in moving])
        page.emulate_media(reduced_motion="no-preference")
    page.evaluate(STYLE_CLEAR)

    def place(miss: str) -> int:
        return next((n for n, row in enumerate(read) if miss.startswith(row.name + ": ")), len(read))

    return tuple(sorted(found, key=place))


def _shoot(browser, url: str, state: str, width: int, out: Path, *,
           question: str = READ_QUESTION, canonical: bool = True, mutate: bool = False) -> Shot:
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
        if state in SHARING_PANELS and page.query_selector("#sharing-open") is not None:
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
        activation = None
        if state in ACTIVATION_PATHS:
            activation = tuple(page.evaluate(ACTIVATION_READING))
        page.evaluate(SCROLL_TOP)
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        squeezed = page.evaluate(SQUEEZED_COUNT)
        jargon = page.evaluate(JARGON_COUNT)
        scroll_y = page.evaluate(SCROLL_Y)
        short = tuple(page.evaluate(SHORT_CONTROLS))
        acts = tuple(page.evaluate(ACTS_ROW))
        path = out / f"{state}-{width}.png"
        page.screenshot(path=str(path), full_page=True)
        style: tuple[str, ...] = ()
        checked: tuple[str, ...] = ()
        broke: tuple[str, ...] = ()
        if style_applies():
            for selector in STYLE_STEPS.get(state, ()):
                if page.query_selector(selector) is not None:
                    page.click(selector)
                    page.evaluate(STYLE_SETTLE)
            rows = [row for row in STYLE_CHECKS
                    if state in row.states and width in row.widths and (canonical or not row.fixture)]
            if rows:
                style = read_style(page, rows)
                checked = tuple(row.name for row in rows)
                if mutate:
                    broke = tuple(
                        row.name for row in rows
                        if any(miss.startswith(row.name + ": ") for miss in read_style(
                            page, rows, mutation=row.broken, only=row.name)))
    finally:
        page.close()
    return Shot(state, width, path, scroll_width, squeezed, jargon, tell, scroll_y=scroll_y,
                short=short, ask=ask, goal=goal, acts=acts, thread=thread, reading=reading,
                card=card, activation=activation, style=style, checked=checked, broke=broke)


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
    unlined = [shot for shot in taken if shot.state in ACTIVATION_SHOWN
               and shot.activation not in (
                   (ACTIVATION_SHOWN[shot.state],) if reads_other()
                   else (ACTIVATION_SHOWN[shot.state], ACTIVATION_BASE))]
    for shot in unlined:
        print(f"console-screenshots: {shot.path.name} does not show the activation line with its "
              "Activate button")
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
    broken = [shot for shot in taken if shot.style]
    for shot in broken:
        print(f"console-screenshots: {shot.path.name} breaks a page style "
              f"({'; '.join(shot.style)})")
    return 1 if (wide or squeezed or jargon or closed or unasked or unfilled or unthreaded or unread
                 or unlined or uncarded or offrow or scrolled or short or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
