"""A repeatable screenshot set of the console's sprint states (#1086).

Run: just console-screenshots [out]   (Playwright and its Chromium come from nixpkgs)

Contract:
- `STATES` names the fifty-seven screens the sprint block, the finished list, the message life, the
  Spend page, the notices fold, the desk's spend figures and the controls must read well on (`tell-box-open` is
  the sprint block with its Tell box opened; `owner-check` is the sprint block with a held
  issue's owner check beside it; `spend-page` is the `/spend` page over seeded transcripts: a
  running sprint's manager session, an outside-sprint session and one workflow run, with spend on
  at least four of the last seven days; `notices-fold` is `owner/web`'s open Notices fold
  over two sprints whose live-fault claims name one file: on the branch's console the sprint blocks
  show the overlap line and no card asks about it; on the base commit's console (`overlap_card()`)
  the seed also records the owner-only card the base contract had the later-started sprint send,
  which is the before picture (#1347);
  `notice-post-open` is that fold with the owner's post control opened, and shot against a page
  that has no such control it is the same fold, which is how the before pictures are made;
  `live-fault` is one running sprint with a live fault its manager declared on issue 12 (its
  `fault.declared` row is seeded as a literal kind, so the module needs nothing the base commit
  lacks): the sprint line carries the declaration and the owner's Withdraw, and on a base console
  that ignores the row the same sprint shows neither, which is the before picture (#1432);
  `waiting-its-turn` is a sprint whose only movement is the land lock held by a pull request of another issue,
  with the sprint's own pull request registered behind it (`console_land_queue`) and a live delivery run of the sprint's issue
  in its `pr` step (a run that is not live is no holder of the sprint's), whose run line reads "waiting its turn to
  merge, position 1", not quiet; a base console reads "waiting its turn to merge", the before picture;
  `manager-cannot-hear` is a running sprint whose manager session (listed, named for the sprint)
  has a transcript whose last peer-message record is one the client held and did not deliver
  (#1229), read once through the movement poll, so its line reads that the manager cannot hear
  the console; `permission-stale` is a running sprint whose manager session (listed, named for
  the sprint) folded working, then a `PermissionRequest` hook row for a Bash prompt, then a
  transcript whose `user` record is stamped after that hook (the 21 Nov reading: the manager's own
  hook refused the prompt at once and it went on working); on the branch's console the heading reads
  "Nothing needs you" and the session reads working after the first session poll, on the base
  commit's the same seed reads "1 thing needs you" with the terminal sentence, the before picture
  (#1424); `permission-card` is that sprint with its manager's held Bash prompt, `git worktree add
  ../.worktrees/issue-12` with the words "Create the delivery's worktree", posted to
  `/api/permission-prompt` by its literal path with the sprint's secret and kept held while shooting
  (a phase `wait` right before each width's shot), so the branch's console shows the card with Allow
  once and Refuse under "1 thing needs you"; on a console that does not know the route (the base answers 405) the seed
  is the `PermissionRequest` hook row only, which is the before picture; `permission-long` is the same sprint holding a
  long heredoc command (a python3 script that rewrites test names, a `cat` into `/tmp` and a `git diff` into `review/diff.txt`),
  so the card shows its summary of what it reads, runs and writes above the folded text, and the base console the raw text;
  `waiting-until` is the `stuck` sprint whose report states a wait until a time two hours
  ahead (#1380), so its line reads "waiting until" with that time, and `paused` the same sprint whose
  report states a pause with `PAUSE_REASON`, so its line reads "paused: " and the reason (a base console
  ignores both and reads the stage phrase, which is the before picture); `desk-spend` is the desk page over seeded transcripts: a running sprint and a finished,
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
  picture, its reading None).
  `deeper-offer` and `deeper-answer` seed the same desk, `owner/web` with no sprint and two
  threads: thread `DEEPER_THREAD`, a light answer (asked 40 minutes ago) and the Dig deeper
  answer to the same question on a stronger model (asked 30, answered 12), each with its own
  `Spent ...` line from a seeded transcript; and thread `DEEPER_OFFER_THREAD`, a light answer
  (asked 10 minutes ago) whose Dig deeper is still offered, so its estimate is the first
  thread's deeper spend (the spend before). On a page with the reading panel `deeper-answer`
  clicks the Questions fold and the first thread's line, then reads `DEEPER_READING` (the panel,
  each row's answer and spend line, Make it a goal; `DEEPER_ROWS` holds the seeded phrase and
  spend of each), and
  `deeper-offer` clicks the fold and the second thread's line and its Dig deeper (`DEEP_OPEN`,
  never Start, which alone posts), waits for the estimate, then reads `OFFER_READING` (the same, and the estimate's text, which
  must carry the deeper row's tokens and dollars, `DEEPER_ESTIMATE`); on a page without the panel
  each clicks the fold and its thread's summary (`DEEPER_BASE_THREAD`), which is the before
  picture, its `deeper` None; `main` prints `does not show` for a shot for which `deeper_shows`
  is false (`DEEPER_SAID`), a None reading passing only when `serves_reading_panel` is false.
  `activation-tooling` and `activation-host` are the desk with no sprint and an
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
  `guest-steer` is `guest-page` over a fixture of three `owner/web` sprints and a release confirm: two
  sprints the colleague started (every row of theirs carries `"by"`), one whose brief is approved and
  whose newest message is the colleague's answer to a plain question, so the line `Answered by
  COLLEAGUE: ...` shows, and one whose brief version 1 waits, so the page shows an open card the colleague
  can act on with its Approve and Ask for changes controls; and an owner sprint with an owner message;
  and one tracker card, a release confirm of `owner/web#12`, waiting on the owner, which the page
  draws as `.guest-wait` with no control. `owner-actors` is the owner's desk over the same seed.
  `owner-accounts` is that desk again with the accounts panel opened (`#capacity` clicked), the last state.
  `guest-page`, `guest-steer`, `owner-actors` and `owner-accounts` also hold the pool's three accounts, `work-main` and
  `work-spare`, each with a week and a 5h window, and `colleague-1`, which COLLEAGUE added himself (an
  `account.added` row `{"by": COLLEAGUE, "profile": "colleague-1", "identity": <the mark of its directory>}` written straight to the log, the identity without which his row has no token and the page no Sign out or Remove) and
  whose week is the tightest of the three (5% left against `work-spare`'s 10% and `work-main`'s 60%);
  every manager runs on `work-main`, so the guest page shows `yours`, `Account 2` and `Account 3` and
  the sprint's account, `Account 2`, and the owner's strip shows COLLEAGUE beside `colleague-1` in
  its tightest node, the one the 480 px width keeps. On a page with `#pool` the
  guest shots wait for the pool, a session reset and the sprint's account (`.sprint-account`); on a
  page without it they wait for none of them. On a page with `.pool-add` the `guest-page` and
  `guest-steer` shots click it at each width and wait for `.guest-consent` and a disabled
  `.guest-signin` (the consent open, nothing ticked, nothing posted); on a page without it they click
  nothing. `owner-actors` also waits for `.cap-tightest .cap-owner` on a page that has a `.cap-owner`
  and for none on a page that has not. `owner-accounts` waits for the opened panel (`#accounts:not([hidden])`)
  and, on a page that has an `.acct-owner`, for `.acct-row .acct-owner`. `offers_account_changes()`
  (`ConsoleService` has `sign_out_account`) keys the account controls on the code being shot, never on
  the page: when it is true `owner-accounts` also waits for `.acct-row .acct-signout` and `guest-page` for
  `.pool-yours .pool-signout` and `.pool-yours .pool-remove`, unconditionally, so a head capture whose page
  lacks a control times out and fails instead of writing a picture without it; on the base commit's archive
  it is false and neither waits, so a base run still writes every file. With `--sheets` `capture` also writes
  `<state>-sheet.png` after each state's widths, the shots side by side in one PNG that must stay
  under the 2 MiB a picture may be, and `main` prints each sheet's path after the shots. `--states a,b`
  shoots only the named states (each a member of `STATES`; the default is every state), and `--composite NAME`
  (only with `--sheets`) writes `NAME` after the last state: the named states' sheets side by side in one
  PNG under the same 2 MiB, which `main` prints after the sheets. Each
  width waits for what the owner judges to be visible, which fails the run when it is not:
  `guest-steer` the door check of `guest-page`, then `.started-by`, `Answered by`, `.guest-wait` and
  `#inbox button.approve`; `owner-actors` `.started-by` and `Answered by`. The rows are seeded
  straight into the event log, so the base commit's service, which ignores `by`, serves a page
  without those parts. On a page whose service does not read the actor (`reads_actors()` is False,
  `SprintState` having no `started_by`) those waits are skipped, so a base run still writes every
  file and the pictures are the before pictures of the actors.
  `register-apply` and `register-draft` are the console's registration of `sample-app`, a
  repository with no contract whose ready plan is drafted in schema 3 (`FACT_LINE`),
  served with a stand-in adopter and forge so the plan can be
  applied: `register-apply` is the ready Apply card of a project whose dev-shell hooks are not installed,
  opening on the line that says Apply installs them (`register.HOOKS_LINE`) before the plan's own (`REGISTER_PLAN_LINES`), with the registration entry reduced to "needs you"
  and no draft beside it; `register-draft` is the same plan after the owner chose Not now (the
  `adoption.deferred` row is seeded), so no card asks and the registration's draft rows show with
  the project id as a fact line with no Change control. `register-reconcile-apply` and
  `register-reconcile-draft` are the same two screens for a repository that already has a contract
  and pending adoption work, a `reconcile` plan (#1333): the row seeds the reading the console takes
  of a pre-commit hook whose runner is not on the plain PATH and of a `devenv.nix`, so the plan
  proposes the same command, and the first is the Apply card, the second the plan after Not now.
  `REGISTER_READING` reads the card's first
  line, the proposal's draft row and whether that row has a Change button, and `REGISTER_SHOWN`
  holds what each state must read on a page that proposes it (`proposes(state)`, which is
  `shows_facts()` for `register-draft` and `proposes_reconcile()` for the reconcile pair); on
  a page that does not (the base commit's) the reading is `REGISTER_BASE`, which is the before
  picture, and any other reading fails. The base commit's register-draft has no facts and drafts the
  commit environment as a main row with a Change button, so that row is its reading; its reconcile
  row has no draft, so its Apply card opens on the plan's own first line and shows nothing.
  `WIDTHS` are the two viewport widths each is shot at (`BETWEEN_WIDTHS` are read, never shot). `capture`
  writes `<state>-<width>.png` for every pair, so a full run writes 114 files.
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
  choices visible); or when a `deeper-offer` or `deeper-answer` shot on a page with the panel does not read as
  `deeper_shows` says (each row's seeded answer phrase and exact spend line, Make it a goal and,
  for the offer, the estimate holding the deeper row's figures), a None reading failing on a
  page that has the panel; or when a `questions-open` shot reads neither `OPEN_THREAD` (the fold
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
  and steps as `StyleCheck` and `STYLE_STEPS` say (`look-card` is shot with its viewer closed,
  then opens its first picture, so the viewer rows read it open). The style reading and its steps run only when
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
- `adoption-merge`, `adoption-moved` and `adoption-failed` are the adoption card of a pull request the console opened
  and read ready, seeded through a stand-in forge that reads it as it is: the first at the head
  the console pushed, so the card offers Merge, the second at another head, so the card says why
  it does not (#1338). The third is the first with Merge clicked, its stand-in forge refusing the
  merge and then reading the pull request merged at another head: the card has left the inbox and
  the page keeps the refusal as the "Could not merge the adoption" notice with its Dismiss button
  (the notice of a refused click whose card the forge's state removed); its two widths are
  served by two consoles, since the click cannot be repeated. On a page with no merge the opened step's `created` member is left out (a
  base console refuses it) and both shots wait only for the card, which is the before picture.
- `live-several` reads its issues' titles from a stand-in tracker on a console that takes a `title_reader`, and a base
  console draws its stage phrase, which is the before picture.
- The before pictures are the base commit's service, view and page together: this module imports
  nothing from `agent_tools` that the base commit lacks, so running it with `PYTHONPATH` at an
  archive of the base commit's `python/` (`git archive <base> python`) serves the base page over the
  same fixtures; swapping in only the base `page.html` is not a before picture, since the head view's
  `questions` object draws nothing on it. The after pictures run with `PYTHONPATH` at the branch. `guest_door_kwargs` and `guest_door` pick the
base commit's guest port or the branch's guest socket, so a base run still serves the guest states.
"""
from __future__ import annotations

import argparse
import base64
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
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_tools.console import account_add, approve, capacity, contract_draft, event_log, manager, pictures, register, sessions, signin, view
from agent_tools.console.activation import Activation
from agent_tools.console.answer import FORGE_DOWN
from agent_tools.console.event_log import SHARING_COLLEAGUE, SHARING_TAILNET, EventLog
from agent_tools.console.movement import LocalReading
from agent_tools.console.service import ConsoleService
from agent_tools.console.sprints import TELL_MINUTE_TEXT, Question, SprintState, create_secret
from agent_tools.system.forge_api import ForgeError

from . import console_screenshot_stand_ins as stand_ins
from .console_land_queue import land_queue_reader
from .console_screenshot_permissions import HELD_PROMPTS, PERMISSION_MANAGER, hold_permission, keep_permission
from .console_screenshot_stand_ins import UnixHTTPConnection as _UnixHTTPConnection, door_connection as _door_connection
from .console_test_support import hook_body, write_registry

STATES = ("live-several", "waiting-on-you", "stuck", "tell-box-open", "message-sent",
          "message-picked-up", "message-replied", "message-not-picked-up", "finished-list",
          "nothing-running", "waiting-its-turn", "manager-cannot-hear", "permission-stale", "permission-card",
          "permission-long", "waiting-until", "paused",
          "owner-check", "spend-page", "notices-fold",
          "notice-post-open", "live-fault", "desk-spend", "failed-start", "goal-open", "goal-near", "goal-over",
          "inbox-card", "question-words", "question-refused", "look-card", "look-moved",
          "look-failed", "accounts-panel", "ask-box", "questions-closed", "questions-open",
          "ask-goal", "question-read", "deeper-offer", "deeper-answer", "activation-tooling", "activation-host", "register-apply",
          "register-draft", "register-reconcile-apply", "register-reconcile-draft", "adoption-merge", "adoption-moved", "adoption-failed", "sharing-panel",
          "sharing-off", "sharing-unreadable", "sharing-reached", "guest-page", "guest-steer", "owner-actors",
          "owner-accounts")
WIDTHS = (1440, 480)
# The widths in between a row may also name: they take no picture, a row at one is read in the
# 1440 shot's page after its own rows, with the viewport resized to it.
BETWEEN_WIDTHS = (1180, 900)
STYLE_WIDTHS = (*WIDTHS, *BETWEEN_WIDTHS)
HEIGHT = 900
GOAL_NEAR_CHARS = 1900
GOAL_OVER_CHARS = 2100
MINUTE = 60.0
PAUSE_REASON = "the lead freed its account for a release"
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
                  "guest-page", "guest-steer")
SHARING_PANELS = ("sharing-panel", "sharing-off", "sharing-unreadable", "sharing-reached")
REGISTER_STATES = ("register-apply", "register-draft", "register-reconcile-apply",
                   "register-reconcile-draft")
ADOPTION_STATES = ("adoption-merge", "adoption-moved", "adoption-failed")
CLICKED_STATES = ("adoption-failed",)
PERMISSION_STATES = ("permission-stale", "permission-card", "permission-long")
ADOPTION_BRANCH = "adopt-" + "5" * 12
ADOPTION_COMMIT = "a" * 40
ADOPTION_MOVED_HEAD = "d" * 40
ADOPTION_PULL_ID = 1007
ADOPTION_CARD = "#inbox .adoption"
REGISTER_NAME = "sample-app"
REGISTER_PLAN_ID = "sha256:" + "6" * 64
REGISTER_PLAN_LINES = ["moves 2 agent files under .agents/", "writes the project contract"]
PROPOSAL_LINE = "commits run in its development shell: devenv shell (found in its files)"
FACT_LINE = "project id and issue tracker: GitHub, as owner/sample-app (read from its remote)"
REGISTER_SHOWN = {"register-draft": (None, FACT_LINE, False),
                  "register-reconcile-apply": (PROPOSAL_LINE, None, False),
                  "register-reconcile-draft": (None, PROPOSAL_LINE, True)}
REGISTER_BASE = {"register-draft": (None, PROPOSAL_LINE, True),
                 "register-reconcile-apply": (REGISTER_PLAN_LINES[0], None, False),
                 "register-reconcile-draft": (None, None, False)}
