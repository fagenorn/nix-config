"""deliver-standard.js landing scenarios against stub agents: the green-first lease, the queue it leaves and the look carry.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import re
import unittest

from . import test_deliver_standard_program as base
from .test_deliver_standard_program import (
    ARGS,
    AWAIT_REASON,
    D,
    F,
    FIX,
    MARKED,
    PROGRAM,
    RED,
    SHA,
    green_read,
    labels,
    prompt,
    red_read,
    run,
    run_out,
    schema_of,
)

TIER = "integration"


def beat(hold):
    """The lease beat a held step starts first: `hold --detach`, which returns at once and beats in a background process
    for the whole step, the stop on anything but beating, and the one-shot hold before each push and merge. Written out
    here, not read from the program."""
    return (f"First start the lease beat: run alone and exactly: {hold} --detach\n"
            "It returns at once and leaves a background process that beats the land lease every 60 seconds for the whole step and stops by itself when your session ends. "
            "Go on only when it prints beating. "
            "When it prints anything else (not_held, unleased, an error or nothing) the lease is lost or not beating: stop at once, run nothing more and answer as you do when the step cannot be done "
            "(a failed or blocked answer, never a success) with lease lost in its notes or detail.\n"
            f"The background beat tells you nothing later, so immediately before every git push and every merge this step makes, run alone and exactly: {hold}\n"
            "When it prints not_held, do not push or merge: stop and answer as above.\n")


class GreenFirstTest(unittest.TestCase):
    """The land lease is asked for only once the head is read green, and the checks wait under it beats the lease."""

    D = "d" * 40
    BEHIND = {"land-take": {"behind": True}, "sync-1": {"merge_commit": "d" * 40}}
    HOLD = f"forge-claim land hold --repo owner/repo --branch dev --sha {SHA}"

    def synced(self, **replies):
        """The default run whose take answers behind: one clean sync to D, its checks (checks-2) read at D."""
        return run_out(replies={"checks-2": green_read(self.D), **replies}, patch=self.BEHIND)

    def test_the_lease_is_asked_for_only_after_the_head_is_green(self):
        out = run_out(replies={"land-take": {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": False}},
                      patch={"pr": {"green": green_read(SHA)}})
        calls = out["calls"]
        names = labels(calls)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("pr"):][:3], ["pr", "land-take", "merge"])
        self.assertNotIn("forge-claim land", prompt(calls, "pr"))
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait --lease\n", prompt(calls, "land-take"))
        acquire = [line for line in prompt(calls, "merge").splitlines() if "forge-claim land acquire" in line]
        self.assertEqual(len(acquire), 1)
        self.assertTrue(acquire[0].endswith(f"--sha {SHA} --lease"), acquire)

    def test_a_pending_green_read_polls_without_the_lock_and_stops_after_three(self):
        pending = green_read(state="pending", pending=["e2e"])
        out = run_out(replies={"green-checks-1": pending, "green-checks-2": pending}, patch={"pr": {"green": pending}})
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "checks-pending")
        self.assertEqual(names[names.index("pr"):], ["pr", "green-checks-1", "green-checks-2"])
        self.assertFalse([c["label"] for c in out["calls"] if "forge-claim land" in c["prompt"]])
        self.assertNotIn("land-unlock", names)

    def test_a_red_head_is_fixed_before_the_lease_is_asked_for(self):
        out = run_out(replies={"green-checks-1": green_read(FIX)},
                      patch={"pr": {"green": red_read(RED)}, "fix-ci": {"start_head": SHA, "commit": FIX}})
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertLess(names.index("fix-ci"), names.index("land-take"))
        self.assertIn("The landing lock of the branch dev is not held and was not asked for yet: run no forge-claim command.",
                      prompt(out["calls"], "fix-ci"))
        before = out["calls"][:names.index("land-take")]
        self.assertFalse([c["label"] for c in before if "forge-claim land" in c["prompt"]])

    def test_a_behind_green_head_syncs_once_and_reruns_its_checks_once(self):
        out = self.synced()
        calls = out["calls"]
        names = labels(calls)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):names.index("merge") + 1], ["land-take", "sync-1", "land-push-2", "checks-2", "merge"])
        self.assertEqual([n for n in names if n.startswith("sync-")], ["sync-1"])
        self.assertEqual([n for n in names if n.startswith("checks-")], ["checks-2"])
        self.assertIn(beat(self.HOLD) + "The branch is behind dev.", prompt(calls, "sync-1"))
        self.assertIn(beat(self.HOLD), prompt(calls, "land-push-2"))
        self.assertIn(beat(self.HOLD.replace(SHA, self.D)), prompt(calls, "merge"))

    def test_a_held_step_beats_the_lease_in_the_background_for_its_whole_length(self):
        """The beat is a detached `hold` for the step's whole length (it rewrites the beat every 60 s itself) that returns
        at once, so the step's own long command runs beside it in the foreground; a beat sent once would lapse at 180 s."""
        calls = self.synced()["calls"]
        for label in ("sync-1", "land-push-2", "merge"):
            with self.subTest(label=label):
                text = prompt(calls, label)
                # the detached beat, and the one-shot hold before each push and merge
                self.assertEqual(text.count("forge-claim land hold"), 2)
                self.assertEqual(text.count("--detach\n"), 1)
                self.assertNotIn("run_in_background set to true", text)
                self.assertIn("beats the land lease every 60 seconds for the whole step", text)
                self.assertIn("Go on only when it prints beating.", text)
                self.assertIn("the lease is lost or not beating: stop at once", text)
        # A step that holds nothing starts no beat.
        for label in ("pr", "land-take"):
            self.assertNotIn("forge-claim land hold", prompt(calls, label))

    def test_a_sync_step_that_reports_the_lease_lost_is_followed_by_no_push_and_no_merge(self):
        """The loss is injected into the held sync step: nothing is pushed or merged under that lease after it."""
        lost = {"status": "blocked", "conflicted": False, "notes": "lease lost"}
        out = run_out(replies={"sync-1": lost}, patch={"land-take": {"behind": True}})
        names = labels(out["calls"])
        self.assertNotEqual(out["result"]["stage"], "done")
        self.assertEqual(out["result"]["stage"], "sync")
        after = out["calls"][names.index("sync-1") + 1:]
        # only the release of the lease follows: no push step, no checks step, no merge step
        self.assertEqual([c["label"] for c in after], ["land-unlock"])

    def test_a_merge_step_that_reports_the_lease_lost_merges_nothing_more(self):
        lost = {"merged": False, "notes": "lease lost"}
        out = run_out(replies={"merge": lost})
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "merge")
        after = out["calls"][names.index("merge") + 1:]
        self.assertEqual([c["label"] for c in after], ["land-unlock"])
        self.assertEqual(names.count("merge"), 1)

    def test_a_clean_sync_whose_head_is_a_follow_up_commit_beats_through_its_review_and_fix(self):
        """The review of a clean merge with commits on top runs while the lease is still held."""
        head = "e" * 40
        finding = {"verdict": "findings", "descends": True, "findings": [{"severity": "important", "summary": "dropped a change", "failing_input": "x"}]}
        fixed = {"start_head": head, "commit": "f" * 40, "notes": "ok", "tests": ["t"]}
        out = run_out(replies={"checks-2": green_read("f" * 40), "sync-review-1": finding},
                      patch={**self.BEHIND, "sync-1": {"merge_commit": self.D, "head": head}, "fix-sync-1": fixed})
        calls = out["calls"]
        names = labels(calls)
        self.assertNotIn("land-unlock", names[:names.index("fix-sync-1")])
        for label in ("sync-review-1", "fix-sync-1", "fix-sync-review-1"):
            with self.subTest(label=label):
                self.assertIn(beat(self.HOLD), prompt(calls, label))

    def test_every_merge_follows_a_passed_poll_of_an_up_to_date_head(self):
        # (label, head) of each read that passed with the base not past the head.
        runs = (
            (run_out(replies={"land-take": {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": False}}), [("pr", SHA)], "land-take", False),
            (self.synced(), [("checks-2", self.D)], "land-take", True),
        )
        for out, reads, take, behind in runs:
            with self.subTest(reads=reads):
                names = labels(out["calls"])
                for position, call in enumerate(out["calls"]):
                    if call["label"] != "merge":
                        continue
                    head = re.search(r"--match-head-commit ([0-9a-f]{40})", call["prompt"]).group(1)
                    earlier = [(label, h) for label, h in reads if h == head and names.index(label) < position]
                    self.assertTrue(earlier, f"merge at {head} follows no passed read at it: {names}")
                    # The green read of the pr call counts only when the take after it found the head up to date.
                    if earlier[-1][0] == "pr":
                        self.assertNotIn("sync-1", names[names.index("pr"):position])

    def test_every_stop_after_the_lease_releases_it_once(self):
        pending = green_read(state="pending", pending=["e2e"])
        cases = {
            "checks-pending": ({"replies": {"green-checks-1": pending, "green-checks-2": pending}, "patch": {"pr": {"green": pending}}}, 0, None),
            "sync": ({"patch": {"land-take": {"behind": True}, "sync-1": {"status": "blocked", "notes": "dirty tree"}}}, 1, SHA),
            "merge": ({"replies": {"merge": None}}, 1, SHA),
        }
        for stage, (scenario, unlocks, sha) in cases.items():
            with self.subTest(stage=stage):
                out = run_out(**scenario)
                names = labels(out["calls"])
                self.assertEqual(out["result"]["stage"], stage)
                self.assertEqual(names.count("land-unlock"), unlocks)
                if sha:
                    self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {sha}\n", prompt(out["calls"], "land-unlock"))
                    self.assertLess(names.index("land-take"), names.index("land-unlock"))
                else:
                    self.assertNotIn("land-take", names)

    def test_the_checks_wait_under_the_lease_beats_instead_of_watching(self):
        out = self.synced()
        checks = prompt(out["calls"], "checks-2")
        self.assertIn(f"forge-claim land hold --repo owner/repo --branch dev --sha {self.D} --seconds 120", checks)
        self.assertNotIn("gh pr checks 42 --repo owner/repo --watch", checks)
        self.assertIn("at most 25 times", checks)
        self.assertIn("When hold prints not_held the lease is lost: stop waiting at once and return state lost", checks)
        self.assertIn("lost", schema_of(out["calls"], "checks-2")["properties"]["state"]["enum"])


class LeaveQueueTest(unittest.TestCase):
    """A red check at the up-to-date head leaves the queue; a second red stops naming it."""

    D = "d" * 40
    TAKES = [{"behind": True}, {}]
    BEHIND = {"sync-1": {"merge_commit": "d" * 40}, "fix-ci": {"start_head": "d" * 40, "commit": FIX}}
    LEFT = "left the land queue: ci failed at the up-to-date head "

    @staticmethod
    def red(head):
        return {"state": "failed", "head": head, "failing": ["ci"], "details": "FAIL test_cache"}

    def test_a_red_check_at_the_up_to_date_head_releases_the_lease_before_the_fix_and_takes_it_once_the_fix_is_green(self):
        out = run_out(replies={"land-take": self.TAKES, "checks-2": self.red(self.D)}, patch=self.BEHIND)
        calls = out["calls"]
        names = labels(calls)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertLess(names.index("land-unlock"), names.index("fix-ci"))
        self.assertIn(f"forge-claim land release --repo owner/repo --branch dev --sha {self.D}\n", prompt(calls, "land-unlock"))
        self.assertIn("The land lock was released before this fix; run no forge-claim command.", prompt(calls, "fix-ci"))
        self.assertNotIn("lock_released", schema_of(calls, "fix-ci")["properties"])
        self.assertIn(self.LEFT + self.D, out["logs"])
        # The fix commit is pushed and read green with no lock command; only then is the lease asked for at it.
        self.assertEqual(names[names.index("fix-ci-review"):names.index("merge")],
                         ["fix-ci-review", "land-push-3", "green-checks-1", "land-take"])
        self.assertNotIn("land acquire --repo", prompt(calls, "green-checks-1"))
        self.assertIn(f"--sha {FIX} --wait --lease\n", prompt(calls, "land-take"))
        self.assertNotIn("checks-3", names)
        self.assertEqual(names.count("land-unlock"), 1)

    def test_a_second_red_at_the_up_to_date_head_stops_naming_it(self):
        second = dict(self.red(FIX), behind=False, required=["ci"])
        out = run_out(replies={"land-take": self.TAKES, "checks-2": self.red(self.D), "green-checks-1": second}, patch=self.BEHIND)
        names = labels(out["calls"])
        result = out["result"]
        self.assertEqual(result["stage"], "checks")
        self.assertEqual(result["details"], self.LEFT + FIX)
        self.assertEqual(names.count("land-unlock"), 1)
        self.assertEqual(names[-1], "green-checks-1")


class LostLeaseTest(unittest.TestCase):
    """A lease another landing took over is waited for again at the back, within the wait budget."""

    D = "d" * 40
    BEHIND = {"land-take": {"behind": True}, "sync-1": {"merge_commit": "d" * 40}}
    E = "e" * 40
    MERGED = {"merged": True, "merge_commit": SHA, "notes": "merged", "lock": {"verdict": "already_held", "lock_sha": SHA}}

    def test_a_holder_that_lost_its_lease_waits_again_at_the_back(self):
        lost = {"lock": {"verdict": "held_by", "lock_sha": self.E, "pr": 77}, "merged": False}
        out = run_out(replies={"merge": [lost, self.MERGED]})
        calls = out["calls"]
        names = labels(calls)
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):], ["land-take", "merge", "land-relock-1", "merge", "hold", "close-out"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {SHA} --wait --lease\n", prompt(calls, "land-relock-1"))
        self.assertNotIn("land-unlock", names)
        self.assertTrue([line for line in out["logs"] if "land lease" in line and "lost" in line], out["logs"])

    def test_a_take_that_leaves_behind_out_polls_the_checks_before_the_merge(self):
        """A held lease whose reply does not say behind false (the harness fills a missing key, so null stands for it) is not read as up to date: the checks are polled first."""
        held = {"renew": {"verdict": "renewed"}, "lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": None}
        out = run_out(replies={"land-take": held})
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):], ["land-take", "checks-1", "merge", "hold", "close-out"])

    def test_a_relock_after_a_lost_merge_recheck_that_leaves_behind_out_polls_the_checks_first(self):
        lost = {"lock": {"verdict": "held_by", "lock_sha": self.E, "pr": 77}, "merged": False}
        held = {"renew": {"verdict": "renewed"}, "lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": None}
        out = run_out(replies={"merge": [lost, self.MERGED], "land-relock-1": held})
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):], ["land-take", "merge", "land-relock-1", "checks-2", "merge", "hold", "close-out"])

    def test_a_lease_lost_during_the_checks_wait_waits_again(self):
        lost = {"state": "lost", "lock_sha": self.E}
        out = run_out(replies={"checks-2": lost, "checks-3": green_read(self.D)}, patch=self.BEHIND)
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):], ["land-take", "sync-1", "land-push-2", "checks-2", "land-relock-1", "checks-3",
                                                             "merge", "hold", "close-out"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {self.D} --wait --lease\n", prompt(out["calls"], "land-relock-1"))

    def test_a_move_refused_while_the_lease_is_held_waits_again(self):
        refused = {"lock": {"verdict": "lost_to", "lock_sha": self.E, "pr": 77}}
        out = run_out(replies={"checks-2": refused, "checks-3": green_read(self.D)}, patch=self.BEHIND)
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "done")
        self.assertEqual(names[names.index("land-take"):], ["land-take", "sync-1", "land-push-2", "checks-2", "land-relock-1", "checks-3",
                                                             "merge", "hold", "close-out"])
        self.assertNotIn("land-unlock", names)

    def test_a_lost_lease_past_the_wait_budget_stops_land_contended(self):
        retries = int(re.search(r"^const LAND_WAIT_RETRIES = (\d+)$", PROGRAM.read_text(encoding="utf-8"), re.M).group(1))
        waiting = {"lock": {"verdict": "land-contended", "lock_sha": self.E, "waited_s": 3000, "position": 3, "ahead": [7, 8]}}
        out = run_out(replies={"checks-2": {"state": "lost", "lock_sha": self.E}, **{f"land-relock-{k}": waiting for k in range(1, 12)}},
                      patch=self.BEHIND)
        names = labels(out["calls"])
        self.assertEqual(out["result"]["stage"], "land-contended")
        # Each wait ran out at place 3 behind two others and spent a retry: the first wait and then the retries.
        self.assertEqual(len([n for n in names if n.startswith("land-relock-")]), retries + 1)
        self.assertNotIn("merge", names)
        self.assertNotIn("land-unlock", names)


