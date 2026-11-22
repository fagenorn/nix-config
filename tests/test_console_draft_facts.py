"""The drafted contract's derived values are fact lines with no Change control (#1485, ADR-console-033 D1)."""

import json
import unittest

from agent_tools.console import contract_draft, register
from agent_tools.console.view import derive_view

from .test_console_page import ASKING, START, cards, full, has_class, nodes, registered, render

TIER = "integration"  # the page cases run the page under node
PROTECTION = json.dumps({"required_status_checks": {"strict": True, "checks": [{"context": "CI"}]}})
READING = {"remotes": [("origin", "https://github.com/sample-owner/sample-app.git")],
           "default_branch": "trunk", "branches": ["trunk"],
           "files": ["README.md", "justfile", ".github/branch-protection.json"],
           "texts": {"justfile": "lint:\n\ttrue\ntest:\n\ttrue\n"},
           "protection_after": PROTECTION}


def registration_of(reading):
    row = register.drafting("/x/sample-app", contract_draft.draft("/x/sample-app", reading))
    return derive_view([], registration=register.view_entry(
        None, {**row, "at": "2026-11-15T08:00:00+00:00"}))["registration"]


class DraftFactsTest(unittest.TestCase):
    def test_a_derived_value_is_a_fact_line_with_no_change_control(self) -> None:
        registration = registration_of(READING)
        by_field = {entry["field"]: entry for entry in registration["draft"]}
        identity = by_field["project-identity"]
        self.assertIs(identity["fact"], True)
        self.assertIs(identity["more"], False)
        self.assertEqual(identity["options"], [])
        self.assertEqual(
            identity["line"],
            "project id and issue tracker: GitHub, as sample-owner/sample-app (read from its remote)")
        self.assertEqual({f: by_field[f]["fact"] for f in contract_draft.FIELDS},
                         {f: False for f in contract_draft.FIELDS})
        self.assertEqual({f: by_field[f]["fact"] for f in contract_draft.FACTS},
                         {f: True for f in contract_draft.FACTS})
        self.assertEqual(registration["draft_more"], "and 2 more settings at their usual values")

    def test_a_fact_entry_draws_no_change_control(self) -> None:
        editable = {"field": "integration-branch", "line": "integration branch: trunk (read from its remote)",
                    "value": "trunk", "options": [], "text": True, "more": False, "fact": False,
                    "placeholder": "a branch name"}
        fact = {"field": "project-identity",
                "line": "project id and issue tracker: GitHub, as o/r (read from its remote)",
                "value": "o/r", "options": [], "text": False, "more": False, "fact": True,
                "placeholder": None}
        later = {"field": "release", "line": "release profile: unsupported (the console's starting value)",
                 "value": "unsupported", "options": [], "text": True, "more": True, "fact": False,
                 "placeholder": "the release profile"}
        drafted = {**ASKING, "questions": [], "draft": [editable, fact, later],
                   "draft_more": "and 1 more setting at its usual value"}
        (snap,) = render([START, {"frame": cards([], drafted)}, {"snapshot": True}])
        self.assertIn(fact["line"], full(snap["register"]))
        (row,) = [n for n in nodes(snap["register"]) if n["tag"] == "li" and full(n).startswith(fact["line"])]
        self.assertEqual([n for n in nodes(row) if n["tag"] == "button"], [])
        (fold,) = registered(snap, "draft-more")
        self.assertNotIn(fact["line"], full(fold))
        self.assertEqual([full(n) for n in registered(snap, "draft-change")], ["Change"])
        self.assertFalse(any(has_class(n, "draft-edit") for n in nodes(row)))

    def test_a_fact_that_cannot_be_derived_names_the_missing_file(self) -> None:
        registration = registration_of({**READING, "protection_after": None})
        (entry,) = [e for e in registration["draft"] if e["field"] == "required-checks"]
        self.assertIs(entry["fact"], True)
        self.assertEqual(
            entry["line"],
            "checks a pull request must pass: cannot be derived until "
            ".github/branch-protection.json is in the repository")


if __name__ == "__main__":
    unittest.main()