# The first line of the Apply card's list, the proposal's draft row and whether that row carries a
# visible Change button; None for what the page does not show.
REGISTER_READING = """(() => {
  const shown = (node) => node && node.getClientRects().length > 0;
  const first = document.querySelector('.apply-lines li');
  const row = Array.from(document.querySelectorAll('ul.register-draft > li')).find((item) => {
    const line = item.querySelector('.draft-line');
    return shown(line) && /^(commits run in its development shell|project id and issue tracker)/.test(line.textContent.trim());
  });
  const change = row ? row.querySelector('button.draft-change') : null;
  return [shown(first) ? first.textContent.trim() : null,
          row ? row.querySelector('.draft-line').textContent.trim() : null, Boolean(shown(change))];
})()"""
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
READING_PANEL_ID = b'id="reading"'
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
# The Dig deeper states (#1435): thread 1 holds a light answer and its deeper answer, thread 2 a
# light answer whose Dig deeper is still offered, so its estimate is thread 1's deeper spend.
DEEPER_STATES = ("deeper-offer", "deeper-answer")
# The panel's reading of the deeper thread: whether the panel shows, each shown row's answer and
# spend line text (whitespace collapsed), and whether the last row shows Make it a goal.
DEEPER_READING = """(() => {
  const shown = (node) => Boolean(node && node.getClientRects().length > 0);
  const text = (node) => (node && shown(node) ? node.textContent.replace(/\\s+/g, ' ').trim() : '');
  const panel = document.querySelector('#reading');
  if (!shown(panel)) return [false, [], false];
  const rows = Array.from(panel.querySelectorAll('ol.ask-list > li.ask')).filter(shown);
  const last = rows.length ? rows[rows.length - 1] : null;
  return [true,
          rows.map((row) => [text(row.querySelector('.ask-answer')), text(row.querySelector('p.ask-spend'))]),
          Boolean(last && shown(last.querySelector('button.ask-goal')))];
})()"""
# The panel's reading of the Dig deeper offer once its confirmation is open: the same three members
# and, last, the text of the estimate the confirmation shows ('' when it shows none).
OFFER_READING = """(() => {
  const shown = (node) => Boolean(node && node.getClientRects().length > 0);
  const text = (node) => (node && shown(node) ? node.textContent.replace(/\\s+/g, ' ').trim() : '');
  const panel = document.querySelector('#reading');
  if (!shown(panel)) return [false, [], false, ''];
  const rows = Array.from(panel.querySelectorAll('ol.ask-list > li.ask')).filter(shown);
  return [true,
          rows.map((row) => [text(row.querySelector('.ask-answer')), text(row.querySelector('p.ask-spend'))]),
          shown(panel.querySelector('button.ask-goal')), text(panel.querySelector('p.ask-deep-estimate'))];
})()"""
# What each picture must read, from the seed: per row a phrase its answer holds and its spend line
# exactly (the figures follow from the seeded transcripts at the published per-million rates).
DEEPER_LIGHT_SNIPPET = "do not say which parts of an issue take long"
DEEPER_SNIPPET = "Review and planning take most of the time; the tasks take most of the tokens."
DEEPER_OFFER_SNIPPET = "The test check fails most often: 9 of the last 40 pull requests"
DEEPER_ESTIMATE = "Earlier deeper answers here spent about 2,184,000 tokens, $2.76 each."
DEEPER_ROWS = {
    "deeper-answer": ((DEEPER_LIGHT_SNIPPET, "Spent 544,000 tokens, about $0.38"),
                      (DEEPER_SNIPPET, "Spent 2,184,000 tokens, about $2.76")),
    "deeper-offer": ((DEEPER_OFFER_SNIPPET, "Spent 362,000 tokens, about $0.25"),)}
# The least a finished reading holds, and the reading a page without the panel gives (None).
DEEPER_SHOWN = {"deeper-answer": (True, DEEPER_ROWS["deeper-answer"], True),
                "deeper-offer": (True, DEEPER_ROWS["deeper-offer"], True, DEEPER_ESTIMATE)}


def _frozen(value):
    """A reading from the page (nested lists) as nested tuples."""
    return tuple(_frozen(item) for item in value) if isinstance(value, list) else value


def deeper_shows(state: str, deeper) -> bool:
    """Whether a deeper state's reading is its seeded rows (answer phrase and exact spend), Make it a goal and, for the offer, the deeper row's figures."""
    want = DEEPER_ROWS[state]
    if not isinstance(deeper, tuple) or len(deeper) != (4 if state == "deeper-offer" else 3):
        return False
    panel, rows, goal = deeper[:3]
    if panel is not True or goal is not True or len(rows) != len(want):
        return False
    for (answer, spend), (snippet, spent) in zip(rows, want):
        if snippet not in answer or spend != spent:
            return False
    return state != "deeper-offer" or DEEPER_ESTIMATE in deeper[3]


DEEPER_SAID = {
    "deeper-offer": "the Dig deeper estimate with the answer's spend line and Make it a goal",
    "deeper-answer": "the deeper answer with its spend lines and Make it a goal"}
DEEP_OPEN = "#reading button.ask-deep"
DEEP_ESTIMATE = "#reading p.ask-deep-estimate"
DEEPER_BASE_THREAD = {
    "deeper-offer": 'details[data-key="thread:owner/web:1435b1"] > summary',
    "deeper-answer": 'details[data-key="thread:owner/web:1435a1"] > summary'}
DEEPER_THREAD = "1435a1"
DEEPER_ID = "1435a2"
DEEPER_QUESTION = "Where do agents spend time and tokens on issues, and which parts take long?"
DEEPER_LIGHT_SESSION = "4a8e2c61-9d3f-4b70-8e15-c2f6a9d4b183"
DEEPER_SESSION = "b7d14e93-2a6c-4f85-9b30-e8c5f1a27d46"
DEEPER_LIGHT_ANSWER = (
    "Answer: The console's records hold spend by day and project, not by phase or issue, so they "
    "do not say which parts of an issue take long.\n"
    "Read: the console's records\n"
    "Ran: none\n"
    "Could not find out: the time and tokens of each phase\n"
    "Question for you: none")
DEEPER_ANSWER = "\n".join((
    "Answer: **Review and planning take most of the time; the tasks take most of the tokens.** "
    "Over the last 30 days, 14 delivery runs:",
    "",
    "- Plan: 31% of the agent-seconds, 18% of the tokens",
    "- Tasks: 44% of the agent-seconds, 61% of the tokens",
    "- Review: 25% of the agent-seconds, 21% of the tokens",
    "",
    "Issue 12 took longest: 3 runs and 2 h 10 min, most of it in review.",
    "Read: the transcripts part of the console's records",
    "Ran: none",
    "Could not find out: none",
    "Question for you: none"))
DEEPER_OFFER_THREAD = "1435b1"
DEEPER_OFFER_QUESTION = "Which checks fail most often on this project's pull requests?"
DEEPER_OFFER_SESSION = "e3c95a07-6b2d-4e18-a4f9-0d7b3c58e912"
DEEPER_OFFER_ANSWER = (
    "Answer: The test check fails most often: 9 of the last 40 pull requests, then the lint "
    "check on 4.\n"
    "Read: the console's records\n"
    "Ran: none\n"
    "Could not find out: none\n"
    "Question for you: none")


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
    registering: bool = False
    adopting: bool = False
    refusing: bool = False
    prompting: str = ""
    titled: bool = False


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
    `fills` reads each match against its parent's content width, `right_edge` that its right edge
    stands at its parent's content edge, `hugs` that its content box is no wider than its text, and
    `largest_type` (`value` is `<px>|<selector list>`) that no element under `selector` has a
    `font-size` of `<px>` or more unless it matches the list. `track_max` (`value` is
    `<index>:<fraction>`) wants the px track at that 1-based index of the resolved
    `grid-template-columns` to be at most that fraction of the content width, and `tracks` (`value`
    is a count) that the grid has exactly that many top-level tracks. `alpha_max` wants the colour
    to be clear or to have an alpha of at most `value`, `opaque` that it is one palette colour at
    alpha 1, and `follows_shape` that a loaded `img` is as tall as its own shape makes it at its
    width, within its `min-height` and `max-height`. `kind_look` (`value` is the comma-separated
    list of properties) compares every rendered control of the seven kinds outside a state
    (disabled, busy, pressed, picked, hovered, active or focused) with a bare scratch element of
    its kind on those properties, only the borders for a bare control, and wants each to be at
    least 32px tall; `contrast` wants the WCAG ratio of the colour (of `pseudo`) against the first
    opaque background behind it to be at least `value` (a colour the page cannot read as RGB is a
    named miss, `unreadable <colour>`); `declared` wants the value the CSSOM cascade gives `prop`
    of the `pseudo` rules matching the subject (for a pseudo-element no engine resolves) to be
    `value`. A width in `BETWEEN_WIDTHS` is read in the 1440 shot's page, resized to it.
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


# The selectors clicked, in order, after a state's picture and before its style reading: the
# look card opens its first picture in the viewer, so the viewer rows read what the owner sees.
STYLE_STEPS: dict[str, tuple[str, ...]] = {"look-card": ("button.pic-thumb",)}
WANTS = frozenset({"equals", "in", "not", "starts", "min", "max", "same_as", "gt",
                   "none_peach", "palette", "tokens", "distinct", "sizes_shared", "fills",
                   "largest_type", "right_edge", "hugs", "track_max", "tracks", "alpha_max",
                   "opaque", "follows_shape", "kind_look", "contrast", "declared"})
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
    "opaque": list(PALETTE.values()),
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
# The guest pages are read only by the guest rows (#1313).
_GUEST_PAGES = ("guest-page", "guest-steer")
_EVERY_STATE = tuple(state for state in STATES if state not in _GUEST_PAGES)
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
    # A colour painted by a gradient's stops is as prohibited as one painted flat (#1313).
    StyleCheck("peach-only-needs-gradient", _EVERY_STATE, _BOTH, "body", "background-image",
               "none_peach", _NEEDS,
               ".top-in { background-image: linear-gradient(rgb(245, 169, 127), rgb(36, 39, 58)) !important }"),
    StyleCheck("runs-not-red", ("live-several", "waiting-its-turn"), (1440,),
               ".run, .runs, .moved, .quiet", "color", "not", PALETTE["--red"],
               ".run, .runs, .moved, .quiet { color: rgb(237, 135, 150) !important }", every=True),
    StyleCheck("palette-notices", ("notices-fold",), _BOTH, ".line.notices", "color", "palette",
               "notices", ".notice-label { color: rgb(183, 189, 248) !important }"),
    StyleCheck("palette-notices-gradient", ("notices-fold",), _BOTH, ".line.notices",
               "background-image", "palette", "notices",
               ".notice { background-image: linear-gradient(var(--peach), var(--base)) !important }"),
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
_DESK_STATES = tuple(state for state in _EVERY_STATE if state != "spend-page")
_RGB = "rgb(1, 2, 3)"


def _row(name, states, selector, prop, want, value, bad, widths=_BOTH, **kw):
    """A row reading `selector`'s `prop`, broken by a rule that sets the property to `bad`."""
    states = (states,) if isinstance(states, str) else tuple(states)
    return StyleCheck(name, states, tuple(widths), selector, prop, want, value,
                      f"{selector}{kw.get('pseudo', '')} {{ {prop}: {bad} !important }}", **kw)


def _group(prefix, states, selector, reads, widths=_BOTH, **kw):
    """The rows `<prefix>-<prop>` of one selector, one per `(prop, want, value, bad)` read."""
    return tuple(_row(f"{prefix}-{prop}", states, selector, prop, want, value, bad, widths, **kw)
                 for prop, want, value, bad in reads)


_NOTHING = "nothing-running"
_OPEN_GOAL = ".goal-bar.open .goal-count"
_PLAIN_BACKGROUND = "rgba(0, 0, 0, 0)"
_INLINE_BLOCK = (("display", "equals", "inline-block", "block"),
                 ("max-width", "equals", "100%", "none"),
                 ("overflow", "equals", "hidden", "visible"),
                 ("text-overflow", "equals", "ellipsis", "clip"),
                 ("white-space", "equals", "nowrap", "normal"),
                 ("vertical-align", "equals", "bottom", "top"))
_SEC_UI = '<span class="sec-ui" style="font-family: var(--ui)" data-style-probe></span>'
_DISPLAY_LEAD = (".statement h1, .statement h1 *, .card .q, .card .q *, .reading-question, "
                 ".reading-question *")
_SEC_H = (("font-style", "equals", "normal", "italic"),
          ("font-weight", "equals", "600", "400"),
          ("font-size", "equals", "15px", "30px"),
          ("line-height", "equals", "21px", "40px"),
          ("color", "equals", PALETTE["--text"], _RGB))


def _sec_h(prefix, selector, **kw):
    return (*_group(prefix, _NOTHING, selector, _SEC_H, **kw),
            _row(f"{prefix}-font-family", _NOTHING, selector, "font-family", "same_as", ".sec-ui",
                 "serif", compare_probe=_SEC_UI, compare_host="#digest", **kw))


