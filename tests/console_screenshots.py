"""A repeatable screenshot set of the console's sprint states (#1086).

Run: just console-screenshots [out]   (Playwright and its Chromium come from nixpkgs)

Contract:
- `STATES` names the twenty screens the sprint block, the finished list, the message life, the
  Spend page, the notices fold, the desk's spend figures and the controls must read well on (`tell-box-open` is
  the sprint block with its Tell box opened; `owner-check` is the sprint block with a held
  issue's owner check beside it; `spend-page` is the `/spend` page over seeded transcripts: a
  running sprint's manager session, an outside-sprint session and one workflow run, with spend on
  at least four of the last seven days; `notices-fold` is `owner/web`'s open Notices fold;
  `notice-post-open` is that fold with the owner's post control opened, and shot against a page
  that has no such control it is the same fold, which is how the before pictures are made;
  `desk-spend` is the desk page over seeded transcripts: a running sprint and a finished,
  landed one, each with a manager session on two or more days, and an outside-sprint session
  with one batch delivery run, with the sprint block, the finished line and the run line open
  so the spend figures show; `goal-open` is the sprint block of `tell-box-open` with the top
  bar's goal field focused so its box is open; `inbox-card` is `owner/web`'s question card with
  two options and an owner check beside it; `accounts-panel` is the accounts panel opened over
  two signed-in profiles, `work-main` and `work-spare`, each with one capacity reading;
  `ask-box` is `owner/web`'s Ask box opened over one answered question (its answer, Read and Ran
  lines) and one question still working, and shot against a page with no Ask box it is the desk
  without it, which is the before picture; `ask-goal` is the `ask-box` fixture with `owner/web`'s
  answered question's Make it a goal clicked, so the goal box shows filled from it with
  `owner/web` chosen, and shot against a page without that control it is unclicked, which is the
  before picture);
  `WIDTHS` are the two viewport widths each is shot at. `capture`
  writes `<state>-<width>.png` for every pair, so a full run writes 40 files.
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
  the sprint block's content, `OPEN_TELL`); or when an `ask-box` shot of a page that has the Ask
  box does not show `owner/web`'s open field, its working question and its answered question's
  Read line (`OPEN_ASK`); or when an `ask-goal` shot's reading is not `FILLED_GOAL` (the box
  closed, the wrong text or project, or the field clipping the filled text); or when any shot is not taken from the top of the
  page (`window.scrollY` is not 0 right before its full-page capture); or when any shot has a
  rendered, visible button, input, textarea, select, `btn-` link or `btn-` summary under 32 px
  tall (`SHORT_CONTROLS`, read after the state is drawn). It returns 2 with a one-line
  reason when Playwright or Chromium is missing, else 0. Playwright is imported inside `capture` only,
  so the fixture half of this module needs nothing beyond the standard library.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console import capacity, event_log, manager, sessions, signin
from agent_tools.console.event_log import EventLog
from agent_tools.console.service import ConsoleService
from agent_tools.console.sprints import TELL_MINUTE_TEXT

from .console_test_support import write_registry

STATES = ("live-several", "waiting-on-you", "stuck", "tell-box-open", "message-sent",
          "message-picked-up", "message-replied", "message-not-picked-up", "finished-list",
          "nothing-running", "owner-check", "spend-page", "notices-fold", "notice-post-open",
          "desk-spend", "goal-open", "inbox-card", "accounts-panel", "ask-box", "ask-goal")
WIDTHS = (1440, 480)
HEIGHT = 900
MINUTE = 60.0
PROJECTS = ("owner/web", "owner/api", "owner/docs")
TRACKER_URL = "https://github.com/owner/web/issues"
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
ASK_OPEN = 'li.asks[data-project="owner/web"] button.ask-open'
OPEN_ASK = (True, "Working on it", ASK_READ_LINE)
ASK_GOAL = 'li.asks[data-project="owner/web"] button.ask-goal'
FILLED_GOAL = (True, ASK_ANSWERED_QUESTION + "\n\n" + ASK_ANSWER_SUMMARY, "owner/web", True)
DESK_OUTSIDE = "outside-1136"


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
               stop: float | None = None, held: bool = False) -> tuple[str, str]:
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


def _seed_state(seed: _Seed, state: str, web_root: str = "") -> tuple[str, ...]:
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
    elif state in ("tell-box-open", "goal-open"):
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


def build_fixture(root: Path, state: str, now_s: float) -> Fixture:
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
        accounts=accounts, config=config, state=state_dir, projects=projects)
    write_registry(fixture.registry, [
        {"project_id": name, "root": str(path)} for name, path in zip(PROJECTS, projects)])
    at = [_iso(now_s)]
    log = EventLog(fixture.store, clock=lambda: at[0])
    try:
        sprint_ids = _seed_state(_Seed(log, at, now_s), state, str(projects[0]))
    finally:
        log.close()
    if state == "accounts-panel":
        for name in ("work-main", "work-spare"):
            (accounts / "profiles" / name).mkdir(parents=True, exist_ok=True)
    if state == "spend-page":
        _write_spend(fixture, now_s, sprint_ids[0])
    elif state == "desk-spend":
        _write_desk_spend(fixture, now_s, *sprint_ids)
    return fixture


def start_service(fixture: Fixture, now_s: float, launches: list | None = None) -> ConsoleService:
    def launcher(launch: manager.Launch) -> None:
        if launches is not None:
            launches.append(launch)

    service = ConsoleService(
        fixture.store, fixture.registry, port=0, session_dirs=lambda: [fixture.config / "sessions"],
        profile_dirs=lambda: sorted((fixture.accounts / "profiles").glob("*")), token_path=fixture.token, sprint_secrets=fixture.secrets,
        session_poll_seconds=3600, nudger=lambda nudge: None, launcher=launcher,
        activity=lambda root: None, slug_of=lambda root: None,
        branch_pattern_of=lambda repo: None, dispatch=lambda job: job(),
        repo_of=lambda cwd: cwd, ping_log=lambda: None)
    service.start()
    service.poll_spend()
    return service


def capture(out: Path, states: Sequence[str] = STATES,
            widths: Sequence[int] = WIDTHS) -> list[Shot]:
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
                    service = start_service(build_fixture(Path(tmp).resolve(), state, now_s), now_s)
                    try:
                        host, port = service.address
                        for width in widths:
                            path = "spend" if state == "spend-page" else ""
                            taken.append(
                                _shoot(browser, f"http://{host}:{port}/{path}", state, width, out))
                    finally:
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
  const block = document.querySelector('li.asks');
  if (!block) return null;
  const mine = document.querySelector('li.asks[data-project="owner/web"]');
  if (!mine) return [false, null, null];
  const field = mine.querySelector('textarea.ask-text');
  let shown = false;
  if (field) {{
    const rect = field.getBoundingClientRect();
    shown = field.getClientRects().length > 0 && rect.width > 0 && rect.height > 0
      && getComputedStyle(field).visibility !== 'hidden';
  }}
  const visible = (node) => node.getClientRects().length > 0;
  const read = (start, selector) => {{
    const row = Array.from(mine.querySelectorAll('li.ask')).find((item) => {{
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


def _shoot(browser, url: str, state: str, width: int, out: Path) -> Shot:
    page = browser.new_page(viewport={"width": width, "height": HEIGHT})
    try:
        page.goto(url)
        page.wait_for_selector("#breakdowns h2" if state == "spend-page" else "#projects h2")
        if state in ("finished-list", "desk-spend"):
            if state == "desk-spend":
                page.click('details[data-key="line:owner/web"] > summary')
            page.click('details[data-key="finished"] > summary')
            page.click('details[data-key^="ended:"] > summary')
        if state in ("notices-fold", "notice-post-open"):
            page.click('details[data-key^="notices:"] > summary')
            if state == "notice-post-open" and page.query_selector("button.notice-open"):
                page.click("button.notice-open")
        if state == "goal-open":
            page.focus("textarea.goal-text")
            page.wait_for_selector(".goal-box")
        if state == "accounts-panel":
            page.click("#capacity")
            page.wait_for_selector("#accounts:not([hidden])")
        tell = None
        if state == "tell-box-open":
            page.click("button.tell-open")
            page.wait_for_selector(".tell-hint")
            tell = tuple(page.evaluate(TELL_READING))
        ask = None
        if state == "ask-box" and page.query_selector("li.asks"):
            page.click(ASK_OPEN)
            page.wait_for_selector('li.asks[data-project="owner/web"] textarea.ask-text')
            ask = tuple(page.evaluate(ASK_READING))
        goal = None
        if state == "ask-goal" and page.query_selector(ASK_GOAL):
            page.click(ASK_GOAL)
            page.wait_for_selector("#goal .goal-box")
            goal = tuple(page.evaluate(GOAL_READING))
        page.evaluate(SCROLL_TOP)
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        squeezed = page.evaluate(SQUEEZED_COUNT)
        jargon = page.evaluate(JARGON_COUNT)
        scroll_y = page.evaluate(SCROLL_Y)
        short = tuple(page.evaluate(SHORT_CONTROLS))
        path = out / f"{state}-{width}.png"
        page.screenshot(path=str(path), full_page=True)
    finally:
        page.close()
    return Shot(state, width, path, scroll_width, squeezed, jargon, tell, scroll_y=scroll_y,
                short=short, ask=ask, goal=goal)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="console-screenshots",
        description="Shoot the console's sprint states against a fixture console.")
    parser.add_argument("--out", required=True, help="the directory the PNG files go to")
    args = parser.parse_args(argv)
    saved = {name: os.environ.get(name) for name in sandbox_environ(Path("."))}
    with tempfile.TemporaryDirectory(prefix="console-shots-env-") as tmp:
        os.environ.update(sandbox_environ(Path(tmp).resolve()))
        try:
            taken = capture(Path(args.out))
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
    jargon = [shot for shot in taken if shot.jargon > 0]
    for shot in jargon:
        print(f"console-screenshots: {shot.path.name} shows a jargon label ({shot.jargon})")
    closed = [shot for shot in taken if shot.state == "tell-box-open" and shot.tell != OPEN_TELL]
    for shot in closed:
        print(f"console-screenshots: {shot.path.name} does not show the open Tell box")
    unasked = [shot for shot in taken
               if shot.state == "ask-box" and shot.ask not in (None, OPEN_ASK)]
    for shot in unasked:
        print(f"console-screenshots: {shot.path.name} does not show the open Ask box")
    unfilled = [shot for shot in taken
                if shot.state == "ask-goal" and shot.goal not in (None, FILLED_GOAL)]
    for shot in unfilled:
        print(f"console-screenshots: {shot.path.name} does not show the goal box filled from "
              "the answer")
    scrolled = [shot for shot in taken if shot.scroll_y != 0]
    for shot in scrolled:
        print(f"console-screenshots: {shot.path.name} is not taken from the top of the page "
              f"(scrolled {shot.scroll_y:g} px)")
    short = [shot for shot in taken if shot.short]
    for shot in short:
        print(f"console-screenshots: {shot.path.name} has a control under 32 px "
              f"({', '.join(shot.short)})")
    return 1 if wide or squeezed or jargon or closed or unasked or unfilled or scrolled or short else 0


if __name__ == "__main__":
    sys.exit(main())
