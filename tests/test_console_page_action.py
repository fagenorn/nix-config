"""The desk page's card for an owner-approved action: its line and its exact command (issue 1687)."""

import re
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_page import PAGE, Q0, START, frame, full, has_class, nodes, question, render


ACTION_COMMAND = "curl -sS -X POST http://127.0.0.1:27999/api/plan-approve --data '<b>x</b>'"
ACTION_LINE = ("Choosing \"Run it once\" lets the manager run exactly this command once, "
               "within 60 minutes of your answer:")


class PageActionTest(unittest.TestCase):
    def test_an_action_card_shows_the_exact_command_under_its_line(self) -> None:
        asked = {**question(0, "May the manager run this one Apply?", ["Run it once", "Do not run it"],
                            "Run it once"),
                 "owner_only": True, "consequential": True,
                 "action": {"command": ACTION_COMMAND, "approve_index": 0, "line": ACTION_LINE}}
        (snap,) = render([START, {"frame": frame([asked])}, {"snapshot": True}])
        (lead,) = [n for n in nodes(snap["inbox"]) if has_class(n, "lead")]
        (line,) = [n for n in nodes(lead) if has_class(n, "action-line")]
        (command,) = [n for n in nodes(lead) if has_class(n, "action-command")]
        self.assertEqual(line["tag"], "p")
        self.assertEqual(full(line), ACTION_LINE)
        self.assertEqual(command["tag"], "pre")
        self.assertEqual(full(command), ACTION_COMMAND)
        kids = lead["children"]
        self.assertLess(kids.index(line), kids.index(command))

    def test_the_command_is_drawn_in_logical_order_whatever_letters_it_holds(self) -> None:
        # Right-to-left letters are legitimate text, so the card cannot refuse them; without a bidi
        # override the browser would reorder and mirror the characters between two of them, and the
        # owner would read other than the bytes that run (e.g. "echo hi \u05d0#" then ">\u05d0 rm").
        (rule,) = re.findall(r"^\.action-command \{([^}]*)\}", PAGE.read_text(encoding="utf-8"), re.M)
        declarations = {key.strip(): value.strip()
                        for key, value in (part.split(":", 1) for part in rule.split(";") if part.strip())}
        self.assertEqual(declarations["direction"], "ltr")
        self.assertEqual(declarations["unicode-bidi"], "bidi-override")

    def test_an_inbox_row_command_is_covered_by_the_same_unscoped_override(self) -> None:
        # The override must not hang off `.card`: a second open question renders as a `li.row`, and
        # the owner approves from that row too.
        hebrew = "echo hi \u05d0# ;>\u05d0 rm -rf ~"
        def action_question(index: int, command: str) -> dict:
            return {**question(index, f"May the manager run Apply {index}?", ["Run it once", "Do not run it"],
                               "Run it once"),
                    "owner_only": True, "consequential": True,
                    "action": {"command": command, "approve_index": 0, "line": ACTION_LINE}}
        (snap,) = render([START, {"frame": frame([action_question(0, ACTION_COMMAND),
                                                  action_question(1, hebrew)])}, {"snapshot": True}])
        (row,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "li" and has_class(n, "row")]
        (command,) = [n for n in nodes(row) if has_class(n, "action-command")]
        self.assertEqual(full(command), hebrew)
        css = PAGE.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^[^\n{]*action-command[^\n{]*\{", css, re.M), [".action-command {"])

    def test_a_question_with_no_action_shows_no_action_nodes(self) -> None:
        (snap,) = render([START, {"frame": frame([Q0])}, {"snapshot": True}])
        found = [n for n in nodes(snap["inbox"])
                 if has_class(n, "action-line") or has_class(n, "action-command")]
        self.assertEqual(found, [])
