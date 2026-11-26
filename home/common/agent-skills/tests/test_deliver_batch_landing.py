"""deliver-batch.js landing scenarios against stub agents: the green-first lease, a conflict resolved outside it and the waits for it.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from . import test_deliver_batch_program as base
from .test_deliver_batch_program import (
    ABORTED,
    B,
    BEHIND,
    C,
    FIX,
    HELD,
    OPEN_PR,
    PRE_MERGE_CONTS,
    PROGRAM,
    SHA,
    green,
    labels,
    land_labels,
    land_release_shas,
    object_branch,
    prompt,
    row,
    run,
    run_full,
    schema_of,
    train_run,
    unpushed,
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


class ConflictedSyncOutsideLockTest(unittest.TestCase):
    """A sync merge that conflicts is aborted under the land lock and resolved, tested, reviewed and fixed outside it; the
    reviewed head is read green before it takes the lock again, waiting, and a clean merge never leaves it."""

    RELEASE = "forge-claim land release --repo owner/repo --branch dev --sha "
    FOUND = {"verdict": "findings", "findings": [{"severity": "important", "summary": "dropped a change", "failing_input": "x"}]}
    TAKES = [{"behind": True}, {}]

    def land(self, **replies):
        return run_full(replies=dict({"land-sync-1-1": ABORTED, "land-take-1": self.TAKES, "land-checks-1-2": green(B)}, **replies))

    def test_a_conflict_is_aborted_released_resolved_and_the_lock_taken_again_once_green(self):
        out = self.land()
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-checks-1-2", "land-take-1", "land-merge-1", "close-out-1"])
        sync = prompt(calls, "land-sync-1-1")
        self.assertIn("If the merge conflicts, do not resolve it: run git merge --abort inside /r/.wt/w-issue-1-x", sync)
        self.assertIn("confirm no merge is left in progress", sync)
        self.assertIn("conflicted", next(c for c in calls if c["label"] == "land-sync-1-1")["schema"]["properties"]["status"]["enum"])
        # The first hold ends at the head it was taken at, before the resolution starts.
        self.assertIn(f"{self.RELEASE}{SHA}\n", prompt(calls, "land-unlock-1"))
        resolve = prompt(calls, "land-sync-resolve-1-1")
        for text in ("The landing lock is not held while you work", "rev-parse -q --verify MERGE_HEAD", "merge origin/dev",
                     "git -C /r/.wt/w-issue-1-x push origin issue-1-x"):
            self.assertIn(text, resolve)
        # The reviewed head is recorded and read green with no lock command; only then is the lock taken at it with --wait.
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"Accepted head: {B}\n", record)
        self.assertNotIn("land acquire", record)
        self.assertNotIn("forge-claim land", prompt(calls, "land-checks-1-2"))
        take = prompt(calls, "land-take-1")
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B} --wait --lease\n", take)
        self.assertIn("merge-base --is-ancestor origin/dev HEAD", take)
        # The merge keeps its one-shot check, and the second hold is released once, in the close-out call.
        merge = prompt(calls, "land-merge-1")
        self.assertIn(f"--sha {B} --lease\n", merge)
        self.assertIn("Only when lock's verdict is already_held or moved", merge)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "close-out-1"))
        self.assertEqual(out["logs"][-1], "#1: landed")

    def test_a_clean_merge_keeps_the_lock(self):
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "ok"}})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"move the cross-host landing lock of the branch dev to the head {B}", record)
        self.assertNotIn("--wait --lease\n", record)

    def test_behind_again_after_the_second_take_a_clean_merge_stays_under_the_lock(self):
        out = self.land(**{"land-take-1": [{"behind": True}, {"behind": True}],
                           "land-sync-1-2": {"status": "done", "conflicted": False, "head": C, "notes": "ok"}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-checks-1-2", "land-take-1", "land-sync-1-2", "land-record-1-2", "land-merge-1",
                                              "close-out-1"])
        again = prompt(calls, "land-record-1-2")
        self.assertIn(f"--sha {C} --lease\n", again)
        self.assertNotIn("--wait --lease\n", again)
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))

    def test_behind_again_with_a_second_conflict_is_resolved_outside_the_lock_again(self):
        replies = {"land-take-1": [{"behind": True}, {"behind": True}, {}], "land-checks-1-3": green(C),
                   "land-sync-1-2": dict(ABORTED, head=B),
                   "land-sync-resolve-1-2": {"status": "done", "conflicted": True, "head": C, "merge_commit": C, "notes": "ok"}}
        out = self.land(**replies)
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), [
            "land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-record-1-1",
            "land-checks-1-2", "land-take-1", "land-sync-1-2", "land-unlock-1", "land-sync-resolve-1-2", "land-sync-review-1-2", "land-record-1-2",
            "land-checks-1-3", "land-take-1", "land-merge-1", "close-out-1"])
        # Each hold is released once, at the head it was held at.
        unlocks = [c["prompt"] for c in calls if c["label"] == "land-unlock-1"]
        self.assertEqual([self.RELEASE + sha + "\n" in text for sha, text in zip((SHA, B), unlocks)], [True, True])
        self.assertIn(f"--sha {C} --wait --lease\n", prompt(calls, "land-take-1"))
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))
        # Behind once more after the second round: the sync budget is spent, and the third hold is released by the wrapper.
        out = self.land(**dict(replies, **{"land-take-1": [{"behind": True}] * 3}))
        got = row(out["result"], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("land-contended", "behind dev after 2 resyncs in all"))
        self.assertNotIn("land-merge-1", labels(out["calls"]))
        self.assertEqual(labels(out["calls"]).count("land-unlock-1"), 3)
        self.assertIn(f"{self.RELEASE}{C}\n", prompt(out["calls"], "land-unlock-1"))

    def test_a_refused_take_after_a_resolution_never_merges_and_holds_nothing(self):
        for verdict in ("land-contended", "held_by", "lost_to"):
            with self.subTest(verdict=verdict):
                out = self.land(**{"land-take-1": [{"behind": True}, {"lock": {"verdict": verdict, "lock_sha": C, "by": "h2/b9"}}],
                                   **{f"land-lock-1-{k}": {"lock": {"verdict": "land-contended", "lock_sha": C}} for k in (1, 2, 3)}})
                result, calls = out["result"], out["calls"]
                # Only a wait that ran out is waited for again, as often as a first wait is (LAND_WAIT_RETRIES).
                self.assertEqual([label for label in labels(calls) if label.startswith("land-lock-")],
                                 [f"land-lock-1-{k}" for k in (1, 2, 3)] if verdict == "land-contended" else [])
                got = row(result, 1)
                self.assertEqual((got["outcome"], got["reason"]), ("land-contended", f"the land lock is held by another landing ({verdict})"))
                ls = labels(calls)
                for gone in ("land-merge-1", "land-status-1-1", "close-out-1"):
                    self.assertNotIn(gone, ls)
                # Nothing is held after the refusal: the only release is the one before the resolution.
                self.assertEqual(ls.count("land-unlock-1"), 1)
                self.assertLess(ls.index("land-unlock-1"), ls.index("land-sync-resolve-1-1"))
                self.assertEqual(result["relaunch"]["conts"], PRE_MERGE_CONTS)

    def test_a_take_after_a_resolution_that_answers_acquired_still_merges_only_on_the_pre_merge_check(self):
        taken = [{"behind": True}, {"lock": {"verdict": "acquired", "lock_sha": B, "waited_s": 1740, "waited_on": [2257]}}]
        out = self.land(**{"land-take-1": taken})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertIn("land-take-1: waited 29 min for the land lock of dev behind PR #2257", out["logs"])
        out = self.land(**{"land-take-1": taken,
                           "land-merge-1": {"merged": False, "notes": "held_by", "lock": {"verdict": "held_by", "lock_sha": C}}})
        got = row(out["result"], 1)
        self.assertEqual((got["outcome"], got["reason"]), ("land-contended", "the land lock was lost to another landing 4 times"))
        self.assertNotIn("close-out-1", labels(out["calls"]))

    def test_a_lost_take_after_a_resolution_releases_what_it_may_hold(self):
        # No reply: the waiting acquire may have taken the lock at the reviewed head, so the wrapper releases there.
        out = self.land(**{"land-take-1": [{"behind": True}, None]})
        result, calls = out["result"], out["calls"]
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-lock"))
        self.assertEqual(labels(calls).count("land-unlock-1"), 2)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "land-unlock-1"))
        self.assertNotIn("land-merge-1", labels(calls))
        # The record step refused before any lock command: nothing is held and nothing more is released.
        out = self.land(**{"land-record-1-1": {"ok": False, "head": C, "detail": "the head moved", "lock": None, "checks": None}})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual(labels(out["calls"]).count("land-unlock-1"), 1)

    def test_every_stop_outside_the_lock_releases_once_and_accepts_nothing(self):
        stops = {
            "the resolution is lost": ({"land-sync-resolve-1-1": None}, "stopped"),
            "the resolution is blocked": ({"land-sync-resolve-1-1": {"status": "blocked", "conflicted": True, "notes": "too tangled"}}, "conflict"),
            "the resolution names no head": ({"land-sync-resolve-1-1": {"status": "done", "conflicted": True, "notes": "ok"}}, "stopped"),
            "the review is lost": ({"land-sync-review-1-1": None}, "sync-review"),
            "the fix is lost": ({"land-sync-review-1-1": self.FOUND, "land-sync-fix-1-1": None}, "sync-review"),
            "the finding survives": ({"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.FOUND}, "sync-review"),
        }
        for name, (replies, outcome) in stops.items():
            with self.subTest(stop=name):
                out = self.land(**replies)
                result, ls = out["result"], labels(out["calls"])
                self.assertEqual(row(result, 1)["outcome"], outcome)
                self.assertEqual(ls.count("land-unlock-1"), 1)
                self.assertEqual(ls[ls.index("land-sync-1-1") + 1], "land-unlock-1")
                # The accepted head is never rewritten, so a relaunch finds the pushed merge unaccepted and reviews it through the child.
                for gone in ("land-record-1-1", "land-merge-1", "close-out-1"):
                    self.assertNotIn(gone, ls)
                # A fix commit a stop left unpushed is carried as untested; every other stop keeps the child's cont.
                self.assertEqual(result["relaunch"]["conts"], unpushed("sync-fix", B, base.SyncFixRoundTest.FIXED) if name == "the finding survives" else PRE_MERGE_CONTS)

    def test_a_relaunch_after_a_stop_outside_the_lock_goes_through_the_child(self):
        first, _, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-sync-review-1-1": None})
        result, calls, _ = run(args=first["relaunch"], patch={"facts-1": dict(HELD, open_pr=OPEN_PR)},
                               replies={"readopt-1": {"ok": False, "reason": "unaccepted", "detail": B}})
        ls = labels(calls)
        self.assertLess(ls.index("readopt-1"), ls.index("child-1"))
        self.assertLess(ls.index("child-1"), ls.index("land-pr-1"))
        self.assertEqual(row(result, 1)["outcome"], "landed")

    def test_a_sync_step_that_resolved_the_conflict_itself_is_released_and_reviewed(self):
        resolved = {"status": "done", "conflicted": True, "head": B, "merge_commit": B, "notes": "ok"}
        out = self.land(**{"land-sync-1-1": resolved})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(land_labels(out["calls"]), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-review-1-1", "land-record-1-1",
                                                     "land-checks-1-2", "land-take-1", "land-merge-1", "close-out-1"])
        self.assertIn(f"--sha {B} --wait --lease\n", prompt(out["calls"], "land-take-1"))
        out = self.land(**{"land-sync-1-1": resolved, "land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.FOUND})
        self.assertEqual(row(out["result"], 1)["outcome"], "sync-review")
        self.assertNotIn("land-merge-1", labels(out["calls"]))

    def test_a_resolution_that_says_it_merged_cleanly_is_reviewed_all_the_same(self):
        clean = {"land-sync-resolve-1-1": {"status": "done", "conflicted": False, "head": B, "notes": "dev moved"}}
        out = self.land(**clean)
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(land_labels(out["calls"]), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1",
                                                     "land-sync-review-1-1", "land-record-1-1", "land-checks-1-2", "land-take-1", "land-merge-1",
                                                     "close-out-1"])
        self.assertIn(f"merge commit {B}", prompt(out["calls"], "land-sync-review-1-1"))
        self.assertIn(f"--sha {B} --wait --lease\n", prompt(out["calls"], "land-take-1"))
        out = self.land(**clean, **{"land-sync-review-1-1": self.FOUND, "land-sync-rereview-1-1": self.FOUND})
        self.assertEqual(row(out["result"], 1)["outcome"], "sync-review")
        self.assertNotIn("land-merge-1", labels(out["calls"]))

    FOLLOWED = {"status": "done", "conflicted": True, "head": C, "merge_commit": B, "resolved_files": ["x.py"],
                "markers_checked": True, "tests": ["t"], "notes": "the tests caught a missed version bump; fixed on top of the merge"}
    DESCENDS = {"verdict": "pass", "findings": [], "descends": True}

    def test_a_resolution_whose_head_does_not_descend_from_its_merge_commit_never_lands(self):
        """Only the sync review's own proof of ancestry accepts a head that is not the merge commit."""
        unrelated = {"verdict": "pass", "findings": [], "descends": False}
        unproven = {"verdict": "pass", "findings": []}
        for name, replies in {
            "resolved outside the lock": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": self.FOLLOWED, "land-sync-review-1-1": unrelated},
            "resolved by the sync step": {"land-sync-1-1": self.FOLLOWED, "land-sync-review-1-1": unrelated},
            "the review proves nothing": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": self.FOLLOWED, "land-sync-review-1-1": unproven},
            "an unrelated head with findings": {"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": self.FOLLOWED,
                                                "land-sync-review-1-1": dict(self.FOUND, descends=False)},
        }.items():
            with self.subTest(case=name):
                result, calls, _ = run(patch=BEHIND, replies=replies)
                got = row(result, 1)
                self.assertEqual((got["outcome"], got["stage"]), ("stopped", "land-sync"))
                self.assertEqual(got["reason"], f"land-sync: the resolution names the head {C} and the merge commit {B}, and the head does not "
                                                "descend from it: only a reviewed merge commit lands")
                ls = labels(calls)
                for gone in ("land-sync-fix-1-1", "land-record-1-1", "land-merge-1"):
                    self.assertNotIn(gone, ls)
                self.assertEqual(ls.count("land-unlock-1"), 1)
        # An abbreviated merge commit of the same head is the same commit.
        out = self.land(**{"land-sync-resolve-1-1": {"status": "done", "conflicted": True, "head": B, "merge_commit": B[:12], "notes": "ok"}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertNotIn("descends", prompt(out["calls"], "land-sync-review-1-1"))

    def test_a_resolution_with_commits_on_top_of_its_merge_commit_is_reviewed_over_both_and_lands_at_its_head(self):
        """A follow-up commit the resolver made after the merge is reviewed with the merge, and the head is what lands."""
        out = self.land(**{"land-sync-resolve-1-1": self.FOLLOWED, "land-sync-review-1-1": self.DESCENDS, "land-checks-1-2": green(C)})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-checks-1-2", "land-take-1", "land-merge-1", "close-out-1"])
        review = prompt(calls, "land-sync-review-1-1")
        wt = "/r/.wt/w-issue-1-x"
        for needle in (f"git -C {wt} show --cc {B}", f"git -C {wt} merge-base --is-ancestor {B} {C}",
                       f"git -C {wt} rev-list --count --min-parents=2 {B}..{C}", f"git -C {wt} diff {B}..{C}",
                       f"git -C {wt} diff --check {B} {C}", "return descends true only when the first exits 0 and the second prints 0",
                       "above all for a test or check they weaken, skip or delete"):
            with self.subTest(needle=needle):
                self.assertIn(needle, review)
        schema = schema_of(calls, "land-sync-review-1-1")
        self.assertIn("descends", schema["required"])
        self.assertEqual(schema["properties"]["descends"], {"type": "boolean"})
        # Everything downstream is at the head: the accepted head, the lock, the merge and the release.
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"Accepted head: {C}\n", record)
        self.assertIn(f"confirm headRefOid is {C}", record)
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {C} --wait --lease\n", prompt(calls, "land-take-1"))
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))
        self.assertEqual(land_release_shas(calls), [SHA, C])

    def test_a_resolution_that_names_no_merge_commit_never_lands(self):
        """The head may be a follow-up commit, so a conflicted resolution naming a head alone names no merge to review."""
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": ABORTED, "land-sync-resolve-1-1": {
            "status": "done", "conflicted": True, "head": C, "resolved_files": ["x.py"], "notes": "ok"}})
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["stage"], got["reason"]),
                         ("stopped", "land-sync", "land-sync: the resolution named no merge commit"))
        ls = labels(calls)
        for gone in ("land-sync-review-1-1", "land-record-1-1", "land-merge-1"):
            self.assertNotIn(gone, ls)
        # The only step that runs a merge command, land-merge, never ran (asserted above); what ran is the landing up to the resolution.
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1"])
        self.assertEqual(ls.count("land-unlock-1"), 1)

    def test_a_sync_step_that_resolved_the_conflict_itself_and_names_no_merge_commit_never_lands(self):
        """The same refusal when the sync step, not the resolve step, answers conflicted with a head alone."""
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": {
            "status": "done", "conflicted": True, "head": C, "resolved_files": ["x.py"], "notes": "ok"}})
        got = row(result, 1)
        self.assertEqual((got["outcome"], got["stage"], got["reason"]),
                         ("stopped", "land-sync", "land-sync: the resolution named no merge commit"))
        ls = labels(calls)
        for gone in ("land-sync-resolve-1-1", "land-sync-review-1-1", "land-record-1-1", "land-merge-1"):
            self.assertNotIn(gone, ls)
        self.assertEqual(land_labels(calls)[:3], ["land-pr-1", "land-take-1", "land-sync-1-1"])

    def test_a_clean_sync_whose_head_is_not_its_merge_commit_is_reviewed_too(self):
        clean = {"status": "done", "conflicted": False, "head": C, "merge_commit": B, "notes": "ok"}
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": clean, "land-sync-review-1-1": self.DESCENDS})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-sync-review-1-1", "land-record-1-1", "land-merge-1", "close-out-1"])
        self.assertIn(f"diff {B}..{C}", prompt(calls, "land-sync-review-1-1"))
        self.assertIn(f"--match-head-commit {C}", prompt(calls, "land-merge-1"))
        result, calls, _ = run(patch=BEHIND, replies={"land-sync-1-1": clean, "land-sync-review-1-1": {"verdict": "pass", "findings": [], "descends": False}})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-sync"))
        self.assertNotIn("land-merge-1", labels(calls))

    def test_the_fix_round_of_a_resolution_with_follow_up_commits_starts_at_its_head_and_names_the_range(self):
        d = "d" * 40
        fixed = {"status": "done", "start_head": C, "commit": d, "notes": "ok", "tests": ["t"]}
        found = dict(self.FOUND, descends=True)
        out = self.land(**{"land-sync-resolve-1-1": self.FOLLOWED, "land-sync-review-1-1": found, "land-sync-fix-1-1": fixed,
                           "land-checks-1-2": green(d)})
        calls = out["calls"]
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        rng = f"merge commit {B} (git -C /r/.wt/w-issue-1-x show --cc {B}) and the commits made on top of it up to the head {C} (git -C /r/.wt/w-issue-1-x diff {B}..{C})"
        self.assertIn(rng, prompt(calls, "land-sync-fix-1-1"))
        self.assertIn("on top of that head", prompt(calls, "land-sync-fix-1-1"))
        rereview = prompt(calls, "land-sync-rereview-1-1")
        self.assertIn(f"diff {C}..{d}", rereview)
        self.assertIn(f"merge commit {B} and the commits made on top of it up to the head {C}", rereview)
        self.assertIn(f"--match-head-commit {d}", prompt(calls, "land-merge-1"))
        # A fix that started at the merge commit, beneath the follow-up commits, is not a fix of the reviewed head.
        out = self.land(**{"land-sync-resolve-1-1": self.FOLLOWED, "land-sync-review-1-1": found,
                           "land-sync-fix-1-1": dict(fixed, start_head=B)})
        self.assertEqual(row(out["result"], 1)["outcome"], "sync-review")
        self.assertNotIn("land-merge-1", labels(out["calls"]))

    def test_the_resolver_runs_its_tests_before_it_commits_the_merge_and_never_amends_it(self):
        resolve = prompt(self.land()["calls"], "land-sync-resolve-1-1")
        before = "still before committing, run in full every test file among or covering the files you resolved by hand"
        self.assertIn(before, resolve)
        self.assertLess(resolve.index("diff --check HEAD"), resolve.index(before))
        self.assertLess(resolve.index(before), resolve.index("commit the merge only once they pass"))
        self.assertNotIn(", commit the merge, and run in full", resolve)
        for needle in ("never amend or redo the merge: fix it in a commit on top of it", "run those tests again",
                       "merge_commit (the full sha of the merge commit)",
                       "head (the full sha of HEAD: the merge commit, or the last commit you made on top of it)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, resolve)

    def test_a_take_after_a_resolution_whose_wait_ran_out_waits_again_like_a_first_wait(self):
        out_of_time = {"lock": {"verdict": "land-contended", "lock_sha": C, "waited_s": 3600, "waited_on": [7]}}
        takes = {"land-take-1": [{"behind": True}, out_of_time]}
        out = self.land(**takes, **{"land-lock-1-1": {"lock": {"verdict": "land-contended", "lock_sha": C}},
                                    "land-lock-1-2": {"lock": {"verdict": "acquired", "lock_sha": B, "waited_s": 900, "waited_on": [7, 9]}}})
        result, calls = out["result"], out["calls"]
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual(land_labels(calls), ["land-pr-1", "land-take-1", "land-sync-1-1", "land-unlock-1", "land-sync-resolve-1-1", "land-sync-review-1-1",
                                              "land-record-1-1", "land-checks-1-2", "land-take-1", "land-lock-1-1", "land-lock-1-2", "land-merge-1",
                                              "close-out-1"])
        again = next(c for c in calls if c["label"] == "land-lock-1-2")
        self.assertEqual((again["agentType"], again["model"]), ("clerk", "sonnet"))
        self.assertIn("forge-claim renew --repo owner/repo --issue 1", again["prompt"])
        self.assertIn(f"forge-claim land acquire --repo owner/repo --branch dev --sha {B} --wait --lease\n", again["prompt"])
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(calls, "close-out-1"))
        self.assertEqual([line for line in out["logs"] if "waited" in line],
                         ["land-take-1: waited 60 min for the land lock of dev behind PR #7",
                          "land-lock-1-2: waited 15 min for the land lock of dev behind PR #7, #9"])
        # A lost claim ends the wait; a lost reply may hold the lock at the reviewed head, which the wrapper releases.
        out = self.land(**takes, **{"land-lock-1-1": {"renew": {"verdict": "not_held", "by": "h2/b9"}, "lock": None}})
        self.assertEqual(row(out["result"], 1)["outcome"], "claim-lost")
        self.assertEqual(labels(out["calls"]).count("land-unlock-1"), 1)

    FAILED = {"verdict": "error", "detail": "boom"}

    def unlocks(self, out):
        return [c["prompt"] for c in out["calls"] if c["label"] == "land-unlock-1"]

    def test_a_release_that_failed_before_the_resolution_is_tried_again_at_the_stop(self):
        for name, first in {"an error": self.FAILED, "a lost reply": None, "a dead agent": "throw"}.items():
            with self.subTest(release=name):
                out = self.land(**{"land-unlock-1": [first, {"verdict": "released"}], "land-sync-review-1-1": None})
                dead = name == "a dead agent"  # the landing ends where the agent died; the resolution never starts
                self.assertEqual(row(out["result"], 1)["outcome"], "stopped" if dead else "sync-review")
                self.assertEqual("land-sync-resolve-1-1" in labels(out["calls"]), not dead)
                # Both releases name the sha the lock is held at: the head it was taken at.
                self.assertEqual([f"{self.RELEASE}{SHA}\n" in text for text in self.unlocks(out)], [True, True])
                self.assertNotIn("land-merge-1", labels(out["calls"]))

    def test_after_a_failed_release_a_lost_move_releases_the_earlier_sha_then_the_reviewed_head(self):
        out = self.land(**{"land-unlock-1": [self.FAILED, {"verdict": "released"}], "land-record-1-1": None})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-record"))
        first, last = self.unlocks(out)
        self.assertIn(f"{self.RELEASE}{SHA}\n", last)
        self.assertIn(f"When it prints not_held with lock_sha {B}, run alone and exactly: {self.RELEASE}{B}", last)
        self.assertNotIn("When it prints not_held", first)

    def test_after_a_failed_release_the_move_outcomes_keep_the_right_sha(self):
        failed = {"land-unlock-1": [self.FAILED, {"verdict": "released"}]}
        # The record step moves the lock that was never released: the landing goes on and the close-out releases the reviewed head.
        out = self.land(**failed, **{"land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "moved", "lock_sha": B}}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertEqual(len(self.unlocks(out)), 1)
        self.assertIn(f"{self.RELEASE}{B}\n", prompt(out["calls"], "close-out-1"))
        # The record step refused before any lock command: the earlier sha is still marked held and is released again.
        out = self.land(**failed, **{"land-record-1-1": {"ok": False, "head": C, "detail": "the head moved", "lock": None, "checks": None}})
        self.assertEqual((row(out["result"], 1)["outcome"], row(out["result"], 1)["stage"]), ("stopped", "land-record"))
        self.assertEqual([f"{self.RELEASE}{SHA}\n" in text for text in self.unlocks(out)], [True, True])
        # Another landing took the lock the move found lost: this landing waits again at the back, and nothing is released twice.
        out = self.land(**failed, **{"land-record-1-1": {"ok": True, "head": B, "lock": {"verdict": "held_by", "lock_sha": C}, "checks": None}})
        self.assertEqual(row(out["result"], 1)["outcome"], "landed")
        self.assertIn("land-lock-1-1", labels(out["calls"]))
        self.assertEqual(len(self.unlocks(out)), 1)


class WaitByPlaceTest(unittest.TestCase):
    """The retries of a lock wait are spent only by a wait that made no progress. A wait that ended first in line, or at a
    better place than the wait before it, is made again for nothing, and a ceiling of six hours bounds the waits in all."""

    @staticmethod
    def ran_out(position, **lock):
        return {"lock": dict({"verdict": "land-contended", "lock_sha": B, "waited_s": 3000, "waited_on": [7],
                              "position": position, "ahead": [] if position == 1 else [7]}, **lock)}

    def waits(self, first, *later):
        """The run whose first wait and whose land-lock steps answer these places; the step after the last takes the lock."""
        replies = {"land-take-1": self.ran_out(first)}
        replies.update({f"land-lock-1-{k}": self.ran_out(place) for k, place in enumerate(later, 1)})
        result, calls, _ = run(replies=replies)
        return row(result, 1)["outcome"], [label for label in labels(calls) if label.startswith("land-lock-")]

    def test_a_wait_that_ends_first_in_line_never_ends_land_contended(self):
        """The 2441 shape: four waits, the last three first in line with nobody ahead."""
        outcome, steps = self.waits(2, 1, 1, 1, 1)
        self.assertEqual((outcome, steps), ("landed", [f"land-lock-1-{k}" for k in range(1, 6)]))

    def test_a_wait_whose_place_improved_spends_no_retry(self):
        outcome, steps = self.waits(5, 4, 3, 2, 2)
        self.assertEqual((outcome, steps), ("landed", [f"land-lock-1-{k}" for k in range(1, 6)]))

    def test_a_wait_with_no_progress_still_ends_land_contended(self):
        for name, places in (("the same place", (2, 2, 2, 2)), ("a worse place", (2, 3, 4, 5)), ("no place read", (None,) * 4),
                             ("one better place, then none", (3, 2, 2, 2, 2))):
            with self.subTest(name):
                outcome, steps = self.waits(*places)
                # Three retries, as before, plus one wait for each place gained.
                self.assertEqual((outcome, steps), ("land-contended", [f"land-lock-1-{k}" for k in range(1, len(places))]))

    def test_the_waits_in_all_stop_at_the_ceiling(self):
        """First in line for ever (a holder that never lets go): no wait starts that could end after six hours."""
        self.assertIn("const LAND_WAIT_MAX_S = 6 * 3600\nconst LAND_WAIT_CALL_S = 3000\n", PROGRAM.read_text(encoding="utf-8"))
        outcome, steps = self.waits(*[1] * 12)
        self.assertEqual((outcome, steps), ("land-contended", [f"land-lock-1-{k}" for k in range(1, 7)]))  # 7 waits of 50 minutes
        # A reply that names no waited_s counts as a whole call, so a silent clerk cannot wait for ever.
        replies = {"land-take-1": {"lock": {"verdict": "land-contended", "position": 1}}}
        replies.update({f"land-lock-1-{k}": {"lock": {"verdict": "land-contended", "position": 1}} for k in range(1, 12)})
        result, calls, _ = run(replies=replies)
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertEqual(len([label for label in labels(calls) if label.startswith("land-lock-")]), 6)

    def test_a_reply_that_under_reports_its_wait_does_not_lift_the_ceiling(self):
        for waited in (0, 1, -5, None):
            with self.subTest(waited_s=waited):
                lock = {"verdict": "land-contended", "position": 1, "waited_s": waited}
                replies = {"land-take-1": {"lock": lock}}
                replies.update({f"land-lock-1-{k}": {"lock": lock} for k in range(1, 12)})
                result, calls, _ = run(replies=replies)
                self.assertEqual(row(result, 1)["outcome"], "land-contended")
                self.assertEqual(len([label for label in labels(calls) if label.startswith("land-lock-")]), 6)

    def test_a_take_after_a_resolution_judges_each_wait_by_its_own_reply(self):
        """The take's wait ended first in line; the waits after it end at place 3 and spend the retries."""
        replies = {"land-sync-1-1": ABORTED, "land-checks-1-2": green(B), "land-take-1": [{"behind": True}, self.ran_out(1, lock_sha=C)],
                   **{f"land-lock-1-{k}": self.ran_out(3, lock_sha=C) for k in range(1, 10)}}
        result, calls, _ = run(patch=BEHIND, replies=replies)
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertEqual([label for label in labels(calls) if label.startswith("land-lock-")], [f"land-lock-1-{k}" for k in range(1, 5)])

    def test_the_ceiling_is_one_for_the_landing_and_the_retries_are_new_for_each_run_of_waits(self):
        """Four waits before the lock came, then a take first in line for ever: its own retries are untouched, and its waits
        stop where the six hours of the landing do (seven waits of 50 minutes in all)."""
        replies = {"land-take-1": [self.ran_out(1), self.ran_out(1, lock_sha=C)],
                   **{f"land-lock-1-{k}": self.ran_out(1) for k in (1, 2, 3)},
                   "land-lock-1-4": {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": True}, "land-sync-1-1": ABORTED,
                   "land-checks-1-2": green(B), **{f"land-lock-1-{k}": self.ran_out(1, lock_sha=C) for k in range(5, 10)}}
        result, calls, _ = run(replies=replies)
        self.assertEqual(row(result, 1)["outcome"], "land-contended")
        self.assertEqual([label for label in labels(calls) if label.startswith("land-lock-")],
                         [f"land-lock-1-{k}" for k in range(1, 7)])

    def test_a_take_after_a_resolution_first_in_line_waits_again_without_a_retry(self):
        ran_out = self.ran_out(1, lock_sha=C)
        replies = {"land-sync-1-1": ABORTED, "land-take-1": [{"behind": True}, ran_out],
                   **{f"land-lock-1-{k}": ran_out for k in (1, 2, 3, 4)},
                   "land-checks-1-2": {"state": "passed", "head": B, "required": ["ci"], "passed": ["ci"]}}
        result, calls, _ = run(patch=BEHIND, replies=replies)
        self.assertEqual(row(result, 1)["outcome"], "landed")
        self.assertEqual([label for label in labels(calls) if label.startswith("land-lock-")], [f"land-lock-1-{k}" for k in range(1, 6)])

    def test_the_lock_replies_carry_the_place(self):
        _, calls, _ = run(replies={"land-take-1": self.ran_out(1)})
        for label in ("land-take-1", "land-lock-1-1"):
            with self.subTest(label=label):
                self.assertIn("waited_s and waited_on from its output, and position and ahead when it prints them.", prompt(calls, label))
                lock = object_branch(schema_of(calls, label)["properties"]["lock"])["properties"]
                self.assertEqual((lock["position"], lock["ahead"]),
                                 ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, {"type": "array", "items": {"type": "integer"}}))

    def test_both_programs_carry_the_same_budget(self):
        def budget(path):
            text = "\n".join(l for l in path.read_text(encoding="utf-8").split("\n") if not l.lstrip().startswith("//"))
            start = text.index("const LAND_WAIT_RETRIES = ")
            return "\n".join(l for l in text[start:text.index("\n}\n", text.index("const waitBudget = ", start)) + 3].split("\n") if not l.lstrip().startswith("//"))
        self.assertIn("return spent <= LAND_WAIT_RETRIES && total + LAND_WAIT_CALL_S <= LAND_WAIT_MAX_S", budget(PROGRAM))
        self.assertEqual(budget(PROGRAM), budget(PROGRAM.with_name("deliver-standard.js")))


class BatchGreenFirstTest(unittest.TestCase):
    """A serial landing asks for the land lease only once its head is green, beats it while it waits for the checks and
    waits again at the back when it loses it; a train takes no lease."""

    PASSED = {"state": "passed", "head": SHA, "required": ["ci"], "passed": ["ci"]}
    TAKEN = {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": False}
    MERGED = {"status": "done", "conflicted": False, "head": B, "merge_commit": B, "notes": "ok"}

    def test_a_serial_landing_takes_the_lease_only_after_the_head_is_green(self):
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA, "checks": self.PASSED}, "land-take-1": self.TAKEN})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-pr-1"), ls.index("land-take-1"))
        self.assertLess(ls.index("land-take-1"), ls.index("land-merge-1"))
        self.assertNotIn("forge-claim land", prompt(calls, "land-pr-1"))
        self.assertIn(f"--sha {SHA} --wait --lease", prompt(calls, "land-take-1"))
        self.assertIn(f"--sha {SHA} --lease\n", prompt(calls, "land-merge-1"))

    def test_a_train_takes_the_lock_without_a_lease(self):
        _, calls, _ = train_run()
        self.assertIn("train-build-1", labels(calls))
        for c in calls:
            if c["kind"] == "agent":
                with self.subTest(label=c["label"]):
                    self.assertNotIn("--lease", c["prompt"])
                    self.assertNotIn("forge-claim land hold", c["prompt"])

    def test_a_lost_lease_before_the_merge_waits_again_at_the_back(self):
        lost = {"lock": {"verdict": "held_by", "lock_sha": B, "pr": 77, "by": "h2/b9"}, "merged": False, "notes": "held"}
        result, calls, _ = run(replies={"land-merge-1": [lost, {"merged": True, "merge_commit": SHA, "notes": "merged"}],
                                        "land-lock-1-1": self.TAKEN})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-merge-1"), ls.index("land-lock-1-1"))
        self.assertEqual(ls.count("land-merge-1"), 2)
        self.assertIn(f"--sha {SHA} --wait --lease", prompt(calls, "land-lock-1-1"))

    def test_a_train_hands_over_at_a_lock_reply_that_holds_behind(self):
        _, calls, _ = train_run(replies={"land-take-1": {"lock": {"verdict": "acquired", "lock_sha": SHA}, "behind": True}})
        ls = labels(calls)
        self.assertIn("land-take-1", ls)
        self.assertLess(ls.index("land-take-1"), ls.index("train-pr-2"))

    def test_a_pending_head_takes_no_lock(self):
        pending = {"state": "pending", "head": SHA, "pending": ["ci"]}
        result, calls, _ = run(replies={"land-pr-1": {"pr": 41, "head": SHA, "checks": pending}, "land-checks-1-2": pending,
                                        "land-checks-1-3": pending})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "checks-pending"))
        self.assertFalse([label for label in labels(calls) if label.startswith(("land-take-", "land-lock-", "land-merge-"))])
        self.assertFalse([c["label"] for c in calls if "forge-claim land" in c.get("prompt", "")])

    def test_a_checks_wait_under_the_lease_beats_it_and_a_lost_beat_waits_again(self):
        lost = {"state": "lost", "head": B, "lock_sha": C}
        result, calls, _ = run(replies={"land-take-1": dict(self.TAKEN, behind=True), "land-sync-1-1": self.MERGED,
                                        "land-record-1-1": {"ok": True, "head": B, "checks": lost}, "land-checks-1-3": green(B)})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        record = prompt(calls, "land-record-1-1")
        self.assertIn(f"forge-claim land hold --repo owner/repo --branch dev --sha {B} --seconds 120", record)
        self.assertNotIn("--repo owner/repo --watch", record)
        self.assertIn(f"--sha {B} --wait --lease", prompt(calls, "land-lock-1-1"))
        self.assertLess(labels(calls).index("land-record-1-1"), labels(calls).index("land-lock-1-1"))

    HOLD = f"forge-claim land hold --repo owner/repo --branch dev --sha {SHA}"

    def test_the_sync_step_under_the_lease_beats_it_in_the_background_for_its_whole_length(self):
        """A sync merge that runs its tests holds the lease for minutes; a beat sent once at its start lapses at 180 s."""
        result, calls, _ = run(replies={"land-take-1": dict(self.TAKEN, behind=True), "land-sync-1-1": self.MERGED})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        text = prompt(calls, "land-sync-1-1")
        self.assertEqual(text.count("forge-claim land hold"), 2)  # the detached beat, and the hold before the push
        self.assertIn(beat(self.HOLD), text)
        self.assertEqual(text.count("--detach\n"), 1)
        self.assertLess(text.index("--detach\n"), text.index("4. After a clean merge, push"))
        # No step that holds nothing starts one: the pull request step, the checks read before the lock and the take.
        for label in ("land-pr-1", "land-take-1"):
            self.assertNotIn("forge-claim land hold", prompt(calls, label))

    def test_the_merge_step_under_the_lease_beats_it_before_the_recheck_and_the_merge(self):
        """A landing that goes straight from the take to the merge keeps the lease beating through a slow merge."""
        result, calls, _ = run()
        self.assertEqual(row(result, 1)["outcome"], "landed")
        merge = prompt(calls, "land-merge-1")
        self.assertTrue(merge.startswith("First start the lease beat: run alone and exactly: forge-claim land hold --repo owner/repo --branch dev --sha "), merge[:120])
        self.assertEqual(merge.count("--detach\n"), 1)
        self.assertLess(merge.index("--detach\n"), merge.index("re-check the cross-host landing lock"))
        self.assertLess(merge.index("--detach\n"), merge.index("gh pr merge"))

    def test_a_sync_step_that_reports_the_lease_lost_is_followed_by_no_push_and_no_merge(self):
        """The loss is injected into the held sync step, whose last step is a push: nothing lands under that lease after it."""
        lost = {"status": "blocked", "conflicted": False, "notes": "lease lost"}
        result, calls, _ = run(replies={"land-take-1": dict(self.TAKEN, behind=True), "land-sync-1-1": lost})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "land-sync"))
        after = calls[labels(calls).index("land-sync-1-1") + 1:]
        self.assertEqual([c["label"] for c in after], ["land-unlock-1"])  # only the release: no push, checks or merge step
        self.assertIn("immediately before every git push and every merge this step makes", prompt(calls, "land-sync-1-1"))

    def test_a_merge_step_that_reports_the_lease_lost_merges_nothing_more(self):
        lost = {"merged": False, "notes": "lease lost"}
        result, calls, _ = run(replies={"land-merge-1": lost})
        self.assertEqual((row(result, 1)["outcome"], row(result, 1)["stage"]), ("stopped", "merge"))
        self.assertEqual(labels(calls).count("land-merge-1"), 1)

    def test_a_conflicted_sync_beats_while_it_aborts_and_the_resolution_outside_the_lock_starts_none(self):
        out = run_full(replies={"land-sync-1-1": ABORTED, "land-take-1": [dict(self.TAKEN, behind=True), {}], "land-checks-1-2": green(B)})
        calls = out["calls"]
        self.assertIn(beat(self.HOLD), prompt(calls, "land-sync-1-1"))
        self.assertNotIn("forge-claim land hold", prompt(calls, "land-sync-resolve-1-1"))

    def test_a_clean_merge_with_commits_on_top_beats_through_its_review_and_fix(self):
        """The review and the fix of a clean merge with a follow-up commit run while the lease is still held."""
        found = {"verdict": "findings", "descends": True, "findings": [{"severity": "important", "summary": "dropped a change", "failing_input": "x"}]}
        merged = {"status": "done", "conflicted": False, "head": C, "merge_commit": B, "notes": "ok"}
        fixed = {"status": "done", "start_head": C, "commit": "d" * 40, "notes": "ok", "tests": ["t"]}
        out = run_full(replies={"land-take-1": dict(self.TAKEN, behind=True), "land-sync-1-1": merged, "land-sync-review-1-1": found,
                                "land-sync-fix-1-1": fixed, "land-checks-1-2": green("d" * 40)})
        calls = out["calls"]
        ls = labels(calls)
        self.assertNotIn("land-unlock-1", ls[:ls.index("land-sync-rereview-1-1")])
        for label in ("land-sync-1-1", "land-sync-review-1-1", "land-sync-fix-1-1", "land-sync-rereview-1-1"):
            with self.subTest(label=label):
                self.assertIn(beat(self.HOLD), prompt(calls, label))

    def test_a_red_check_at_a_synced_head_releases_the_lock_before_the_fix(self):
        red = {"state": "failed", "head": B, "failing": ["ci"]}
        result, calls, _ = run(replies={"land-take-1": [dict(self.TAKEN, behind=True), {}], "land-sync-1-1": self.MERGED,
                                        "land-record-1-1": {"ok": True, "head": B, "checks": red}, "land-checks-1-3": green(FIX)})
        self.assertEqual(row(result, 1)["outcome"], "landed")
        ls = labels(calls)
        self.assertLess(ls.index("land-unlock-1"), ls.index("land-fix-1"))
        self.assertLess(ls.index("land-fix-1"), ls.index("land-record-1-2"))
        # The fix head is read green with no lock command; only then is the lock taken at it.
        self.assertLess(ls.index("land-record-1-2"), ls.index("land-checks-1-3"))
        self.assertLess(ls.index("land-checks-1-3"), len(ls) - 1 - ls[::-1].index("land-take-1"))
        self.assertNotIn("forge-claim land", prompt(calls, "land-checks-1-3"))
        self.assertIn(f"--sha {FIX} --wait --lease", prompt(calls, "land-take-1"))