class LookCarryLandingTest(unittest.TestCase):
    """A landing resync that moves the head asks look-approval carry, after verifying the new head, before it asks the owner again."""

    PICS = [{"kind": "before", "path": "/r/pics/before.png"}, {"kind": "after", "path": "/r/pics/after.png"}]
    NEEDED = dict(base.LookResumeTest.MOVED, **{"look-status": {"verdict": "needed", "kept_from": None},
                                           "look-checks-1": {"state": "passed", "head": D, "behind": False, "required": ["ci"], "passed": ["ci"]}})
    # The verified carry leaves the land queue first (the harness default of the own-files rule is touched), so the
    # landing reads the head green, takes the lease again and reads the status again: needed, then the approval the carry recorded.
    AFTER_CARRY = [{"verdict": "needed", "kept_from": None}, {"verdict": "approved", "kept_from": SHA}]
    TAKES = [{"behind": True}, {}]
    CARRIED = {"verdict": "carried", "from": SHA, "reason": None, "rule": "pictures", "comment_id": 501}
    FILES_CARRIED = dict(CARRIED, rule="look-files")
    OK = [{"id": "build", "status": "pass", "summary": "ok"}]
    BARE = {"head": D, "clean": True, "merge_only": True, "results": OK}

    def approve(self, patch=None, replies=None, cont=None):
        if cont is None:
            first, _ = run(patch={"setup": {"look": MARKED}})
            cont = first["cont"]
        replies = dict({"land-take": self.TAKES}, **(replies or {}))
        if patch is None and "look-status" not in replies:
            replies["look-status"] = self.AFTER_CARRY
        return run(args=dict(ARGS, cont=cont, look={"answer": "approve", "head": SHA}), patch=self.NEEDED if patch is None else patch, replies=replies)

    def stops_unasked(self, result, calls, stage="look-carry"):
        got = labels(calls)
        self.assertEqual(result["stage"], stage)
        self.assertNotIn("merge", got)
        self.assertFalse([l for l in got if l.startswith("look-checks-")], got)
        self.assertIn("land-unlock", got)

    def test_a_head_that_only_merged_the_integration_branch_lands_on_a_carry_line(self):
        """The verified carry runs outside the land queue (D12): a land-unlock comes before its verification.

        The landing then reads the head green, takes the lease at the back, reads the recorded approval and merges.
        """
        result, calls = self.approve(replies={"look-carry": self.CARRIED})
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        order = ["look-status", "look-carry-own", "land-unlock", "look-carry-verify", "look-carry", "green-checks-1", "look-status", "merge"]
        self.assertEqual([l for l in got if l in order], order)
        self.assertNotIn("land acquire --repo", prompt(calls, "green-checks-1"))
        self.assertIn("land acquire --repo owner/repo --branch dev --sha " + D + " --wait --lease\n", prompt(calls, "land-take"))
        verify = prompt(calls, "look-carry-verify")
        self.assertIn("merge-base --is-ancestor " + SHA + " " + D, verify)
        self.assertIn("rev-list --no-merges " + SHA + ".." + D + " ^origin/dev", verify)
        self.assertIn("merge-tree --write-tree", verify)
        self.assertIn("Run the project's declared verification once on the worktree head", verify)
        self.assertIn("look-approval carry --repo owner/repo --issue 9 --pr 42 --from " + SHA + " --head " + D
                      + " --before /r/pics/before.png --after /r/pics/after.png", prompt(calls, "look-carry"))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertIn("look-approval tick --repo owner/repo --issue 9 --pr 42 --head " + D, prompt(calls, "close-out"))
        for call in calls:
            self.assertNotIn("look-approval post", call["prompt"])

    def test_a_head_with_no_pictures_carries_by_the_look_file_rule(self):
        """The carry leaves the land queue first (D12), then the landing retakes the lease and merges."""
        result, calls = self.approve(replies={"look-carry-verify": self.BARE, "look-carry": self.FILES_CARRIED})
        self.assertEqual(result["stage"], "done", labels(calls))
        carry = prompt(calls, "look-carry")
        self.assertIn("look-approval carry --repo owner/repo --issue 9 --pr 42 --from " + SHA + " --head " + D + "\n", carry)
        for flag in (" --before ", " --after ", " --picture "):
            self.assertNotIn(flag, carry)
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        for call in calls:
            self.assertNotIn("look-approval post", call["prompt"])

    def test_a_changed_look_file_diff_stops_for_a_new_look(self):
        needed = {"verdict": "needed", "from": SHA, "reason": "look-files-differ", "rule": "look-files", "comment_id": None}
        result, calls = self.approve(replies={"look-carry-verify": self.BARE, "look-carry": needed})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["reason"], "the approval of " + SHA + " does not carry to " + D + ": look-files-differ; " + AWAIT_REASON)
        self.assertLess(got.index("look-carry"), got.index("look-checks-1"))
        self.assertNotIn("merge", got)
        self.assertIn("land-unlock", got)

    def test_a_carried_reply_must_name_its_rule(self):
        cases = (("no rule", {}, {k: v for k, v in self.CARRIED.items() if k != "rule"}),
                 ("another rule", {}, dict(self.CARRIED, rule="other")),
                 ("pictures rule with no pictures", {"look-carry-verify": self.BARE}, dict(self.CARRIED, rule="pictures")))
        for name, extra, reply in cases:
            with self.subTest(case=name):
                result, calls = self.approve(replies=dict(extra, **{"look-carry": reply}))
                self.stops_unasked(result, calls)

    def test_a_changed_picture_stops_for_a_new_look(self):
        result, calls = self.approve()
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["reason"], "the approval of " + SHA + " does not carry to " + D + ": pictures-differ; " + AWAIT_REASON)
        self.assertEqual(result["pictures"], self.PICS)
        self.assertLess(got.index("look-carry"), got.index("look-checks-1"))
        self.assertNotIn("merge", got)
        self.assertIn("land-unlock", got)
        self.assertEqual(result["cont"]["look"], {"pr": 42, "head": D})

    def test_a_non_merge_commit_stops_for_a_new_look_at_the_new_head(self):
        theirs = [{"kind": "before", "path": "/r/pics/a-before.png"}, {"kind": "after", "path": "/r/pics/a-after.png"}]
        mine = [{"kind": "before", "path": "/r/pics/h-before.png"}, {"kind": "after", "path": "/r/pics/h-after.png"}]
        first, _ = run(patch={"setup": {"look": MARKED}, "verify": {"pictures": theirs}})
        reply = {"head": D, "clean": True, "merge_only": False, "results": self.OK, "pictures": mine}
        result, calls = self.approve(cont=first["cont"], replies={"look-carry-verify": reply})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        self.assertEqual(result["pictures"], mine)
        self.assertEqual(result["cont"]["verified"]["head"], D)
        self.assertEqual(result["cont"]["verified"]["pictures"], mine)
        self.assertTrue(result["reason"].endswith("it adds commits that are not clean merges of dev; " + AWAIT_REASON), result["reason"])
        self.assertNotIn("look-carry", got)
        self.assertIn("look-checks-1", got)

    def test_a_worktree_that_cannot_reach_the_new_head_asks_for_the_owners_look(self):
        stale = {"head": F, "clean": True, "merge_only": False, "results": []}
        result, calls = self.approve(replies={"look-carry-verify": stale})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], D)
        for label in ("look-carry", "merge"):
            self.assertNotIn(label, got)
        self.assertIn("look-checks-1", got)
        self.assertIn("land-unlock", got)

    def test_a_carry_whose_verification_fails_stops_without_asking(self):
        failed = {"head": D, "clean": True, "merge_only": True, "results": [{"id": "build", "status": "fail", "summary": "boom"}]}
        result, calls = self.approve(replies={"look-carry-verify": failed})
        self.stops_unasked(result, calls)
        self.assertNotIn("look-carry", labels(calls))

    def test_an_unusable_verification_reply_stops_without_asking(self):
        for name, reply in (("none", None), ("another head", {"head": F, "clean": True, "merge_only": True, "results": self.OK})):
            with self.subTest(reply=name):
                result, calls = self.approve(replies={"look-carry-verify": reply})
                self.stops_unasked(result, calls)
                self.assertNotIn("look-carry", labels(calls))

    def test_a_picture_path_with_a_space_reaches_the_command_as_one_quoted_argument(self):
        """The carry leaves the land queue first (D12), then the landing retakes the lease and merges."""
        spaced = {"head": D, "clean": True, "merge_only": True, "results": self.OK,
                  "pictures": [{"kind": "before", "path": "/r/my pics/b.png"}, {"kind": "after", "path": "/r/my pics/it's a.png"}]}
        result, calls = self.approve(replies={"look-carry-verify": spaced, "look-carry": self.CARRIED})
        self.assertEqual(result["stage"], "done")
        self.assertIn(" --head " + D + " --before '/r/my pics/b.png' --after '/r/my pics/it'\\''s a.png'\n", prompt(calls, "look-carry"))

    def test_a_picture_path_that_is_not_absolute_or_spans_lines_carries_nothing(self):
        for path in ("pics/a.png", "/r/pics/a\nb.png", "/"):
            with self.subTest(path=path):
                odd = {"head": D, "clean": True, "merge_only": True, "results": self.OK, "pictures": [{"kind": "after", "path": path}]}
                result, calls = self.approve(replies={"look-carry-verify": odd})
                self.assertEqual(result["stage"], "awaiting-look")
                self.assertNotIn("look-carry", labels(calls))

    def test_an_approval_recorded_between_the_status_and_the_carry_lands_the_head(self):
        """The carry leaves the land queue first (D12), then the landing retakes the lease and merges."""
        own = [{"verdict": "needed", "kept_from": None}, {"verdict": "approved", "kept_from": None}]
        result, calls = self.approve(replies={"look-status": own, "look-carry": {"verdict": "approved", "from": None, "reason": None, "comment_id": None}})
        self.assertEqual(result["stage"], "done", labels(calls))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        stopped, _ = self.approve(replies={"look-status": own, "look-carry": {"verdict": "approved", "from": None, "reason": None, "comment_id": None}, "merge": None})
        self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": D, "approved": D})

    def test_an_unusable_carry_reply_stops_without_asking(self):
        replies = (({"verdict": "moved"}), ({"verdict": "error", "detail": "x"}), None, ({"verdict": "carried"}),
                   {"verdict": "carried", "from": SHA, "rule": "pictures", "comment_id": None},
                   {"verdict": "carried", "from": None, "rule": "pictures", "comment_id": 501},
                   {"verdict": "carried", "from": SHA[:7], "rule": "pictures", "comment_id": 501},
                   {"verdict": "carried", "from": F, "rule": "pictures", "comment_id": 501},
                   {"verdict": "carried", "from": SHA, "rule": "pictures", "comment_id": 0}, {"verdict": "needed"},
                   {"verdict": "needed", "reason": "whatever"}, {"verdict": "needed", "reason": "no-pictures"})
        for reply in replies:
            with self.subTest(reply=reply):
                result, calls = self.approve(replies={"look-carry": reply})
                self.stops_unasked(result, calls)

    def test_a_status_that_stays_needed_after_the_carry_stops_instead_of_carrying_again(self):
        """One carry runs per head: when look-status still answers needed at the carried head, the delivery stops."""
        result, calls = self.approve(replies={"look-status": {"verdict": "needed", "kept_from": None}, "look-carry": self.CARRIED})
        got = labels(calls)
        self.assertEqual(result["stage"], "look-carry")
        self.assertEqual(result["head"], D)
        self.assertEqual(got.count("look-carry-verify"), 1, got)
        self.assertEqual(got.count("look-carry"), 1, got)
        self.assertNotIn("merge", got)

    def test_a_kept_approval_runs_no_carry(self):
        result, calls = self.approve(patch=dict(self.NEEDED, **{"look-status": {"verdict": "approved", "kept_from": SHA}}))
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("look-carry-verify", labels(calls))
        self.assertNotIn("look-carry", labels(calls))

    def test_a_stop_after_a_carry_keeps_the_owners_head_for_the_resume(self):
        """The carry leaves the land queue first (D12), so the second landing's carry follows a land-unlock too."""
        stopped, _ = self.approve(replies={"look-carry": self.CARRIED, "merge": None})
        self.assertEqual(stopped["stage"], "merge")
        self.assertEqual(stopped["cont"]["look"], {"pr": 42, "head": D, "approved": D, "owner": SHA})
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch", "renew": {"verdict": "renewed"},
                 "lock": {"verdict": "already_held", "lock_sha": D}}
        replies = {"look-status": self.AFTER_CARRY, "look-carry": self.CARRIED,
                   "merge": [stale, {"merged": True, "merge_commit": F, "notes": "merged", "renew": {"verdict": "renewed"},
                                     "lock": {"verdict": "already_held", "lock_sha": F}}]}
        patch = dict(base.LookResumeTest.MOVED, **{"checks-3": {"state": "behind", "head": D}, "sync-2": {"merge_commit": F, "head": F},
                                              "checks-4": {"state": "passed", "head": F, "required": ["ci"], "passed": ["ci"]},
                                              "checks-5": {"state": "passed", "head": F, "required": ["ci"], "passed": ["ci"]}})
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch=patch, replies=replies)
        self.assertEqual(result["stage"], "done", labels(calls))
        self.assertIn("--from " + SHA + " --head " + F, prompt(calls, "look-carry"))
        self.assertNotIn("--from " + D, prompt(calls, "look-carry"))

    def test_a_second_resync_carries_from_the_owners_head(self):
        """The second resync's verified carry leaves the land queue first (D12); the landing retakes the lease at F."""
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch", "renew": {"verdict": "renewed"},
                 "lock": {"verdict": "already_held", "lock_sha": D}}
        replies = {"look-status": [{"verdict": "approved", "kept_from": SHA}] + self.AFTER_CARRY,
                   "merge": [stale, {"merged": True, "merge_commit": F, "notes": "merged", "renew": {"verdict": "renewed"},
                                     "lock": {"verdict": "already_held", "lock_sha": F}}],
                   "look-carry": self.CARRIED}
        patch = dict(base.LookResumeTest.MOVED, **{"checks-3": {"state": "behind", "head": D}, "sync-2": {"merge_commit": F, "head": F},
                                              "checks-4": {"state": "passed", "head": F, "required": ["ci"], "passed": ["ci"]},
                                              "checks-5": {"state": "passed", "head": F, "required": ["ci"], "passed": ["ci"]}})
        result, calls = self.approve(patch=patch, replies=replies)
        self.assertEqual(result["stage"], "done", labels(calls))
        verify = prompt(calls, "look-carry-verify")
        self.assertIn("rev-list --no-merges " + SHA + ".." + F, verify)
        self.assertNotIn(D + ".." + F, verify)
        self.assertIn("--from " + SHA + " --head " + F, prompt(calls, "look-carry"))
        self.assertIn("--match-head-commit " + F, prompt(calls, "merge"))


