"""A long command's permission card shows its summary and folds the full text (ADR-console-104)."""

import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_page import PERMISSION_ITEM, START, frame, full, nodes, of_class, permission_cards, render

TIER = "fast"  # the page harness under node and the standard library

LONG_COMMAND = "python3 - <<'PY'\n" + "print(1)\n" * 40 + "PY"
LONG_ITEM = {
    **PERMISSION_ITEM, "command": LONG_COMMAND,
    "summary": {
        "read": True, "runs": ["python3", "cp"], "writes": ["notes/plan.md", "/tmp/out.txt"],
        "outside": ["/tmp/out.txt"],
        "scripts": [{"program": "python3", "lines": 40, "paths": ["tests/test_x.py"]}]}}
UNREAD = "The console could not read what this command does: read it in full below before you answer."


def card_of(*steps: dict) -> dict:
    (snap,) = render([START, *steps, {"snapshot": True}])
    (card,) = permission_cards(snap)
    return card


def shape(card: dict) -> list:
    return [(c["tag"], c["cls"].split()[0] if c["cls"] else "") for c in card["children"]]


def summary_of(card: dict) -> dict:
    (box,) = of_class(card, "div", "cmd-summary")
    return box


def lines_of(card: dict) -> list:
    return [(n["cls"].split()[0], full(n)) for n in summary_of(card)["children"]]


def summarised(**summary: object) -> dict:
    return {**LONG_ITEM, "summary": {"read": True, "runs": [], "writes": [], "outside": [], "scripts": [], **summary}}


class PageLongPermissionCardTest(unittest.TestCase):
    def test_a_long_commands_card_opens_with_its_summary_and_folds_the_full_text(self) -> None:
        card = card_of({"frame": frame([LONG_ITEM])})
        self.assertEqual(shape(card), [
            ("p", "q"), ("p", "words"), ("div", "cmd-summary"), ("details", "cmd-fold"), ("p", "meta"), ("div", "act")])
        self.assertEqual(lines_of(card), [
            ("summary-runs", "Runs python3, cp"),
            ("summary-writes", "Writes or deletes notes/plan.md, /tmp/out.txt"),
            ("summary-script", "Runs a python3 script of 40 lines the console does not read; it names tests/test_x.py"),
            ("summary-outside", "Outside its own copy of the project: /tmp/out.txt")])
        (fold,) = of_class(card, "details", "cmd-fold")
        self.assertFalse(fold["open"])
        (pre,) = of_class(card, "pre", "cmd")
        self.assertIn(pre, nodes(fold))
        self.assertEqual(full(pre), LONG_COMMAND)
        (label,) = [c for c in fold["children"] if c["tag"] == "summary"]
        self.assertEqual(full(label), f"Show the full command ({len(LONG_COMMAND)} characters)")
        self.assertEqual(fold["children"][0], label)

    def test_an_unread_summary_says_so_and_still_folds_the_text(self) -> None:
        card = card_of({"frame": frame([{**LONG_ITEM, "summary": {"read": False}}])})
        self.assertEqual(lines_of(card), [("summary-unread", UNREAD)])
        (fold,) = of_class(card, "details", "cmd-fold")
        self.assertFalse(fold["open"])
        self.assertEqual(full(of_class(fold, "pre", "cmd")[0]), LONG_COMMAND)

    def test_a_short_command_with_a_null_summary_keeps_todays_card(self) -> None:
        card = card_of({"frame": frame([{**PERMISSION_ITEM, "summary": None}])})
        self.assertEqual(shape(card), [("p", "q"), ("p", "words"), ("pre", "cmd"), ("p", "meta"), ("div", "act")])
        self.assertEqual([n for n in nodes(card) if n["tag"] == "details"], [])

    def test_a_summary_list_shows_eight_and_counts_the_rest(self) -> None:
        writes = [f"w{i}.txt" for i in range(10)]
        card = card_of({"frame": frame([summarised(
            writes=writes, scripts=[{"program": "sh", "lines": 1, "paths": []}])])})
        self.assertEqual(lines_of(card)[0], (
            "summary-writes", "Writes or deletes " + ", ".join(writes[:8]) + ", and 2 more"))
        self.assertEqual(of_class(card, "p", "summary-runs"), [])
        self.assertEqual(lines_of(card)[1], (
            "summary-script", "Runs a sh script of 1 line the console does not read"))

    def test_an_unrecognised_writer_says_no_write_it_recognises(self) -> None:
        card = card_of({"frame": frame([summarised(runs=["curl"], outside=["/tmp/x.bin"])])})
        self.assertEqual([t for _, t in lines_of(card)], [
            "Runs curl", "No write the console recognises", "Outside its own copy of the project: /tmp/x.bin"])
        every = " ".join(full(n) for n in nodes(card))
        self.assertNotIn("no file", every)
        self.assertNotIn("Writes no", every)

    def test_the_full_command_fold_stays_open_through_a_frame(self) -> None:
        card = card_of({"frame": frame([LONG_ITEM])}, {"open": "cmd:permission/7"}, {"frame": frame([LONG_ITEM])})
        (fold,) = of_class(card, "details", "cmd-fold")
        self.assertTrue(fold["open"])

    def test_summary_text_is_never_markup(self) -> None:
        card = card_of({"frame": frame([summarised(writes=["<b>x</b>"], outside=["<i>y</i>"])])})
        self.assertEqual([n for n in nodes(card) if n["tag"] in ("b", "i")], [])
        self.assertIn(("summary-writes", "Writes or deletes <b>x</b>"), lines_of(card))


if __name__ == "__main__":
    unittest.main()