STYLE_CHECKS += (
    *_group("top-wrap", _NOTHING, ".top-in", (("flex-wrap", "equals", "wrap", "nowrap"),)),
    *_group("top-wrap", _NOTHING, ".top-in", (
        ("row-gap", "equals", "10px", "1px"), ("column-gap", "equals", "28px", "1px"),
        ("gap", "equals", "10px 28px", "1px")), widths=(1440,)),
    _row("statement-narrow-font-size", _NOTHING, ".statement h1", "font-size", "max", "37.9",
         "3rem", widths=(480,),
         probe='<div class="statement" data-style-probe><h1>x</h1></div>', host="body"),
    *_group("goal-box", "goal-open", ".goal-box", (
        ("max-height", "max", "900", "none"), ("overflow-y", "equals", "auto", "visible"))),
    _row("goal-box-width-1440", "goal-open", ".goal-box", "width", "max", "600", "700px",
         widths=(1440,)),
    _row("goal-box-width-480", "goal-open", ".goal-box", "width", "max", "448", "700px",
         widths=(480,)),
    *_group("goal-projects", "goal-open", ".goal-projects", (
        ("min-width", "equals", "0px", "50px"), ("max-width", "equals", "100%", "none"),
        ("overflow-y", "equals", "auto", "visible"), ("flex", "equals", "0 1 auto", "1 1 auto"),
        ("min-height", "equals", "0px", "50px"))),
    *_group("goal-projects-li", "goal-open", ".goal-projects li", (
        ("min-width", "equals", "0px", "50px"), ("max-width", "equals", "100%", "none"))),
    *_group("goal-project", "goal-open", ".goal-project", (
        ("min-width", "equals", "0px", "50px"), ("max-width", "equals", "100%", "none"),
        ("overflow-wrap", "equals", "anywhere", "normal"))),
    _row("goal-filter-min-width", "goal-open", ".goal-filter", "min-width", "equals", "0px",
         "50px"),
    _row("goal-act-flex", "goal-open", ".goal-act", "flex", "equals", "0 0 auto", "1 1 auto"),
    _row("goal-bar-flex-480", _NOTHING, ".goal-bar", "flex", "equals", "1 0 100%", "1 1 10px",
         widths=(480,)),
    _row("goal-bar-max-width-480", _NOTHING, ".goal-bar", "max-width", "equals", "none", "300px",
         widths=(480,)),
    _row("goal-bar-flex-1440", _NOTHING, ".goal-bar", "flex", "equals", "1 1 192px", "0 0 10px",
         widths=(1440,)),
    _row("goal-bar-min-width-1440", _NOTHING, ".goal-bar", "min-width", "equals", "192px", "10px",
         widths=(1440,)),
    _row("goal-bar-max-width-1440", _NOTHING, ".goal-bar", "max-width", "equals", "440px", "300px",
         widths=(1440,)),
    *_group("placeholder", _NOTHING, ".goal-in .goal-text", (
        ("white-space", "equals", "nowrap", "normal"), ("overflow", "equals", "hidden", "visible"),
        ("text-overflow", "equals", "ellipsis", "clip")), pseudo="::placeholder"),
    _row("placeholder-host-text-overflow", _NOTHING, ".goal-in .goal-text", "text-overflow",
         "equals", "ellipsis", "clip"),
    _row("goal-focus-border-color", _NOTHING, ".goal-in", "border-color", "equals",
         PALETTE["--lav"], _RGB, forced=("focus-within",)),
    _row("goal-focus-outline", _NOTHING, ".goal-in .field-bare", "outline", "equals",
         "rgb(202, 211, 245) none 0px", "2px solid " + _RGB,
         forced=("focus-visible",)),
    _row("goal-count-closed-display", _NOTHING, ".goal-count", "display", "equals", "none", "block",
         probe='<span class="goal-count" data-style-probe></span>', host="#goal"),
    *_group("goal-count", "goal-open", _OPEN_GOAL, (
        ("display", "equals", "block", "none"), ("position", "equals", "absolute", "static"),
        ("color", "equals", PALETTE["--ov2"], _RGB), ("white-space", "equals", "normal", "nowrap"),
        ("flex-basis", "equals", "auto", "300px"), ("min-width", "in", "auto|0px", "300px"))),
    _row("goal-count-width", "goal-open", _OPEN_GOAL, "width", "hugs", "", "300px"),
    _row("goal-count-near-color", "goal-near", _OPEN_GOAL, "color", "equals", PALETTE["--ov2"],
         _RGB),
    *_group("goal-count-over", "goal-over", ".goal-count.over", (
        ("color", "equals", PALETTE["--red"], _RGB), ("white-space", "equals", "normal", "nowrap"),
        ("flex-basis", "equals", "auto", "300px"), ("min-width", "in", "auto|0px", "300px"))),
    _row("goal-count-over-width", "goal-over", ".goal-count.over", "width", "hugs", "", "300px"),
    *_group("goal-status", "goal-open", ".goal-status", (
        ("display", "not", "none", "none"), ("visibility", "equals", "visible", "hidden")),
        probe='<p class="goal-status" data-style-probe>Could not send: this project is not '
              'registered</p>', host="#goal .goal-box"),
    _row("goal-status-empty-display", "goal-open", ".goal-status:empty", "display", "equals",
         "none", "block", probe='<p class="goal-status" data-style-probe></p>',
         host="#goal .goal-box"),
    *_group("fail-shown", _NOTHING, ".fail", (
        ("display", "not", "none", "none"), ("visibility", "equals", "visible", "hidden")),
        probe='<p class="fail" data-style-probe>x</p>', host="#inbox"),
    *_group("cap", "accounts-panel", ".cap", (
        ("flex", "equals", "0 0 auto", "1 1 auto"), ("overflow", "equals", "hidden", "visible"),
        ("min-width", "equals", "0px", "50px"), ("max-width", "equals", "100%", "none"),
        ("white-space", "equals", "nowrap", "normal"), ("flex-wrap", "equals", "nowrap", "wrap"),
        ("font-size", "equals", "13px", "20px"), ("color", "equals", PALETTE["--sub0"], _RGB),
        ("cursor", "equals", "pointer", "default"), ("text-align", "equals", "left", "right"),
        ("padding", "equals", "0px", "9px"), ("font-style", "equals", "normal", "italic"),
        ("font-weight", "equals", "400", "700"), ("line-height", "equals", "19.5px", "40px"),
        ("background-image", "equals", "none", "linear-gradient(red, red)"))),
    _row("cap-font-family", "accounts-panel", ".cap", "font-family", "same_as", "body", "serif"),
    _row("cap-background-color", _NOTHING, ".cap", "background-color", "equals", _PLAIN_BACKGROUND,
         _RGB),
    _row("cap-child-flex", "accounts-panel", ".cap > *", "flex", "equals", "0 0 auto", "1 1 auto",
         every=True),
    _row("cap-acct-max-width", "accounts-panel", ".cap-acct", "max-width", "equals", "100%",
         "none"),
    _row("cap-acct-white-space", "accounts-panel", ".cap-acct", "white-space", "equals", "nowrap",
         "normal"),
    *_group("cap-acct-name", "accounts-panel", ".cap-acct b", (
        ("overflow", "equals", "hidden", "visible"), ("text-overflow", "equals", "ellipsis", "clip"),
        ("white-space", "equals", "nowrap", "normal"), ("max-width", "max", "160", "none"))),
    _colour("cap-excl-color", "accounts-panel", ".cap-excl", "--ov2", host="#capacity",
            probe='<span class="cap-excl" data-style-probe>x</span>'),
    _colour("cap-pin-mark-color", "accounts-panel", ".cap-pin-mark", "--ov2", host="#capacity",
            probe='<span class="cap-pin-mark" data-style-probe>x</span>'),
    _row("cap-extra-display", "accounts-panel", ".cap-extra", "display", "equals", "none", "block",
         widths=(480,), probe='<span class="cap-extra" data-style-probe>x</span>',
         host="#capacity"),
    _row("brand-white-space", _NOTHING, ".brand", "white-space", "equals", "nowrap", "normal"),
    _row("top-fit-width", _NOTHING, ".top-in > *", "width", "max", "448", "600px", widths=(480,),
         every=True),
    _row("top-fit-min-width", _NOTHING, ".goal-bar, .cap", "min-width", "max", "448", "600px",
         widths=(480,), every=True),
    _row("top-fit-flex-basis", _NOTHING, ".goal-bar", "flex-basis", "max", "448", "600px",
         widths=(480,)),
    _row("top-fit-meter-width", "accounts-panel", ".meter", "width", "max", "448", "600px",
         widths=(480,), every=True),
    _row("top-fit-meter-min-width", "accounts-panel", ".meter", "min-width", "in", "auto|0px",
         "600px", widths=(480,), every=True),
    _row("top-fit-meter-flex-basis", "accounts-panel", ".meter", "flex-basis", "equals", "auto",
         "600px", widths=(480,), every=True),
    _row("meter-fill-background-color", _NOTHING, ".meter i", "background-color", "equals",
         PALETTE["--sub0"], _RGB, probe='<span class="meter" data-style-probe><i></i></span>',
         host="#capacity"),
    _row("meter-fill-background-image", _NOTHING, ".meter i", "background-image", "equals", "none",
         "linear-gradient(red, red)",
         probe='<span class="meter" data-style-probe><i></i></span>', host="#capacity"),
    _row("meter-excluded-background-color", _NOTHING, ".cap-excluded .meter i", "background-color",
         "equals", PALETTE["--s2"], _RGB,
         probe='<span class="cap-acct cap-excluded" data-style-probe><span class="meter"><i></i>'
               '</span></span>', host="#capacity"),
    _row("meter-excluded-background-image", _NOTHING, ".cap-excluded .meter i",
         "background-image", "equals", "none", "linear-gradient(red, red)",
         probe='<span class="cap-acct cap-excluded" data-style-probe><span class="meter"><i></i>'
               '</span></span>', host="#capacity"),
    StyleCheck("lead-type-font-size", _DESK_STATES, _BOTH, "body", "font-size", "largest_type",
               "24|" + _DISPLAY_LEAD, ".brand { font-size: 30px !important }", fixture=True),
    _row("lead-type-card-font-size", "inbox-card", ".card .q", "font-size", "equals", "24px",
         "20px"),
    _row("lead-type-card-font", "inbox-card", ".card .q", "font", "starts", "600 24px / 31.2px ",
         "20px serif"),
    _row("lead-type-reading-font-size", "question-read", ".reading-question", "font-size",
         "equals", "24px", "20px", fixture=True),
    _row("lead-type-reading-font", "question-read", ".reading-question", "font", "starts",
         "600 24px / 31.2px ", "20px serif", fixture=True),
    *_group("lead-narrow", "inbox-card", ".card.lead", (
        ("padding-left", "max", "16", "40px"), ("padding-right", "max", "16", "40px"),
        ("padding", "equals", "20px 16px", "9px")), widths=(480,)),
    _row("q-full-width-text-wrap", "inbox-card", ".card .q", "text-wrap", "equals", "pretty",
         "balance"),
    _row("q-full-width-reg-text-wrap", "inbox-card", ".card .q.reg", "text-wrap", "not", "balance",
         "balance",
         probe='<div class="card" data-style-probe><p class="q reg">x</p></div>'),
    _row("q-full-width-rest-text-wrap", "inbox-card", ".rest .q.reg", "text-wrap", "not",
         "balance", "balance",
         probe='<div class="rest" data-style-probe><p class="q reg">x</p></div>'),
    _row("reg-ask-font-size-1440", "inbox-card", ".card .q.reg", "font-size", "equals", "20px",
         "30px", widths=(1440,),
         probe='<div class="card" data-style-probe><p class="q reg">x</p></div>'),
    _row("reg-ask-font-size-480", "inbox-card", ".card .q.reg", "font-size", "max", "16", "30px",
         widths=(480,), probe='<div class="card" data-style-probe><p class="q reg">x</p></div>'),
    *_group("reg-ask-rest", "inbox-card", ".rest .q.reg", (
        ("font-weight", "equals", "600", "400"), ("font-size", "equals", "16px", "30px"),
        ("line-height", "equals", "22.4px", "40px"),
        ("font", "starts", "600 16px / 22.4px ", "20px serif")),
        probe='<div class="rest" data-style-probe><p class="q reg">x</p></div>'),
    *_group("seg", "inbox-card", ".seg", (
        ("display", "equals", "inline-block", "inline"), ("max-width", "equals", "100%", "none"),
        ("overflow-wrap", "equals", "anywhere", "normal")),
        probe='<span class="seg" data-style-probe>x</span>', host="#inbox"),
    *_group("held-blocks", "inbox-card", ".held.blocks", (
        ("white-space", "equals", "nowrap", "normal"), ("overflow", "equals", "hidden", "visible"),
        ("text-overflow", "equals", "ellipsis", "clip")),
        probe='<p class="held blocks" data-style-probe>x</p>', host="#inbox"),
    _row("notice-margin-top", "notices-fold", ".notice + .notice", "margin-top", "equals", "12px",
         "0px"),
    _row("notice-head-display", "notices-fold", ".notice-head", "display", "equals", "flex",
         "block"),
    _row("notice-head-flex-wrap", "notices-fold", ".notice-head", "flex-wrap", "equals", "nowrap",
         "wrap"),
    _row("notice-who-flex", "notices-fold", ".notice-who", "flex", "equals", "1 1 auto",
         "0 0 auto"),
    _row("notice-who-min-width", "notices-fold", ".notice-who", "min-width", "equals", "0px",
         "50px"),
    _row("notice-who-display", "notices-fold", ".notice-who", "display", "equals", "block",
         "flex"),
    _row("notice-label-display", "notices-fold", ".notice-label", "display", "equals", "inline",
         "inline-block"),
    _row("notice-from-display", "notices-fold", ".notice-from", "display", "equals", "inline",
         "inline-block"),
    StyleCheck("notice-age-right", ("notices-fold",), _BOTH, ".notice-head .notice-age", "right",
               "right_edge", "", ".notice-head .notice-age { margin-right: 40px !important }"),
    _row("notice-age-margin-left", "notices-fold", ".notice-head .notice-age", "margin-left",
         "min", "0", "-5px"),
    _row("notice-age-flex", "notices-fold", ".notice-head .notice-age", "flex", "equals",
         "0 0 auto", "1 1 auto"),
    _colour("notice-age-color", "notices-fold", ".notice-head .notice-age", "--ov2",
            widths=_BOTH),
    _colour("notice-words-color", "notices-fold", ".notice-words", "--text", widths=_BOTH),
    *_group("notice-code", "notices-fold", ".notice code", (
        ("background-color", "equals", PALETTE["--mantle"], _RGB),
        ("background-image", "equals", "none", "linear-gradient(red, red)"),
        *_INLINE_BLOCK), probe='<p class="notice" data-style-probe><code>x</code></p>'),
    *_group("notice-child", "notices-fold", ".notice > *", (
        ("overflow-wrap", "equals", "anywhere", "normal"), ("min-width", "equals", "0px", "50px")),
        every=True),
    *_group("notices-project", "notices-fold", ".notices-project", (
        ("overflow-wrap", "equals", "anywhere", "normal"), ("margin-left", "equals", "10px",
                                                           "0px"))),
    *_group("notice-long", "notices-fold", ".notice .notice-long", _INLINE_BLOCK,
            probe='<p class="notice" data-style-probe><span class="notice-long">x</span></p>'),
    _row("notice-gap-open", "notices-fold", ".notice-list + .notice-open", "margin-top", "min",
         "12", "4px",
         probe='<div data-style-probe><ul class="notice-list"></ul><p class="notice-open">x</p>'
               '</div>'),
    _row("notice-gap-post", "notice-post-open", ".notice-list + .notice-post", "margin-top", "min",
         "12", "4px",
         probe='<div data-style-probe><ul class="notice-list"></ul><p class="notice-post">x</p>'
               '</div>'),
    *(_row(f"disclosure-{name}-{prop}", state, selector, prop, want, value, bad)
      for name, state, selector in (("notices", "notices-fold", ".line.notices summary"),
                                    ("finished", "finished-list", ".finished-list > summary"),
                                    ("sprint", "live-several", ".sprint-detail summary"))
      for prop, want, value, bad in (
          ("display", "equals", "list-item", "block"),
          ("list-style-type", "in", "disclosure-closed|disclosure-open", "none"))),
    # No engine resolves the marker's own style, so its declared display is read from the cascade.
    _row("disclosure-notices-marker-display", "notices-fold", ".line.notices summary", "display",
         "declared", "revert", "none", pseudo="::-webkit-details-marker"),
    _row("thread-open-display", "questions-open", ".thread-open", "display", "equals", "flex",
         "block"),
    _row("thread-summary-display", "questions-open", ".line.questions > details > summary",
         "display", "equals", "list-item", "block"),
    _row("thread-summary-list-style-type", "questions-open", ".line.questions > details > summary",
         "list-style-type", "in", "disclosure-closed|disclosure-open", "none"),
    *_group("thread-first", "questions-open", ".thread-first", (
        ("text-overflow", "equals", "ellipsis", "clip"), ("white-space", "equals", "nowrap",
                                                          "normal"),
        ("flex", "equals", "1 1 auto", "0 0 auto"))),
    _row("reading-weight-panel", "question-read", "#reading", "font-weight", "equals", "400",
         "700"),
    _row("reading-weight-call-out", "question-read", "p.reading", "font-weight", "equals", "600",
         "400", probe='<p class="reading" data-style-probe>x</p>', host="#reading"),
    _row("answer-type-white-space", "question-read", ".ask-answer p", "white-space", "equals",
         "pre-line", "normal", fixture=True),
    _row("answer-type-font-size", "question-read", ".ask-answer", "font-size", "same_as", ".opt .ot",
         "30px", fixture=True,
         compare_probe='<div class="opt" data-style-probe><span class="ot">x</span></div>',
         compare_host="#reading"),
    _row("answer-type-p-font-size", "question-read", ".ask-answer p", "font-size", "same_as",
         ".ask-answer", "30px", fixture=True),
    _row("answer-type-li-font-size", "question-read", ".ask-answer li", "font-size", "same_as",
         ".ask-answer", "30px", fixture=True),
    _row("answer-type-list-font-size", "question-read", ".ask-answer .md-list", "font-size",
         "same_as", ".ask-answer", "30px", fixture=True),
    _row("answer-type-font", "question-read", ".ask-answer p", "font", "same_as", ".ask-answer",
         "20px serif", fixture=True),
    _row("answer-type-li-font", "question-read", ".ask-answer li", "font", "same_as", ".ask-answer",
         "20px serif", fixture=True),
    _row("answer-type-list-font", "question-read", ".ask-answer .md-list", "font", "same_as",
         ".ask-answer", "20px serif", fixture=True),
    # Each list kind is read on its own rendered subject, since the canonical answer holds a
    # bulleted list only (#1313).
    *(_row(f"answer-type-{kind}-{key}", "question-read", f".ask-answer {kind}.md-list", prop,
           "same_as", ".ask-answer", bad, host="#reading",
           probe=f'<div class="ask-answer" data-style-probe><{kind} class="md-list"><li>x</li>'
                 f'</{kind}></div>')
      for kind in ("ul", "ol")
      for key, prop, bad in (("font-size", "font-size", "30px"), ("font", "font", "20px serif"))),
    *(_row(f"digest-lines-{name}-{prop}", _NOTHING, f"{list_} li", prop, want, value, bad,
           probe='<div data-style-probe><ul class="digest"><li><time class="at">x</time>'
                 '<span class="said">y</span></li></ul><ul class="earlier-list"><li>'
                 '<time class="at">x</time><span class="said">y</span></li>'
                 '<li class="more-n">and 2 more</li></ul></div>', host="#digest")
      for name, list_ in (("digest", ".digest"), ("earlier", ".earlier-list"))
      for prop, want, value, bad in (
          ("display", "equals", "grid", "block"),
          ("grid-template-columns", "starts", "88px ", "1fr"),
          ("flex-wrap", "equals", "nowrap", "wrap"))),
    *_group("digest-lines-more", _NOTHING, ".earlier-list .more-n", (
        ("display", "equals", "block", "grid"), ("grid-column", "equals", "auto", "1 / 3")),
        probe='<div data-style-probe><ul class="earlier-list"><li class="more-n">and 2 more</li>'
              '</ul></div>', host="#digest"),
    *_sec_h("sec-h-work", "#projects h2"),
    *_sec_h("sec-h-digest", ".digest-head",
            probe='<h2 class="sec-h digest-head" data-style-probe>Since you last looked, '
                  '<time>x</time></h2>', host="#digest"),
    *_sec_h("sec-h-promoted", "#promoted h2",
            probe='<h2 class="sec-h" data-style-probe>Capacity</h2>', host="#promoted"),
)
_LIVE = "live-several"
_LOOK = "look-card"
_OWNER = "owner-check"
_MARK = '<span class="message-new">new reply</span>'
_CHECK_LIST = ('<ul class="sprint-checks" data-style-probe><li><button class="sprint-check '
               'btn-quiet btn-bare">x</button></li></ul>')