VERIFY_TEXT = "Run the project's declared verification once on the worktree head"


def acquires(call):
    return "forge-claim land acquire" in call["prompt"] and call["label"] != "merge"


def verified_under_the_lock(calls):
    """Labels of a verification that ran between a lock acquire and the next land-unlock."""
    held, bad = False, []
    for call in calls:
        if call["label"] == "land-unlock":
            held = False
        elif acquires(call):
            held = True
        elif call["label"] in ("look-carry-verify", "look-reverify") and held:
            bad.append(call["label"])
    return bad


class OwnFilesCarryTest(unittest.TestCase):
    """A clean sync that touched no own file carries the approval with no local verification (D11).

    Any other head change leaves the land queue before the verified carry (D12).
    """

    OWN = {"verdict": "carried", "from": SHA, "reason": None, "rule": "own-files", "comment_id": 502}
    TOUCHED = {"verdict": "needed", "from": SHA, "reason": "own-files-touched", "rule": "own-files", "comment_id": None}
    CARRIED = LookCarryLandingTest.CARRIED
    APPROVED = {"verdict": "approved", "kept_from": None}
    SYNCED = dict(base.LookResumeTest.MOVED, **{"checks-3": base.LookResumeTest.MOVED["checks-2"]})

    def approve(self, replies=None, patch=None):
        first, _ = run(patch={"setup": {"look": MARKED}})
        return run(args=dict(ARGS, cont=first["cont"], look={"answer": "approve", "head": SHA}),
                   patch=self.SYNCED if patch is None else patch, replies=dict({"land-take": LookCarryLandingTest.TAKES}, **(replies or {})))

    def test_a_clean_sync_that_touches_no_own_file_lands_with_no_local_verification(self):
        result, calls = self.approve(replies={"look-carry-own": self.OWN, "merge": {"merged": True, "merge_commit": D, "notes": "merged"}})
        got = labels(calls)
        self.assertEqual(result["stage"], "done", got)
        for label in ("look-carry-verify", "look-reverify", "look-carry"):
            self.assertNotIn(label, got)
        for call in calls[got.index("pr") + 1:]:
            self.assertNotIn(VERIFY_TEXT, call["prompt"])
            self.assertNotIn("look-approval post", call["prompt"])
        self.assertIn("look-approval carry --repo owner/repo --issue 9 --pr 42 --from " + SHA + " --head " + D + " --own-files",
                      prompt(calls, "look-carry-own"))
        self.assertIn(beat("forge-claim land hold --repo owner/repo --branch dev --sha " + D)
                      + "Then run alone and exactly: look-approval carry", prompt(calls, "look-carry-own"))
        between = got[got.index("sync-1"):got.index("merge")]
        self.assertEqual([l for l in between if l.startswith("checks-")], ["checks-2"])
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertLess(got.index("look-status"), got.index("look-carry-own"))
        self.assertLess(got.index("look-carry-own"), got.index("merge"))
        self.assertNotIn("land-unlock", got)

    def test_an_own_file_touched_by_the_sync_leaves_the_queue_before_the_verified_carry(self):
        replies = {"look-carry-own": self.TOUCHED, "look-carry": self.CARRIED, "look-status": [{"verdict": "needed", "kept_from": None}, self.APPROVED]}
        result, calls = self.approve(replies=replies)
        got = labels(calls)
        self.assertEqual(result["stage"], "done", got)
        order = ["look-carry-own", "land-unlock", "look-carry-verify", "look-carry", "green-checks-1", "look-status", "merge"]
        self.assertEqual([l for l in got[got.index("look-carry-own"):] if l in order], order)
        self.assertIn("forge-claim land release --repo owner/repo --branch dev --sha " + D, prompt(calls, "land-unlock"))
        self.assertIn("land acquire --repo owner/repo --branch dev --sha " + D + " --wait --lease\n", prompt(calls, "land-take"))
        self.assertEqual(verified_under_the_lock(calls), [])
        self.assertEqual(got.count("look-carry-verify"), 1)
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        for call in calls:
            self.assertNotIn("look-approval post", call["prompt"])

    def test_a_conflicted_sync_never_asks_the_own_files_rule(self):
        patch = dict(self.SYNCED, **{"sync-1": {"status": "conflicted", "conflicted": True, "notes": "a.py"},
                                    "sync-resolve-1": {"merge_commit": D, "head": D}})
        replies = {"look-carry": self.CARRIED, "look-status": [{"verdict": "needed", "kept_from": None}, self.APPROVED]}
        result, calls = self.approve(replies=replies, patch=patch)
        got = labels(calls)
        self.assertEqual(result["stage"], "done", got)
        self.assertNotIn("look-carry-own", got)
        verify = got.index("look-carry-verify")
        self.assertEqual(got[verify - 1], "land-unlock")
        last = max(i for i, l in enumerate(got[:verify]) if l == "land-unlock")
        self.assertFalse([c["label"] for c in calls[last:verify] if acquires(c)])
        self.assertEqual(verified_under_the_lock(calls), [])

    def test_a_carried_reply_naming_another_rule_or_head_stops(self):
        cases = (("another rule", dict(self.OWN, rule="pictures")), ("another head", dict(self.OWN, **{"from": F})),
                 ("no comment", dict(self.OWN, comment_id=0)), ("no rule", {k: v for k, v in self.OWN.items() if k != "rule"}),
                 ("moved", {"verdict": "moved"}), ("none", None), ("unknown reason", dict(self.TOUCHED, reason="whatever")))
        for name, reply in cases:
            with self.subTest(case=name):
                result, calls = self.approve(replies={"look-carry-own": reply})
                got = labels(calls)
                self.assertEqual(result["stage"], "look-carry")
                self.assertEqual(got.count("land-unlock"), 1)
                self.assertNotIn("merge", got)
                self.assertNotIn("look-carry-verify", got)

    def test_a_fallback_that_needs_a_new_look_stops_holding_nothing(self):
        needed = {"verdict": "needed", "from": SHA, "reason": "pictures-differ", "rule": "pictures", "comment_id": None}
        result, calls = self.approve(replies={"look-carry-own": self.TOUCHED, "look-carry": needed,
                                              "look-checks-1": {"state": "passed", "head": D, "behind": False, "required": ["ci"], "passed": ["ci"]}})
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(got.count("land-unlock"), 1)
        self.assertLess(got.index("land-unlock"), got.index("look-carry-verify"))
        self.assertFalse([l for l in got if l.startswith("land-relock-")], got)
        self.assertNotIn("merge", got)


