"""The picture run's desk with one card and seven running sprints (#1807), and the run's choice of states and widths."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .console_screenshots import _Seed

SEVEN_SPRINTS = "seven-sprints"
# (project index, title, started minutes ago, last report minutes ago, asks): every report is under ten minutes old so
# no sprint reads as stuck; `asks` is the one card.
SPRINTS: tuple[tuple[int, str, int, int, bool], ...] = (
    (0, "Add resumable uploads", 30, 6, True),
    (0, "Fix the settings page", 20, 2, False),
    (0, "Try a new cache", 40, 3, False),
    (1, "Keep the importer fast", 60, 4, False),
    (1, "Retire the old exporter", 50, 5, False),
    (2, "Index the search pages", 35, 7, False),
    (2, "Check the broken links", 25, 8, False),
)
MILESTONES = {"Index the search pages": "the page index", "Check the broken links": "the link checker"}


def seed_seven_sprints(seed: _Seed, projects: Sequence[str], minute: float) -> None:
    """Seven running sprints over the three projects, one of them holding the desk's only open question."""
    for index, title, started, report, asks in SPRINTS:
        seed.sprint(projects[index], title, started=started * minute, report=report * minute, asks=asks)


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