_WAIT_LIST = '<ul class="sprint-checks" data-style-probe><li class="wait">x</li></ul>'
_REST_ROW = '<ul class="rest" data-style-probe><li class="row">x</li></ul>'
_CARD_HEAD = '<div class="card" data-style-probe><div class="head">x</div></div>'
_REST_HEAD = ('<ul class="rest" data-style-probe><li class="row"><div class="head"><span>a</span>'
              '<span class="wait">waiting</span></div></li></ul>')
_LEAD_BRIEFS = ('<div data-style-probe><article class="card lead">x</article>'
                '<details class="row brief-row">x</details><details class="row brief-row">y'
                '</details></div>')
_LEAD_REST = ('<div data-style-probe><article class="card lead">x</article>'
              '<ul class="rest"><li class="row">x</li></ul></div>')
_ANSWERED = ('<details class="done-item" data-style-probe><summary><b>Which database?</b>'
             '<span>answered</span></summary></details>')
_DRAFT = ('<ul class="register-draft" data-style-probe><li><span>a line</span>'
          '<button class="draft-change btn-quiet">Change</button></li></ul>')
_OPAQUE_LOOK = "rgba(24, 25, 38, .5)"
_NO_IMAGE = "linear-gradient(red, red)"
_HEAD = ".sp-head"
# A line after a line has the hair above it unless it is `.after-line`, which the rule removes.
_BLOCK = "#list > li.line + li.line:not(.after-line)"
_ANSWER_CLIP = (("white-space", "equals", "nowrap", "normal"), ("overflow", "equals", "hidden", "visible"),
                ("text-overflow", "equals", "ellipsis", "clip"), ("min-width", "equals", "0px", "50px"))
_ANSWER_SPAN = ".done-item summary > span"


def _wide(row_name, state, selector, prop, want, value, bad, **kw):
    """The 1440 row of a property whose 480 value differs."""
    return _row(f"{row_name}-1440", state, selector, prop, want, value, bad, widths=(1440,), **kw)


def _narrow(row_name, state, selector, prop, want, value, bad, **kw):
    """The 480 row of a property whose 1440 value differs."""
    return _row(f"{row_name}-480", state, selector, prop, want, value, bad, widths=(480,), **kw)


STYLE_CHECKS += (
    # The new-reply mark in a summary, the check line and the wait line.
    _row("new-mark-gap-finished", "finished-list", ".finished-list > summary .message-new",
         "margin-left", "equals", "10px", "0px", widths=(1440,), host="#projects",
         probe=f'<details class="finished-list" data-style-probe><summary>Finished {_MARK}'
               '</summary></details>'),
    _row("new-mark-gap-earlier", "finished-list", ".sprint-earlier summary .message-new",
         "margin-left", "equals", "10px", "0px", widths=(1440,), host="#projects",
         probe=f'<details class="sprint-earlier" data-style-probe><summary>Earlier {_MARK}'
               '</summary></details>'),
    _row("check-line-color", _OWNER, ".sprint-check", "color", "same_as", ".sprint-detail summary",
         _RGB),
    _row("check-line-cursor", _OWNER, ".sprint-check", "cursor", "same_as", ".sprint-detail summary",
         "default"),
    _row("check-line-font-size", _OWNER, ".sprint-check", "font-size", "same_as", ".sprint-detail",
         "30px"),
    _row("check-line-text-decoration-line", _OWNER, ".sprint-check", "text-decoration-line",
         "equals", "none", "underline"),
    _wide("check-line-min-height", _OWNER, ".sprint-check", "min-height", "same_as", ".btn-quiet",
          "20px", compare_probe='<button class="btn-quiet" data-style-probe>x</button>'),
    _narrow("check-line-min-height", _OWNER, ".sprint-check", "min-height", "equals", "44px", "20px"),
    _narrow("check-line-display", _OWNER, ".sprint-check", "display", "equals", "flex", "block"),
    _narrow("check-line-align-items", _OWNER, ".sprint-check", "align-items", "equals", "flex-start",
            "center"),
    _row("check-line-list-padding", _OWNER, ".sprint-checks", "padding", "equals", "0px 0px 0px 28px",
         "9px"),
    *_group("wait-line", _OWNER, ".sprint-checks .wait", (
        ("margin", "equals", "0px", "9px"), ("padding", "same_as", ".sprint-check", "9px"),
        ("font-size", "same_as", ".sprint-check", "30px")),
        probe=_WAIT_LIST, host="#projects", compare_probe=_CHECK_LIST, compare_host="#projects"),
    _narrow("wait-line-min-height", _OWNER, ".sprint-checks .wait", "min-height", "equals", "44px",
            "20px", probe=_WAIT_LIST, host="#projects"),
    _narrow("wait-line-min-height-same", _OWNER, ".sprint-checks .wait", "min-height", "same_as",
            ".sprint-check", "20px", probe=_WAIT_LIST, host="#projects", compare_probe=_CHECK_LIST,
            compare_host="#projects"),
    # The now sentence, the pips and the project block.
    _row("now-sentence-column-start", _LIVE, ".sp-now", "grid-column-start", "equals", "2", "1"),
    _row("now-sentence-column-end", _LIVE, ".sp-now", "grid-column-end", "equals", "-1", "3"),
    _row("now-sentence-display", _LIVE, ".sp-now", "display", "in", "-webkit-box|flow-root", "block"),
    _row("now-sentence-box-orient", _LIVE, ".sp-now", "-webkit-box-orient", "equals", "vertical",
         "horizontal"),
    _row("now-sentence-line-clamp", _LIVE, ".sp-now", "-webkit-line-clamp", "equals", "2", "5"),
    _row("now-sentence-overflow-y", _LIVE, ".sp-now", "overflow-y", "equals", "hidden", "visible"),
    _row("pips-wrap-flex-wrap", _LIVE, ".pips", "flex-wrap", "equals", "wrap", "nowrap"),
    _row("pips-wrap-pips-white-space", _LIVE, ".pips", "white-space", "not", "nowrap", "nowrap"),
    _row("pips-wrap-prog-white-space", _LIVE, ".sp-prog", "white-space", "not", "nowrap", "nowrap"),
    _row("pips-wrap-columns", _LIVE, _HEAD, "grid-template-columns", "starts", "16px ", "1fr"),
    _row("pips-wrap-columns-max", _LIVE, _HEAD, "grid-template-columns", "track_max", "3:0.5",
         "16px minmax(0, 1fr) 90%"),
    _row("project-block-border-color", _LIVE, _BLOCK, "border-top-color", "equals", _HAIR, _RGB),
    _row("project-block-border-width", _LIVE, _BLOCK, "border-top-width", "min", "1", "0px"),
    _row("project-block-pname-weight", _LIVE, ".pname", "font-weight", "equals", "600", "400"),
    # The brief rows and the registration rows.
    _row("row-head-display", _NOTHING, ".row-head", "display", "equals", "flex", "block",
          probe='<p class="row-head" data-style-probe>x</p>', host="#inbox", widths=(1440,)),
    _row("row-head-summary-display", _NOTHING, ".brief-row > summary", "display", "equals", "flex",
          "block", host="#inbox",
          probe='<details class="row brief-row" data-style-probe><summary class="row-head">x'
                '</summary></details>', widths=(1440,)),
    _row("row-head-b-overflow-wrap", _NOTHING, ".row-head b", "overflow-wrap", "equals", "anywhere",
          "normal", probe='<p class="row-head" data-style-probe><b>x</b></p>', host="#inbox", widths=(1440,)),
    *(_row(f"rest-head-{name}", _NOTHING, ".rest .head", prop, want, value, bad, widths=(1440,),
           probe=_REST_HEAD, host="#inbox", **extra)
      for name, prop, want, value, bad, extra in (
          ("display", "display", "equals", "flex", "block", {}),
          ("column-gap", "column-gap", "same_as", ".card .head", "50px",
           {"compare_probe": _CARD_HEAD, "compare_host": "#inbox"}),
          ("align-items", "align-items", "same_as", ".card .head", "stretch",
           {"compare_probe": _CARD_HEAD, "compare_host": "#inbox"}))),
    StyleCheck("rest-head-wait-right", (_NOTHING,), (1440,), ".head .wait", "right", "right_edge", "",
               ".head .wait { margin-left: 0 !important }", probe=_REST_HEAD, host="#inbox"),
    _row("rest-head-wait-margin-left", _NOTHING, ".head .wait", "margin-left", "min", "0", "-5px",
         widths=(1440,), probe=_REST_HEAD, host="#inbox"),
    *(_row(f"row-gap-padding-{side}", _NOTHING, ".brief-row", f"padding-{side}", "equals", gap,
           "30px", widths=(1440,), probe=_LEAD_BRIEFS, host="#inbox")
      for side, gap in (("top", "12px"), ("bottom", "12px"), ("left", "0px"), ("right", "0px"))),
    *(_row(f"row-gap-padding-{side}-same", _NOTHING, ".brief-row", f"padding-{side}", "same_as",
           ".rest > li.row", "30px", widths=(1440,), probe=_LEAD_BRIEFS, host="#inbox",
           compare_probe=_REST_ROW, compare_host="#inbox")
      for side in ("top", "bottom", "left", "right")),
    _row("row-gap-lead-brief-margin-top", _NOTHING, ".card.lead + .brief-row", "margin-top",
         "equals", "12px", "30px", widths=(1440,), probe=_LEAD_BRIEFS, host="#inbox"),
    _row("row-gap-lead-rest-margin-top", _NOTHING, ".card.lead + .rest", "margin-top", "equals",
         "12px", "30px", widths=(1440,), probe=_LEAD_REST, host="#inbox"),
    _row("row-gap-brief-border-color", _NOTHING, ".brief-row + .brief-row", "border-top-color",
         "equals", _HAIR, _RGB, widths=(1440,), probe=_LEAD_BRIEFS, host="#inbox"),
    # The answered row clips its question to one line.
    *(_row(f"answered-row-b-{prop}", _NOTHING, ".done-item summary > b", prop, want, value, bad,
           probe=_ANSWERED, host="#inbox")
      for prop, want, value, bad in _ANSWER_CLIP),
    *(_row(f"answered-row-span-{prop}", _NOTHING, _ANSWER_SPAN, prop, want, value, bad,
           probe=_ANSWERED, host="#inbox")
      for prop, want, value, bad in _ANSWER_CLIP),
    _row("answered-row-b-flex-grow", _NOTHING, ".done-item summary > b", "flex-grow", "equals", "0",
         "1", probe=_ANSWERED, host="#inbox"),
    _row("answered-row-b-flex-shrink", _NOTHING, ".done-item summary > b", "flex-shrink", "gt",
         _ANSWER_SPAN, "0", probe=_ANSWERED, host="#inbox", compare_probe=_ANSWERED,
         compare_host="#inbox"),
    _row("answered-row-span-flex-grow", _NOTHING, _ANSWER_SPAN, "flex-grow", "equals", "0", "1",
         probe=_ANSWERED, host="#inbox"),
    _row("answered-row-span-flex-shrink", _NOTHING, _ANSWER_SPAN, "flex-shrink", "min", "0.001",
         "0", probe=_ANSWERED, host="#inbox"),
    _row("answered-row-summary-flex-wrap", _NOTHING, ".done-item summary", "flex-wrap", "equals",
         "nowrap", "wrap", probe=_ANSWERED, host="#inbox"),
    _row("answered-row-item-min-width", _NOTHING, ".done-item", "min-width", "equals", "0px", "50px",
         probe=_ANSWERED, host="#inbox"),
    _row("draft-row-display", _NOTHING, ".register-draft li", "display", "equals", "grid", "block",
          probe=_DRAFT, host="#inbox", widths=(1440,)),
    _row("draft-row-columns", _NOTHING, ".register-draft li", "grid-template-columns", "tracks",
          "2", "1fr", probe=_DRAFT, host="#inbox", widths=(1440,)),
    _row("draft-row-change-white-space", _NOTHING, ".draft-change", "white-space", "equals",
          "nowrap", "normal", probe=_DRAFT, host="#inbox", widths=(1440,)),
    # The picture gallery, its thumbnails and the viewer (read open, after STYLE_STEPS).
    _row("pics-flex-wrap", _LOOK, ".pics", "flex-wrap", "equals", "wrap", "nowrap"),
    _row("pics-pic-min-width", _LOOK, ".pic", "min-width", "equals", "0px", "50px"),
    _row("pics-pic-max-width", _LOOK, ".pic", "max-width", "equals", "100%", "none"),
    _row("pics-pair-min-width", _LOOK, ".pic-pair", "min-width", "equals", "0px", "50px"),
    _row("pics-pair-max-width", _LOOK, ".pic-pair", "max-width", "equals", "100%", "none"),
    _row("pics-line-overflow-wrap", _LOOK, ".pic-line", "overflow-wrap", "equals", "anywhere",
         "normal"),
    _wide("pics-pair-display", _LOOK, ".pic-pair", "display", "equals", "flex", "block"),
    _wide("pics-pair-direction", _LOOK, ".pic-pair", "flex-direction", "equals", "row", "column"),
    _wide("pics-pair-align-items", _LOOK, ".pic-pair", "align-items", "equals", "flex-start",
          "stretch"),
    _narrow("pics-pair-direction", _LOOK, ".pic-pair", "flex-direction", "equals", "column", "row"),
    *(_row(f"pics-pair-direction-{at}", _LOOK, ".pic-pair", "flex-direction", "equals", "row",
           "column", widths=(at,)) for at in BETWEEN_WIDTHS),
    _narrow("pics-pair-align-items", _LOOK, ".pic-pair", "align-items", "equals", "stretch",
            "flex-start"),
    _wide("pics-pair-pic-flex", _LOOK, ".pic-pair .pic", "flex", "equals", "1 1 0px", "0 0 auto"),
    _row("thumb-object-fit", _LOOK, ".pic-thumb img", "object-fit", "equals", "contain", "fill"),
    _wide("thumb-max-height", _LOOK, ".pic-thumb img", "max-height", "equals", "180px", "400px"),
    _narrow("thumb-max-height", _LOOK, ".pic-thumb img", "max-height", "equals", "240px", "400px"),
    _row("thumb-width", _LOOK, ".pic-thumb img", "width", "fills", "", "50%", every=True),
    _row("thumb-height", _LOOK, ".pic-thumb img", "height", "follows_shape", "", "50px", every=True),
    *(_row(f"{name}-{kind}", _LOOK, selector, prop, want, value, bad)
      for name, selector in (("thumb", ".pic-thumb"), ("thumb-img", ".pic-thumb img"))
      for kind, prop, want, value, bad in (
          ("background-color", "background-color", "alpha_max", "0.35", "rgb(24, 25, 38)"),
          ("background-image", "background-image", "equals", "none", _NO_IMAGE))),
    _row("viewer-display", _LOOK, ".viewer", "display", "equals", "flex", "block"),
    _row("viewer-direction", _LOOK, ".viewer", "flex-direction", "equals", "column", "row"),
    _row("viewer-overflow-y", _LOOK, ".viewer", "overflow-y", "in", "visible|hidden|clip", "auto"),
    _row("viewer-background-color", _LOOK, ".viewer", "background-color", "opaque", "",
         _OPAQUE_LOOK),
    _row("viewer-background-image", _LOOK, ".viewer", "background-image", "equals", "none",
         _NO_IMAGE),
    _row("viewer-bar-display", _LOOK, ".viewer-bar", "display", "equals", "flex", "block"),
    _row("viewer-bar-direction", _LOOK, ".viewer-bar", "flex-direction", "equals", "row", "column"),
    _row("viewer-bar-wrap", _LOOK, ".viewer-bar", "flex-wrap", "equals", "nowrap", "wrap"),
    _row("viewer-bar-flex", _LOOK, ".viewer-bar", "flex", "equals", "0 0 auto", "1 1 auto"),
    _row("viewer-bar-background-color", _LOOK, ".viewer-bar", "background-color", "opaque", "",
         _OPAQUE_LOOK),
    _row("viewer-bar-background-image", _LOOK, ".viewer-bar", "background-image", "equals", "none",
         _NO_IMAGE),
    _row("viewer-stage-overflow-y", _LOOK, ".viewer-stage", "overflow-y", "equals", "auto",
         "hidden"),
    _row("viewer-stage-align-items", _LOOK, ".viewer-stage", "align-items", "in",
         "normal|flex-start|start", "center"),
    _row("viewer-stage-child-margin-top", _LOOK, ".viewer-stage > *", "margin-top", "equals", "0px",
         "20px"),
    _row("viewer-img-max-width", _LOOK, ".viewer img", "max-width", "equals", "100%", "none"),
    _row("viewer-img-object-fit", _LOOK, ".viewer img", "object-fit", "equals", "contain", "fill"),
    _row("viewer-html-overflow-y", _LOOK, "html", "overflow-y", "equals", "hidden", "visible"),
    _narrow("viewer-bar-button-min-height", _LOOK, ".viewer-bar button", "min-height", "min", "44",
            "20px", every=True),
    _row("viewer-focus-outline-style", _LOOK, ".viewer", "outline-style", "equals", "none", "solid",
         forced=("focus-visible",)),
    _row("viewer-focus-outline", _LOOK, ".viewer", "outline", "equals", "rgb(202, 211, 245) none 0px",
         "2px solid " + _RGB, forced=("focus-visible",)),
    _row("viewer-pair-display", _LOOK, ".viewer-pair", "display", "equals", "flex", "block"),
    _wide("viewer-pair-direction", _LOOK, ".viewer-pair", "flex-direction", "equals", "row",
          "column"),
    _narrow("viewer-pair-direction", _LOOK, ".viewer-pair", "flex-direction", "equals", "column",
            "row"),
)
CONTROL_SELECTOR = 'button, input, textarea, select, a[class*="btn-"], summary[class*="btn-"]'
KINDS = ("btn-primary", "btn-quiet", "btn-danger", "btn-option", "field-line", "field-area",
         "field-code")