class LandQueueDemoTest(unittest.TestCase):
    """The demo (D20): two green approved pull requests queue; the second lands after one sync and one rerun."""

    S1, S2, M1 = "1" * 40, "2" * 40, "e" * 40
    CI, SYNC, MERGE = 520, 60, 30

    class FakeClock:
        def __init__(self):
            self.now = 0

        def advance(self, seconds):
            self.now += seconds

    class FakeForge:
        """The forge a run is computed from: the tip, each pull request's head and own files, the runs per head."""

        def __init__(self, clock, pulls):
            self.clock, self.pulls, self.merged, self.runs = clock, pulls, [], {}
            self.tip, self.tip_files = "0" * 40, set()
            self.base = {n: self.tip for n in pulls}

        def runs_at(self, head):
            return self.runs.get(head, 0)

        def replies(self, pr, sync_commit):
            """The static replies of one run of pull request pr, computed from the state before it."""
            head, own, since = self.pulls[pr]["head"], self.pulls[pr]["own"], self.pulls[pr]["registered"]
            behind = self.tip != self.base[pr]
            replies = {"pr": {"pr": pr, "head": head, "green": green_read(head)},
                       "look-head": {"head": head, "state": "OPEN"},
                       "land-take": {"lock": {"verdict": "acquired", "lock_sha": head, "waited_s": self.clock.now - since}, "behind": behind},
                       "look-status": {"verdict": "needed", "kept_from": None}}
            if behind:
                replies["sync-1"] = {"status": "done", "conflicted": False, "merge_commit": sync_commit, "head": sync_commit}
                replies["checks-2"] = {"state": "passed", "head": sync_commit, "required": ["ci"], "passed": ["ci"]}
                touched = bool(own & self.tip_files)
                replies["look-carry-own"] = ({"verdict": "needed", "from": head, "reason": "own-files-touched", "rule": "own-files", "comment_id": None} if touched
                                              else {"verdict": "carried", "from": head, "reason": None, "rule": "own-files", "comment_id": 502})
            landing = sync_commit if behind else head
            replies["merge"] = {"merged": True, "merge_commit": landing, "notes": "merged",
                                "lock": {"verdict": "already_held", "lock_sha": landing}}
            return replies, landing

        def record(self, pr, calls, landing):
            """The run's effects: each CI run at the head it answered, and the merge that moves the tip."""
            got = labels(calls)
            self.runs[landing] = self.runs.get(landing, 0) + len([l for l in got if l.startswith("checks-")])
            if "merge" in got:
                self.merged.append(pr)
                self.tip, self.tip_files = landing, set(self.pulls[pr]["own"])

    def land(self, forge, pr, sync_commit):
        head = forge.pulls[pr]["head"]
        first, _ = run(patch={"setup": {"look": MARKED, "head": head}, "verify": {"head": head}, "look-pr": {"pr": pr, "head": head}})
        replies, landing = forge.replies(pr, sync_commit)
        result, calls = run(args=dict(ARGS, cont=first["cont"], look={"answer": "approve", "head": head}),
                            patch={"setup": {"look": MARKED, "head": head}}, replies=replies)
        got = labels(calls)
        forge.clock.advance(self.SYNC * got.count("sync-1") + self.CI * len([l for l in got if l.startswith("checks-")]) + self.MERGE * ("merge" in got))
        forge.record(pr, calls, landing)
        return result, calls

    def test_two_green_approved_pull_requests_queue_and_the_second_lands_after_one_sync_and_one_rerun(self):
        clock = self.FakeClock()
        forge = self.FakeForge(clock, {41: {"head": self.S1, "own": {"a.py"}, "registered": 0}, 42: {"head": self.S2, "own": {"b.py"}, "registered": 5}})
        one, calls_one = self.land(forge, 41, self.M1)
        self.assertEqual(one["stage"], "done", labels(calls_one))
        self.assertEqual(clock.now, self.MERGE)
        two, calls = self.land(forge, 42, D)
        got = labels(calls)
        self.assertEqual(two["stage"], "done", got)
        self.assertEqual(forge.merged, [41, 42])
        self.assertEqual(forge.runs_at(D), 1)
        self.assertEqual(forge.runs_at(self.S2), 0)
        self.assertEqual([l for l in got if l.startswith("sync-")], ["sync-1"])
        self.assertEqual([l for l in got if l.startswith("checks-")], ["checks-2"])
        for label in ("look-carry-verify", "look-reverify"):
            self.assertNotIn(label, got)
        for call in calls[got.index("pr") + 1:]:
            self.assertNotIn(VERIFY_TEXT, call["prompt"])
            self.assertNotIn("look-approval post", call["prompt"])
        self.assertIn("--wait --lease", prompt(calls, "land-take"))
        self.assertIn("--match-head-commit " + D, prompt(calls, "merge"))
        self.assertEqual(clock.now, self.MERGE + self.SYNC + self.CI + self.MERGE)
