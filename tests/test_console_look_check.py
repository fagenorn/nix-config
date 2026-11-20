"""The verify check that an approved look raises no owner-review card after activation (#1186).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import look_check
from agent_tools.delivery import look_marker
from agent_tools.system.forge_api import ForgeError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from tests.test_verify_checks import committed_mode

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-look-answered"
SLUG = "octo/widgets"
SINCE = "0" * 39 + "1"
HEAD = "1a2b3c4" + "d" * 33
OTHER_HEAD = "9f8e7d6" + "c" * 33
MARKED = "## Acceptance criteria\n\n- [ ] [human] before merge: the page — measured: the owner\n"
MARKED_AND_HUMAN = ("## Acceptance criteria\n\n- [ ] [human] before merge: the page — measured: the owner\n"
                    "- [ ] [human] the copy reads well\n")
UNMARKED = "## Acceptance criteria\n\n- [ ] [auto] the page works\n"
ACTIVATED = datetime(2026, 11, 16, 10, 30, tzinfo=timezone.utc)
PAGES = f"repos/{SLUG}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page="
COMMIT = f"repos/{SLUG}/commits/{SINCE}"
HELD_EVENTS = [{"event": "labeled", "label": {"name": "needs-verification"},
                "created_at": "2026-11-16T11:30:00Z"}]


def pull(number, issue, merged="2026-11-16T11:00:00Z", updated="2026-11-16T11:05:00Z",
         head=HEAD, body=None):
    return {"number": number, "merged_at": merged, "updated_at": updated,
            "body": f"Work.\n\nRefs #{issue}\n" if body is None else body,
            "head": {"sha": head}}


def issue_fake(number, state="open", body=MARKED, held=True):
    return {"number": number, "state": state, "body": body,
            "labels": [{"name": "needs-verification"}] if held else []}


def comment(cid, number, pr, head=HEAD, answer="approved", association="OWNER"):
    return {"id": cid, "author_association": association, "updated_at": "2026-11-16T11:10:00Z",
            "body": look_marker.approval_body(number, pr, head, answer, "m1")}


def view(open=(), read=("2026-11-16T13:00:00.000000+00:00", True, "2026-11-16T12:59:00.000000+00:00"),
         entries=None):
    project = {"type": "project", "root": "/w",
               "tracker_read": None if read is None else {"read_at": read[0], "ok": read[1],
                                                          "began_at": read[2]}}
    return {"entries": entries or [project], "inbox": {"open": list(open), "answered": []}}


def card(key="octo/widgets#7/ac1", repo="Octo/Widgets", issue=7, kind="owner-review", criterion=1):
    return {"key": key, "repo": repo, "issue": issue, "kind": kind, "criterion": criterion}


class World:
    def __init__(self, pages=None, issues=None, events=None, comments=None):
        self.pages = {1: [pull(50, 7)]} if pages is None else pages
        self.issues = {7: issue_fake(7)} if issues is None else issues
        self.events = {7: HELD_EVENTS} if events is None else events
        self.comments = {7: [comment(1, 7, 50)]} if comments is None else comments
        self.reads = []
        self.merged = "2026-11-16T10:00:00Z"

    def get(self, path):
        self.reads.append(path)
        if path == COMMIT:
            return {"commit": {"committer": {"date": self.merged}}}
        if path.startswith(PAGES):
            page = int(path[len(PAGES):])
            if page not in self.pages:
                raise AssertionError(f"unexpected pulls page {page}")
            return self.pages[page]
        for number, found in self.issues.items():
            if path == f"repos/{SLUG}/issues/{number}":
                return found
            if path.startswith(f"repos/{SLUG}/issues/{number}/events?per_page=100&page="):
                return self.events[number] if path.endswith("page=1") else []
        raise AssertionError(f"unexpected read {path}")

    def comments_of(self, repo, number):
        self.reads.append(f"comments {number}")
        return self.comments.get(number, [])

    def issue_reads(self):
        return {int(p.split("/issues/")[1].split("/")[0].split("?")[0])
                for p in self.reads if "/issues/" in p}


def never(url):
    raise AssertionError("the console state must not be read")


class LookCheckTest(unittest.TestCase):
    def run_check(self, world=None, argv=None, *, state=None, activated=ACTIVATED,
                  slug_of=None, fixed=None):
        world = world or World()
        argv = argv if argv is not None else ["--repo", SLUG, "--since", SINCE]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = look_check.main(
                argv, get=world.get, comments=world.comments_of,
                state=state or (lambda url: view()), activated_at=lambda: activated,
                fixed_activation=fixed or (lambda since, current: current),
                slug_of={"/w": SLUG}.get if slug_of is None else slug_of)
        lines = out.getvalue().splitlines()
        self.assertEqual(1, len(lines), out.getvalue())
        return code, json.loads(lines[0])

    def test_the_first_marked_landing_held_and_read_with_no_card_is_met(self):
        code, out = self.run_check()
        self.assertEqual((0, {"issue": 7, "pr": 50, "status": "met"}), (code, out))

    def test_an_owner_review_card_for_that_issue_is_not_met(self):
        code, out = self.run_check(state=lambda url: view(open=[card()]))
        self.assertEqual(1, code)
        self.assertEqual({"issue": 7, "keys": ["octo/widgets#7/ac1"], "pr": 50,
                          "status": "not_met"}, out)

    def test_cards_of_other_issues_or_kinds_do_not_count(self):
        code, out = self.run_check(state=lambda url: view(open=[
            card("octo/widgets#8/ac1", issue=8), card("octo/widgets#7/ask", kind="verify-ask")]))
        self.assertEqual((0, "met"), (code, out["status"]))

    def test_no_marked_landing_since_the_activation_is_not_yet(self):
        cases = {
            "merged before the commit": World(pages={1: [pull(50, 7, merged="2026-11-16T09:00:00Z",
                                                              updated="2026-11-16T09:30:00Z")]}),
            "unmarked issue": World(issues={7: issue_fake(7, body=UNMARKED)}),
            "approval of another head": World(comments={7: [comment(1, 7, 50, head=OTHER_HEAD)]}),
            "changes answer": World(comments={7: [comment(1, 7, 50, answer="changes")]}),
            "untrusted approval": World(comments={7: [comment(1, 7, 50, association="NONE")]}),
        }
        for name, world in cases.items():
            with self.subTest(name):
                code, out = self.run_check(world, state=never)
                self.assertEqual((75, {"status": "waiting"}), (code, out))

    def test_a_landing_before_activation_is_passed_over_for_the_next_one(self):
        def world():
            return World(
                pages={1: [pull(50, 7), pull(49, 6, merged="2026-11-16T10:15:00Z",
                                             updated="2026-11-16T10:16:00Z")]},
                issues={6: issue_fake(6), 7: issue_fake(7)},
                events={6: HELD_EVENTS, 7: HELD_EVENTS},
                comments={6: [comment(1, 6, 49)], 7: [comment(1, 7, 50)]})
        first = world()
        code, out = self.run_check(first)
        self.assertEqual((0, 7, 50), (code, out["issue"], out["pr"]))
        self.assertNotIn(6, first.issue_reads())
        early = datetime(2026, 11, 16, 10, 10, tzinfo=timezone.utc)
        code, out = self.run_check(world(), activated=early)
        self.assertEqual((0, 6, 49), (code, out["issue"], out["pr"]))

    def test_the_activation_time_must_be_known(self):
        world = World()
        code, out = self.run_check(world, activated=None, state=never)
        self.assertEqual((75, {"status": "activation_unknown"}), (code, out))
        self.assertFalse([p for p in world.reads if p.startswith(PAGES)])

    def test_the_first_landing_by_merge_time_is_judged(self):
        world = World(
            pages={1: [pull(51, 8, merged="2026-11-16T12:00:00Z", updated="2026-11-16T12:01:00Z"),
                       pull(50, 7)]},
            issues={7: issue_fake(7), 8: issue_fake(8)},
            events={7: HELD_EVENTS, 8: HELD_EVENTS},
            comments={7: [comment(1, 7, 50)], 8: [comment(1, 8, 51)]})
        code, out = self.run_check(world)
        self.assertEqual((0, 7, 50), (code, out["issue"], out["pr"]))
        self.assertNotIn(8, world.issue_reads())

    def test_the_earliest_landing_on_a_later_page_is_found(self):
        filler = [pull(1000 + i, 99, merged=None, updated="2026-11-16T12:30:00Z")
                  for i in range(99)]
        later = pull(51, 8, merged="2026-11-16T12:00:00Z", updated="2026-11-16T12:01:00Z")
        world = World(
            pages={1: filler + [later], 2: [pull(50, 7)]},
            issues={7: issue_fake(7), 8: issue_fake(8)},
            events={7: HELD_EVENTS, 8: HELD_EVENTS},
            comments={7: [comment(1, 7, 50)], 8: [comment(1, 8, 51)]})
        code, out = self.run_check(world)
        self.assertEqual((0, 7, 50), (code, out["issue"], out["pr"]))

    def test_paging_stops_at_the_activation_boundary(self):
        page = [pull(1000 + i, 99, merged=None, updated="2026-11-16T10:20:00Z")
                for i in range(100)]
        code, out = self.run_check(World(pages={1: page}), state=never)
        self.assertEqual((75, {"status": "waiting"}), (code, out))

    def test_a_closed_landing_is_passed_over(self):
        world = World(
            pages={1: [pull(50, 7), pull(52, 9, merged="2026-11-16T12:00:00Z",
                                         updated="2026-11-16T12:01:00Z")]},
            issues={7: issue_fake(7, state="closed", held=False), 9: issue_fake(9)},
            events={9: HELD_EVENTS},
            comments={7: [comment(1, 7, 50)], 9: [comment(1, 9, 52)]})
        code, out = self.run_check(world)
        self.assertEqual((0, 9, 52), (code, out["issue"], out["pr"]))

    def test_a_landing_not_yet_held_is_not_yet(self):
        world = World(issues={7: issue_fake(7, held=False)})
        code, out = self.run_check(world, state=never)
        self.assertEqual((75, {"issue": 7, "pr": 50, "status": "not_held"}), (code, out))

    def test_an_unanswering_console_is_not_yet(self):
        code, out = self.run_check(state=lambda url: None)
        self.assertEqual((75, {"issue": 7, "pr": 50, "status": "not_running"}), (code, out))

    def test_no_fresh_read_of_the_repository_is_not_yet(self):
        cases = (
            ("not_registered", view(), lambda root: None),
            ("not_read", view(read=None), None),
            ("stale", view(read=("2026-11-16T13:00:00.000000+00:00", False,
                                 "2026-11-16T12:59:00.000000+00:00")), None),
            ("not_read", view(read=("2026-11-16T13:00:00.000000+00:00", True,
                                    "2026-11-16T11:20:00.000000+00:00")), None),
            ("not_read", view(read=("2026-11-16T13:00:00.000000+00:00", True, "later")), None),
            ("not_read", view(read=("2026-11-16T13:00:00.000000+00:00", True, None)), None),
        )
        for status, answer, slug_of in cases:
            with self.subTest(status, view=answer["entries"][0].get("tracker_read")):
                code, out = self.run_check(state=lambda url, answer=answer: answer,
                                           slug_of=slug_of)
                self.assertEqual((75, {"issue": 7, "pr": 50, "status": status}), (code, out))

    def test_a_read_that_began_before_the_hold_and_ended_after_it_is_not_fresh(self):
        straddling = view(read=("2026-11-16T11:45:00.000000+00:00", True,
                                "2026-11-16T11:29:00.000000+00:00"))
        code, out = self.run_check(state=lambda url: straddling)
        self.assertEqual((75, {"issue": 7, "pr": 50, "status": "not_read"}), (code, out))
        started_at_the_hold = view(read=("2026-11-16T11:45:00.000000+00:00", True,
                                          "2026-11-16T11:30:00.000000+00:00"))
        code, out = self.run_check(state=lambda url: started_at_the_hold)
        self.assertEqual((0, "met"), (code, out["status"]))

    def test_only_cards_of_look_marker_criteria_count(self):
        world = lambda: World(issues={7: issue_fake(7, body=MARKED_AND_HUMAN)})
        ordinary = card("octo/widgets#7/ac2", criterion=2)
        code, out = self.run_check(world(), state=lambda url: view(open=[ordinary]))
        self.assertEqual((0, "met"), (code, out["status"]))
        code, out = self.run_check(world(), state=lambda url: view(open=[ordinary, card()]))
        self.assertEqual((1, "not_met", ["octo/widgets#7/ac1"]), (code, out["status"], out["keys"]))

    def test_a_marker_line_tick_leaves_open_is_no_look_criterion(self):
        """#1356: the console waits only for look markers `tick` ticks, the lines the marker reader recognizes."""
        marker = "- [ ] [human] before merge: the page \u2014 measured: the owner\n"
        body = "## Acceptance criteria\n\n" + marker + "- ```\n  sample\n  ```\n" + marker
        self.assertEqual(look_check.look_criteria(body), frozenset({1}))

    def test_a_later_activation_does_not_move_the_boundary(self):
        later = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)
        code, out = self.run_check(activated=later, state=never)
        self.assertEqual((75, {"status": "waiting"}), (code, out))
        code, out = self.run_check(activated=later, fixed=lambda since, current: ACTIVATED)
        self.assertEqual((0, 7, 50), (code, out["issue"], out["pr"]))

    def test_the_first_activation_is_recorded_once_and_read_back(self):
        later = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}):
            self.assertEqual(ACTIVATED, look_check.default_fixed_activation(SINCE, ACTIVATED))
            self.assertEqual(ACTIVATED, look_check.default_fixed_activation(SINCE, later))
            self.assertEqual(later, look_check.default_fixed_activation(OTHER_HEAD, later))
        with mock.patch.dict(os.environ, {"HOME": ""}):
            self.assertEqual(later, look_check.default_fixed_activation(SINCE, later))

    def test_a_quiet_project_inside_a_group_is_found(self):
        project = view()["entries"][0]
        group = [{"type": "quiet_group", "projects": [project]}]
        code, out = self.run_check(state=lambda url: view(entries=group))
        self.assertEqual((0, "met"), (code, out["status"]))

    def test_usage_and_forge_errors_exit_2(self):
        for argv in (["--repo", SLUG, "--since", "abc"], ["--since", SINCE],
                     ["--repo", SLUG, "--since", SINCE, "--url", "https://example.com"]):
            with self.subTest(argv):
                world = World()
                code, out = self.run_check(world, argv)
                self.assertEqual((2, "error"), (code, out["status"]))
                self.assertEqual([], world.reads)
        world = World()
        world.get = lambda path: (_ for _ in ()).throw(ForgeError("gh_failed", "x"))
        code, out = self.run_check(world)
        self.assertEqual((2, "error"), (code, out["status"]))

    def test_the_wrapper_runs_the_module_and_is_executable(self):
        self.assertEqual("100755", committed_mode(ROOT / WRAPPER))
        done = subprocess.run([str(ROOT / WRAPPER)], cwd=ROOT, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()