BUTTON_KINDS = KINDS[:4]
FIELD_KINDS = KINDS[4:]
LOOK = ("padding-top", "padding-right", "padding-bottom", "padding-left",
        *(f"border-{side}-{part}" for side in ("top", "right", "bottom", "left")
          for part in ("width", "style", "color")),
        *(f"border-{corner}-radius" for corner in ("top-left", "top-right", "bottom-right",
                                                   "bottom-left")),
        "font-family", "font-size", "font-style", "font-weight", "line-height", "color",
        "background-color", "background-image", "cursor", "outline-style", "outline-width",
        "outline-color", "opacity")
_SPEND = ("spend-page",)
_PAGES = (_NOTHING, "spend-page")
_UI = '<span class="k-ui" style="font-family: var(--ui)" data-style-probe></span>'
_GRADIENT = "linear-gradient(red, red)"
# A value each property of a kind row must refuse, for the `broken` rule of its row.
_REFUSED = {
    "display": "block", "align-items": "flex-start", "gap": "1px", "column-gap": "1px",
    "min-height": "1px", "padding": "1px", "font-style": "italic", "font-weight": "300",
    "font-size": "30px", "line-height": "40px", "font-family": "serif", "text-align": "right",
    "text-decoration-line": "underline", "color": _RGB, "background-color": _RGB,
    "background-image": _GRADIENT, "border-width": "3px", "border-style": "double",
    "border-color": _RGB, "border-radius": "1px", "cursor": "default",
    "transition-property": "none", "transition-duration": "5s", "letter-spacing": "5px",
    "resize": "none", "width": "50%", "opacity": "1", "outline-style": "none",
    "outline-width": "5px", "outline-color": _RGB, "outline-offset": "9px", "transform": "none",
}
_SHARED_BUTTON = (
    ("display", "equals", "inline-flex"), ("align-items", "equals", "center"),
    ("gap", "equals", "8px"), ("min-height", "equals", "32px"), ("padding", "equals", "5px 12px"),
    ("font-style", "equals", "normal"), ("font-weight", "equals", "500"),
    ("font-size", "equals", "14px"), ("line-height", "equals", "19.6px"),
    ("font-family", "same_as", ".k-ui"), ("text-align", "equals", "left"),
    ("text-decoration-line", "equals", "none"), ("color", "equals", PALETTE["--sub1"]),
    ("background-color", "equals", _CLEAR), ("background-image", "equals", "none"),
    ("border-width", "equals", "1px"), ("border-style", "equals", "solid"),
    ("border-color", "equals", PALETTE["--s1"]), ("border-radius", "equals", "8px"),
    ("cursor", "equals", "pointer"),
    ("transition-property", "equals", "background-color, border-color"),
    ("transition-duration", "equals", "0.16s, 0.16s"))
_SHARED_FIELD = (
    ("min-height", "equals", "32px"), ("padding", "equals", "5px 10px"),
    ("font-style", "equals", "normal"), ("font-weight", "equals", "400"),
    ("font-size", "equals", "14px"), ("line-height", "equals", "19.6px"),
    ("color", "equals", PALETTE["--text"]), ("background-color", "equals", PALETTE["--mantle"]),
    ("background-image", "equals", "none"), ("border-width", "equals", "1px"), ("border-style", "equals", "solid"),
    ("border-color", "equals", PALETTE["--s1"]), ("border-radius", "equals", "8px"))
# What each kind holds differently from the shared look, and what only the desk page changes.
_KIND_OWN = {
    "btn-primary": {"min-height": "40px", "padding": "0px 16px", "font-weight": "600"},
    "btn-option": {"display": "grid", "gap": "8px 14px", "width": ("fills", ""),
                   "min-height": "44px", "padding": "9px 14px", "color": PALETTE["--text"],
                   "border-color": _CLEAR},
    "field-line": {"font-family": ("same_as", ".k-ui")},
    "field-area": {"font-family": ("same_as", ".k-ui"), "display": "block",
                   "width": ("fills", ""), "min-height": "72px", "resize": "vertical"},
    "field-code": {"font-family": ("starts", "ui-monospace"), "letter-spacing": "0.84px"},
}
_KIND_DESK = {
    "btn-primary": {"background-color": PALETTE["--peach"], "border-color": PALETTE["--peach"],
                    "color": PALETTE["--crust"]},
    "btn-danger": {"color": PALETTE["--red"]},
}


def _specimen(classes, attrs="", mark=True):
    """One control of the page's own markup, `classes` first the kind: a button, an input or a
    textarea, with a placeholder when it is a field."""
    tag = "textarea" if classes.startswith("field-area") else (
        "input" if classes.startswith("field-") else "button")
    head = f'<{tag} class="{classes}"' + ("" if tag == "button" else ' placeholder="x"')
    head += (f" {attrs}" if attrs else "") + (" data-style-probe" if mark else "")
    return head + {"button": ">x</button>", "input": ">", "textarea": "></textarea>"}[tag]


def _pair(kind, *states):
    """One probe holding a `kind` control for each of `states`, read together (`every`)."""
    return ('<span data-style-probe>' + "".join(_specimen(kind, state, mark=False) for state in states)
            + "</span>")


def _look(kind):
    """The (prop, want, value) reads of a kind: the shared look with the kind's own values."""
    base = _SHARED_BUTTON if kind in BUTTON_KINDS else _SHARED_FIELD
    own = _KIND_OWN.get(kind, {})
    reads = [(prop, *(own.get(prop) if isinstance(own.get(prop), tuple) else (want, own.get(prop, value))))
             for prop, want, value in base]
    reads += [(prop, *(v if isinstance(v, tuple) else ("equals", v)))
              for prop, v in own.items() if prop not in {read[0] for read in reads}]
    return reads


def _kind_rows():
    rows = []
    for kind in KINDS:
        spec = {"probe": _specimen(kind), "compare_probe": _UI}
        for prop, want, value in _look(kind):
            extra = dict(spec) if want in ("same_as",) else {"probe": spec["probe"]}
            desk = _KIND_DESK.get(kind, {}).get(prop)
            if desk is None:
                rows.append(_row(f"kind-{kind}-{prop}", _PAGES, f".{kind}", prop, want, value,
                                 "inline-block" if value == "block" else _REFUSED[prop], **extra))
                continue
            for suffix, states, value in (("desk", _NOTHING, desk), ("spend", _SPEND, value)):
                rows.append(_row(f"kind-{kind}-{prop}-{suffix}", states, f".{kind}", prop, want,
                                 value, _REFUSED[prop], **extra))
    option = {"probe": _specimen("btn-option")}
    rows += [
        _row("kind-btn-option-column-gap", _PAGES, ".btn-option", "column-gap", "equals", "14px",
             "1px", **option),
        _row("kind-btn-option-grid", _PAGES, ".btn-option", "grid-template-columns", "starts",
             "22px ", "50px 1fr auto", **option),
        _row("kind-btn-option-grid-tracks", _PAGES, ".btn-option", "grid-template-columns",
             "tracks", "3", "1fr 1fr", **option)]
    return rows


def _bare_rows():
    button = {"probe": _specimen("btn-quiet btn-bare")}
    field = {"probe": _specimen("field-line field-bare")}
    return [
        *(_row(f"bare-btn-quiet-{prop}", _PAGES, ".btn-quiet.btn-bare", prop, "equals", value,
               _REFUSED[prop], **button)
          for prop, value in (("padding", "0px"), ("border-color", _CLEAR),
                              ("background-color", _CLEAR))),
        *(_row(f"bare-field-line-{prop}", _PAGES, ".field-line.field-bare", prop, "equals", value,
               _REFUSED.get(prop, "1px"), **field)
          for prop, value in (("padding-left", "0px"), ("padding-right", "0px"),
                              ("background-color", _CLEAR), ("border-color", _CLEAR)))]


def _state_rows():
    rows = []
    dashed = (("border-width", "1px"), ("border-style", "dashed"), ("cursor", "not-allowed"),
              ("opacity", "0.55"))
    dotted = (("border-width", "1px"), ("border-style", "dotted"), ("cursor", "progress"))
    refused = {"border-style": "solid", "cursor": "default", "border-width": "3px",
               "opacity": "1"}
    for kind in KINDS:
        both = {"every": True, "probe": _pair(kind, "disabled", 'aria-disabled="true"')}
        for prop, value in dashed:
            rows.append(_row(f"disabled-{kind}-{prop}", _PAGES, f".{kind}", prop, "equals", value,
                             refused[prop], **both))
        reads = (("border-color", PALETTE["--s1"]),)
        if kind == "btn-primary":
            rows += [_row(f"disabled-{kind}-{prop}-desk", _NOTHING, f".{kind}", prop, "equals",
                          PALETTE[token], _RGB, **both)
                     for prop, token in (("border-color", "--s2"), ("background-color", "--s1"),
                                         ("color", "--sub0"))]
            rows.append(_row(f"disabled-{kind}-border-color-spend", _SPEND, f".{kind}",
                             "border-color", "equals", PALETTE["--s1"], _RGB, **both))
        else:
            rows += [_row(f"disabled-{kind}-{prop}", _PAGES, f".{kind}", prop, "equals", value,
                          _RGB, **both) for prop, value in reads]
        busy = {"every": True,
                "probe": _pair(kind, 'aria-busy="true"', 'aria-busy="true" disabled')}
        for prop, value in dotted:
            rows.append(_row(f"busy-{kind}-{prop}", _PAGES, f".{kind}", prop, "equals", value,
                             {"border-style": "solid", "cursor": "default",
                              "border-width": "3px"}[prop], **busy))
        if kind in ("btn-primary", "btn-quiet", "btn-danger"):
            rows.append(_row(f"busy-{kind}-content", _PAGES, f".{kind}", "content", "equals",
                             '"…"', "none", pseudo="::after", **busy))
    for kind in ("btn-quiet", "btn-danger", "btn-option"):
        probe = {"probe": _specimen(kind), "forced": ("hover",)}
        for prop, value in (("background-color", _HOVER), ("border-color", PALETTE["--s2"]),
                            ("background-image", "none")):
            rows.append(_row(f"hover-{kind}-{prop}", _PAGES, f".{kind}", prop, "equals", value,
                             _REFUSED[prop], **probe))
    rows += [
        _row("hover-btn-quiet-bare-border-color", _PAGES, ".btn-quiet.btn-bare", "border-color",
             "equals", _CLEAR, _RGB, probe=_specimen("btn-quiet btn-bare"), forced=("hover",)),
        *(_row(f"hover-btn-primary-{prop}-desk", _NOTHING, ".btn-primary", prop, "equals",
               "rgb(248, 187, 152)", _RGB, probe=_specimen("btn-primary"), forced=("hover",))
          for prop in ("background-color", "border-color")),
        *(_row(f"hover-disabled-btn-quiet-{prop}", _PAGES, ".btn-quiet", prop, "equals", value,
               bad, probe=_specimen("btn-quiet", "disabled"), forced=("hover",))
          for prop, value, bad in (("background-color", _CLEAR, _RGB),
                                   ("border-style", "dashed", "solid")))]
    for kind in KINDS:
        probe = {"probe": _specimen(kind), "forced": ("focus-visible",)}
        for prop, value in (("outline-style", "solid"), ("outline-width", "2px"),
                            ("outline-color", PALETTE["--lav"]), ("outline-offset", "2px"),
                            ("border-radius", "8px")):
            rows.append(_row(f"ring-{kind}-{prop}", _PAGES, f".{kind}", prop, "equals", value,
                             _REFUSED[prop], **probe))
    rows += [
        _row("ring-field-bare-outline-style", _PAGES, ".field-line.field-bare", "outline-style",
             "equals", "none", "solid", probe=_specimen("field-line field-bare"),
             forced=("focus-visible",)),
        _row("ring-every-outline-style", _EVERY_STATE, f":is({CONTROL_SELECTOR}):not(.field-bare, "
             ".viewer)", "outline-style", "not", "none", "none", every=True,
             forced=("focus-visible",))]
    for kind in BUTTON_KINDS:
        rows += [
            _row(f"pressed-{kind}-transform", _PAGES, f".{kind}", "transform", "equals",
                 "matrix(1, 0, 0, 1, 0, 1)", "none", probe=_specimen(kind), forced=("active",)),
            _row(f"pressed-{kind}-border-color", _PAGES, f".{kind}", "border-color", "equals",
                 PALETTE["--lav"], _RGB, probe=_specimen(kind, 'aria-pressed="true"')),
            _row(f"pressed-{kind}-font-weight", _PAGES, f".{kind}", "font-weight", "equals", "600",
                 "300", probe=_specimen(kind, 'aria-pressed="true"'))]
    rows.append(_row("pressed-btn-option-background-color-desk", _NOTHING, ".btn-option",
                     "background-color", "equals", "rgba(183, 189, 248, 0.1)", _RGB,
                     probe=_specimen("btn-option", 'aria-pressed="true"')))
    return rows


def _placeholder_rows():
    rows = []
    dark = "rgb(30, 32, 48)"
    for kind in FIELD_KINDS:
        probe = {"probe": _specimen(kind), "pseudo": "::placeholder"}
        rows += [
            _row(f"placeholder-{kind}-opacity", _PAGES, f".{kind}", "opacity", "equals", "1", "0.5",
                 **probe),
            _row(f"placeholder-{kind}-color", _PAGES, f".{kind}", "color", "equals",
                 PALETTE["--ov2"], _RGB, **probe),
            _row(f"placeholder-{kind}-contrast", _PAGES, f".{kind}", "color", "contrast", "4.5",
                 dark, **probe)]
    rows.append(_row("placeholder-goal-contrast", "goal-open", ".goal-bar.open .goal-in .goal-text",
                     "color", "contrast", "4.5", "rgb(36, 39, 58)", pseudo="::placeholder"))
    rows += [_row(f"placeholder-goal-{prop}", "goal-open", ".goal-bar.open .goal-in", prop, "equals",
                  value, bad) for prop, value, bad in (("background-color", PALETTE["--base"], _RGB),
                                                       ("background-image", "none", _GRADIENT))]
    return rows


_MOTION_RULE = ".style-motion i, .style-motion i::before, .style-motion i::after"
_MOTION = ('<span class="style-motion" data-style-probe><style>' + _MOTION_RULE
           + ' { content: ""; transition: opacity 1s; animation: none 1s }</style><i></i></span>')


def _motion_rows():
    rows = []
    for prop in ("transition-duration", "animation-duration"):
        for pseudo, where in (("", ""), ("::before", "-before"), ("::after", "-after")):
            still = f"{_MOTION_RULE} {{ transition-duration: 0s !important; animation-duration: 0s !important }}"
            rows.append(StyleCheck(
                f"motion-reduced-{prop}{where}", _PAGES, (1440,), ".style-motion i", prop, "max",
                "0.000001", "@media (prefers-reduced-motion: reduce) { " + _MOTION_RULE
                + " { transition-duration: 1s !important; animation-duration: 1s !important } }",
                probe=_MOTION, pseudo=pseudo, reduced_motion=True))
            rows.append(StyleCheck(
                f"motion-normal-{prop}{where}", _PAGES, (1440,), ".style-motion i", prop, "min",
                "0.5", still, probe=_MOTION, pseudo=pseudo))
    return rows


