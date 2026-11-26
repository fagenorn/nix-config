"""The picture run's desk with one card and seven running sprints (#1807), and the run's choice of states and widths."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .console_screenshots import _Seed

SEVEN_SPRINTS = "seven-sprints"
# (project index, title, started minutes ago, last report minutes ago, asks): every sprint started over ten hours ago,
# as on the live desk, so the digest's eight-hour window is short; every report is under ten minutes old so no sprint
# reads as stuck; `asks` is the one card.
SPRINTS: tuple[tuple[int, str, int, int, bool], ...] = (
    (0, "Add resumable uploads", 630, 6, True),
    (0, "Fix the settings page", 620, 2, False),
    (0, "Try a new cache", 640, 3, False),
    (1, "Keep the importer fast", 660, 4, False),
    (1, "Retire the old exporter", 650, 5, False),
    (2, "Index the search pages", 635, 7, False),
    (2, "Check the broken links", 625, 8, False),
)
MILESTONES = {"Index the search pages": "the page index", "Check the broken links": "the link checker"}
# The live desk's sprints each list twenty issues: six landed, two building, twelve queued.
ISSUES = tuple({"issue": 101 + i, "stage": "landed" if i < 6 else "building" if i < 8 else "queued"}
               for i in range(20))
LEAD_TEXT = (
    "Before you go further on {title}, I want to settle how the remaining slices are cut and in what order they go "
    "out. The first slices are merged and green, but the later ones touch the same files, and I am worried that "
    "landing them one after another will make each review harder than the last. Could you split the rest into "
    "slices small enough to read in one sitting, and tell me which of them depend on another so I can see what can "
    "run side by side? I would also like your view on the risks. The one I keep coming back to is a partial write "
    "that leaves the old and new shapes side by side for a while, so a reader in the middle of the change sees "
    "neither whole. If you think that is real, say how you would guard against it, and whether a short window of "
    "reading both shapes is acceptable or whether the change must be cut over in one step. Please also say which "
    "checks you plan to run after each slice lands, how long each takes, and which of them you would skip if time "
    "runs short. If any slice needs a decision from me, put it as a question with a recommendation so I can answer "
    "it quickly from the desk. Finally, tell me what you would do differently if the slices grew, because I would "
    "rather stop and re-plan than push a large change through at the end of the day. Keep the answer in plain "
    "words and short paragraphs; I will read it on the desk between other things, and I do not need a table.")
MANAGER_TEXT = (
    "Here is how I would cut the rest of {title}. The remaining work falls into four slices. The first two are "
    "independent of each other and can run side by side, since they touch different files. The third depends on "
    "the first, because it reads the shape the first one writes. The fourth is the clean-up and goes last, once the "
    "others have landed and the checks are green. Each slice is small enough to read in one sitting, and none "
    "changes more than a handful of files. On the risks, you are right about the partial write. I would not leave "
    "both shapes in place for long. The reader will accept either shape for exactly one release, so a reader in the "
    "middle of the change sees one of them whole, and the second slice removes the old shape. That keeps the window "
    "short and makes the cut-over a single reviewed change instead of a sequence of small ones. After each slice "
    "lands I will run the focused tests for the files it touched, which take under a minute, and the full suite "
    "once at the end, which takes several minutes. If time runs short I would skip the full suite for the first "
    "two slices only, never for the third or the fourth. Nothing here needs a decision from you right now. If a "
    "slice grows past what one person can read, I will stop, tell you on the desk, and propose a new split before "
    "writing more code. I will report again when the first of the four has landed, and again when the last one "
    "is merged, with the list of checks I ran and what each of them found.")
FAULTED = ("Keep the importer fast", "Index the search pages")
# (issue, observed, when, proven): each formats into `view.LIVE_FAULT_TEXT` as a line of 380 to 420 characters.
FAULTS: tuple[tuple[int, str, str, str], ...] = (
    (103, "the importer drops every second row of a large upload and reports success to the caller without any "
          "warning in the log, so the owner sees a complete import that is in fact half empty",
     "twice in the last day, on the two largest uploads of the week",
     "the row counts of the file and of the table, which differ by exactly half on both runs"),
    (104, "the search page index is rebuilt from an older snapshot after every restart, so pages published since "
          "the last full build vanish from the results until the next scheduled build runs",
     "on each of the last three restarts, within a minute of the service coming back",
     "the index's build time, which is older than the newest page's publish time each time"),
)
EXCHANGE_AGO = 540  # minutes: past the digest's eight-hour first-visit window, after every brief approval
FAULT_AGO = 530


def seed_seven_sprints(seed: _Seed, projects: Sequence[str], minute: float) -> None:
    """Seven running sprints over the three projects, one of them holding the desk's only open question.

    Each has a twenty-issue report and a last exchange of about 300 words each side; two carry two live faults."""
    for index, title, started, report, asks in SPRINTS:
        project = projects[index]
        sid, goal = seed.sprint(project, title, started=started * minute, report=report * minute, asks=asks,
                                report_extra={"issues": [dict(issue) for issue in ISSUES]})
        said = seed.put(EXCHANGE_AGO * minute, "sprint.messaged", project,
                        {"sprint_id": sid, "goal": goal, "text": LEAD_TEXT.format(title=title)})
        seed.put((EXCHANGE_AGO - 5) * minute, "sprint.answered", project,
                 {"sprint_id": sid, "message": said.seq, "reply": MANAGER_TEXT.format(title=title)})
        if title in FAULTED:
            for issue, observed, when, proven in FAULTS:
                seed.put(FAULT_AGO * minute, "fault.declared", project, {"sprint_id": sid, "goal": goal, "fault": {
                    "issue": issue, "observed": observed, "when": when, "proven": proven}})


def chosen(parser: argparse.ArgumentParser, args: argparse.Namespace, states: tuple[str, ...],
           widths: tuple[int, ...]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    """The states and widths a run shoots; a refused argument exits 2 through `parser`."""
    known = states
    if args.states is not None:
        states = tuple(args.states.split(","))
        unknown = [state for state in states if state not in known]
        if unknown:
            parser.error(f"--states names {', '.join(unknown)}, which are not states")
    if args.composite is not None and not args.sheets:
        parser.error("--composite goes with --sheets")
    if (args.question is None) != (args.answer_file is None):
        parser.error("--question and --answer-file go together")
    if args.widths is not None:
        members = args.widths.split(",")
        if not all(member.isdecimal() and int(member) >= 1 for member in members):
            parser.error("--widths is a comma list of whole numbers of pixels, each at least 1")
        widths = tuple(int(member) for member in members)
    return states, widths