STYLE_CHECKS += (
    StyleCheck("kind-look", _DESK_STATES, _BOTH, "body", "min-height", "kind_look", ",".join(LOOK),
               ":is(.btn-primary, .btn-quiet, .btn-danger, .btn-option, .field-line, .field-area, "
               ".field-code):not([data-style-probe]) { border-top-left-radius: 2px !important }"),
    StyleCheck("kind-height-floor", _EVERY_STATE, _BOTH, ", ".join(f".{kind}" for kind in KINDS),
               "height", "min", "32",
               ", ".join(f".{kind}" for kind in KINDS) + " { height: 10px !important; "
               "min-height: 0 !important }", every=True),
    *_kind_rows(),
    *_bare_rows(),
    *_state_rows(),
    *(_row(f"primary-real-{prop}", "inbox-card", ".card.lead .btn-primary:not(:disabled)"
                                                 ':not([aria-disabled="true"])', prop, "equals",
           PALETTE[token], _RGB, every=True)
      for prop, token in (("background-color", "--peach"), ("border-color", "--peach"),
                          ("color", "--crust"))),
    *_placeholder_rows(),
    *_motion_rows(),
    _row("spend-fit-top-wrap", _SPEND, ".top-in", "flex-wrap", "equals", "wrap", "nowrap",
         widths=(480,)),
    _row("spend-fit-trend-min-width", _SPEND, ".trend-day", "min-width", "equals", "0px", "50px",
         widths=(480,), every=True),
    _row("spend-fit-min-width", _SPEND, ".figure, .row-name", "min-width", "equals", "0px", "50px",
         widths=(480,), every=True),
    _row("spend-fit-width", _SPEND, "#summary", "width", "max", "448", "900px", widths=(480,)),
    _row("spend-fit-flex-basis", _SPEND, ".trend-day", "flex-basis", "equals", "0px", "900px",
         widths=(480,), every=True),
    _row("spend-fit-row-name-wrap", _SPEND, ".row-name", "overflow-wrap", "equals", "anywhere",
         "normal", widths=(480,), every=True),
    # The consent tick is at least 32 px in both directions; SHORT_CONTROLS reads only heights
    # (#1313).
    _row("guest-tick-width", _GUEST_PAGES, ".guest-tick", "width", "min", "32", "20px"),
    _row("guest-tick-height", _GUEST_PAGES, ".guest-tick", "height", "min", "32", "20px"),
    # A hidden owner control in the top bar stays hidden before the guest script removes it; the
    # probe is the capacity button as the guest bytes carry it (#1313).
    _row("guest-top-hidden-display", _GUEST_PAGES, ".top-in > [hidden]", "display", "equals", "none",
         "inline-flex",
         probe='<button type="button" class="cap btn-quiet btn-bare" hidden data-style-probe></button>',
         host=".top-in"),
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
STYLE_SETTLE = r"""(async () => {
  // A picture is fetched after the page draws it, so wait for each one to have its source and load.
  for (let tries = 0; tries < 100; tries++) {
    const waiting = Array.from(document.querySelectorAll('img.pic-img')).some(
      (img) => !img.hidden && (!img.getAttribute('src') || !img.complete));
    if (!waiting) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
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
  const COLOURS = /(?:rgba?|color|oklab|oklch|lab|lch)\([^)]*\)/g;
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
    const image = s.getPropertyValue('background-image');
    if (image !== 'none') for (const colour of image.match(COLOURS) || []) out.push(['background-image', colour]);
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
  // The specificity of one selector as a number: ids, then classes, attributes and pseudo-classes,
  // then tags (a functional pseudo-class counts as one class, whatever it holds).
  const specificity = (selector) => {
    const text = selector.replace(/\[[^\]]*\]/g, '.a');
    const ids = (text.match(/#[\w-]+/g) || []).length;
    const classes = (text.match(/\.[\w-]+|:(?!:)[\w-]+/g) || []).length;
    const tags = (text.replace(/[#.:][\w-]+/g, ' ').match(/(?:^|[\s>+~])[a-zA-Z][\w-]*/g) || []).length;
    return ids * 10000 + classes * 100 + tags;
  };
  // The value the cascade gives `prop` of `node`'s `pseudo`, read from the CSSOM: no engine
  // resolves the style of a legacy pseudo-element it ignores, so the winning rule is the one with
  // the highest importance, then specificity, then order, among the rules that apply at this width.
  const declared = (node, pseudo, prop) => {
    let best = null, order = 0;
    const walk = (rules) => {
      for (const rule of rules) {
        if (rule.media && !window.matchMedia(rule.media.mediaText).matches) continue;
        if (rule.selectorText !== undefined) {
          const value = rule.style.getPropertyValue(prop);
          for (const part of rule.selectorText.split(',')) {
            const text = part.trim();
            if (!value || !text.endsWith(pseudo)) continue;
            const base = text.slice(0, text.length - pseudo.length).trim();
            let hit = false;
            try { hit = node.matches(base); } catch (error) { hit = false; }
            if (!hit) continue;
            const key = [rule.style.getPropertyPriority(prop) === 'important' ? 1 : 0,
                         specificity(base), order++];
            if (best === null || key[0] > best.key[0] || (key[0] === best.key[0]
                && (key[1] > best.key[1] || (key[1] === best.key[1] && key[2] > best.key[2])))) {
              best = {key, value};
            }
          }
        } else if (rule.cssRules) {
          walk(rule.cssRules);
        }
      }
    };
    for (const sheet of document.styleSheets) walk(sheet.cssRules);
    return best === null ? '(none)' : best.value;
  };
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
    } else if (row.want === 'largest_type') {
      const [px, ...rest] = row.value.split('|');
      const allowed = rest.join('|');
      for (const node of nodes) {
        const size = getComputedStyle(node).fontSize;
        if (parseFloat(size) >= parseFloat(px) && !node.matches(allowed)) {
          found.push(`${row.name}: ${label(node)} font-size is ${size}`);
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
  const KIND_TAGS = {'btn-primary': 'button', 'btn-quiet': 'button', 'btn-danger': 'button',
    'btn-option': 'button', 'field-line': 'input', 'field-area': 'textarea', 'field-code': 'input'};
  const BARE_ROLES = ['cap', 'pic-thumb', 'sprint-check', 'draft-pick', 'thread-open', 'goal-text'];
  const IN_A_STATE = ':disabled, [aria-disabled="true"], [aria-busy="true"], [aria-pressed="true"], '
    + '.picked, :hover, :active, :focus-visible';
  const kindLook = (row) => {
    const look = row.value.split(',').map((name) => name.trim()).filter(Boolean);
    const found = [];
    const scratch = {};
    const bareOf = (kind, bare) => {
      const key = kind + ' ' + bare;
      if (!scratch[key]) {
        const node = document.createElement(KIND_TAGS[kind]);
        node.className = bare ? key : kind;
        node.setAttribute('data-style-probe', row.name + ':' + kind);
        document.body.appendChild(node);
        scratch[key] = node;
      }
      return scratch[key];
    };
    let seen = 0;
    for (const kind of Object.keys(KIND_TAGS)) {
      for (const node of onPage('.' + kind)) {
        if (!rendered(node) || node.matches(IN_A_STATE)) continue;
        seen++;
        const first = (node.getAttribute('class') || '').split(/\s+/)[0];
        const bare = node.classList.contains('btn-bare') ? 'btn-bare'
          : node.classList.contains('field-bare') ? 'field-bare' : '';
        let props = kind === 'btn-option' ? [...look, 'display', 'align-items', 'row-gap', 'column-gap'] : look;
        if (bare || BARE_ROLES.includes(first)) props = props.filter((name) => name.startsWith('border'));
        const own = getComputedStyle(node);
        const base = getComputedStyle(bareOf(kind, bare));
        for (const name of props) {
          const got = own.getPropertyValue(name);
          if (!same(got, base.getPropertyValue(name))) found.push(`${row.name}: ${label(node)} ${name} is ${got}`);
        }
        if (parseFloat(own.minHeight) < 32) found.push(`${row.name}: ${label(node)} min-height is ${own.minHeight}`);
      }
    }
    for (const node of Object.values(scratch)) node.remove();
    return seen ? found : [`${row.name}: ${row.selector} is absent`];
  };
  const channelOf = (value) => {
    const unit = value / 255;
    return unit <= 0.03928 ? unit / 12.92 : Math.pow((unit + 0.055) / 1.055, 2.4);
  };
  const luminance = (rgb) => 0.2126 * channelOf(rgb[0]) + 0.7152 * channelOf(rgb[1]) + 0.0722 * channelOf(rgb[2]);
  const rgbOf = (text) => {
    const found = parse(text);
    return found === null ? null : found.split(',').map(Number);
  };
  const backdrop = (node) => {
    for (let at = node; at; at = at.parentElement) {
      const colour = rgbOf(getComputedStyle(at).backgroundColor);
      if (colour && colour[3] === 1) return colour;
    }
    return [255, 255, 255, 1];
  };
  const misses = [];
  for (const row of rows) {
    if (row.want === 'kind_look') { misses.push(...kindLook(row)); continue; }
    if (['none_peach', 'palette', 'sizes_shared', 'largest_type'].includes(row.want)) {
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
      } else if (row.want === 'right_edge') {
        const parent = node.parentElement;
        const cs = getComputedStyle(parent);
        const right = node.getBoundingClientRect().right;
        got = Math.round(right * 100) / 100 + 'px';
        ok = right >= parent.getBoundingClientRect().right - parseFloat(cs.paddingRight) - 1;
      } else if (row.want === 'track_max' || row.want === 'tracks') {
        got = getComputedStyle(node).getPropertyValue('grid-template-columns');
        const found = [];
        let depth = 0, from = 0;
        for (let i = 0; i <= got.length; i++) {
          const char = got.charAt(i);
          if (char === '(') depth++;
          else if (char === ')') depth--;
          else if ((char === ' ' || i === got.length) && depth === 0) {
            if (i > from) found.push(got.slice(from, i));
            from = i + 1;
          }
        }
        if (row.want === 'tracks') {
          ok = found.length === parseInt(row.value, 10);
        } else {
          const [index, fraction] = row.value.split(':');
          const cs = getComputedStyle(node);
          const width = node.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
          const track = found[parseInt(index, 10) - 1];
          ok = track !== undefined && track.endsWith('px') && !track.includes('(')
            && parseFloat(track) <= parseFloat(fraction) * width;
        }
      } else if (row.want === 'alpha_max') {
        const colour = parse(got);
        ok = colour !== null && parseFloat(colour.split(',')[3]) <= parseFloat(row.value);
      } else if (row.want === 'opaque') {
        ok = LISTS.opaque.map(parse).includes(parse(got));
      } else if (row.want === 'follows_shape') {
        const cs = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        got = Math.round(rect.height * 100) / 100 + 'px';
        if (!(node.naturalWidth > 0)) {
          got += ' (not loaded)';
        } else {
          const low = parseFloat(cs.minHeight) || 0;
          const high = cs.maxHeight === 'none' ? Infinity : parseFloat(cs.maxHeight);
          const shape = Math.max(low, Math.min(high, rect.width * node.naturalHeight / node.naturalWidth));
          ok = Math.abs(rect.height - shape) <= 1;
        }
      } else if (row.want === 'hugs') {
        const cs = getComputedStyle(node);
        const width = node.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        const range = document.createRange();
        range.selectNodeContents(node);
        got = Math.round(width * 100) / 100 + 'px';
        ok = width <= range.getBoundingClientRect().width + 1;
      } else if (row.want === 'contrast') {
        const text = getComputedStyle(node, pseudo).color;
        const colour = rgbOf(text);
        if (colour === null) {
          got = 'unreadable ' + text;
        } else {
          const lights = [luminance(colour), luminance(backdrop(node))];
          const ratio = (Math.max(...lights) + 0.05) / (Math.min(...lights) + 0.05);
          got = ratio.toFixed(2);
          ok = ratio >= parseFloat(row.value);
        }
      } else if (row.want === 'declared') {
        got = declared(node, row.pseudo, row.prop);
        ok = got === row.value;
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
                    + `${row.want === 'contrast' ? 'contrast' : row.prop} is ${got}`);
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


def serves_reading_panel(served: Path | None = None) -> bool:
    """Whether the page served has the reading panel (a base run may serve one without it: the before picture)."""
    if served is None:
        import agent_tools.console
        served = Path(next(iter(agent_tools.console.__path__)))
    try:
        return READING_PANEL_ID in (Path(served) / "page.html").read_bytes()
    except OSError:
        return False


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
    register: tuple[str | None, str | None, bool] | None = None
    style: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    broke: tuple[str, ...] = ()
    deeper: tuple | None = None


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
               look: bool = False, report_extra: Mapping | None = None,
               issues: Sequence[Mapping] | None = None,
               then: tuple[float, Sequence[Mapping]] | None = None) -> tuple[str, str]:
        """One approved sprint with a started manager; returns `(sprint_id, goal)`.

        `report_extra` is merged into the `sprint.reported` row's `report`; `issues` replaces its default issue
        rows, and `then` is a second `sprint.reported` row, that many seconds ago, with those issue rows."""
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
        issues = issues or ([{"issue": 12, "stage": "landed"}, {"issue": 13, "stage": "landed"}] if landed
                  else [{"issue": 11, "stage": "held"}, {"issue": 12, "stage": "building"},
                        {"issue": 13, "stage": "queued"}] if held
                  else [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "queued"}])
        if report is not None:
            member = {"status": "the first slice is in review", "phase": "running",
                      "milestone": MILESTONES[title], "tracker_url": TRACKER_URL, "issues": issues,
                      "inbox": [], "next": "merge the first slice", **(report_extra or {})}
            self.put(report, "sprint.reported", project, {**base, "report": member})
            if then is not None:
                self.put(then[0], "sprint.reported", project, {
                    **base, "report": {**member, "issues": list(then[1])}})
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

    def approval(self, project: str, issue: int, ago: float) -> None:
        """One open release confirm of `issue`: a `verify-approve` card waiting on the owner."""
        self.put(ago, "inbox.seen", project, {
            "key": f"{project}#{issue}/9002", "project_id": project, "repo": project,
            "issue": issue, "comment_id": 9002,
            "url": f"https://github.com/{project}/issues/{issue}#issuecomment-9002",
            "reason": "verify-approve", "kind": "approval",
            "question": "Approve the release of the importer change?", "detail": "",
            "check_id": "", "questions": [], "items": [], "answers": ["approve"],
            "paid": False, "confirm": f"{project}#{issue}", "answered": False,
            "held_work": 1, "blocking": [], "version": "v1"})

    def colleague_sprint(self, project: str, title: str, *, started: float, by: str,
                         answered: bool = False) -> tuple[str, str]:
        """One sprint stated by the colleague `by`, every row of theirs carrying `"by"`.

        Without `answered` its brief version 1 is sent and waits. With it the brief is approved, one
        message is sent, one plain question is asked and answered last, so the answer is the
        sprint's newest message.
        """
        self.count += 1
        sid = f"{self.count:016x}"
        goal = f"{title}."
        base = {"sprint_id": sid, "goal": goal}
        actor = {"by": by}
        self.put(started, "goal.stated", project, {**base, **actor})
        self.put(started - 1 * MINUTE, "manager.started", project, {
            "sprint_id": sid, "profile": "work-main",
            "session_name": manager.session_name(project, sid)})
        self.put(started - 4 * MINUTE, "brief.sent", project, {**base, "version": 1, "brief": {
            "title": title, "done": f"{title}, merged and checked.",
            "slices": ["the first slice", "the second slice"], "excluded": [],
            "risks": ["a partial write"], "asks": []}})
        if not answered:
            return sid, goal
        self.put(started - 8 * MINUTE, "brief.approved", project, {**base, "version": 1, **actor})
        self.put(started - 10 * MINUTE, "sprint.messaged", project,
                 {**base, "text": TELL_TEXT, **actor})
        asked = self.put(started - 12 * MINUTE, "questions.asked", project, {
            **base, "blocker": False, "questions": [{
                "question": "Which store should the checkpoint use?",
                "blocks": "the first slice",
                "options": ["the existing database", "a new file"],
                "recommended": "the existing database"}]})
        self.put(started - 14 * MINUTE, "question.answered", project, {
            **base, "round": asked.seq, "index": 0,
            "question": "Which store should the checkpoint use?", "answer": "a new file",
            "chosen": "a new file", "recommended": "the existing database", "differs": True,
            **actor})
        return sid, goal

    def account(self, name: str, week: float, *, session: float | None = None,
                week_in: int = 86400, session_in: int | None = None) -> None:
        """A signed-in profile with one capacity reading whose week window is `week` used.

        With `session` it also has a `5h` window that much used, reset `session_in` seconds on;
        the week window and the reading itself reset `week_in` seconds on.
        """
        self._at[0] = _iso(self.now_s)
        windows = {"7d": {"status": "allowed", "utilization": week,
                          "reset": int(self.now_s) + week_in}}
        if session is not None:
            windows["5h"] = {"status": "allowed", "utilization": session,
                             "reset": int(self.now_s) + session_in}
        reading = capacity.parse_report({
            "http_status": 200, "status": "allowed", "reset": int(self.now_s) + week_in, "binding": None,
            "claim": None, "account": None, "session_id": None, "windows": windows})
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


def _seed_registration(seed: _Seed, state: str, root: str) -> None:
    """A ready plan of `root`, a repository with no contract whose draft is in schema 3 (five fields, then the facts).

    The reading names one GitHub remote, so the draft has no open question and its project id is
    a fact line with no Change. The base commit's draft has no such row; it drafts the commit
    environment as a changeable main-group row instead (the before picture).
    """
    if state.startswith("register-reconcile"):
        fields = (contract_draft.reconcile_fields(root, {
            "hooks": ["pre-commit"], "stranded": ["pre-commit"], "environments": ["devenv.nix"]})
            if proposes_reconcile() else None)
        seed.put(MINUTE, event_log.REGISTRATION_ENDED, None, {
            "by": "owner", "root": root, "project_id": f"owner/{REGISTER_NAME}", "result": "planned",
            "outcome": "reconcile", "headline": f"What adopting {REGISTER_NAME} would change.",
            "lines": list(REGISTER_PLAN_LINES), "note": None, "plan_id": REGISTER_PLAN_ID,
            "state": "ready", "questions": [], "answered": [], "draft": fields, "remote": None})
        if state == "register-reconcile-draft":
            seed.put(MINUTE / 2, event_log.ADOPTION_DEFERRED, None, {"plan_id": REGISTER_PLAN_ID})
        return
    reading = {**contract_draft.read(root),
               "remotes": [("origin", f"https://github.com/owner/{REGISTER_NAME}.git")],
               "default_branch": "main", "branches": ["main"],
               "hooks": ["pre-commit"], "environments": ["devenv.nix"]}
    fields = contract_draft.draft(root, reading)
    seed.put(MINUTE, event_log.REGISTRATION_ENDED, None, {
        "by": "owner", "root": root, "project_id": f"owner/{REGISTER_NAME}", "result": "planned",
        "outcome": "changes", "headline": f"What adopting {REGISTER_NAME} would change.",
        "lines": [*filter(None, [getattr(register, "HOOKS_LINE", None)]), *REGISTER_PLAN_LINES], "note": None, "plan_id": REGISTER_PLAN_ID,
        "state": "ready", "questions": [], "answered": [], "draft": fields, "remote": None})
    if state == "register-draft":
        seed.put(MINUTE / 2, event_log.ADOPTION_DEFERRED, None, {"plan_id": REGISTER_PLAN_ID})


def offers_merge() -> bool:
    """Whether this page's adoption card can offer Merge; a base commit's forge has no such method."""
    return hasattr(approve.GitHubForge, "merge_pull_request")


def overlap_card() -> bool:
    """Whether this console is the base commit's, whose manager contract had a claim overlap's asker send the owner a card.

    True on the base commit's console, whose manager contract had the later-started sprint of an
    unsettled overlap send the owner an owner-only card: the before picture. A console whose view
    carries `OVERLAP_UNSETTLED_TEXT` shows the overlap as one line and asks nobody.
    """
    return not hasattr(view, "OVERLAP_UNSETTLED_TEXT")


LIVE_FAULT_OBSERVED = "saving the settings form drops the billing address"
LIVE_FAULT_WHEN = "12:10 UTC today"
LIVE_FAULT_PROVEN = "a saved form read back from the production database"


def declares_live_faults() -> bool:
    """Whether this service lets the owner withdraw a manager's live-fault declaration (a base commit's has no such method)."""
    return hasattr(ConsoleService, "withdraw_live_fault")


def offers_account_changes() -> bool:
    """Whether this service lets an account be signed out alone (a base commit's service has no such method)."""
    return hasattr(ConsoleService, "sign_out_account")


def _seed_adoption(seed: _Seed, state: str, root: str) -> None:
    """An adoption pull request of `root` the console opened, read ready at the head it pushed or at another.

    Both rows are payload dicts, as a base commit's `approve` refuses the `head` argument and the
    `created` member; a base console ignores the head and refuses the opened step's `created`
    member, so the member is written only when this page offers Merge (the before picture shows
    the card without it).
    """
    pull = {"number": 7, "url": f"https://github.com/owner/{REGISTER_NAME}/pull/7"}
    if offers_merge():
        pull["created"] = True
        pull["id"] = ADOPTION_PULL_ID
    seed.put(MINUTE, event_log.ADOPTION_STEP, None, {
        "by": "owner", "plan_id": REGISTER_PLAN_ID, "root": root, "project_id": f"owner/{REGISTER_NAME}",
        "step": "opened", "branch": ADOPTION_BRANCH, "commit": ADOPTION_COMMIT, "base": "main",
        "pull_request": pull, "reason": None, "note": None, "kept": None, "evidence": None})
    seed.put(MINUTE / 2, event_log.ADOPTION_PULL, None, {
        "plan_id": REGISTER_PLAN_ID, "number": 7, "url": pull["url"], "state": "ready",
        "head": ADOPTION_MOVED_HEAD if state == "adoption-moved" else ADOPTION_COMMIT,
        "base": "main"})


def _seed_state(seed: _Seed, state: str, web_root: str = "",
                read: tuple[str, str] = (READ_QUESTION, READ_ANSWER),
                colleague_identity: str | None = None) -> tuple[str, ...]:
    """Seed the events of `state`; returns the sprint ids whose transcripts the state writes.

    `colleague_identity` is the mark of the colleague's profile directory, which his `account.added` row records."""
    web, api = PROJECTS[0], PROJECTS[1]
    if state in REGISTER_STATES:
        _seed_registration(seed, state, str(Path(web_root).parent / REGISTER_NAME))
        return ()
    if state in ADOPTION_STATES:
        _seed_adoption(seed, state, web_root)
        return ()
    if state == "live-several":
        seed.sprint(api, "Keep the importer fast", started=60 * MINUTE, report=45 * MINUTE,
                    issues=[{"issue": 31, "stage": "building"}, {"issue": 32, "stage": "queued"}])
        seed.sprint(api, "Retire the old exporter", started=5 * 60 * MINUTE,
                    report=3 * 60 * MINUTE, landed=True, close=2 * 60 * MINUTE)
        seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE,
                    asks=True, issues=[{"issue": 41, "stage": "building"}, {"issue": 42, "stage": "queued"}])
        settings = [{"issue": 21, "stage": "held"}, {"issue": 22, "stage": "landing"},
                    {"issue": 23, "stage": "building"}, {"issue": 24, "stage": "queued"}]
        seed.sprint(web, "Fix the settings page", started=20 * MINUTE, report=4 * MINUTE, issues=settings,
                    then=(2 * MINUTE, [{**row, "stage": "landed"} if row["issue"] == 22 else row
                                       for row in settings]))
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
    elif state in PERMISSION_STATES:
        sid, _ = seed.sprint(web, "Add resumable uploads", started=60 * MINUTE,
                             report=45 * MINUTE)
        seed.put(20 * MINUTE, sessions.SEEN, web, {
            "session_id": PERMISSION_MANAGER, "cwd": web_root, "repo": web_root,
            "state": "working", "name": manager.session_name(web, sid)})
        if state == "permission-stale":
            seed.put(10 * MINUTE, sessions.HOOK, web, {
                "event": "PermissionRequest", "session_id": PERMISSION_MANAGER, "cwd": web_root,
                "repo": web_root, "tool_name": "Bash"})
        return (sid,)
    elif state == "waiting-until":
        seed.sprint(web, "Add resumable uploads", started=60 * MINUTE, report=45 * MINUTE,
                    report_extra={"wait_until": _iso(seed.now_s + 2 * 3600)})
    elif state == "paused":
        seed.sprint(web, "Add resumable uploads", started=60 * MINUTE, report=45 * MINUTE,
                    report_extra={"paused": PAUSE_REASON})
    elif state == "failed-start":
        seed.failed_start(web, "Add resumable uploads", 3 * MINUTE)
    elif state in (*SHARING_STATES, "owner-actors", "owner-accounts"):
        seed.put(3 * MINUTE, SHARING_TAILNET, None, {"tailnet": TAILNET})
        if state == "sharing-off":
            seed.put(MINUTE, SHARING_TAILNET, None, {"shared": False})
        seed.put(2 * MINUTE, SHARING_COLLEAGUE, None, {"login": COLLEAGUE, "projects": [web]})
        if state in ("guest-steer", "owner-actors", "owner-accounts"):
            seed.colleague_sprint(web, "Add resumable uploads", started=40 * MINUTE,
                                  by=COLLEAGUE, answered=True)
            seed.colleague_sprint(web, "Fix the settings page", started=20 * MINUTE, by=COLLEAGUE)
            sid, goal = seed.sprint(web, "Try a new cache", started=30 * MINUTE,
                                    report=6 * MINUTE)
            seed.message(web, sid, goal, sent=2 * MINUTE)
            seed.approval(web, 12, MINUTE)
        else:
            seed.sprint(web, "Add resumable uploads", started=30 * MINUTE, report=6 * MINUTE)
            seed.sprint(api, "Keep the importer fast", started=60 * MINUTE, report=45 * MINUTE)
        if state in ("guest-page", "guest-steer", "owner-actors", "owner-accounts"):
            seed.account("work-main", 0.4, session=0.25, week_in=3 * 86400, session_in=2 * 3600)
            seed.account("work-spare", 0.9, session=0.6, week_in=5 * 86400, session_in=4 * 3600)
            added = {"by": COLLEAGUE, "profile": "colleague-1"}
            if colleague_identity is not None:
                added["identity"] = colleague_identity
            seed.put(10 * MINUTE, event_log.ACCOUNT_ADDED, None, added)
            seed.account("colleague-1", 0.95, session=0.5, week_in=2 * 86400, session_in=3 * 3600)
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
        first, first_goal = seed.sprint(web, "Add resumable uploads", started=20 * MINUTE,
                                        report=2 * MINUTE)
        sid, goal = seed.sprint(web, "Fix the settings page", started=20 * MINUTE,
                                report=2 * MINUTE)
        seed.put(100, "notice.posted", web, {"sprint_id": first, "goal": first_goal, "notice": {
            "kind": "claim", "text": "resuming an upload from its row",
            "what": "python/agent_tools/console/page.html", "until": "the upload row lands",
            "issue": 12, "live_fault": True}})
        seed.put(90, "notice.posted", web, {"sprint_id": sid, "goal": goal, "notice": {
            "kind": "claim", "text": "reworking the settings form",
            "what": "python/agent_tools/console/page.html", "until": "the form lands",
            "issue": 13, "live_fault": True}})
        if overlap_card():
            seed.put(60, "questions.asked", web, {
                "sprint_id": sid, "goal": goal, "blocker": False, "questions": [{
                    "question": "Which lands first in python/agent_tools/console/page.html: "
                                "Add resumable uploads or Fix the settings page? "
                                "Both fix a live fault.",
                    "blocks": "the settings form slice",
                    "options": ["Add resumable uploads lands first",
                                "Fix the settings page lands first"],
                    "recommended": "Add resumable uploads lands first", "owner_only": True}]})
        seed.put(30, "notice.posted", web, {"poster": "owner", "notice": {
            "kind": "heads-up", "text": "routes are frozen until Friday"}})
    elif state == "live-fault":
        sid, goal = seed.sprint(web, "Fix the settings page", started=30 * MINUTE,
                                report=6 * MINUTE)
        seed.put(4 * MINUTE, "fault.declared", web, {"sprint_id": sid, "goal": goal, "fault": {
            "issue": 12, "observed": LIVE_FAULT_OBSERVED, "when": LIVE_FAULT_WHEN,
            "proven": LIVE_FAULT_PROVEN}})
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
    elif state in DEEPER_STATES:
        seed.put(40 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": DEEPER_THREAD, "question": DEEPER_QUESTION,
            "profile": "work-main", "session_id": DEEPER_LIGHT_SESSION})
        seed.put(38 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": DEEPER_THREAD, "outcome": "answered", "answer": DEEPER_LIGHT_ANSWER})
        seed.put(30 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": DEEPER_ID, "question": DEEPER_QUESTION, "thread_id": DEEPER_THREAD,
            "deep": True, "profile": "work-main", "session_id": DEEPER_SESSION})
        seed.put(12 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": DEEPER_ID, "outcome": "answered", "answer": DEEPER_ANSWER})
        seed.put(10 * MINUTE, event_log.PROJECT_QUESTION_ASKED, web, {
            "question_id": "1435b1", "question": DEEPER_OFFER_QUESTION,
            "profile": "work-main", "session_id": DEEPER_OFFER_SESSION})
        seed.put(8 * MINUTE, event_log.PROJECT_QUESTION_ANSWERED, web, {
            "question_id": "1435b1", "outcome": "answered", "answer": DEEPER_OFFER_ANSWER})
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

    def __call__(self, sid: str, cwd: str, days_ago: int, input: int, output: int,
                 model: str = "claude-sonnet-4-6") -> dict:
        self.count += 1
        when = datetime.fromtimestamp(self.now_s, timezone.utc) - timedelta(days=days_ago)
        return {"type": "assistant", "sessionId": sid, "cwd": cwd,
                "timestamp": when.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "message": {"id": f"msg-{self.count:04d}", "model": model,
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


def _write_deeper(fixture: Fixture, now_s: float) -> None:
    """Transcripts for the Dig deeper states: each question's session, written today.

    The light sessions total 544,000 and 362,000 tokens; the deeper one runs on `claude-opus-4-6`
    and totals 2,184,000, so its dollars per token are the dearer.
    """
    web = str(fixture.projects[0])
    assistant = _Assistant(now_s)
    slug = fixture.config / "projects" / "-web"
    slug.mkdir(parents=True, exist_ok=True)
    (slug / f"{DEEPER_LIGHT_SESSION}.jsonl").write_bytes(_transcript([
        assistant(DEEPER_LIGHT_SESSION, web, 0, 30_000, 2_000) for _ in range(2)]))
    (slug / f"{DEEPER_SESSION}.jsonl").write_bytes(_transcript([
        assistant(DEEPER_SESSION, web, 0, 60_000, 6_000, model="claude-opus-4-6")
        for _ in range(4)]))
    (slug / f"{DEEPER_OFFER_SESSION}.jsonl").write_bytes(_transcript([
        assistant(DEEPER_OFFER_SESSION, web, 0, 20_000, 1_000) for _ in range(2)]))


def _write_held_manager(fixture: Fixture, now_s: float) -> None:
    """The deaf manager's transcript: a delivered peer message, then the one the client held."""
    slug = fixture.config / "projects" / "-web"
    slug.mkdir(parents=True, exist_ok=True)
    (slug / f"{DEAF_MANAGER}.jsonl").write_bytes(_transcript([
        {"type": "user", "origin": {"kind": "peer"}, "message": {"content": "carry on"}},
        {"type": "system", "content": "Held peer message from the console, not delivered until "
                                      "you approve it at this terminal"}]))


def _write_permission_manager(fixture: Fixture, now_s: float) -> None:
    """The stale-wait manager's transcript: a `user` record stamped after the seeded `PermissionRequest` hook."""
    slug = fixture.config / "projects" / "-web"
    slug.mkdir(parents=True, exist_ok=True)
    (slug / f"{PERMISSION_MANAGER}.jsonl").write_bytes(_transcript([
        {"type": "user", "timestamp": _iso(now_s - 5 * MINUTE), "message": {"content": "carry on"}}]))


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
        activating=ACTIVATION_PATHS.get(state, ()), registering=state in REGISTER_STATES,
        adopting=state in ADOPTION_STATES, refusing=state == "adoption-failed", titled=state == "live-several")
    write_registry(fixture.registry, [
        {"project_id": name, "root": str(path)} for name, path in zip(PROJECTS, projects)])
    at = [_iso(now_s)]
    colleague_identity = None
    if state in ("accounts-panel", "guest-page", "guest-steer", "owner-actors", "owner-accounts"):
        colleague = ("colleague-1",) if state != "accounts-panel" else ()
        for name in ("work-main", "work-spare", *colleague):
            (accounts / "profiles" / name).mkdir(parents=True, exist_ok=True)
        if colleague:
            # The directory's own mark: the console owns the account to the colleague only while the
            # row's identity is the directory's, and his pool row carries a token only then.
            colleague_identity = account_add.mark(accounts / "profiles" / "colleague-1")
    log = EventLog(fixture.store, clock=lambda: at[0])
    try:
        sprint_ids = _seed_state(_Seed(log, at, now_s, console / "pictures"), state, str(projects[0]), read=read,
                                 colleague_identity=colleague_identity)
    finally:
        log.close()
    if state == "manager-cannot-hear":
        _write_held_manager(fixture, now_s)
    if state == "permission-stale":
        _write_permission_manager(fixture, now_s)
    if state in HELD_PROMPTS:
        create_secret(fixture.secrets, sprint_ids[0])
        fixture = replace(fixture, prompting=sprint_ids[0])
    if state == "spend-page":
        _write_spend(fixture, now_s, sprint_ids[0])
    elif state == "desk-spend":
        _write_desk_spend(fixture, now_s, *sprint_ids)
    elif state in DEEPER_STATES:
        _write_deeper(fixture, now_s)
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


def reads_actors() -> bool:
    """Whether this page's service reads who started a sprint (`SprintState` has `started_by`)."""
    return "started_by" in SprintState.__dataclass_fields__


def _activation_reader(paths: tuple[str, ...]):
    """A stand-in reading of merged changes outside the console; a base commit's `Activation` has no `other`."""
    def read(roots):
        other = {"other": paths} if reads_other() else {}
        return Activation(sorted(roots)[0], (), ACTIVATION_COMMIT, **other)
    return read


class _AdoptionForge:
    """A stand-in forge of the adoption states: it reads the seeded pull request as it is, so a poll
    changes nothing. `adoption-merge` and `adoption-moved` are never clicked; with `refuses` its
    merge call fails and the pull request then reads merged at another head, as when someone else
    merged it with commits the console did not push."""

    def __init__(self, head: str, refuses: bool = False):
        self._head = head
        self._refuses = refuses
        self._refused = False

    def pull_request_reading(self, slug, number, cancel=None) -> dict:
        if self._refused:
            return {"state": "merged", "head": ADOPTION_MOVED_HEAD, "base": "main", "checks_error": None,
                    "id": ADOPTION_PULL_ID}
        return {"state": "ready", "head": self._head, "base": "main", "checks_error": None,
                "id": ADOPTION_PULL_ID}

    def merge_pull_request(self, slug, number, head, cancel=None) -> None:
        if not self._refuses:
            raise AssertionError("this state's pull request is never merged")
        self._refused = True
        raise ForgeError("gh_failed", "the pull request was merged elsewhere")

    def pull_request_state(self, slug, number, cancel=None) -> str:
        return "ready"


def _seeded_head(fixture: Fixture) -> str:
    """The head the fixture's adoption pull request row records."""
    log = EventLog(fixture.store)
    try:
        return [event.payload["head"] for event in log.events()
                if event.kind == event_log.ADOPTION_PULL][-1]
    finally:
        log.close()


class _Inert:
    """A stand-in adopter or forge: its presence lets a ready plan be applied, nothing calls it."""


def shows_facts() -> bool:
    """Whether this page's drafted contract shows its derived values as fact lines with no Change."""
    return hasattr(contract_draft, "FACTS")


def proposes_reconcile() -> bool:
    """Whether this page's reconcile plan can propose that command for a hook its PATH cannot find."""
    return hasattr(contract_draft, "reconcile_fields")


def proposes(state: str) -> bool:
    """Whether this page proposes the commit environment in the register state `state`."""
    return proposes_reconcile() if state.startswith("register-reconcile") else shows_facts()


def guest_door_kwargs(constructor, folder: Path) -> dict:
    """The constructor arguments that open the guest door: the branch's socket, else the base's port."""
    if "guest_socket" in inspect.signature(constructor).parameters:
        return {"guest_socket": folder / "guest" / "guest.sock"}
    return {"guest_port": 0}


def guest_door(service) -> str | tuple[str, int]:
    """Where `service` listens for guests: its socket path, else (the base commit) its address."""
    return service.guest_socket if hasattr(service, "guest_socket") else service.guest_address


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
        forge["pull_reader"] = land_queue_reader(fixture.holding)
    if fixture.activating:
        forge["activation_reader"] = _activation_reader(fixture.activating)
    if fixture.registering:
        forge.update(adopter=_Inert(), forge=_Inert())
    if fixture.adopting:
        forge["forge"] = _AdoptionForge(_seeded_head(fixture), refuses=fixture.refusing)
    bound: list = []
    service = ConsoleService(
        fixture.store, fixture.registry, port=0, session_dirs=lambda: [fixture.config / "sessions"],
        profile_dirs=lambda: sorted((fixture.accounts / "profiles").glob("*")), token_path=fixture.token, sprint_secrets=fixture.secrets,
        session_poll_seconds=3600, nudger=lambda nudge: None, launcher=launcher,
        activity=lambda root: None,
        slug_of=(lambda root: "owner/web") if fixture.holding or fixture.titled else (lambda root: None),
        branch_pattern_of=lambda repo: "issue-<num>-<slug>" if fixture.holding else None,
        dispatch=lambda job: job(),
        repo_of=lambda cwd: cwd, ping_log=lambda: None,
        **({} if guest_dir is None else guest_door_kwargs(ConsoleService, guest_dir)),
        **_tailnet_kwargs(guest_dir, tailnet_readable, bound),
        **(stand_ins.title_kwargs(ConsoleService) if fixture.titled else {}), **forge)
    bound.append(service)
    service.start()
    if guest_dir is not None and "status_reader" in inspect.signature(ConsoleService).parameters:
        service.poll_serve()
    service.poll_spend()
    if fixture.titled:
        stand_ins.poll_titles(service)
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
            read: tuple[str, str] = (READ_QUESTION, READ_ANSWER), sheets: bool = False,
            mutate: bool = False, composite: str | None = None) -> list[Shot]:
    if composite is not None and not sheets:
        raise ValueError("a composite is made of the sheets: pass sheets with it")
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
                # A state that clicks changes its console for good, so each width gets its own.
                groups = [(width,) for width in widths] if state in CLICKED_STATES else [tuple(widths)]
                shot_paths = []
                for group in groups:
                    with tempfile.TemporaryDirectory(prefix="console-shots-") as tmp, \
                            tempfile.TemporaryDirectory(prefix="cg-", dir="/tmp") as door:
                        now_s = datetime.now(timezone.utc).timestamp()
                        fixture = build_fixture(Path(tmp).resolve(), state, now_s, read=read)
                        service = start_service(
                            fixture, now_s,
                            guest_dir=Path(door) if state in SHARING_STATES else None,
                            tailnet_readable=state != "sharing-unreadable")
                        serve = None
                        try:
                            host, port = service.address
                            if state in HELD_PROMPTS:
                                held = hold_permission(service, fixture, state)
                            if state in SHARING_PANELS:
                                guest_requests(state, guest_door(service))
                            elif state in ("guest-page", "guest-steer"):
                                serve = _Serve(guest_door(service))
                                host, port = serve.address
                            for width in group:
                                if state in HELD_PROMPTS:
                                    keep_permission(service, fixture, held)
                                path = "spend" if state == "spend-page" else ""
                                taken.append(
                                    _shoot(browser, f"http://{host}:{port}/{path}", state, width, out,
                                           question=read[0],
                                           canonical=read == (READ_QUESTION, READ_ANSWER),
                                           mutate=mutate))
                                shot_paths.append(out / f"{state}-{width}.png")
                        finally:
                            if serve is not None:
                                serve.close()
                            service.close()
                if sheets:
                    sheet(browser, shot_paths, out / f"{state}-sheet.png")
            if sheets and composite is not None:
                composite_sheet(browser, out, states, composite)
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
  const owners = Array.from(document.querySelectorAll(
    '#projects button.notice-withdraw, #projects button.live-fault-withdraw')).filter(
    (button) => button.innerText.trim() === 'Withdraw').length;
  return folds + rows + Math.max(0, (phrases ? phrases.length : 0) - owners);
})()"""


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
    read = [row for row in rows if only is None or row.name == only]
    page.evaluate(STYLE_CLEAR)
    if mutation is not None:
        page.evaluate(STYLE_MUTATE, mutation)
    # Only the rows read are placed: a mutated read of one row would otherwise lay out every
    # other row's probe again, which takes the whole run past an hour.
    page.evaluate(STYLE_PLACE, [asdict(row) for row in read])
    page.evaluate(STYLE_SETTLE)
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
        if state in ("guest-page", "guest-steer") and page.query_selector("#console-door") is not None:
            page.wait_for_selector("#top-who:not([hidden])")
            if page.query_selector("#capacity") is not None:
                raise RuntimeError("the guest shot is not the guest page")
        if state in ("guest-page", "guest-steer") and page.query_selector("#pool") is not None:
            for selector in ("#pool:not([hidden])", "#pool .pool-session time", ".sprint-account"):
                page.wait_for_selector(selector)
        if state in ("guest-page", "guest-steer") and page.query_selector(".pool-add") is not None:
            page.click(".pool-add")
            for selector in (".guest-consent", ".guest-signin:disabled"):
                page.wait_for_selector(selector)
        if state == "guest-steer" and reads_actors():
            for selector in (".started-by", "text=Answered by", ".guest-wait", "#inbox button.approve"):
                page.wait_for_selector(selector)
        if state == "owner-actors" and reads_actors():
            for selector in (".started-by", "text=Answered by"):
                page.wait_for_selector(selector)
        if state == "owner-actors" and page.query_selector(".cap-owner") is not None:
            page.wait_for_selector(".cap-tightest .cap-owner")
        if state == "guest-page" and offers_account_changes():
            for selector in (".pool-yours .pool-signout", ".pool-yours .pool-remove"):
                page.wait_for_selector(selector)
        if state == "owner-accounts":
            page.click("#capacity")
            page.wait_for_selector("#accounts:not([hidden])")
            if page.query_selector(".acct-owner") is not None:
                page.wait_for_selector(".acct-row .acct-owner")
            if offers_account_changes():
                page.wait_for_selector(".acct-row .acct-signout")
        if state in ADOPTION_STATES:
            page.wait_for_selector(
                ADOPTION_CARD + (" .reason" if state == "adoption-moved" else " button.adoption-merge")
                if offers_merge() else ADOPTION_CARD)
        if state == "adoption-failed" and offers_merge():
            page.click(ADOPTION_CARD + " button.adoption-merge")
            page.wait_for_selector("#inbox .adoption-failed button.adoption-failed-dismiss")
            page.wait_for_selector(ADOPTION_CARD, state="detached")
        if state in ("finished-list", "desk-spend"):
            if state == "desk-spend":
                page.click('details[data-key="line:owner/web"] > summary')
            page.click('details[data-key="finished"] > summary')
            page.click('details[data-key^="ended:"] > summary')
        if state in ("notices-fold", "notice-post-open"):
            page.click('details[data-key^="notices:"] > summary')
            if state == "notice-post-open" and page.query_selector("button.notice-open"):
                page.click("button.notice-open")
        if state == "live-fault" and declares_live_faults():
            for selector in (".sprint-checks .live-fault", ".live-fault-withdraw"):
                page.wait_for_selector(selector)
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
        paneled = (state in ("ask-box", "ask-goal", "questions-open", "question-read",
                             *DEEPER_STATES)
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
        deeper = None
        if state in DEEPER_STATES:
            if paneled:
                thread_id = DEEPER_THREAD if state == "deeper-answer" else DEEPER_OFFER_THREAD
                for selector in (ASK_FOLD, thread_line(thread_id)):
                    page.click(selector)
                if state == "deeper-answer":
                    deeper = _frozen(page.evaluate(DEEPER_READING))
                else:
                    if page.query_selector(DEEP_OPEN):
                        page.click(DEEP_OPEN)
                        page.wait_for_selector(DEEP_ESTIMATE)
                    deeper = _frozen(page.evaluate(OFFER_READING))
            elif page.query_selector(ASK_FOLD):
                for selector in (ASK_FOLD, DEEPER_BASE_THREAD[state]):
                    page.click(selector)
        activation = None
        if state in ACTIVATION_PATHS:
            activation = tuple(page.evaluate(ACTIVATION_READING))
        register = None
        if state in REGISTER_STATES:
            register = tuple(page.evaluate(REGISTER_READING))
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
            reads = [(width, [row for row in STYLE_CHECKS
                              if state in row.states and width in row.widths
                              and (canonical or not row.fixture)])]
            if width == WIDTHS[0]:
                reads += [(between, [row for row in STYLE_CHECKS
                                     if state in row.states and between in row.widths
                                     and (canonical or not row.fixture)])
                          for between in BETWEEN_WIDTHS]
            for at, rows in reads:
                if not rows:
                    continue
                if at != width:
                    page.set_viewport_size({"width": at, "height": HEIGHT})
                    page.evaluate(STYLE_SETTLE)
                style += read_style(page, rows)
                checked += tuple(row.name for row in rows)
                if mutate:
                    broke += tuple(
                        row.name for row in rows
                        if any(miss.startswith(row.name + ": ") for miss in read_style(
                            page, rows, mutation=row.broken, only=row.name)))
    finally:
        page.close()
    return Shot(state, width, path, scroll_width, squeezed, jargon, tell, scroll_y=scroll_y,
                short=short, ask=ask, goal=goal, acts=acts, thread=thread, reading=reading,
                card=card, activation=activation, register=register, style=style, checked=checked, broke=broke,
                deeper=deeper)


def sheet(browser, paths: Sequence[Path], out: Path) -> Path:
    """One PNG of the given pictures side by side, top-aligned, in the order given.

    Refuses with a RuntimeError when the file is over `pictures.MAX_BYTES`, the size `sprint ask`
    refuses a picture over.
    """
    out = Path(out)
    images = "".join(
        '<img src="data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode() + '">'
        for path in paths)
    page = browser.new_page(viewport={"width": 2400, "height": HEIGHT})
    try:
        page.set_content(
            "<!doctype html><html><body style=\"margin:0;background:#fff\">"
            "<div id=\"row\" style=\"display:inline-flex;align-items:flex-start;gap:16px;"
            f"padding:16px;background:#fff\">{images}</div></body></html>")
        page.locator("#row").screenshot(path=str(out))
    finally:
        page.close()
    size = out.stat().st_size
    if size > pictures.MAX_BYTES:
        raise RuntimeError(f"{out} is {size} bytes, over the {pictures.MAX_BYTES} a picture may be")
    return out


def composite_sheet(browser, out: Path, states: Sequence[str], name: str) -> Path:
    """The named states' sheets side by side in `out / name`; refuses over `pictures.MAX_BYTES` as `sheet` does."""
    out = Path(out)
    return sheet(browser, [out / f"{state}-sheet.png" for state in states], out / name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="console-screenshots",
        description="Shoot the console's sprint states against a fixture console.")
    parser.add_argument("--out", required=True, help="the directory the PNG files go to")
    parser.add_argument("--question", help="the owner's question, shot with --answer-file")
    parser.add_argument("--answer-file", help="the stored answer's text (UTF-8), shot with --question")
    parser.add_argument("--sheets", action="store_true",
                        help="also write <state>-sheet.png, the state's widths side by side")
    parser.add_argument("--states", help="a comma list of the states to shoot (default every state)")
    parser.add_argument("--composite", help="with --sheets, also write NAME, the shot states' sheets side by side")
    args = parser.parse_args(argv)
    states = STATES
    if args.states is not None:
        states = tuple(args.states.split(","))
        unknown = [state for state in states if state not in STATES]
        if unknown:
            parser.error(f"--states names {', '.join(unknown)}, which are not states")
    if args.composite is not None and not args.sheets:
        parser.error("--composite goes with --sheets")
    if (args.question is None) != (args.answer_file is None):
        parser.error("--question and --answer-file go together")
    real = args.question is not None
    if real:
        text = Path(args.answer_file).read_text(encoding="utf-8")
    saved = {name: os.environ.get(name) for name in sandbox_environ(Path("."))}
    with tempfile.TemporaryDirectory(prefix="console-shots-env-") as tmp:
        os.environ.update(sandbox_environ(Path(tmp).resolve()))
        try:
            taken = (capture(Path(args.out), states=("question-read",), read=(args.question, text),
                             sheets=args.sheets, composite=args.composite)
                     if real else capture(Path(args.out), states=states, sheets=args.sheets,
                                          composite=args.composite))
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
    if args.sheets:
        for state in dict.fromkeys(shot.state for shot in taken):
            print(Path(args.out) / f"{state}-sheet.png")
        if args.composite is not None:
            print(Path(args.out) / args.composite)
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
    paneled_page = serves_reading_panel()
    undeep = [shot for shot in taken if shot.state in DEEPER_ROWS
              and not (deeper_shows(shot.state, shot.deeper)
                       or (shot.deeper is None and not paneled_page))]
    for shot in undeep:
        print(f"console-screenshots: {shot.path.name} does not show {DEEPER_SAID[shot.state]}")
    unlined = [shot for shot in taken if shot.state in ACTIVATION_SHOWN
               and shot.activation not in (
                   (ACTIVATION_SHOWN[shot.state],) if reads_other()
                   else (ACTIVATION_SHOWN[shot.state], ACTIVATION_BASE))]
    for shot in unlined:
        print(f"console-screenshots: {shot.path.name} does not show the activation line with its "
              "Activate button")
    proposals = [shot for shot in taken if shot.state in REGISTER_SHOWN and shot.register != (
        REGISTER_SHOWN[shot.state] if proposes(shot.state) else REGISTER_BASE[shot.state])]
    for shot in proposals:
        print(f"console-screenshots: {shot.path.name} does not show the proposed commit "
              "environment on the Apply card or as a changeable draft line")
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
                 or undeep or unlined or proposals or uncarded or offrow or scrolled or short or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
